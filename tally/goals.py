"""Goals with a destination and a trajectory.

`plan.goals()` answers "how full is this savings account". This answers the
harder one: given where the whole picture is going, do you arrive, and if not,
what would have to change.

The trajectory is measured, not assumed. It comes from how net worth has
actually moved over the last few months, which means a goal gets less
optimistic on its own when a month goes badly -- rather than holding a cheerful
projection that was true in March.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import analytics

ZERO = Decimal(0)
# Below this many months of history the slope is noise, not a trend.
MIN_MONTHS_FOR_TREND = 2
TREND_DAYS = 180


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _networth_series(conn, days: int = TREND_DAYS) -> list[dict]:
    end = date.today()
    start = end - timedelta(days=days)
    accounts = conn.execute(
        """SELECT id, name, type, subtype, current_balance, credit_limit
           FROM v_acct WHERE NOT hidden""").fetchall()
    flows = conn.execute(
        "SELECT account_id, date, sum(amount) AS amount FROM v_txn WHERE date >= %s GROUP BY 1,2",
        (start,)).fetchall()
    return analytics.estimate_balance_history(accounts, flows, start, end)


def _positions(conn) -> dict:
    """Where the household stands right now, per goal kind."""
    rows = conn.execute(
        """SELECT type, coalesce(sum(current_balance), 0) AS total
           FROM v_acct WHERE NOT hidden GROUP BY type""").fetchall()
    by_type = {r["type"]: _q(r["total"]) for r in rows}
    assets = sum((v for k, v in by_type.items() if k not in analytics.LIABILITY_TYPES), ZERO)
    debts = sum((v for k, v in by_type.items() if k in analytics.LIABILITY_TYPES), ZERO)
    savings = conn.execute(
        """SELECT coalesce(sum(current_balance), 0) AS total FROM v_acct
           WHERE NOT hidden AND type = 'depository'
             AND coalesce(subtype, '') IN ('savings', 'money market', 'cd')""").fetchone()["total"]
    # Everyday spending, for turning "six months of expenses" into a number.
    monthly_spend = conn.execute(
        """SELECT coalesce(sum(spend), 0) / 3 AS m FROM v_txn
           WHERE kind = 'expense' AND date >= current_date - 92""").fetchone()["m"]
    cash = conn.execute(
        """SELECT coalesce(sum(current_balance), 0) AS total FROM v_acct
           WHERE NOT hidden AND type = 'depository'""").fetchone()["total"]
    return {
        "net_worth": assets - debts, "savings": _q(savings), "debt_free": debts,
        "emergency_fund": _q(cash), "monthly_spend": _q(monthly_spend),
    }


def _slope(series: list[dict]) -> Decimal | None:
    """Change in net worth per month, from the ends of the measured series.

    Deliberately not a least-squares fit. The series is a balance estimate
    walked back from today's balances, so its early values carry the most
    accumulated error; a regression would weight that error as though it were
    signal. First-to-last over the period is cruder and harder to mislead.
    """
    if len(series) < 2:
        return None
    first, last = series[0], series[-1]
    days = (last["date"] - first["date"]).days
    if days < MIN_MONTHS_FOR_TREND * 30:
        return None
    start_nw = Decimal(first["assets"]) - Decimal(first["liabilities"])
    end_nw = Decimal(last["assets"]) - Decimal(last["liabilities"])
    return _q((end_nw - start_nw) / Decimal(days) * Decimal("30.4"))


def target_for(goal: dict, pos: dict) -> Decimal:
    """A goal in months of spending resolves to a number now, so it moves when
    life does instead of going stale."""
    if goal["kind"] == "debt_free":
        return ZERO
    if goal["target_months"] is not None:
        return _q(Decimal(goal["target_months"]) * pos["monthly_spend"])
    return _q(goal["target_amount"])


def evaluate(conn, today: date | None = None) -> dict:
    today = today or date.today()
    pos = _positions(conn)
    series = _networth_series(conn)
    slope = _slope(series)

    rows = conn.execute(
        """SELECT g.*, a.name AS account_name, coalesce(a.current_balance, 0) AS account_balance
           FROM goals g LEFT JOIN v_acct a ON a.id = g.account_id
           WHERE NOT g.archived AND tally_can_see(g.owner_id)
             AND g.kind IN ('net_worth', 'debt_free', 'emergency_fund', 'savings')
           ORDER BY g.target_date NULLS LAST, g.id""").fetchall()

    out = []
    for g in rows:
        kind = g["kind"]
        target = target_for(g, pos)
        current = _q(g["account_balance"]) if g["account_id"] else pos.get(kind, ZERO)

        # Debt is the one goal where the number going DOWN is progress, so
        # "remaining" and "percent" both have to be read the other way up.
        if kind == "debt_free":
            remaining = current
            percent = None if current <= 0 else 0.0
            done = current <= 0
            pace = -slope if slope is not None else None
        else:
            remaining = max(target - current, ZERO)
            percent = float(min(current / target, 1)) if target > 0 else None
            done = remaining <= 0
            pace = slope

        months_needed = None
        if g["target_date"]:
            months_needed = max(Decimal("0.1"), Decimal((g["target_date"] - today).days) / Decimal("30.4"))
        required = _q(remaining / months_needed) if months_needed and remaining > 0 else None

        eta = months_at_pace = None
        if remaining > 0 and pace and pace > 0:
            months_at_pace = int((remaining / pace).to_integral_value(rounding=ROUND_HALF_UP))
            # Cap the horizon rather than print "arrives in 2174".
            eta = today + timedelta(days=int(30.4 * months_at_pace)) if months_at_pace <= 720 else None

        if done:
            state = "done"
        elif required is None:
            state = "no_deadline"
        elif pace is None:
            state = "too_early"
        elif pace >= required:
            state = "on_track"
        else:
            state = "behind"

        out.append({
            **g, "target": target, "current": current, "remaining": remaining, "percent": percent,
            "required_per_month": required, "pace_per_month": _q(pace) if pace is not None else None,
            "months_at_pace": months_at_pace, "eta": eta, "state": state, "done": done,
            "shortfall_per_month": _q(required - pace) if (required is not None and pace is not None
                                                           and required > pace) else None,
        })

    return {
        "goals": out, "net_worth": pos["net_worth"], "pace_per_month": slope,
        "monthly_spend": pos["monthly_spend"], "measured_over_days": TREND_DAYS,
        "series": series,
        "positions": pos,
    }


def suggestions(conn) -> list[dict]:
    """Goals worth having that the household has not set, phrased as the
    standard advice rather than invented numbers."""
    pos = _positions(conn)
    have = {r["kind"] for r in conn.execute(
        "SELECT DISTINCT kind FROM goals WHERE NOT archived AND tally_can_see(owner_id)").fetchall()}
    out = []
    if "emergency_fund" not in have and pos["monthly_spend"] > 0:
        out.append({"kind": "emergency_fund", "name": "Emergency fund",
                    "target_months": 3,
                    "why": f"Three months of spending is about {pos['monthly_spend'] * 3:,.0f}. "
                           f"It is the cushion that stops the next surprise going on a card."})
    if "debt_free" not in have and pos["debt_free"] > 0:
        out.append({"kind": "debt_free", "name": "Debt free",
                    "why": f"{pos['debt_free']:,.0f} owed across cards and loans. A date to aim at "
                           f"makes the payoff plan a schedule instead of a hope."})
    if "net_worth" not in have:
        rounded = (pos["net_worth"] // 10000 + 1) * 10000
        out.append({"kind": "net_worth", "name": f"Net worth of {rounded:,.0f}",
                    "target_amount": rounded,
                    "why": "One number for the whole picture, so progress is visible even in a month "
                           "where nothing feels like it moved."})
    return out
