"""Numbers the dashboard shows. All of it computed here, none of it by a model.

Pure functions (net worth estimation, recurring detection) take plain rows so
they can be tested without a database. The SQL lives in api.py's routes.
"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

LIABILITY_TYPES = {"credit", "loan"}


# ---------------------------------------------------------------- net worth

def estimate_balance_history(accounts: list[dict], daily_flows: list[dict],
                             start: date, end: date) -> list[dict]:
    """Walk each account's balance backwards from today using its transactions.

    accounts:    {id, type, current_balance}
    daily_flows: {account_id, date, amount} summed per day, Plaid sign (+ = out)

    Depository/investment: balance before a day = after + that day's outflows.
    Credit/loan (balance = owed): owed before a day = after - that day's charges.

    It is an estimate: it knows nothing about balance changes that never show up
    as a transaction (investment gains, interest capitalised off-statement). Real
    daily snapshots replace it as balances_daily accumulates.
    """
    flows: dict[str, dict[date, Decimal]] = defaultdict(dict)
    for f in daily_flows:
        flows[f["account_id"]][f["date"]] = Decimal(f["amount"])

    today = date.today()
    series_by_account: dict[str, dict[date, Decimal]] = {}
    for a in accounts:
        bal = Decimal(a["current_balance"] or 0)
        liability = a["type"] in LIABILITY_TYPES
        out: dict[date, Decimal] = {}
        d = max(today, end)
        acc_flows = flows.get(a["id"], {})
        while d >= start:
            if d <= end:
                out[d] = bal
            amt = acc_flows.get(d, Decimal(0))
            # Undo day d to get the balance at the end of d-1.
            bal = bal - amt if liability else bal + amt
            d -= timedelta(days=1)
        series_by_account[a["id"]] = out

    rows = []
    d = start
    while d <= end:
        assets = liabilities = Decimal(0)
        for a in accounts:
            v = series_by_account[a["id"]].get(d, Decimal(0))
            if a["type"] in LIABILITY_TYPES:
                liabilities += v
            else:
                assets += v
        rows.append({"date": d, "assets": assets, "liabilities": liabilities,
                     "net_worth": assets - liabilities})
        d += timedelta(days=1)
    return rows


# ---------------------------------------------------------------- recurring

# Categories where buying something twice is a habit, not a bill. A coffee
# every Tuesday has a cadence and a stable price and is still not something
# anybody can cancel, so a stream here has to look like an actual subscription
# -- the same amount, not merely a similar one -- before it counts.
#
# This also stops a double count in the runway: everyday spending is already
# projected per-day by plan._daily_discretionary, so a a fast food chain "bill" would
# be charged twice against the same money.
HABIT_CATEGORIES = {"dining", "groceries", "auto", "travel"}
# How much of the history has to sit on one price before it is a fixed price.
FIXED_SHARE = 0.6
# ...and how long that history has to be, in a habit category, before the
# stability means anything. Three visits to a fast food chain at 12.71, 12.82, 12.82
# are two coincidentally equal receipts, and on three points that reads as a
# 67% fixed price. A real subscription in one of these categories -- a meal kit,
# a coffee plan -- bills many times, so asking for a longer run costs nothing
# and removes the whole class of accident.
HABIT_MIN_CHARGES = 6

CADENCES = [  # name, nominal days, tolerance
    ("weekly", 7, 2),
    ("biweekly", 14, 2),
    ("monthly", 30.4, 4),
    ("quarterly", 91, 8),
    ("yearly", 365, 15),
]


@dataclass
class Stream:
    key: str
    name: str
    logo_url: str | None
    account_id: str
    account_name: str
    category: str
    category_label: str
    kind: str
    cadence: str
    interval_days: float
    count: int
    first_date: date
    last_date: date
    next_date: date
    last_amount: Decimal
    typical_amount: Decimal
    previous_amount: Decimal | None
    price_changed_on: date | None
    active: bool
    # A bill charges the same amount; a habit merely costs about the same.
    # Coffee at 7.10, 7.45, 6.80 is regular and is not a subscription.
    fixed_price: bool

    @property
    def monthly_cost(self) -> Decimal:
        return (self.typical_amount * Decimal(30.4) / Decimal(self.interval_days)).quantize(Decimal("0.01"))


def _cadence(intervals: list[int]) -> tuple[str, float] | None:
    med = median(intervals)
    for name, nominal, tol in CADENCES:
        if abs(med - nominal) <= tol:
            fitting = sum(1 for i in intervals if abs(i - nominal) <= tol * 1.5)
            if fitting / len(intervals) >= 0.7:
                return name, nominal
    return None


def detect_recurring(rows: list[dict], today: date | None = None) -> list[Stream]:
    """Find charges and deposits that repeat on a schedule.

    rows: v_txn rows, posted only, expense or income kind, any order.

    Grouped by merchant AND account, so the same service billed on two cards
    is two streams, which is exactly what the duplicate check needs to see.
    """
    today = today or date.today()
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in rows:
        if r["kind"] not in ("expense", "income"):
            continue
        key = r.get("merchant_entity_id") or r["display_name"].lower()
        groups[(key, r["account_id"])].append(r)

    streams = []
    for (key, account_id), txns in groups.items():
        txns.sort(key=lambda r: r["date"])
        # Same-day repeats (a double charge) are one occurrence for cadence.
        by_day: dict[date, list[dict]] = defaultdict(list)
        for t in txns:
            by_day[t["date"]].append(t)
        days_seen = sorted(by_day)
        if len(days_seen) < 3:
            continue
        intervals = [(b - a).days for a, b in zip(days_seen, days_seen[1:])]
        found = _cadence(intervals)
        if not found:
            continue
        cadence, nominal = found

        amounts = [abs(Decimal(by_day[d][0]["amount"])) for d in days_seen]
        typical = Decimal(median(amounts))
        # Groceries every Saturday are "weekly" by date but not a bill. A real
        # recurring charge moves little from one occurrence to the next, even
        # a utility that doubles across a season does it gradually.
        if not typical:
            continue
        steps = [abs(b - a) / a for a, b in zip(amounts, amounts[1:]) if a]
        if not steps or median(steps) > Decimal("0.35"):
            continue

        # The same amount over and over is what a subscription looks like.
        # Anything that merely lands in the same range is a habit.
        commonest = max(Counter(amounts).values())
        fixed_price = commonest / len(amounts) >= FIXED_SHARE

        last = by_day[days_seen[-1]][0]
        if last["category"] in HABIT_CATEGORIES and not (
                fixed_price and len(days_seen) >= HABIT_MIN_CHARGES):
            continue
        # A price change is news for about six months after it happens. Only
        # fixed-price streams (subscriptions) qualify; a utility bill moving
        # every month is not a "price increase".
        prev_amount = changed_on = None
        fixed = len(set(amounts)) <= 2
        if fixed:
            for i in range(len(amounts) - 1, 0, -1):
                if amounts[i] != amounts[i - 1]:
                    if (today - days_seen[i]).days <= 190 and all(a == amounts[-1] for a in amounts[i:]):
                        prev_amount, changed_on = amounts[i - 1], days_seen[i]
                    break
        interval = median(intervals)
        next_date = days_seen[-1] + timedelta(days=round(nominal))
        streams.append(Stream(
            key=str(key), name=last["display_name"], logo_url=last.get("logo_url"),
            account_id=account_id, account_name=last["account_name"],
            category=last["category"], category_label=last["category_label"], kind=last["kind"],
            cadence=cadence, interval_days=nominal, count=len(days_seen),
            first_date=days_seen[0], last_date=days_seen[-1], next_date=next_date,
            last_amount=amounts[-1], typical_amount=amounts[-1],
            previous_amount=prev_amount, price_changed_on=changed_on,
            active=(today - days_seen[-1]).days <= interval * 1.6,
            fixed_price=fixed_price,
        ))
    return sorted(streams, key=lambda s: s.next_date)
