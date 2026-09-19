"""Accounts and transactions Tally is told about rather than shown.

Cash, a card that will not link, a loan from a friend, a car. Plus splitting
one charge into the things it actually bought.

Manual rows are marked `source = 'manual'` and never touched by a sync; Plaid
rows can be split but not edited or deleted here.
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import scope
from .state import state

router = APIRouter(prefix="/api")

ACCOUNT_TYPES = {"depository", "credit", "loan", "investment", "other"}


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


class ManualAccount(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    type: str = Field(pattern="^(depository|credit|loan|investment|other)$")
    subtype: str | None = Field(default=None, max_length=30)
    institution_name: str | None = Field(default=None, max_length=60)
    # For credit and loan accounts this is what is OWED, the same as Plaid.
    current_balance: Decimal = Decimal(0)
    credit_limit: Decimal | None = None
    mask: str | None = Field(default=None, max_length=4)


@router.post("/accounts/manual")
def create_account(body: ManualAccount):
    account_id = f"manual-{uuid.uuid4().hex[:12]}"
    with _conn() as conn:
        conn.execute(
            """INSERT INTO accounts (id, item_id, source, name, mask, type, subtype, current_balance,
                   available_balance, credit_limit, institution_name, iso_currency)
               VALUES (%s, NULL, 'manual', %s,%s,%s,%s,%s,%s,%s,%s,'USD')""",
            (account_id, body.name, body.mask, body.type, body.subtype, body.current_balance,
             body.current_balance if body.type == "depository" else None,
             body.credit_limit, body.institution_name or "Added by hand"))
        return conn.execute(
            "SELECT id, name, mask, type, subtype, current_balance, institution_name FROM v_acct WHERE id = %s",
            (account_id,)).fetchone()


class BalanceIn(BaseModel):
    current_balance: Decimal
    credit_limit: Decimal | None = None


@router.put("/accounts/manual/{account_id}/balance")
def set_balance(account_id: str, body: BalanceIn):
    """Manual balances go stale by nature, so updating one is a single field."""
    with _conn() as conn:
        n = conn.execute(
            """UPDATE accounts SET current_balance = %s,
                   available_balance = CASE WHEN type = 'depository' THEN %s ELSE available_balance END,
                   credit_limit = COALESCE(%s, credit_limit), updated_at = now()
               WHERE id = %s AND source = 'manual'""",
            (body.current_balance, body.current_balance, body.credit_limit, account_id)).rowcount
        if not n:
            raise HTTPException(404, "no such manual account")
        # A manual balance is a fact about today; record it so net worth has history.
        conn.execute(
            """INSERT INTO balances_daily (account_id, day, current_balance)
               VALUES (%s, current_date, %s)
               ON CONFLICT (account_id, day) DO UPDATE SET current_balance = EXCLUDED.current_balance""",
            (account_id, body.current_balance))
    return {"ok": True}


@router.delete("/accounts/manual/{account_id}")
def delete_account(account_id: str):
    """Removes the account and the manual transactions on it. Manual only."""
    with _conn() as conn:
        row = conn.execute("SELECT source, name FROM v_acct WHERE id = %s", (account_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such account")
        if row["source"] != "manual":
            raise HTTPException(400, "this account comes from a bank; hide it in Accounts instead")
        n = conn.execute("SELECT count(*) AS n FROM transactions WHERE account_id = %s", (account_id,)).fetchone()["n"]
        conn.execute("DELETE FROM accounts WHERE id = %s", (account_id,))
    return {"ok": True, "deleted_transactions": n}


class ManualTxn(BaseModel):
    account_id: str
    date: date
    # Positive = money out, the same convention as everywhere else in Tally.
    amount: Decimal
    name: str = Field(min_length=1, max_length=80)
    category: str | None = None
    note: str | None = None


@router.post("/transactions/manual")
def create_txn(body: ManualTxn):
    with _conn() as conn:
        acct = conn.execute("SELECT source FROM v_acct WHERE id = %s", (body.account_id,)).fetchone()
        if not acct:
            raise HTTPException(404, "no such account")
        if acct["source"] != "manual":
            raise HTTPException(400, "transactions can only be added to manual accounts")
        if body.category and not conn.execute("SELECT 1 FROM categories WHERE key = %s",
                                              (body.category,)).fetchone():
            raise HTTPException(400, "unknown category")
        txn_id = f"manual-{uuid.uuid4().hex[:16]}"
        conn.execute(
            """INSERT INTO transactions (id, account_id, amount, iso_currency, date, name, pending,
                   category, note, source, raw)
               VALUES (%s,%s,%s,'USD',%s,%s,false,%s,%s,'manual',%s)""",
            (txn_id, body.account_id, body.amount, body.date, body.name, body.category, body.note,
             Jsonb({"manual": True, "original_description": body.name})))
        return conn.execute("SELECT * FROM v_txn WHERE id = %s", (txn_id,)).fetchone()


@router.delete("/transactions/manual/{txn_id}")
def delete_txn(txn_id: str):
    with _conn() as conn:
        row = conn.execute("SELECT source FROM transactions WHERE id = %s", (txn_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such transaction")
        if row["source"] != "manual":
            raise HTTPException(400, "only transactions you added by hand can be deleted")
        conn.execute("DELETE FROM transactions WHERE id = %s", (txn_id,))
    return {"ok": True}


# ---------------------------------------------------------------- splits

class SplitPart(BaseModel):
    amount: Decimal
    category: str
    note: str | None = None


class SplitIn(BaseModel):
    parts: list[SplitPart] = Field(min_length=2, max_length=12)


@router.post("/transactions/{txn_id}/split")
def split(txn_id: str, body: SplitIn):
    """Replace one charge with its parts. The parts must add up to the charge."""
    total = sum((p.amount for p in body.parts), Decimal(0))
    with _conn() as conn:
        t = conn.execute(
            """SELECT id, account_id, amount, date, name, merchant_name, logo_url, pfc_primary,
                      pfc_detailed, pfc_confidence, is_split_parent, raw
               FROM transactions WHERE id = %s""", (txn_id,)).fetchone()
        if not t:
            raise HTTPException(404, "no such transaction")
        if t["is_split_parent"]:
            raise HTTPException(400, "this transaction is already split")
        if abs(total - Decimal(t["amount"])) > Decimal("0.01"):
            raise HTTPException(400, f"the parts add up to {total}, but the charge is {t['amount']}")
        keys = {r["key"] for r in conn.execute("SELECT key FROM categories").fetchall()}
        bad = [p.category for p in body.parts if p.category not in keys]
        if bad:
            raise HTTPException(400, f"unknown category: {', '.join(bad)}")

        for i, p in enumerate(body.parts, 1):
            conn.execute(
                """INSERT INTO transactions (id, account_id, amount, iso_currency, date, name, merchant_name,
                       logo_url, pending, pfc_primary, pfc_detailed, pfc_confidence, category, note,
                       parent_id, source, raw)
                   VALUES (%s,%s,%s,'USD',%s,%s,%s,%s,false,%s,%s,%s,%s,%s,%s,'split',%s)""",
                (f"{txn_id}-split-{i}", t["account_id"], p.amount, t["date"],
                 f"{t['name']} ({i}/{len(body.parts)})", t["merchant_name"], t["logo_url"],
                 t["pfc_primary"], t["pfc_detailed"], t["pfc_confidence"], p.category, p.note,
                 txn_id, Jsonb(t["raw"])))
        conn.execute("UPDATE transactions SET is_split_parent = true WHERE id = %s", (txn_id,))
        return conn.execute(
            "SELECT * FROM v_txn WHERE parent_id = %s ORDER BY id", (txn_id,)).fetchall()


@router.delete("/transactions/{txn_id}/split")
def unsplit(txn_id: str):
    with _conn() as conn:
        n = conn.execute("DELETE FROM transactions WHERE parent_id = %s", (txn_id,)).rowcount
        if not n:
            raise HTTPException(404, "that transaction is not split")
        conn.execute("UPDATE transactions SET is_split_parent = false WHERE id = %s", (txn_id,))
        return conn.execute("SELECT * FROM v_txn WHERE id = %s", (txn_id,)).fetchone()


@router.get("/transactions/{txn_id}/split")
def get_split(txn_id: str):
    with _conn() as conn:
        parent = conn.execute(
            "SELECT id, name, amount, date, is_split_parent FROM transactions WHERE id = %s",
            (txn_id,)).fetchone()
        if not parent:
            raise HTTPException(404, "no such transaction")
        parts = conn.execute(
            """SELECT id, amount, category, category_label, category_icon, note
               FROM v_txn WHERE parent_id = %s ORDER BY id""", (txn_id,)).fetchall()
    return {"parent": parent, "parts": parts}
