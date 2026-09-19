"""Goals, share links and search."""
import datetime
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, Field

from . import auth, bills, budgets, goals, research, scope, search, setup, share, trends
from .state import state

router = APIRouter(prefix="/api")


def _conn():
    return scope.connection()


def _who(request: Request) -> int | None:
    return state["auth"].person(request.cookies.get(auth.COOKIE))


# ---------------------------------------------------------------- goals

def _goals_payload(conn) -> dict:
    """Every goals response is the same shape. A create that returned less than
    a read would mean the page had to refetch to redraw itself."""
    return {**goals.evaluate(conn), "suggestions": goals.suggestions(conn)}


@router.get("/goals")
def list_goals():
    with _conn() as conn:
        return _goals_payload(conn)


class GoalIn(BaseModel):
    kind: str = Field(pattern="^(net_worth|debt_free|emergency_fund|savings)$")
    name: str = Field(min_length=1, max_length=60)
    target_amount: Decimal | None = Field(default=None, ge=0)
    target_months: Decimal | None = Field(default=None, gt=0, le=120)
    target_date: datetime.date | None = None
    account_id: str | None = None
    note: str | None = None
    personal: bool = False


@router.post("/goals")
def create_goal(body: GoalIn, request: Request):
    if body.kind != "debt_free" and body.target_amount is None and body.target_months is None:
        raise HTTPException(400, "a goal needs a target amount, or a number of months of spending")
    me = _who(request)
    with _conn() as conn:
        row = conn.execute(
            """INSERT INTO goals (kind, name, target_amount, target_months, target_date,
                                  account_id, note, owner_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.kind, body.name, body.target_amount, body.target_months, body.target_date,
             body.account_id, body.note, me if body.personal else None)).fetchone()
        return {"id": row["id"], **_goals_payload(conn)}


class GoalPatch(BaseModel):
    name: str | None = None
    target_amount: Decimal | None = None
    target_months: Decimal | None = None
    target_date: datetime.date | None = None
    note: str | None = None
    achieved: bool | None = None
    archived: bool | None = None


@router.patch("/goals/{goal_id}")
def edit_goal(goal_id: int, body: GoalPatch, request: Request):
    sets, params = [], []
    for field in ("name", "target_amount", "target_months", "target_date", "note"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = %s"); params.append(v)
    if body.achieved is not None:
        sets.append("achieved_on = %s"); params.append(date.today() if body.achieved else None)
    if body.archived is not None:
        sets.append("archived = %s"); params.append(body.archived)
    if not sets:
        raise HTTPException(400, "nothing to change")
    with _conn() as conn:
        if not conn.execute(f"UPDATE goals SET {', '.join(sets)} WHERE id = %s",
                            params + [goal_id]).rowcount:
            raise HTTPException(404, "no such goal")
        return _goals_payload(conn)


@router.delete("/goals/{goal_id}")
def delete_goal(goal_id: int, request: Request):
    with _conn() as conn:
        if not conn.execute("DELETE FROM goals WHERE id = %s", (goal_id,)).rowcount:
            raise HTTPException(404, "no such goal")
        return _goals_payload(conn)


# ---------------------------------------------------------------- getting started

@router.get("/setup")
def setup_state():
    with _conn() as conn:
        return {**setup.state(conn), "summary": setup.first_month(conn)}


@router.post("/setup/budgets")
def setup_budgets():
    """Take every suggestion at once. The first-run path is one button, because
    asking somebody to pick sixteen numbers from nothing is how budgeting gets
    abandoned in week one."""
    with _conn() as conn:
        month = budgets.month_start(date.today())
        picked = budgets.suggest(conn)
        for s in picked:
            conn.execute(
                """INSERT INTO budgets (category, month, amount, rollover) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (category, month, COALESCE(owner_id, 0))
                   DO UPDATE SET amount = EXCLUDED.amount, rollover = EXCLUDED.rollover,
                                 updated_at = now()""",
                (s["category"], month, s["amount"], s["rollover"]))
        return {"applied": [s["category"] for s in picked], **setup.state(conn)}


@router.post("/setup/goals")
def setup_goals():
    """Add the goals Tally would suggest, using the standard advice rather than
    invented numbers."""
    with _conn() as conn:
        added = []
        for g in goals.suggestions(conn):
            conn.execute(
                """INSERT INTO goals (kind, name, target_amount, target_months, note)
                   VALUES (%s,%s,%s,%s,%s)""",
                (g["kind"], g["name"], g.get("target_amount"), g.get("target_months"), g["why"]))
            added.append(g["name"])
        return {"added": added, **setup.state(conn)}


# ---------------------------------------------------------------- what keeps working

@router.get("/findings")
def list_findings(status: str = "open", rescan: bool = False):
    """What Tally has found while nobody was looking."""
    with _conn() as conn:
        if rescan:
            research.run(conn)
        return research.listing(conn, status)


@router.post("/findings/scan")
def scan_findings():
    with _conn() as conn:
        return research.run(conn)


class FindingUpdate(BaseModel):
    status: str = Field(pattern="^(open|acted|dismissed)$")
    # Which list the caller is looking at, so the response matches their screen
    # rather than always answering with the open ones.
    viewing: str = Field(default="open", pattern="^(open|acted|dismissed|all)$")
    note: str | None = None
    # What acting on it was actually worth. Without this the app can claim it
    # saves money and never has to prove it.
    saved: Decimal | None = None


@router.post("/findings/{finding_id}")
def update_finding(finding_id: int, body: FindingUpdate):
    with _conn() as conn:
        row = conn.execute(
            """UPDATE findings
                  SET status = %s,
                      resolved_on = CASE WHEN %s = 'open' THEN NULL ELSE current_date END
                WHERE id = %s RETURNING id""",
            (body.status, body.status, finding_id)).fetchone()
        if not row:
            raise HTTPException(404, "no such finding")
        if body.status == "acted" and (body.saved is not None or body.note):
            conn.execute(
                "INSERT INTO finding_outcomes (finding_id, note, saved) VALUES (%s,%s,%s)",
                (finding_id, body.note, body.saved))
        return research.listing(conn, body.viewing)


# ---------------------------------------------------------------- the long view

@router.get("/trends")
def trends_overview():
    with _conn() as conn:
        return {
            "years": trends.years(conn),
            "year_over_year": trends.year_over_year(conn),
            "months": trends.by_month(conn),
            "merchants": trends.merchants(conn),
            "available_years": trends.available_years(conn),
        }


@router.get("/trends/review")
def annual_review(year: int | None = None):
    with _conn() as conn:
        return trends.annual_review(conn, year)


# ---------------------------------------------------------------- getting out of one

@router.get("/subscriptions")
def subscriptions():
    """Every recurring charge, with a way out of each."""
    with _conn() as conn:
        return bills.cancellation_help(conn)


# ---------------------------------------------------------------- search

@router.get("/search")
def do_search(q: str = Query(min_length=1, max_length=300), use_ai: bool = True):
    with _conn() as conn:
        return search.ask(conn, q, state.get("llm") if use_ai else None)


# ---------------------------------------------------------------- share links

@router.get("/share-links")
def list_links(request: Request):
    with scope.unscoped() as conn:
        return {"links": share.listing(conn)}


class ShareIn(BaseModel):
    label: str = Field(min_length=1, max_length=60)
    start_date: datetime.date
    end_date: datetime.date
    detail: str = Field(default="summary", pattern="^(summary|transactions)$")
    expires_on: datetime.date | None = None


@router.post("/share-links")
def create_link(body: ShareIn, request: Request):
    """The token comes back once, here, and is never retrievable again."""
    if body.end_date < body.start_date:
        raise HTTPException(400, "the end date is before the start date")
    me = _who(request)
    with scope.unscoped() as conn:
        link = share.create(conn, body.label, body.start_date, body.end_date, body.detail,
                            body.expires_on, created_by=me, as_person=me)
        return {**link, "url": f"/shared/{link['token']}", "links": share.listing(conn)}


@router.delete("/share-links/{link_id}")
def revoke_link(link_id: int, request: Request):
    with scope.unscoped() as conn:
        if not share.revoke(conn, link_id):
            raise HTTPException(404, "no such link")
        return {"ok": True, "links": share.listing(conn)}


@router.get("/shared/{token}")
def read_share(token: str):
    """No session, no cookie: the token is the whole credential, and everything
    it may read is decided by the stored row rather than by this request."""
    with scope.unscoped() as conn:
        link = share.resolve(conn, token)
        if not link:
            return JSONResponse({"detail": "This link has expired or been turned off."}, status_code=404)
        # See exactly what the person who made it could see, frozen at that
        # moment. Widening later must never widen a link already handed out.
        if link["as_person"] is not None:
            conn.execute("SELECT set_config('tally.viewer', %s, true)", (str(link["as_person"]),))
        return share.contents(conn, link)
