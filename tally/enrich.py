"""Background enrichment: readable merchant names and categories for the rows
Plaid was unsure about. Runs after sync; safe to rerun; never overrides a name a person set.

Both tasks batch many rows per call and use structured output, so a run over a
few hundred new transactions is a handful of model calls, not hundreds.
"""
import logging
import re

from .llm import LLM, LLMUnavailable

log = logging.getLogger("tally.enrich")

MERCHANT_BATCH = 25
CATEGORY_BATCH = 15

_MERCHANT_SYSTEM = """You turn raw bank statement descriptions into the short name a person would use for that payee.

Rules:
- 1 to 4 words. Title Case. No store numbers, dates, reference codes, city, or state.
- Keep the payment rail only when the payee is a person or a landlord: "Zelle to Harbourside Lettings" is fine.
- Transfers between the person's own accounts: say what it is, e.g. "Transfer to Savings", "Card Payment".
- Interest and bank fee lines: plain words, e.g. "Interest Earned", "Overdraft Fee", "Monthly Service Fee".
- Never invent a brand that is not in the text. If unsure, clean up the words that are there.

Examples:
"ZELLE PAYMENT TO HARBOURSIDE LETTINGS LLC" -> "Zelle to Harbourside Lettings"
"ONLINE TRANSFER TO SAVINGS XXXXXX0925" -> "Transfer to Savings"
"CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224" -> "Chase Card Payment"
"SQ *COFFEE COAST SEASIDE" -> "Coffee Coast"
"PAYPAL *DIGIGOODS4U" -> "Digigoods4U (PayPal)"
"""

_CATEGORY_SYSTEM = """You assign each bank transaction to exactly one budgeting category from a fixed list.

Think about what the money was actually for. A negative amount is money coming IN (refund, deposit, payment received).
Card payments and moves between the person's own accounts are transfers, never income or spending.
Return the category key, not the label. Use "other" only when nothing fits.
"""


def _clean_name(name: str) -> str | None:
    name = re.sub(r"\s+", " ", (name or "")).strip().strip('"').strip()
    if not name or len(name) > 48 or re.search(r"\d{5,}", name):
        return None
    return name


def clean_merchants(pool, llm: LLM, max_batches: int = 8) -> int:
    """Name every payee Plaid could not. Returns names written."""
    written = 0
    for _ in range(max_batches):
        with pool.connection() as conn:
            rows = conn.execute(
                """SELECT tally_raw_key(bank_text) AS raw_key, min(bank_text) AS sample, count(*) AS n
                   FROM (SELECT COALESCE(NULLIF(raw->>'original_description', ''), name) AS bank_text
                         FROM transactions WHERE merchant_name IS NULL) t
                   WHERE tally_raw_key(bank_text) <> ''
                     AND NOT EXISTS (SELECT 1 FROM merchant_aliases a WHERE a.raw_key = tally_raw_key(t.bank_text))
                   GROUP BY 1 ORDER BY 3 DESC LIMIT %s""", (MERCHANT_BATCH,)).fetchall()
        if not rows:
            break
        listing = "\n".join(f"{i}. {r['sample']}" for i, r in enumerate(rows))
        schema = {"type": "object", "required": ["names"], "properties": {"names": {
            "type": "array", "items": {"type": "object", "required": ["i", "name"],
                                       "properties": {"i": {"type": "integer"}, "name": {"type": "string"}}}}}}
        try:
            out = llm.json("merchant_names", [
                {"role": "system", "content": _MERCHANT_SYSTEM},
                {"role": "user", "content": f"Name each payee. Return every index.\n\n{listing}"},
            ], schema)
        except LLMUnavailable as e:
            log.warning("merchant naming skipped: %s", e)
            break
        by_i = {n.get("i"): _clean_name(n.get("name", "")) for n in out.get("names", [])}
        with pool.connection() as conn:
            for i, r in enumerate(rows):
                name = by_i.get(i)
                # A row the model skipped or botched still gets an alias, from its
                # own words, so it is not re-sent forever.
                if not name:
                    name = _clean_name(re.sub(r"[\d#*]+", " ", r["sample"]).title()) or r["sample"][:40]
                    source_model = "fallback"
                else:
                    source_model = llm.model
                conn.execute(
                    """INSERT INTO merchant_aliases (raw_key, clean_name, source, model) VALUES (%s,%s,'llm',%s)
                       ON CONFLICT (raw_key) DO NOTHING""", (r["raw_key"], name, source_model))
                written += 1
    return written


def categorize(pool, llm: LLM, max_batches: int = 6) -> int:
    """Categories for payees Plaid marked LOW/UNKNOWN confidence. Returns rows written.

    One decision per payee, applied to all its low-confidence rows: a merchant
    cannot land in two categories, and 70 rows is ~10 model decisions, not 70.
    Fees, card payments and transfers never reach the model; rules own those.
    """
    with pool.connection() as conn:
        cats = conn.execute("SELECT key, label, kind FROM categories ORDER BY sort").fetchall()
        examples = conn.execute(
            """(SELECT DISTINCT ON (display_name) display_name, category FROM v_txn
                WHERE category_source IN ('user', 'rule') ORDER BY display_name, date DESC LIMIT 15)""").fetchall()
    keys = [c["key"] for c in cats]
    cat_list = "\n".join(f"- {c['key']}: {c['label']} ({c['kind']})" for c in cats)
    ex = "\n".join(f'{e["display_name"]} -> {e["category"]}' for e in examples) or "(none yet)"
    written = 0
    for _ in range(max_batches):
        with pool.connection() as conn:
            payees = conn.execute(
                """SELECT v.merchant_key, min(v.display_name) AS payee, min(v.bank_text) AS sample,
                          count(*) AS n, round(avg(v.amount), 2) AS avg_amount, min(v.account_type) AS account_type,
                          mode() WITHIN GROUP (ORDER BY v.pfc_detailed) AS bank_guess
                   FROM v_txn v JOIN transactions t ON t.id = v.id
                   WHERE v.category_source = 'plaid' AND t.category_ai IS NULL AND NOT v.pending
                     AND (t.pfc_confidence IS NULL OR t.pfc_confidence IN ('LOW', 'UNKNOWN'))
                     AND coalesce(t.pfc_primary, '') NOT IN ('BANK_FEES', 'TRANSFER_IN', 'TRANSFER_OUT', 'LOAN_PAYMENTS')
                   GROUP BY v.merchant_key ORDER BY count(*) DESC LIMIT %s""", (CATEGORY_BATCH,)).fetchall()
        if not payees:
            break
        listing = "\n".join(
            f"{i}. payee: {p['payee']} | bank text: \"{p['sample']}\" | {p['n']} transactions, avg {p['avg_amount']} | "
            f"account: {p['account_type']} | bank's guess: {p['bank_guess'] or 'none'}"
            for i, p in enumerate(payees))
        schema = {"type": "object", "required": ["items"], "properties": {"items": {
            "type": "array", "items": {"type": "object", "required": ["i", "payee", "category"], "properties": {
                "i": {"type": "integer"}, "payee": {"type": "string"},
                "category": {"type": "string", "enum": keys}}}}}}
        try:
            out = llm.json("categorize", [
                {"role": "system", "content": f"{_CATEGORY_SYSTEM}\nCategories:\n{cat_list}"},
                {"role": "user", "content": f"How this person categorizes:\n{ex}\n\n"
                                            f"Amounts: positive = money spent, negative = money received.\n"
                                            f"For each payee return its index, its payee name copied exactly, and one category.\n\n"
                                            f"{listing}"},
            ], schema)
        except LLMUnavailable as e:
            log.warning("categorize skipped: %s", e)
            break
        decided = {}
        for it in out.get("items", []):
            i = it.get("i")
            # The echoed name must match the row it claims to be, or the answer
            # belongs to a different payee and is thrown away.
            if isinstance(i, int) and 0 <= i < len(payees) and it.get("category") in keys \
                    and _same(it.get("payee", ""), payees[i]["payee"]):
                decided[i] = it["category"]
        with pool.connection() as conn:
            for i, p in enumerate(payees):
                # Undecided or misaligned: keep Plaid's answer, but mark the rows
                # done so they are not re-sent every sync.
                model = llm.model if i in decided else "kept-plaid"
                n = conn.execute(
                    """UPDATE transactions t SET category_ai = COALESCE(%s, v.category), category_ai_model = %s
                       FROM v_txn v WHERE v.id = t.id AND v.merchant_key = %s AND v.category_source = 'plaid'
                         AND t.category_ai IS NULL
                         AND (t.pfc_confidence IS NULL OR t.pfc_confidence IN ('LOW', 'UNKNOWN'))""",
                    (decided.get(i), model, p["merchant_key"])).rowcount
                written += n
    return written


def _same(a: str, b: str) -> bool:
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    a, b = norm(a), norm(b)
    return bool(a) and (a == b or a in b or b in a)

def run(pool, llm: LLM) -> dict:
    status = llm.status()
    if not status.get("reachable"):
        return {"skipped": "ollama unreachable", **status}
    return {"merchant_names": clean_merchants(pool, llm), "categories": categorize(pool, llm)}
