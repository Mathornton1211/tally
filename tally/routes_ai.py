"""AI routes: chat, digest, enrichment, merchant renames, status."""
import json
import threading
from datetime import date, timedelta

from fastapi import APIRouter, BackgroundTasks, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from . import chat, digest, enrich, scope
from .llm import LLMUnavailable
from .state import state

router = APIRouter(prefix="/api")
_enrich_lock = threading.Lock()


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


def _llm():
    llm = state.get("llm")
    if llm is None:
        raise HTTPException(503, "AI is not configured")
    return llm


def _last_full_month() -> date:
    return (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)


# ---------------------------------------------------------------- status

@router.get("/ai/status")
def ai_status():
    llm = state.get("llm")
    s = llm.status() if llm else {"reachable": False, "error": "not configured"}
    with _conn() as conn:
        pending = conn.execute(
            """SELECT (SELECT count(DISTINCT tally_raw_key(COALESCE(NULLIF(raw->>'original_description',''), name)))
                         FROM transactions t WHERE merchant_name IS NULL AND NOT EXISTS (
                           SELECT 1 FROM merchant_aliases a
                           WHERE a.raw_key = tally_raw_key(COALESCE(NULLIF(t.raw->>'original_description',''), t.name)))) AS names,
                      (SELECT count(*) FROM v_txn v JOIN transactions t ON t.id = v.id
                         WHERE v.category_source = 'plaid' AND t.category_ai IS NULL AND NOT v.pending
                           AND (t.pfc_confidence IS NULL OR t.pfc_confidence IN ('LOW','UNKNOWN'))) AS categories""").fetchone()
        done = conn.execute(
            """SELECT (SELECT count(*) FROM merchant_aliases WHERE source = 'llm') AS names,
                      (SELECT count(*) FROM transactions WHERE category_ai IS NOT NULL) AS categories""").fetchone()
        calls = conn.execute(
            """SELECT task, count(*) AS calls, count(*) FILTER (WHERE NOT ok) AS failed,
                      round(avg(ms)) AS avg_ms, max(started_at) AS last
               FROM ai_calls WHERE started_at > now() - interval '7 days' GROUP BY task ORDER BY task""").fetchall()
    return {**s, "pending": pending, "done": done, "calls_7d": calls, "enriching": _enrich_lock.locked()}


def _run_enrich():
    if not _enrich_lock.acquire(blocking=False):
        return
    try:
        enrich.run(state["pool"], state["llm"])
    finally:
        _enrich_lock.release()


@router.post("/ai/enrich")
def run_enrich(background: BackgroundTasks):
    _llm()
    if _enrich_lock.locked():
        return {"queued": False, "running": True}
    background.add_task(_run_enrich)
    return {"queued": True}


# ---------------------------------------------------------------- chat

class ChatTurn(BaseModel):
    role: str = Field(pattern="^(user|assistant)$")
    content: str = Field(max_length=4000)


class ChatIn(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    history: list[ChatTurn] = []


@router.post("/chat")
def ask(body: ChatIn):
    llm = _llm()

    def events():
        # A dedicated connection for the whole stream; the pool one would be
        # returned mid-generation.
        with state["pool"].connection() as conn:
            for ev in chat.ask(conn, llm, body.question, [h.model_dump() for h in body.history]):
                yield json.dumps(ev, default=str) + "\n"

    return StreamingResponse(events(), media_type="application/x-ndjson",
                             headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


@router.get("/chat/suggestions")
def suggestions():
    last = _last_full_month().strftime("%B")
    with _conn() as conn:
        top = conn.execute(
            """SELECT display_name FROM v_txn WHERE kind = 'expense' AND date >= current_date - 60
               GROUP BY 1 ORDER BY sum(spend) DESC OFFSET 2 LIMIT 1""").fetchone()
    out = [
        f"How much did I spend eating out in {last}?",
        "What are my biggest recurring charges?",
        "Groceries by month this year",
        "Which merchants did I spend the most at in the last 90 days?",
        "How much do I owe on my credit cards?",
    ]
    if top:
        out.insert(2, f"How much have I spent at {top['display_name']} since January?")
    return out[:6]


# ---------------------------------------------------------------- digest

@router.get("/digest")
def get_digest(month: date | None = None):
    m = (month or _last_full_month()).replace(day=1)
    with _conn() as conn:
        row = conn.execute("SELECT * FROM digests WHERE month = %s", (m,)).fetchone()
        has_data = conn.execute("SELECT 1 FROM transactions WHERE date >= %s AND date < %s + interval '1 month' LIMIT 1",
                                (m, m)).fetchone() is not None
    return {"month": m, "digest": row, "has_data": has_data}


@router.post("/digest")
def make_digest(month: date | None = None):
    llm = _llm()
    m = (month or _last_full_month()).replace(day=1)
    try:
        with _conn() as conn:
            row = digest.write(conn, llm, m)
    except LLMUnavailable as e:
        raise HTTPException(503, f"local model unavailable: {e}")
    return {"month": m, "digest": row, "has_data": True}


# ---------------------------------------------------------------- merchant rename

class RenameIn(BaseModel):
    txn_id: str
    name: str = Field(min_length=1, max_length=48)


@router.put("/merchants/name")
def rename_merchant(body: RenameIn):
    with _conn() as conn:
        row = conn.execute(
            "SELECT tally_raw_key(bank_text) AS k, bank_text FROM v_txn WHERE id = %s", (body.txn_id,)).fetchone()
        if not row or not row["k"]:
            raise HTTPException(404, "no such transaction")
        conn.execute(
            """INSERT INTO merchant_aliases (raw_key, clean_name, source) VALUES (%s, %s, 'user')
               ON CONFLICT (raw_key) DO UPDATE SET clean_name = EXCLUDED.clean_name, source = 'user',
                 model = NULL, created_at = now()""", (row["k"], body.name.strip()))
        n = conn.execute("SELECT count(*) AS n FROM v_txn WHERE tally_raw_key(bank_text) = %s", (row["k"],)).fetchone()["n"]
    return {"name": body.name.strip(), "applied_to": n}
