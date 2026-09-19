"""Plan routes: runway, payments due, payoff. Goals live in routes_more."""
from dataclasses import asdict
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from psycopg.types.json import Jsonb
from pydantic import BaseModel, Field

from . import bills, brief, income, invest, plan, scope, sync
from .state import state

router = APIRouter(prefix="/api")

DEFAULTS = {"monthly_extra": "0", "cash_buffer": "0", "strategy": "avalanche"}


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


def _settings(conn) -> dict:
    rows = {r["key"]: r["value"] for r in conn.execute("SELECT key, value FROM app_settings").fetchall()}
    return {**DEFAULTS, **rows}


def _payoff_json(p: plan.Payoff) -> dict:
    return asdict(p)


@router.get("/plan")
def get_plan():
    with _conn() as conn:
        s = _settings(conn)
        extra = Decimal(str(s["monthly_extra"]))
        buffer = Decimal(str(s["cash_buffer"]))
        rw = plan.runway(conn, buffer=buffer)
        ds = plan.debts(conn)
        cmp_ = plan.compare(ds, extra) if ds else None
        return {
            "settings": s,
            "mode": plan.mode(conn, rw, ds),
            "runway": rw,
            "essentials_per_month": plan.essentials_per_month(conn),
            "debts": [{**asdict(d), "monthly_interest": d.monthly_interest, "utilization": d.utilization}
                      for d in ds],
            "debt_total": sum((d.balance for d in ds), Decimal(0)),
            "monthly_interest_total": sum((d.monthly_interest for d in ds), Decimal(0)),
            "minimums_total": sum((d.minimum for d in ds), Decimal(0)),
            "utilization": _utilization(ds),
            "payoff": None if not cmp_ else {
                "strategy": s["strategy"],
                "chosen": _payoff_json(cmp_["plans"][s["strategy"]] if s["strategy"] in cmp_["plans"]
                                       else cmp_["plans"]["avalanche"]),
                "minimums": _payoff_json(cmp_["minimums"]),
                "avalanche": _payoff_json(cmp_["plans"]["avalanche"]),
                "snowball": _payoff_json(cmp_["plans"]["snowball"]),
                "interest_saved": cmp_["interest_saved"],
                "months_saved": cmp_["months_saved"],
            },
            "goals": plan.goals(conn),
            "suggested_goals": plan.suggested_goals(conn, rw, ds),
        }


def _utilization(ds: list[plan.Debt]) -> dict | None:
    cards = [d for d in ds if d.kind == "credit" and d.credit_limit]
    if not cards:
        return None
    used = sum((d.balance for d in cards), Decimal(0))
    limit = sum((d.credit_limit for d in cards), Decimal(0))
    return {"used": used, "limit": limit, "percent": float(used / limit) if limit else None,
            "cards": [{"account_id": d.account_id, "name": d.name, "mask": d.mask, "balance": d.balance,
                       "limit": d.credit_limit, "percent": d.utilization} for d in cards]}


@router.get("/payoff")
def payoff(extra: float = 0, strategy: str = "avalanche", target: str | None = None):
    """What a given monthly extra does. Drives the slider, so it stays cheap."""
    if strategy not in plan.STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    with _conn() as conn:
        ds = plan.debts(conn)
    if not ds:
        return {"debts": 0}
    if target:  # "what if I attack this one instead"
        ds = sorted(ds, key=lambda d: d.account_id != target)
        strategy = "custom"
        result = plan.simulate(ds, Decimal(str(extra)), "minimums-order")
    else:
        result = plan.simulate(ds, Decimal(str(extra)), strategy)
    base = plan.simulate(ds, Decimal(0), "minimums")
    return {
        "result": _payoff_json(result), "minimums": _payoff_json(base),
        "interest_saved": base.total_interest - result.total_interest,
        "months_saved": (base.months - result.months) if (base.months and result.months) else None,
    }


class PlanSettings(BaseModel):
    monthly_extra: Decimal | None = Field(default=None, ge=0)
    cash_buffer: Decimal | None = Field(default=None, ge=0)
    strategy: str | None = None


@router.put("/plan/settings")
def put_settings(body: PlanSettings):
    if body.strategy and body.strategy not in plan.STRATEGIES:
        raise HTTPException(400, "unknown strategy")
    with _conn() as conn:
        for key, value in body.model_dump(exclude_none=True).items():
            conn.execute(
                """INSERT INTO app_settings (key, value, updated_at) VALUES (%s, %s, now())
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                (key, Jsonb(str(value))))
        return _settings(conn)


class GoalIn(BaseModel):
    name: str = Field(min_length=1, max_length=60)
    kind: str = Field(pattern="^(emergency|savings|payoff|custom)$")
    target_amount: Decimal = Field(gt=0)
    account_id: str | None = None
    monthly_contribution: Decimal | None = Field(default=None, ge=0)
    target_date: date | None = None


# Goals live in routes_more.py. They started here as "progress against one
# savings account" and grew into "are you on track, at the pace you are
# actually moving" -- the same table, the richer read. Two endpoints for one
# concept is how an app ends up with two answers to the same question.

@router.get("/notify/status")
def notify_status():
    n = state.get("notifier")
    s = n.status() if n else {"enabled": False, "reason": "not configured"}
    with _conn() as conn:
        recent = conn.execute(
            """SELECT kind, title, ok, error, created_at FROM notifications
               ORDER BY id DESC LIMIT 5""").fetchall()
        week = conn.execute("SELECT value FROM app_settings WHERE key = 'last_brief_week'").fetchone()
    return {**s, "recent": recent, "last_brief_week": week["value"] if week else None}


@router.post("/notify/test")
def notify_test():
    n = state.get("notifier")
    if not n or not n.enabled:
        raise HTTPException(503, "notifications are not configured")
    ok = n.send("Tally is connected", "Alerts and the weekly brief will arrive here.",
                kind="test", priority=3, tag="wave", path="/")
    if not ok:
        raise HTTPException(502, "ntfy did not accept the message")
    return {"sent": True}


@router.get("/brief/preview")
def brief_preview():
    """What this week's brief would say, without sending it."""
    with _conn() as conn:
        f = brief.facts(conn)
        title, body = brief.compose(f)
    return {"title": title, "body": body, "facts": f}


@router.post("/brief/send")
def brief_send():
    n = state.get("notifier")
    if not n or not n.enabled:
        raise HTTPException(503, "notifications are not configured")
    with _conn() as conn:
        return brief.send_weekly(conn, state["pool"], n, force=True)


@router.get("/whatif")
def whatif(monthly_income: float = 0, extra_to_debt: float = 0, cut_flexible_percent: float = 0):
    with _conn() as conn:
        return plan.what_if(conn, Decimal(str(monthly_income)), Decimal(str(extra_to_debt)),
                            Decimal(str(cut_flexible_percent)))


@router.get("/income/freelance")
def freelance(year: int | None = None):
    with _conn() as conn:
        s = _settings(conn)
        rate = Decimal(str(s.get("tax_rate", income.DEFAULT_RATE)))
        return income.summary(conn, year, rate)


class TaxSettings(BaseModel):
    tax_rate: Decimal | None = Field(default=None, ge=0, le=60)
    tax_account_id: str | None = None


@router.put("/income/settings")
def put_tax_settings(body: TaxSettings):
    with _conn() as conn:
        for key, value in body.model_dump(exclude_none=True).items():
            conn.execute(
                """INSERT INTO app_settings (key, value, updated_at) VALUES (%s,%s, now())
                   ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""",
                (key, Jsonb(str(value))))
        return _settings(conn)


@router.get("/bills")
def negotiable_bills():
    """Recurring bills where asking for a better price actually works."""
    with _conn() as conn:
        return bills.negotiable(conn)


# ---------------------------------------------------------------- investments

@router.get("/investments")
def investments():
    with _conn() as conn:
        return invest.portfolio(conn)


@router.post("/investments/sync")
def refresh_investments():
    out = {}
    with _conn() as conn:
        items = [r["id"] for r in conn.execute("SELECT id FROM items WHERE status = 'ok'").fetchall()]
    for item_id in items:
        with _conn() as conn:
            try:
                out[item_id] = sync.sync_investments(conn, state["plaid"], state["box"], item_id)
            except Exception as e:
                out[item_id] = f"error: {e}"
    return out


@router.post("/liabilities/sync")
def refresh_liabilities():
    """Pull APRs, minimums and due dates again. Cheap, and the numbers that
    matter most here are the ones that change on a statement cycle."""
    out = {}
    with _conn() as conn:
        items = [r["id"] for r in conn.execute("SELECT id FROM items WHERE status = 'ok'").fetchall()]
    for item_id in items:
        with _conn() as conn:
            try:
                out[item_id] = sync.sync_liabilities(conn, state["plaid"], state["box"], item_id)
            except Exception as e:
                out[item_id] = f"error: {e}"
    return out
