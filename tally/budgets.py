"""Budgets: what a month is meant to cost, and what it is actually doing.

A budget is only useful before the month ends. "You spent $612 of $500" is a
receipt, not a budget -- by the time it is red the money is gone. So every
number here is built to answer the question on day 14 rather than day 31:

  spent        what has gone out so far
  committed    what is already promised -- the subscriptions and bills that
               recur and have not hit yet this month. Money that is spoken for
               is not money you can spend, and no mainstream budget app counts it
  projected    spent + committed + the day-to-day rate applied to the days
               left. The recurring part is deliberately NOT extrapolated:
               rent went out on the 1st and is not going out again, and an
               app that projects it four times over spends the month shouting
               about categories that were never in trouble
  per_day      what is left, after commitments, divided by the days remaining

Rollover is per category (see migration 013). Off, each month starts fresh at
the full amount. On, the leftover or the overspend carries forward, so a
category that funds itself over time -- car repairs, medical, gifts -- actually
works instead of being "under budget" eleven months a year and catastrophic in
the twelfth.
"""
from calendar import monthrange
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import analytics

ZERO = Decimal(0)
# Below this, a suggestion is noise rather than a budget worth keeping.
SUGGEST_FLOOR = Decimal(15)
# A projection off three days of data is a rumour.
PROJECT_AFTER_DAYS = 5


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def month_start(d: date) -> date:
    return d.replace(day=1)


def month_end(d: date) -> date:
    return d.replace(day=monthrange(d.year, d.month)[1])


def add_months(d: date, n: int) -> date:
    m = d.month - 1 + n
    return date(d.year + m // 12, m % 12 + 1, 1)


def effective(conn, month: date) -> dict[str, dict]:
    """The budget in force for each category in `month`: the most recent row
    at or before it, so one row keeps applying until another replaces it.

    In a household, a budget is measured against what the viewer can see --
    shared accounts plus their own. Two partners with everything joint see
    identical numbers; two partners with private accounts each see their own
    side of a shared target. That is a consequence of the privacy rule, not a
    separate decision: showing someone a total they cannot break down would
    mean showing them spending they are not allowed to see.
    """
    rows = conn.execute(
        """SELECT DISTINCT ON (b.category) b.category, b.amount, b.rollover, b.month AS set_on,
                  b.owner_id, c.label, c.icon, c.essential, c.sort
           FROM budgets b JOIN categories c ON c.key = b.category
           WHERE b.month <= %s AND tally_can_see(b.owner_id)
           ORDER BY b.category, b.month DESC, b.owner_id NULLS LAST""", (month,)).fetchall()
    return {r["category"]: {**r, "amount": _q(r["amount"])} for r in rows}


def carry_in(conn, month: date) -> dict[str, Decimal]:
    """What rolls into `month` for the categories that roll over: every earlier
    budgeted month's amount minus what was actually spent in it.

    It accumulates from the first budget ever set for that category. Turning
    rollover on does not retroactively invent a balance for months that were
    never budgeted, because those months have no row to accumulate from.
    """
    first = conn.execute(
        "SELECT min(month) AS m FROM budgets WHERE tally_can_see(owner_id)").fetchone()["m"]
    if first is None or first >= month:
        return {}
    rows = conn.execute(
        """WITH months AS (
               SELECT generate_series(%s::date, %s::date, '1 month')::date AS m
           ), eff AS (
               SELECT months.m, b.category, b.amount, b.rollover
               FROM months
               CROSS JOIN LATERAL (
                   SELECT DISTINCT ON (category) category, amount, rollover
                   FROM budgets WHERE month <= months.m AND tally_can_see(owner_id)
                   ORDER BY category, month DESC, owner_id NULLS LAST
               ) b
           )
           SELECT e.category, sum(e.amount - coalesce(cm.spent, 0)) AS carry
           FROM eff e
           LEFT JOIN v_category_months cm ON cm.month = e.m AND cm.category = e.category
           WHERE e.rollover
           GROUP BY e.category""",
        (first, add_months(month, -1))).fetchall()
    return {r["category"]: _q(r["carry"]) for r in rows}


def _streams(conn) -> list:
    rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income')
             AND date >= current_date - 400""").fetchall()
    return analytics.detect_recurring(rows)


# Anything billed per calendar month has to be stepped per calendar month.
# Rounding "monthly" to 30 days puts a second rent payment in every 31-day
# month, which doubles the commitment on exactly the categories -- rent, loans,
# insurance -- where being wrong is loudest.
_CALENDAR_STEPS = {"monthly": 1, "quarterly": 3, "yearly": 12}


def _shift(s, anchor: date, k: int) -> date:
    months = _CALENDAR_STEPS.get(s.cadence)
    if months:
        d = add_months(anchor, months * k)
        return d.replace(day=min(anchor.day, monthrange(d.year, d.month)[1]))
    return anchor + timedelta(days=round(s.interval_days) * k)


def _occurrences(s, start: date, end: date, limit: int = 6) -> list[date]:
    """When a stream is expected to land between start and end.

    Counted from the last charge actually observed rather than from the
    predicted next one: a real date is a better anchor than an average. The
    same walk answers "has rent already gone out this month" and "what is still
    coming", so the two can never disagree.
    """
    step = max(1.0, float(s.interval_days))
    lo = int((start - s.last_date).days // step) - 1
    hi = int((end - s.last_date).days // step) + 1
    out = []
    for k in range(lo, hi + 1):
        d = _shift(s, s.last_date, k)
        if start <= d <= end:
            out.append(d)
            if len(out) >= limit:
                break
    return out


def upcoming(streams, start: date, end: date) -> tuple[dict[str, Decimal], dict[str, list]]:
    """Recurring charges expected between start and end, per category."""
    totals: dict[str, Decimal] = {}
    detail: dict[str, list] = {}
    for s in streams:
        if s.kind != "expense" or not s.active:
            continue
        for d in _occurrences(s, start, end):
            totals[s.category] = totals.get(s.category, ZERO) + s.typical_amount
            detail.setdefault(s.category, []).append(
                {"name": s.name, "logo_url": s.logo_url, "date": d, "amount": _q(s.typical_amount)})
    return {k: _q(v) for k, v in totals.items()}, detail


def status(conn, month: date | None = None, today: date | None = None, streams: list | None = None) -> dict:
    """The whole month in one read: per-category and totals.

    `streams` is accepted so a caller that has already detected recurring
    charges -- the alert scan does -- does not pay for it twice.
    """
    today = today or date.today()
    month = month_start(month or today)
    last = month_end(month)
    days = last.day

    # A past month is fully elapsed; a future one has not started. Only the
    # current month gets a partial day count, and that is the only month where
    # pace and projection mean anything.
    if last < today:
        elapsed, current = days, False
    elif month > today:
        elapsed, current = 0, False
    else:
        elapsed, current = today.day, True
    days_left = days - elapsed

    budgets = effective(conn, month)
    carry = carry_in(conn, month)
    spent_rows = conn.execute(
        "SELECT category, spent, transactions FROM v_category_months WHERE month = %s", (month,)).fetchall()
    spent = {r["category"]: _q(r["spent"]) for r in spent_rows}
    counts = {r["category"]: r["transactions"] for r in spent_rows}

    commit_total, commit_detail, paid_already = ({}, {}, {})
    if current:
        found = _streams(conn) if streams is None else streams
        if days_left > 0:
            commit_total, commit_detail = upcoming(found, today + timedelta(days=1), last)
        paid_already, _ = upcoming(found, month, today)

    out = []
    for key, b in budgets.items():
        amount = b["amount"]
        c_in = carry.get(key, ZERO) if b["rollover"] else ZERO
        available = amount + c_in
        used = spent.get(key, ZERO)
        due = commit_total.get(key, ZERO)
        remaining = available - used
        left = remaining - due

        projected = None
        if current and elapsed >= PROJECT_AFTER_DAYS:
            # Only the day-to-day part of a month repeats. Rent went out on the
            # 1st and is not going out again; extrapolating it says a $2,150
            # rent budget is heading for $3,794 by the 17th, which is how a
            # budget app ends up crying wolf in every category that holds a bill.
            day_to_day = max(used - paid_already.get(key, ZERO), ZERO)
            rest = day_to_day / Decimal(elapsed) * Decimal(days_left)
            projected = _q(used + due + rest)
        elif not current and elapsed:
            projected = used

        if used > available:
            state = "over"
        elif projected is not None and projected > available:
            state = "watch"
        else:
            state = "under"

        out.append({
            "category": key, "label": b["label"], "icon": b["icon"], "essential": b["essential"],
            "amount": amount, "rollover": b["rollover"], "carry_in": _q(c_in), "set_on": b["set_on"],
            "owner_id": b["owner_id"], "personal": b["owner_id"] is not None,
            "available": _q(available), "spent": used, "committed": due, "transactions": counts.get(key, 0),
            "remaining": _q(remaining), "left_after_commitments": _q(left),
            "percent": float(used / available) if available > 0 else None,
            "projected": projected, "state": state,
            "per_day": _q(left / Decimal(days_left)) if days_left > 0 and left > 0 else None,
            "upcoming": commit_detail.get(key, []),
            "sort": b["sort"],
        })
    out.sort(key=lambda r: (r["state"] != "over", r["state"] != "watch", -float(r["spent"])))

    # Spending with no budget behind it. Mint's quiet failure was letting the
    # month leak out through categories nobody had budgeted, so it is named here
    # rather than left out of the totals.
    unbudgeted = [
        {"category": k, "spent": v, "label": lbl, "icon": icon}
        for k, v, lbl, icon in (
            (r["category"], _q(r["spent"]), r["label"], r["icon"]) for r in conn.execute(
                """SELECT cm.category, cm.spent, c.label, c.icon
                   FROM v_category_months cm JOIN categories c ON c.key = cm.category
                   WHERE cm.month = %s ORDER BY cm.spent DESC""", (month,)).fetchall())
        if k not in budgets and v > 0
    ]

    budgeted = sum((r["available"] for r in out), ZERO)
    used_total = sum((r["spent"] for r in out), ZERO)
    due_total = sum((r["committed"] for r in out), ZERO)
    leak = sum((r["spent"] for r in unbudgeted), ZERO)
    projected_total = sum((r["projected"] for r in out if r["projected"] is not None), ZERO)

    income = conn.execute(
        """SELECT coalesce(sum(income), 0) AS earned FROM v_txn
           WHERE kind = 'income' AND date BETWEEN %s AND %s""", (month, last)).fetchone()["earned"]

    return {
        "month": month, "days": days, "elapsed": elapsed, "days_left": days_left, "current": current,
        "pace": round(elapsed / days, 4),
        "categories": out, "unbudgeted": unbudgeted,
        "budgeted": _q(budgeted), "spent": _q(used_total), "committed": _q(due_total),
        "remaining": _q(budgeted - used_total), "left_after_commitments": _q(budgeted - used_total - due_total),
        "projected": _q(projected_total) if projected_total else None,
        "unbudgeted_spent": _q(leak),
        "total_spent": _q(used_total + leak),
        "income": _q(income),
        "any": bool(out),
    }


def _round_sensibly(v: Decimal) -> Decimal:
    """Budgets are decisions, not measurements. $247.13 pretends to a precision
    nobody holds themselves to; $250 is the number a person would actually say."""
    step = Decimal(5) if v < 100 else Decimal(10) if v < 500 else Decimal(25)
    return (v / step).quantize(Decimal(1), rounding=ROUND_HALF_UP) * step


def suggest(conn, months: int = 3, today: date | None = None) -> list[dict]:
    """Starting amounts from what the last few complete months actually cost.

    The median, not the mean: one blown month or one holiday should not set the
    budget for every month after it. Complete months only -- the current one is
    half-finished and would suggest half the real number.
    """
    today = today or date.today()
    end = month_start(today)                      # exclusive: skip the partial month
    start = add_months(end, -months)
    rows = conn.execute(
        """SELECT cm.category, c.label, c.icon, c.essential, c.sort,
                  percentile_cont(0.5) WITHIN GROUP (ORDER BY cm.spent) AS median,
                  count(*) AS months, max(cm.spent) AS worst
           FROM v_category_months cm JOIN categories c ON c.key = cm.category
           WHERE cm.month >= %s AND cm.month < %s AND cm.spent > 0
           GROUP BY 1,2,3,4,5 ORDER BY 5""", (start, end)).fetchall()
    existing = {r["category"] for r in conn.execute(
        "SELECT DISTINCT category FROM budgets WHERE tally_can_see(owner_id)").fetchall()}

    out = []
    for r in rows:
        median = _q(r["median"])
        if median < SUGGEST_FLOOR:
            continue
        out.append({
            "category": r["category"], "label": r["label"], "icon": r["icon"], "essential": r["essential"],
            "amount": _round_sensibly(median), "median": median, "worst": _q(r["worst"]),
            "months": r["months"], "already_budgeted": r["category"] in existing,
            # Repairs, medical and gifts arrive in lumps. A fixed monthly target
            # for them is wrong every single month; rollover is what makes them work.
            "rollover": r["category"] in ("home", "health", "auto", "giving"),
        })
    return out


def alerts(conn, today: date | None = None, streams: list | None = None) -> list[dict]:
    """Two worth interrupting someone for: a category already over, and one
    heading over with enough of the month left to do something about it."""
    today = today or date.today()
    s = status(conn, today, today, streams)
    if not s["current"]:
        return []
    out = []
    for c in s["categories"]:
        if c["state"] == "over":
            over = c["spent"] - c["available"]
            out.append({
                "kind": "budget_over", "category": c["category"], "severity": "low",
                "title": f"{c['label']} is ${over:,.2f} over budget",
                "detail": f"${c['spent']:,.2f} spent of ${c['available']:,.2f} with {s['days_left']} days left "
                          f"in the month.",
                "amount": _q(over), "occurred_on": today,
                "fingerprint": f"budget_over:{c['category']}:{s['month']:%Y-%m}",
            })
        elif c["state"] == "watch" and s["days_left"] >= 7:
            # "$0.00 a day keeps it inside" is a lie when the bills still to
            # come already spend more than is left. Say which of the two it is.
            if c["per_day"] is not None:
                advice = f"About ${c['per_day']:,.2f} a day for the rest of the month keeps it inside."
            elif c["committed"] > 0:
                advice = (f"${c['committed']:,.2f} of bills still to come this month puts it over on their "
                          f"own, so this one needs a bigger budget rather than more care.")
            else:
                advice = "Nothing is left in it for the rest of the month."
            out.append({
                "kind": "budget_pace", "category": c["category"], "severity": "low",
                "title": f"{c['label']} is on pace to go over",
                "detail": f"${c['spent']:,.2f} of ${c['available']:,.2f} by day {s['elapsed']}, heading for "
                          f"about ${c['projected']:,.2f}. {advice}",
                "amount": _q(c["projected"] - c["available"]), "occurred_on": today,
                "fingerprint": f"budget_pace:{c['category']}:{s['month']:%Y-%m}",
            })
    return out
