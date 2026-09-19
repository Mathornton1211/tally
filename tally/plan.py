"""Runway, upcoming payments, and debt payoff. HANDOFF section 7 extended.

Written for the situation the owner is actually in: several cards, income that is not
a salary, and a need to know two things before anything else.

  1. Do I make it to the next money, and what is due before then?
  2. Which card do I attack, and when does this end?

The simulation and the projection are pure functions over plain rows, so the
numbers can be checked by hand in tests. No model is involved anywhere here.
"""
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from . import analytics

CENTS = Decimal("0.01")
ZERO = Decimal(0)
MAX_MONTHS = 600  # 50 years. Past this a plan is not a plan.


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(CENTS, rounding=ROUND_HALF_UP)


# ---------------------------------------------------------------- debts

@dataclass
class Debt:
    account_id: str
    name: str
    mask: str | None
    kind: str                     # credit | loan
    balance: Decimal
    apr: Decimal | None
    apr_source: str               # issuer | entered | estimated | unknown
    minimum: Decimal
    minimum_source: str           # issuer | assumed
    due_date: date | None
    is_overdue: bool
    credit_limit: Decimal | None

    @property
    def monthly_interest(self) -> Decimal:
        if not self.apr:
            return ZERO
        return _q(self.balance * self.apr / Decimal(1200))

    @property
    def utilization(self) -> float | None:
        if not self.credit_limit or self.credit_limit <= 0:
            return None
        return float(self.balance / self.credit_limit)


# A card's minimum is typically the greater of a percent of the balance and a
# floor. Used only when the issuer did not tell us, and labelled as assumed.
ASSUMED_MIN_PERCENT = Decimal("0.02")
ASSUMED_MIN_FLOOR = Decimal("35")


def assumed_minimum(balance: Decimal, apr: Decimal | None) -> Decimal:
    if balance <= 0:
        return ZERO
    interest = (balance * (apr or ZERO) / Decimal(1200))
    return _q(max(balance * ASSUMED_MIN_PERCENT, ASSUMED_MIN_FLOOR, interest + Decimal(10), ZERO))


def debts(conn) -> list[Debt]:
    rows = conn.execute(
        """SELECT a.id, a.name, a.mask, a.type, a.current_balance, a.credit_limit,
                  l.apr AS issuer_apr, l.minimum_payment, l.next_due_date, l.is_overdue,
                  s.apr AS entered_apr
           FROM v_acct a
           LEFT JOIN liabilities l ON l.account_id = a.id
           LEFT JOIN account_settings s ON s.account_id = a.id
           WHERE NOT a.hidden AND a.type IN ('credit', 'loan')
             AND coalesce(a.current_balance, 0) > 0
           ORDER BY a.current_balance DESC""").fetchall()
    # Effective rate from interest actually charged, when nobody told us the APR.
    estimated = {r["account_id"]: r["rate"] for r in conn.execute(
        """SELECT account_id,
                  round(sum(amount) * 4 / nullif(max(bal), 0) * 100, 2) AS rate
           FROM (SELECT v.account_id, v.amount, a.current_balance AS bal
                 FROM v_txn v JOIN accounts a ON a.id = v.account_id
                 WHERE v.date >= current_date - 90 AND v.amount > 0
                   AND (v.pfc_detailed = 'BANK_FEES_INTEREST_CHARGE' OR v.bank_text ~* 'INTEREST CHARGE')) t
           GROUP BY account_id""").fetchall() if r["rate"]}

    out = []
    for r in rows:
        apr, src = None, "unknown"
        if r["issuer_apr"] is not None:
            apr, src = Decimal(r["issuer_apr"]), "issuer"
        elif r["entered_apr"] is not None:
            apr, src = Decimal(r["entered_apr"]), "entered"
        elif r["id"] in estimated:
            apr, src = Decimal(estimated[r["id"]]), "estimated"
        balance = _q(r["current_balance"])
        if r["minimum_payment"] is not None:
            minimum, min_src = _q(r["minimum_payment"]), "issuer"
        else:
            minimum, min_src = assumed_minimum(balance, apr), "assumed"
        out.append(Debt(
            account_id=r["id"], name=r["name"], mask=r["mask"],
            kind="credit" if r["type"] == "credit" else "loan",
            balance=balance, apr=apr, apr_source=src, minimum=minimum, minimum_source=min_src,
            due_date=r["next_due_date"], is_overdue=bool(r["is_overdue"]),
            credit_limit=_q(r["credit_limit"]) if r["credit_limit"] else None))
    return out


# ---------------------------------------------------------------- payoff

STRATEGIES = {
    "avalanche": "Highest rate first. Costs the least.",
    "snowball": "Smallest balance first. First win comes soonest.",
    "minimums": "Minimum payments only.",
}


@dataclass
class Payoff:
    strategy: str
    months: int | None                  # None = never, at this payment level
    payoff_date: date | None
    total_interest: Decimal
    total_paid: Decimal
    monthly_payment: Decimal
    order: list[dict] = field(default_factory=list)
    stalled: list[str] = field(default_factory=list)   # debts the minimum cannot outpace
    balances: list[dict] = field(default_factory=list)  # total balance by month, for a chart


def _order(debts_: list[Debt], strategy: str) -> list[Debt]:
    if strategy == "snowball":
        return sorted(debts_, key=lambda d: (d.balance, -(d.apr or ZERO)))
    if strategy == "avalanche":
        # Unknown rate sorts last: better to attack a rate we can prove.
        return sorted(debts_, key=lambda d: (d.apr is None, -(d.apr or ZERO), d.balance))
    # "minimums" and "minimums-order" (the owner picked the target himself) keep the
    # order they were handed.
    return list(debts_)


def simulate(debts_: list[Debt], extra: Decimal = ZERO, strategy: str = "avalanche",
             start: date | None = None) -> Payoff:
    """Month by month: add interest, pay minimums, throw everything spare at the
    target. The freed-up minimum of a cleared debt rolls into the next one,
    which is the whole point of a payoff plan.
    """
    start = start or date.today()
    extra = _q(extra)
    bal = {d.account_id: d.balance for d in debts_}
    interest_paid = {d.account_id: ZERO for d in debts_}
    paid_off: dict[str, int] = {}
    total_interest = total_paid = ZERO
    order = _order(debts_, strategy)
    by_id = {d.account_id: d for d in debts_}
    monthly = sum((d.minimum for d in debts_), ZERO) + (extra if strategy != "minimums" else ZERO)
    series: list[dict] = []

    month = 0
    while month < MAX_MONTHS and any(v > 0 for v in bal.values()):
        month += 1
        # Interest first, the way a statement does it.
        for d in debts_:
            if bal[d.account_id] > 0 and d.apr:
                i = _q(bal[d.account_id] * d.apr / Decimal(1200))
                bal[d.account_id] += i
                interest_paid[d.account_id] += i
                total_interest += i
        budget = monthly
        # Minimums on everything.
        for d in debts_:
            if bal[d.account_id] <= 0:
                continue
            pay = min(d.minimum, bal[d.account_id], budget)
            bal[d.account_id] -= pay
            budget -= pay
            total_paid += pay
        # Everything left goes to the target, then the next one.
        for d in order:
            if budget <= 0:
                break
            if bal[d.account_id] <= 0:
                continue
            pay = min(budget, bal[d.account_id])
            bal[d.account_id] -= pay
            budget -= pay
            total_paid += pay
        for d in debts_:
            if bal[d.account_id] <= 0 and d.account_id not in paid_off:
                paid_off[d.account_id] = month
        series.append({"month": month, "balance": _q(sum(bal.values()))})
        if all(bal[d.account_id] >= d.balance for d in debts_ if d.balance > 0) and month > 2:
            break  # going backwards: minimums do not cover interest

    done = all(v <= 0 for v in bal.values())
    stalled = [by_id[k].name for k, v in bal.items() if v > 0]
    payoff_date = None
    if done:
        y, m = divmod(start.month - 1 + month, 12)
        payoff_date = date(start.year + y, m + 1, min(start.day, 28))
    return Payoff(
        strategy=strategy, months=month if done else None, payoff_date=payoff_date,
        total_interest=_q(total_interest), total_paid=_q(total_paid), monthly_payment=_q(monthly),
        order=[{"account_id": d.account_id, "name": d.name, "mask": d.mask,
                "balance": d.balance, "apr": d.apr, "apr_source": d.apr_source,
                "minimum": d.minimum, "minimum_source": d.minimum_source,
                "interest_paid": _q(interest_paid[d.account_id]),
                "paid_off_month": paid_off.get(d.account_id), "rank": i + 1}
               for i, d in enumerate(order)],
        stalled=[] if done else stalled,
        balances=series[:240],
    )


def compare(debts_: list[Debt], extra: Decimal = ZERO, start: date | None = None) -> dict:
    """Minimums only versus the two orderings, at the same total payment."""
    base = simulate(debts_, ZERO, "minimums", start)
    plans = {s: simulate(debts_, extra, s, start) for s in ("avalanche", "snowball")}
    best = plans["avalanche"]
    return {
        "minimums": base,
        "plans": plans,
        "interest_saved": _q(base.total_interest - best.total_interest),
        "months_saved": (base.months - best.months) if (base.months and best.months) else None,
    }


# ---------------------------------------------------------------- runway

@dataclass
class Event:
    date: date
    name: str
    amount: Decimal          # positive = money out
    kind: str                # bill | minimum | subscription | income | spending
    account: str | None = None


def _daily_discretionary(conn, days: int = 60) -> Decimal:
    """Everyday spending per day (food, fuel, shopping), from the last 60 days.

    A projection that only counts scheduled bills always looks fine and is
    always wrong, because eating happens too.
    """
    r = conn.execute(
        """SELECT coalesce(sum(spend), 0) / %s AS per_day FROM v_txn
           WHERE kind = 'expense' AND date >= current_date - %s
             AND category IN ('groceries', 'dining', 'auto', 'shopping', 'entertainment',
                              'personal', 'health', 'home', 'other')""",
        (days, days)).fetchone()
    return _q(r["per_day"])


def runway(conn, horizon_days: int = 90, buffer: Decimal | None = None) -> dict:
    """Project the cash balance forward, day by day, to the day it runs out."""
    today = date.today()
    end = today + timedelta(days=horizon_days)
    cash_rows = conn.execute(
        """SELECT id, name, mask, coalesce(available_balance, current_balance, 0) AS balance
           FROM v_acct WHERE NOT hidden AND type = 'depository' ORDER BY balance DESC""").fetchall()
    cash = _q(sum(Decimal(r["balance"]) for r in cash_rows))

    stream_rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income') AND date >= current_date - 400""").fetchall()
    streams = [s for s in analytics.detect_recurring(stream_rows) if s.active]
    # Only money that actually leaves cash. A subscription billed to a card is
    # already inside that card's balance and its minimum payment; counting both
    # would charge the owner twice for the same Netflix.
    acct_type = {r["id"]: r["type"] for r in conn.execute("SELECT id, type FROM v_acct").fetchall()}

    events: list[Event] = []
    for s in streams:
        # A few dollars of savings interest is not income you can spend, and
        # calling it "next income" hides how long the gap really is.
        if s.kind == "income" and (s.category == "interest" or s.typical_amount < Decimal(100)):
            continue
        if acct_type.get(s.account_id) not in ("depository", None):
            continue
        d = s.next_date
        while d <= end:
            if d >= today:
                events.append(Event(
                    date=d, name=s.name,
                    amount=_q(s.typical_amount if s.kind == "expense" else -s.typical_amount),
                    kind="income" if s.kind == "income" else (
                        "subscription" if s.category in ("entertainment", "services") else "bill"),
                    account=s.account_name))
            d += timedelta(days=round(s.interval_days))

    # Card minimums are not in the recurring streams: those live on the card,
    # while the payment leaves checking. Without them a plan misses the bills
    # that carry a late fee and a credit hit.
    for d in debts(conn):
        due = d.due_date
        if d.is_overdue:
            # Already late: it is owed now, not next cycle.
            events.append(Event(date=today, name=f"{d.name} minimum (past due)", amount=d.minimum,
                                kind="overdue", account=d.name))
        if due is None:
            continue
        while due <= end:
            if due >= today:
                events.append(Event(date=due, name=f"{d.name} minimum", amount=d.minimum,
                                    kind="minimum", account=d.name))
            due = (due.replace(day=1) + timedelta(days=32)).replace(day=min(due.day, 28))

    per_day = _daily_discretionary(conn)
    events.sort(key=lambda e: (e.date, -e.amount))

    balance = cash
    series, shortfalls = [], []
    zero_date = None
    low = {"date": today, "balance": cash}
    by_day: dict[date, list[Event]] = {}
    for e in events:
        by_day.setdefault(e.date, []).append(e)
    d = today
    while d <= end:
        for e in by_day.get(d, []):
            balance -= e.amount
            if e.amount > 0 and balance < 0 and len(shortfalls) < 12:
                shortfalls.append({"date": d, "name": e.name, "amount": e.amount,
                                   "projected_balance": _q(balance), "kind": e.kind})
        balance -= per_day
        if balance < low["balance"]:
            low = {"date": d, "balance": _q(balance)}
        if zero_date is None and balance < 0:
            zero_date = d
        series.append({"date": d, "balance": _q(balance)})
        d += timedelta(days=1)

    next_income = next((e for e in events if e.kind == "income"), None)
    # With no income in sight, "safe to spend" is about the next two weeks.
    # Measuring to the end of a 90 day horizon would just print a scary number
    # that answers no question.
    horizon = next_income.date if next_income else today + timedelta(days=14)
    committed_before_income = _q(sum(
        (e.amount for e in events if e.amount > 0 and e.date <= horizon), ZERO))
    buffer = _q(buffer if buffer is not None else ZERO)
    days_of_cover = int((cash / (per_day or Decimal("0.01"))))
    return {
        "today": today,
        "cash": cash,
        "cash_accounts": [{"id": r["id"], "name": r["name"], "mask": r["mask"], "balance": _q(r["balance"])}
                          for r in cash_rows],
        "daily_spending": per_day,
        "days_until_zero": (zero_date - today).days if zero_date else None,
        "zero_date": zero_date,
        "low_point": low,
        "series": series,
        "events": [{"date": e.date, "name": e.name, "amount": e.amount, "kind": e.kind, "account": e.account}
                   for e in events if e.date <= today + timedelta(days=45)],
        "shortfalls": shortfalls,
        "next_income": ({"date": next_income.date, "name": next_income.name,
                         "amount": -next_income.amount} if next_income else None),
        "committed_before_income": committed_before_income,
        "committed_through": horizon,
        "income_expected": next_income is not None,
        "safe_to_spend": _q(cash - committed_before_income - buffer),
        "buffer": buffer,
        "days_of_cover_at_current_spending": days_of_cover,
    }


# ---------------------------------------------------------------- mode

def mode(conn, rw: dict, ds: list[Debt]) -> dict:
    """What this person needs the app to be about today.

    survival: the next few weeks are the question.
    payoff:   the bills are covered, the debt is the question.
    growth:   no revolving debt, so the question is the cushion and the goals.
    """
    revolving = sum((d.balance for d in ds if d.kind == "credit"), ZERO)
    days = rw["days_until_zero"]
    overdue = any(d.is_overdue for d in ds)
    tight = (days is not None and days <= 45) or overdue or rw["safe_to_spend"] < 0
    if tight:
        why = []
        if overdue:
            why.append("a payment is past due")
        if days is not None and days <= 45:
            why.append(f"cash runs out in {days} days at this rate")
        if rw["safe_to_spend"] < 0:
            why.append("the bills before the next money add up to more than the cash on hand")
        return {"mode": "survival", "reasons": why, "revolving_debt": revolving}
    if revolving > 0:
        return {"mode": "payoff", "reasons": ["bills are covered; the cards are what is left"],
                "revolving_debt": revolving}
    return {"mode": "growth", "reasons": ["no card balances"], "revolving_debt": ZERO}


# ---------------------------------------------------------------- what if

def what_if(conn, monthly_income: Decimal, extra_to_debt: Decimal, cut_flexible_percent: Decimal,
            emergency_target: Decimal | None = None) -> dict:
    """One question: if this changes, what happens to the three dates that matter.

    Deliberately simple arithmetic on measured numbers, not a forecast model.
    Every input is a monthly figure the owner can control or hope for.
    """
    today = date.today()
    essentials = essentials_per_month(conn)
    flexible = conn.execute(
        """SELECT coalesce(sum(spend), 0) / 3 AS per_month FROM v_txn
           WHERE kind = 'expense' AND NOT essential AND date >= current_date - 90""").fetchone()["per_month"]
    flexible = _q(flexible)
    cut = _q(flexible * cut_flexible_percent / 100)
    spending = _q(essentials + flexible - cut)

    ds = debts(conn)
    minimums = sum((d.minimum for d in ds), ZERO)
    # Minimums are inside "essentials" already (category loans/fees), so the
    # extra is what goes on top of whatever is being paid today.
    left_over = _q(monthly_income - spending)
    payoff = simulate(ds, max(extra_to_debt, ZERO), "avalanche") if ds else None

    target = _q(emergency_target if emergency_target is not None else essentials * EMERGENCY_MONTHS)
    cash = _q(conn.execute(
        """SELECT coalesce(sum(coalesce(available_balance, current_balance, 0)), 0) AS c
           FROM v_acct WHERE NOT hidden AND type = 'depository'""").fetchone()["c"])
    toward_savings = _q(left_over - extra_to_debt)
    months_to_cushion = None
    if toward_savings > 0 and cash < target:
        months_to_cushion = int(((target - cash) / toward_savings).to_integral_value(rounding=ROUND_HALF_UP))

    return {
        "inputs": {"monthly_income": _q(monthly_income), "extra_to_debt": _q(extra_to_debt),
                   "cut_flexible_percent": cut_flexible_percent},
        "essentials": essentials, "flexible": flexible, "cut": cut, "spending": spending,
        "minimums": minimums,
        "left_over": left_over,
        "covers_the_month": left_over >= 0,
        "shortfall": _q(max(-left_over, ZERO)),
        "debt_free": {"months": payoff.months, "date": payoff.payoff_date,
                      "interest": payoff.total_interest} if payoff else None,
        "cushion": {"target": target, "cash": cash, "monthly": toward_savings,
                    "months": months_to_cushion,
                    "date": (today + timedelta(days=30 * months_to_cushion)) if months_to_cushion else None},
    }


# ---------------------------------------------------------------- goals

EMERGENCY_MONTHS = 3


def essentials_per_month(conn) -> Decimal:
    r = conn.execute(
        """SELECT coalesce(sum(spend), 0) / 3 AS per_month FROM v_txn
           WHERE kind = 'expense' AND date >= current_date - 90
             AND category IN ('rent', 'bills', 'groceries', 'insurance', 'auto', 'health', 'loans')""").fetchone()
    return _q(r["per_month"])


def goals(conn) -> list[dict]:
    rows = conn.execute(
        """SELECT g.*, a.name AS account_name, a.mask AS account_mask,
                  coalesce(a.current_balance, 0) AS account_balance
           FROM goals g LEFT JOIN v_acct a ON a.id = g.account_id
           WHERE NOT g.archived AND tally_can_see(g.owner_id)
             AND g.kind IN ('emergency', 'savings', 'payoff', 'custom')
           ORDER BY g.id""").fetchall()
    out = []
    for g in rows:
        current = _q(g["account_balance"]) if g["account_id"] else ZERO
        target = _q(g["target_amount"])
        monthly = _q(g["monthly_contribution"])
        remaining = max(target - current, ZERO)
        months = int((remaining / monthly).to_integral_value(rounding=ROUND_HALF_UP)) if monthly > 0 else None
        out.append({**g, "current": current, "remaining": remaining,
                    "percent": float(current / target) if target > 0 else None,
                    "months_to_go": months,
                    "eta": (date.today() + timedelta(days=30 * months)) if months else None})
    return out


def _money(v) -> str:
    return f"${Decimal(v):,.2f}"


def suggested_goals(conn, rw: dict, ds: list[Debt]) -> list[dict]:
    """Goals worth offering, given where things stand. Offers, not nags."""
    out = []
    essentials = essentials_per_month(conn)
    starter = _q(min(Decimal(1000), essentials))
    if rw["cash"] < starter:
        out.append({"kind": "emergency", "name": "Starter cushion", "target_amount": starter,
                    "why": f"One month of essentials is about {_money(starter)}. A small cushion is what stops "
                           f"the next surprise going onto a card."})
    elif rw["cash"] < essentials * EMERGENCY_MONTHS and not any(d.kind == "credit" for d in ds):
        out.append({"kind": "emergency", "name": "3 months of essentials",
                    "target_amount": _q(essentials * EMERGENCY_MONTHS),
                    "why": f"Your essentials are about {_money(essentials)} a month."})
    for d in ds:
        if d.kind == "credit" and d.balance > 0:
            out.append({"kind": "payoff", "name": f"Clear {d.name}", "target_amount": d.balance,
                        "account_id": d.account_id,
                        "why": f"{d.name} carries {_money(d.balance)}"
                               + (f" at {d.apr:.2f}% APR, which costs {_money(d.monthly_interest)} a month"
                                  if d.apr else "")})
            break
    return out
