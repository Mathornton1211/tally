"""Fees, alerts, insights, per-account settings, and merchant category rules."""
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from . import fees, insights, monitor, scope
from .state import state

router = APIRouter(prefix="/api")


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


# ---------------------------------------------------------------- fees

@router.get("/fees")
def fee_report(start: date | None = None, end: date | None = None):
    end = end or date.today()
    start = start or (end - timedelta(days=364))
    with _conn() as conn:
        return fees.report(conn, start, end)


# ---------------------------------------------------------------- alerts

@router.get("/alerts")
def list_alerts(status: str = "open", scan: bool = True):
    with _conn() as conn:
        if scan:
            monitor.scan(conn)
        where = "true" if status == "all" else "a.status = %s"
        params = [] if status == "all" else [status]
        rows = conn.execute(
            f"""SELECT a.*, acc.name AS account_name, acc.mask AS account_mask,
                       coalesce((SELECT json_agg(json_build_object(
                           'id', v.id, 'date', v.date, 'amount', v.amount, 'display_name', v.display_name,
                           'name', v.name, 'logo_url', v.logo_url, 'category_icon', v.category_icon,
                           'account_name', v.account_name, 'account_mask', v.account_mask) ORDER BY v.date, v.id)
                         FROM v_txn v WHERE v.id = ANY(a.txn_ids)), '[]') AS transactions
                FROM alerts a LEFT JOIN accounts acc ON acc.id = a.account_id
                WHERE {where}
                ORDER BY CASE a.severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                         a.occurred_on DESC, a.id DESC
                LIMIT 300""", params).fetchall()
        counts = conn.execute(
            """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                      count(*) FILTER (WHERE status = 'open' AND severity IN ('high','medium')) AS urgent,
                      count(*) FILTER (WHERE status = 'fraud') AS fraud,
                      count(*) FILTER (WHERE status IN ('expected','dismissed')) AS resolved
               FROM alerts""").fetchone()
    return {"counts": counts, "alerts": rows}


@router.post("/alerts/scan")
def scan_alerts():
    with _conn() as conn:
        return monitor.scan(conn)


class AlertUpdate(BaseModel):
    status: str = Field(pattern="^(open|expected|dismissed|fraud)$")
    trust_merchant: bool = False


@router.post("/alerts/{alert_id}")
def update_alert(alert_id: int, body: AlertUpdate):
    with _conn() as conn:
        row = conn.execute(
            """UPDATE alerts SET status = %s, resolved_at = CASE WHEN %s = 'open' THEN NULL ELSE now() END
               WHERE id = %s RETURNING rule, merchant_key""", (body.status, body.status, alert_id)).fetchone()
        if not row:
            raise HTTPException(404, "no such alert")
        if body.trust_merchant and body.status == "expected" and row["merchant_key"]:
            conn.execute("INSERT INTO alert_trust (rule, merchant_key) VALUES (%s, %s) ON CONFLICT DO NOTHING",
                         (row["rule"], row["merchant_key"]))
    return {"ok": True}



# ---------------------------------------------------------------- insights

@router.get("/insights")
def get_insights():
    with _conn() as conn:
        return insights.compute(conn)


# ---------------------------------------------------------------- account settings

class AccountSettings(BaseModel):
    apy: Decimal | None = Field(default=None, ge=0, le=100)
    apr: Decimal | None = Field(default=None, ge=0, le=100)
    annual_fee: Decimal | None = Field(default=None, ge=0)
    foreign_fee_pct: Decimal | None = Field(default=None, ge=0, le=10)
    min_balance_waiver: Decimal | None = Field(default=None, ge=0)
    reward_rate: Decimal | None = Field(default=None, ge=0, le=20)
    note: str | None = None
    hidden: bool | None = None


@router.get("/accounts/{account_id}/settings")
def get_settings(account_id: str):
    with _conn() as conn:
        row = conn.execute(
            """SELECT a.id, a.name, a.mask, a.type, a.subtype, a.hidden, s.apy, s.apr, s.annual_fee,
                      s.foreign_fee_pct, s.min_balance_waiver, s.reward_rate, s.note
               FROM v_acct a LEFT JOIN account_settings s ON s.account_id = a.id WHERE a.id = %s""",
            (account_id,)).fetchone()
    if not row:
        raise HTTPException(404, "no such account")
    return row


@router.put("/accounts/{account_id}/settings")
def put_settings(account_id: str, body: AccountSettings):
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM v_acct WHERE id = %s", (account_id,)).fetchone():
            raise HTTPException(404, "no such account")
        conn.execute(
            """INSERT INTO account_settings (account_id, apy, apr, annual_fee, foreign_fee_pct,
                   min_balance_waiver, reward_rate, note, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (account_id) DO UPDATE SET apy = EXCLUDED.apy, apr = EXCLUDED.apr,
                 annual_fee = EXCLUDED.annual_fee, foreign_fee_pct = EXCLUDED.foreign_fee_pct,
                 min_balance_waiver = EXCLUDED.min_balance_waiver, reward_rate = EXCLUDED.reward_rate,
                 note = EXCLUDED.note, updated_at = now()""",
            (account_id, body.apy, body.apr, body.annual_fee, body.foreign_fee_pct,
             body.min_balance_waiver, body.reward_rate, body.note))
        if body.hidden is not None:
            conn.execute("UPDATE accounts SET hidden = %s WHERE id = %s", (body.hidden, account_id))
    return get_settings(account_id)


# ---------------------------------------------------------------- category rules

class RuleIn(BaseModel):
    merchant_key: str
    category: str


@router.get("/rules/preview")
def rule_preview(merchant_key: str):
    with _conn() as conn:
        return conn.execute(
            """SELECT count(*) AS count, count(*) FILTER (WHERE category_overridden) AS overridden
               FROM v_txn WHERE merchant_key = %s""", (merchant_key,)).fetchone()


@router.post("/rules")
def create_rule(body: RuleIn):
    """Every transaction from this merchant, past and future, gets this category.

    One-off edits on that merchant are cleared so they follow the rule; that is
    what "apply to all" means to the person pressing it.
    """
    with _conn() as conn:
        if not conn.execute("SELECT 1 FROM categories WHERE key = %s", (body.category,)).fetchone():
            raise HTTPException(400, "unknown category")
        conn.execute(
            """INSERT INTO category_rules (merchant_key, category) VALUES (%s, %s)
               ON CONFLICT (merchant_key) DO UPDATE SET category = EXCLUDED.category, created_at = now()""",
            (body.merchant_key, body.category))
        cleared = conn.execute(
            """UPDATE transactions SET category = NULL, updated_at = now()
               WHERE category IS NOT NULL AND id IN (SELECT id FROM v_txn WHERE merchant_key = %s)""",
            (body.merchant_key,)).rowcount
        n = conn.execute("SELECT count(*) AS n FROM v_txn WHERE merchant_key = %s", (body.merchant_key,)).fetchone()["n"]
    return {"merchant_key": body.merchant_key, "category": body.category, "applied_to": n, "cleared_overrides": cleared}


@router.get("/rules")
def list_rules():
    with _conn() as conn:
        return conn.execute(
            """SELECT r.merchant_key, r.category, c.label, c.icon, r.created_at,
                      (SELECT count(*) FROM v_txn v WHERE v.merchant_key = r.merchant_key) AS transactions
               FROM category_rules r JOIN categories c ON c.key = r.category ORDER BY r.created_at DESC""").fetchall()


@router.delete("/rules/{merchant_key}")
def delete_rule(merchant_key: str):
    with _conn() as conn:
        n = conn.execute("DELETE FROM category_rules WHERE merchant_key = %s", (merchant_key,)).rowcount
    if not n:
        raise HTTPException(404, "no such rule")
    return {"ok": True}
