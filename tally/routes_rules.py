"""Rules, tags, currency and the household's settings."""
import datetime
from decimal import Decimal

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, money, rules, scope
from .state import state

router = APIRouter(prefix="/api")


def _conn():
    return scope.connection()


def _who(request: Request) -> int | None:
    return state["auth"].person(request.cookies.get(auth.COOKIE))


# ---------------------------------------------------------------- rules

class SplitPart(BaseModel):
    category: str | None = None
    name: str | None = None
    percent: Decimal | None = None
    amount: Decimal | None = None


class RuleIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    pattern: str = Field(min_length=1, max_length=200)
    match_field: str = Field(default="display_name", pattern="^(display_name|bank_text|merchant_key)$")
    match_type: str = Field(default="contains", pattern="^(contains|equals|regex)$")
    min_amount: Decimal | None = None
    max_amount: Decimal | None = None
    account_id: str | None = None
    set_category: str | None = None
    set_name: str | None = Field(default=None, max_length=60)
    add_tags: list[str] = []
    set_note: str | None = Field(default=None, max_length=200)
    split: list[SplitPart] | None = None
    priority: int = 0
    enabled: bool = True
    personal: bool = False


def _clean(body: RuleIn) -> dict:
    d = body.model_dump()
    d["add_tags"] = sorted({t.strip().lower() for t in body.add_tags if t.strip()})
    if body.split:
        # Decimals as strings: this goes to Postgres as jsonb, and json.dumps
        # cannot serialise a Decimal. Strings rather than floats because the
        # values come back out through Decimal(str(...)) and a float round trip
        # on an amount is how a split stops adding up to its parent.
        parts = []
        for part in body.split:
            one = part.model_dump(exclude_none=True)
            for field in ("percent", "amount"):
                if field in one:
                    one[field] = str(one[field])
            parts.append(one)
        try:
            rules.validate_split(parts)
        except ValueError as e:
            raise HTTPException(400, str(e))
        d["split"] = parts
    return d


@router.get("/rules-v2")
def list_rules():
    with _conn() as conn:
        return {"rules": rules.listing(conn), "tags": rules.all_tags(conn)}


@router.post("/rules-v2/preview")
def preview_rule(body: RuleIn):
    with _conn() as conn:
        return rules.preview(conn, _clean(body))


@router.post("/rules-v2")
def create_rule(body: RuleIn, request: Request):
    d = _clean(body)
    me = _who(request)
    with _conn() as conn:
        if d["set_category"] and not conn.execute(
                "SELECT 1 FROM categories WHERE key = %s", (d["set_category"],)).fetchone():
            raise HTTPException(400, "unknown category")
        from psycopg.types.json import Jsonb
        row = conn.execute(
            """INSERT INTO rules (name, pattern, match_field, match_type, min_amount, max_amount,
                                  account_id, set_category, set_name, add_tags, set_note, split,
                                  priority, enabled, owner_id)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (d["name"], d["pattern"], d["match_field"], d["match_type"], d["min_amount"], d["max_amount"],
             d["account_id"], d["set_category"], d["set_name"], d["add_tags"], d["set_note"],
             Jsonb(d["split"]) if d["split"] else None, d["priority"], d["enabled"],
             me if body.personal else None)).fetchone()
        if d["split"]:
            rules.apply_splits(conn)
        return {"id": row["id"], "rules": rules.listing(conn)}


@router.patch("/rules-v2/{rule_id}")
def edit_rule(rule_id: int, body: RuleIn, request: Request):
    d = _clean(body)
    with _conn() as conn:
        # Any change to the matching or the split invalidates rows it already
        # split, so those are undone first and recreated from the new shape.
        rules.unsplit_rule(conn, rule_id)
        from psycopg.types.json import Jsonb
        n = conn.execute(
            """UPDATE rules SET name=%s, pattern=%s, match_field=%s, match_type=%s, min_amount=%s,
                      max_amount=%s, account_id=%s, set_category=%s, set_name=%s, add_tags=%s,
                      set_note=%s, split=%s, priority=%s, enabled=%s, updated_at=now()
               WHERE id=%s""",
            (d["name"], d["pattern"], d["match_field"], d["match_type"], d["min_amount"], d["max_amount"],
             d["account_id"], d["set_category"], d["set_name"], d["add_tags"], d["set_note"],
             Jsonb(d["split"]) if d["split"] else None, d["priority"], d["enabled"], rule_id)).rowcount
        if not n:
            raise HTTPException(404, "no such rule")
        if d["split"] and d["enabled"]:
            rules.apply_splits(conn)
        return {"rules": rules.listing(conn)}


@router.delete("/rules-v2/{rule_id}")
def delete_rule(rule_id: int, request: Request):
    with _conn() as conn:
        undone = rules.unsplit_rule(conn, rule_id)
        if not conn.execute("DELETE FROM rules WHERE id = %s", (rule_id,)).rowcount:
            raise HTTPException(404, "no such rule")
        return {"ok": True, "unsplit": undone, "rules": rules.listing(conn)}


@router.post("/rules-v2/apply-splits")
def run_splits():
    with _conn() as conn:
        return rules.apply_splits(conn)


# ---------------------------------------------------------------- tags

class TagsIn(BaseModel):
    tags: list[str]


@router.put("/transactions/{txn_id}/tags")
def set_tags(txn_id: str, body: TagsIn):
    clean = sorted({t.strip().lower() for t in body.tags if t.strip()})
    with _conn() as conn:
        n = conn.execute("UPDATE transactions SET tags = %s WHERE id = %s", (clean, txn_id)).rowcount
        if not n:
            raise HTTPException(404, "no such transaction")
        return {"id": txn_id, "tags": clean}


@router.get("/tags")
def tags():
    with _conn() as conn:
        return {"tags": rules.all_tags(conn)}


# ---------------------------------------------------------------- currency

@router.get("/currency")
def currency_status():
    with _conn() as conn:
        return money.status(conn)


class HomeIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)


@router.put("/currency/home")
def set_home(body: HomeIn, request: Request):
    with _conn() as conn:
        money.set_home(conn, body.currency)
        return money.status(conn)


class RateIn(BaseModel):
    currency: str = Field(min_length=3, max_length=3)
    rate: Decimal = Field(gt=0)
    as_of: datetime.date | None = None


@router.put("/currency/rate")
def set_rate(body: RateIn, request: Request):
    """One unit of `currency` is worth this many of the home currency."""
    with _conn() as conn:
        money.set_rate(conn, body.currency, body.rate, body.as_of)
        return money.status(conn)


@router.delete("/currency/rate/{currency}")
def clear_rate(currency: str, request: Request):
    with _conn() as conn:
        conn.execute("DELETE FROM fx_rates WHERE currency = %s", (currency.upper(),))
        return money.status(conn)
