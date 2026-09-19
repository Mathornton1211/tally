"""Budgets: set a monthly target per category, and read how the month is going."""
import datetime
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from . import budgets, scope
from .state import state

router = APIRouter(prefix="/api/budgets")


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


@router.get("")
def month_status(month: datetime.date | None = None):
    with _conn() as conn:
        return budgets.status(conn, month)


@router.get("/suggestions")
def suggestions(months: int = Query(default=3, ge=1, le=12)):
    """What the last few complete months actually cost, as starting amounts.

    An empty budget page is useless, and asking someone to guess sixteen numbers
    from nothing is how budgeting gets abandoned in week one.
    """
    with _conn() as conn:
        return {"suggestions": budgets.suggest(conn, months)}


class BudgetIn(BaseModel):
    amount: Decimal = Field(ge=0)
    rollover: bool = False
    month: datetime.date | None = None
    # A one-month change: the old amount is restored from the following month,
    # so "$900 for December" does not quietly become the new normal in January.
    only_this_month: bool = False


@router.put("/{category}")
def set_budget(category: str, body: BudgetIn):
    month = budgets.month_start(body.month or date.today())
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE key = %s AND kind = 'expense'",
                            (category,)).fetchone():
            raise HTTPException(400, "budgets are for expense categories")

        # What is in force for this month right now, before the change: that is
        # what "only this month" has to put back, whether it was set last year
        # or ten seconds ago.
        previous = budgets.effective(conn, month).get(category)
        conn.execute(
            """INSERT INTO budgets (category, month, amount, rollover) VALUES (%s,%s,%s,%s)
               ON CONFLICT (category, month, COALESCE(owner_id, 0))
               DO UPDATE SET amount = EXCLUDED.amount, rollover = EXCLUDED.rollover, updated_at = now()""",
            (category, month, body.amount, body.rollover))

        reverts_to = None
        if body.only_this_month and previous:
            reverts_to = previous["amount"]
            conn.execute(
                """INSERT INTO budgets (category, month, amount, rollover) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (category, month, COALESCE(owner_id, 0))
                   DO UPDATE SET amount = EXCLUDED.amount, rollover = EXCLUDED.rollover, updated_at = now()""",
                (category, budgets.add_months(month, 1), previous["amount"], previous["rollover"]))

        return {"category": category, "month": month, "amount": body.amount,
                "rollover": body.rollover, "reverts_to": reverts_to,
                "status": budgets.status(conn, month)}


@router.delete("/{category}")
def clear_budget(category: str, month: datetime.date | None = None):
    """Drop the budget. Without a month, every row for the category goes, so the
    category is unbudgeted for its whole history rather than half of it."""
    with _conn() as conn:
        if month:
            n = conn.execute("DELETE FROM budgets WHERE category = %s AND month = %s",
                             (category, budgets.month_start(month))).rowcount
        else:
            n = conn.execute("DELETE FROM budgets WHERE category = %s", (category,)).rowcount
        if not n:
            raise HTTPException(404, "no budget for that category")
        return {"ok": True, "removed": n}


class ApplyIn(BaseModel):
    month: datetime.date | None = None
    # Left empty, every suggestion is taken. The first-run path is one button.
    categories: list[str] | None = None
    months: int = Field(default=3, ge=1, le=12)


@router.post("/apply-suggestions")
def apply_suggestions(body: ApplyIn):
    month = budgets.month_start(body.month or date.today())
    with _conn() as conn:
        picked = [s for s in budgets.suggest(conn, body.months)
                  if body.categories is None or s["category"] in body.categories]
        for s in picked:
            conn.execute(
                """INSERT INTO budgets (category, month, amount, rollover) VALUES (%s,%s,%s,%s)
                   ON CONFLICT (category, month, COALESCE(owner_id, 0))
                   DO UPDATE SET amount = EXCLUDED.amount, rollover = EXCLUDED.rollover, updated_at = now()""",
                (s["category"], month, s["amount"], s["rollover"]))
        return {"applied": [s["category"] for s in picked], "status": budgets.status(conn, month)}
