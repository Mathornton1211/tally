"""Funds: what you are saving for, what is already in hand, what it still needs."""
import datetime
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import funds, plan, scope
from .state import state

router = APIRouter(prefix="/api/funds")


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


def _one(conn, fund_id: int) -> dict:
    for f in funds.list_funds(conn, include_archived=True):
        if f["id"] == fund_id:
            return f
    raise HTTPException(404, "no such fund")


@router.get("")
def list_all(include_archived: bool = False):
    with _conn() as conn:
        rows = funds.list_funds(conn, include_archived)
        # The affordability read needs the same projection the Plan page uses.
        rw = plan.runway(conn, horizon_days=45) if rows else None
        for f in rows:
            f["affordability"] = funds.affordability(conn, f, rw) if rw else None
        return {
            "funds": rows,
            "total_target": sum((f["target_amount"] for f in rows if not f["bought"]), Decimal(0)),
            "total_credits": sum((f["credits_total"] for f in rows if not f["bought"]), Decimal(0)),
            "total_saved": sum((f["saved"] for f in rows if not f["bought"]), Decimal(0)),
            "total_still_needed": sum((f["still_needed"] for f in rows if not f["bought"]), Decimal(0)),
        }


class FundIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    target_amount: Decimal = Field(gt=0)
    target_date: date | None = None
    note: str | None = None
    icon: str = "ShoppingBag"
    priority: int = 0


@router.post("")
def create(body: FundIn):
    with _conn() as conn:
        row = conn.execute(
            """INSERT INTO funds (name, target_amount, target_date, note, icon, priority)
               VALUES (%s,%s,%s,%s,%s,%s) RETURNING id""",
            (body.name, body.target_amount, body.target_date, body.note, body.icon, body.priority)).fetchone()
        return _one(conn, row["id"])


class FundPatch(BaseModel):
    name: str | None = Field(default=None, max_length=60)
    target_amount: Decimal | None = Field(default=None, gt=0)
    target_date: date | None = None
    note: str | None = None
    priority: int | None = None
    bought: bool | None = None
    archived: bool | None = None


@router.patch("/{fund_id}")
def patch(fund_id: int, body: FundPatch):
    sets, params = [], []
    for field in ("name", "target_amount", "target_date", "note", "priority"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = %s"); params.append(v)
    if body.bought is not None:
        sets.append("bought_on = %s"); params.append(date.today() if body.bought else None)
    if body.archived is not None:
        sets.append("archived = %s"); params.append(body.archived)
    if not sets:
        raise HTTPException(400, "nothing to change")
    with _conn() as conn:
        n = conn.execute(f"UPDATE funds SET {', '.join(sets)} WHERE id = %s", params + [fund_id]).rowcount
        if not n:
            raise HTTPException(404, "no such fund")
        return _one(conn, fund_id)


@router.delete("/{fund_id}")
def delete(fund_id: int):
    with _conn() as conn:
        n = conn.execute("DELETE FROM funds WHERE id = %s", (fund_id,)).rowcount
    if not n:
        raise HTTPException(404, "no such fund")
    return {"ok": True}


# ---------------------------------------------------------------- credits

class CreditIn(BaseModel):
    kind: str = Field(pattern="^(gift_card|store_credit|rebate|trade_in|other)$")
    label: str = Field(min_length=1, max_length=60)
    amount: Decimal = Field(gt=0)
    merchant: str | None = Field(default=None, max_length=60)
    expires_on: date | None = None
    note: str | None = None


@router.post("/{fund_id}/credits")
def add_credit(fund_id: int, body: CreditIn):
    """A gift card, store credit, a rebate, a trade-in. Money for this only."""
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM funds WHERE id = %s", (fund_id,)).fetchone():
            raise HTTPException(404, "no such fund")
        conn.execute(
            """INSERT INTO fund_credits (fund_id, kind, label, amount, merchant, expires_on, note)
               VALUES (%s,%s,%s,%s,%s,%s,%s)""",
            (fund_id, body.kind, body.label, body.amount, body.merchant, body.expires_on, body.note))
        return _one(conn, fund_id)


class CreditUse(BaseModel):
    used: Decimal = Field(ge=0)


@router.patch("/{fund_id}/credits/{credit_id}")
def use_credit(fund_id: int, credit_id: int, body: CreditUse):
    """Part of a gift card spent leaves the rest available."""
    with _conn() as conn:
        row = conn.execute("SELECT amount FROM fund_credits WHERE id = %s AND fund_id = %s",
                           (credit_id, fund_id)).fetchone()
        if not row:
            raise HTTPException(404, "no such credit")
        if body.used > Decimal(row["amount"]):
            raise HTTPException(400, "that is more than the credit is worth")
        conn.execute("UPDATE fund_credits SET used = %s WHERE id = %s", (body.used, credit_id))
        return _one(conn, fund_id)


@router.delete("/{fund_id}/credits/{credit_id}")
def delete_credit(fund_id: int, credit_id: int):
    with _conn() as conn:
        n = conn.execute("DELETE FROM fund_credits WHERE id = %s AND fund_id = %s",
                         (credit_id, fund_id)).rowcount
        if not n:
            raise HTTPException(404, "no such credit")
        return _one(conn, fund_id)


# ---------------------------------------------------------------- cash and purchases

class ContributionIn(BaseModel):
    amount: Decimal
    # datetime.date spelled out: a field called `date` shadows the imported name.
    date: datetime.date | None = None
    note: str | None = None
    transaction_id: str | None = None


@router.post("/{fund_id}/contributions")
def contribute(fund_id: int, body: ContributionIn):
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM funds WHERE id = %s", (fund_id,)).fetchone():
            raise HTTPException(404, "no such fund")
        conn.execute(
            """INSERT INTO fund_contributions (fund_id, date, amount, source, transaction_id, note)
               VALUES (%s,%s,%s,%s,%s,%s)""",
            (fund_id, body.date or date.today(), body.amount,
             "transaction" if body.transaction_id else "manual", body.transaction_id, body.note))
        return _one(conn, fund_id)


@router.delete("/{fund_id}/contributions/{contribution_id}")
def remove_contribution(fund_id: int, contribution_id: int):
    with _conn() as conn:
        n = conn.execute("DELETE FROM fund_contributions WHERE id = %s AND fund_id = %s",
                         (contribution_id, fund_id)).rowcount
        if not n:
            raise HTTPException(404, "no such contribution")
        return _one(conn, fund_id)


class SpendIn(BaseModel):
    transaction_id: str
    note: str | None = None


@router.post("/{fund_id}/spends")
def add_spend(fund_id: int, body: SpendIn):
    """Count a real purchase against the fund."""
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM transactions WHERE id = %s", (body.transaction_id,)).fetchone():
            raise HTTPException(404, "no such transaction")
        conn.execute(
            """INSERT INTO fund_spends (fund_id, transaction_id, note) VALUES (%s,%s,%s)
               ON CONFLICT (fund_id, transaction_id) DO UPDATE SET note = EXCLUDED.note""",
            (fund_id, body.transaction_id, body.note))
        return _one(conn, fund_id)


@router.delete("/{fund_id}/spends/{transaction_id}")
def remove_spend(fund_id: int, transaction_id: str):
    with _conn() as conn:
        n = conn.execute("DELETE FROM fund_spends WHERE fund_id = %s AND transaction_id = %s",
                         (fund_id, transaction_id)).rowcount
        if not n:
            raise HTTPException(404, "that purchase is not on this fund")
        return _one(conn, fund_id)


class AutoIn(BaseModel):
    # null turns the instruction off and leaves what was already set aside.
    kind: str | None = Field(default=None, pattern="^(per_paycheck|monthly|percent_of_income)$")
    amount: Decimal | None = Field(default=None, gt=0)
    percent: Decimal | None = Field(default=None, gt=0, le=100)


@router.put("/{fund_id}/auto")
def set_auto(fund_id: int, body: AutoIn):
    """Fill this fund automatically when income lands."""
    if body.kind in ("per_paycheck", "monthly") and body.amount is None:
        raise HTTPException(400, "that needs an amount")
    if body.kind == "percent_of_income" and body.percent is None:
        raise HTTPException(400, "that needs a percentage")
    with _conn() as conn:
        n = conn.execute(
            """UPDATE funds SET auto_kind = %s, auto_amount = %s, auto_percent = %s,
                      auto_through = CASE WHEN %s::text IS NULL THEN NULL ELSE current_date END
               WHERE id = %s""",
            (body.kind, body.amount, body.percent, body.kind, fund_id)).rowcount
        if not n:
            raise HTTPException(404, "no such fund")
        return _one(conn, fund_id)


@router.get("/auto/preview")
def preview_auto(kind: str, amount: Decimal | None = None, percent: Decimal | None = None,
                 months: int = 6):
    """What this instruction would have set aside over real past income."""
    with _conn() as conn:
        return funds.auto_preview(conn, kind, amount, percent, months)


@router.post("/auto/run")
def run_auto():
    with _conn() as conn:
        return funds.auto_fill(conn)


@router.get("/for-transaction/{transaction_id}")
def for_transaction(transaction_id: str):
    """Which funds this transaction is already counted against, for the drawer."""
    with _conn() as conn:
        return conn.execute(
            """SELECT f.id, f.name, f.icon FROM fund_spends s JOIN funds f ON f.id = s.fund_id
               WHERE s.transaction_id = %s""", (transaction_id,)).fetchall()
