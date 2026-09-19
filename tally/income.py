"""Freelance income and the tax that is not withheld from it.

Nobody takes tax out of a 1099 deposit, so part of every one belongs to the IRS
and the FTB, not to this month. This module says how much that is, by client and
by quarter, and whether it is actually set aside anywhere.

It is an estimate, clearly labelled as one. Tally is not a tax preparer.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)

# Self-employment tax is 15.3% of 92.35% of net earnings (~14.1%), plus federal
# and state income tax. 27% is a common rule of thumb for a low-to-middle
# bracket in California; the owner can change it in settings.
DEFAULT_RATE = Decimal("27")

# Estimated tax deadlines. Q4 is paid in January of the following year.
QUARTERS = [
    ("Q1", (1, 1), (3, 31), (4, 15)),
    ("Q2", (4, 1), (5, 31), (6, 15)),
    ("Q3", (6, 1), (8, 31), (9, 15)),
    ("Q4", (9, 1), (12, 31), (1, 15)),
]


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"))


def summary(conn, year: int | None = None, rate: Decimal | None = None,
            today: date | None = None) -> dict:
    today = today or date.today()
    year = year or today.year
    rate = Decimal(rate if rate is not None else DEFAULT_RATE)

    rows = conn.execute(
        """SELECT date, display_name, income, bank_text, account_name
           FROM v_txn
           WHERE kind = 'income' AND date >= %s AND date <= %s
             AND (category = 'freelance' OR (category = 'income' AND tally_freelance_default(bank_text)))
           ORDER BY date""", (date(year, 1, 1), date(year, 12, 31))).fetchall()

    total = sum((_q(r["income"]) for r in rows), ZERO)
    by_client: dict[str, Decimal] = defaultdict(Decimal)
    by_month: dict[date, Decimal] = defaultdict(Decimal)
    for r in rows:
        by_client[r["display_name"]] += _q(r["income"])
        by_month[r["date"].replace(day=1)] += _q(r["income"])

    quarters = []
    for name, start, end, due in QUARTERS:
        q_start, q_end = date(year, *start), date(year, *end)
        earned = sum((_q(r["income"]) for r in rows if q_start <= r["date"] <= q_end), ZERO)
        due_date = date(year + 1, *due) if name == "Q4" else date(year, *due)
        quarters.append({
            "quarter": name, "start": q_start, "end": q_end, "due_date": due_date,
            "income": earned, "estimated_payment": _q(earned * rate / 100),
            "past": due_date < today, "next": False,
        })
    upcoming = [q for q in quarters if not q["past"]]
    if upcoming:
        upcoming[0]["next"] = True

    # What is actually sitting aside, if an account has been nominated for it.
    setting = conn.execute("SELECT value FROM app_settings WHERE key = 'tax_account_id'").fetchone()
    tax_account = None
    if setting:
        tax_account = conn.execute(
            "SELECT id, name, mask, current_balance FROM v_acct WHERE id = %s",
            (str(setting["value"]).strip('"'),)).fetchone()

    should_hold = _q(total * rate / 100)
    held = _q(tax_account["current_balance"]) if tax_account else ZERO
    salary = conn.execute(
        """SELECT coalesce(sum(income), 0) AS s FROM v_txn
           WHERE kind = 'income' AND category = 'income' AND date >= %s
             AND NOT tally_freelance_default(bank_text)""", (date(year, 1, 1),)).fetchone()["s"]

    return {
        "year": year, "rate_percent": rate,
        "freelance_income": total,
        "other_income": _q(salary),
        "should_set_aside": should_hold,
        "set_aside": held,
        "short_by": _q(max(should_hold - held, ZERO)),
        "tax_account": tax_account,
        "clients": sorted(({"name": k, "income": v, "share": float(v / total) if total else None}
                           for k, v in by_client.items()), key=lambda c: -c["income"]),
        "by_month": [{"month": m, "income": v} for m, v in sorted(by_month.items())],
        "quarters": quarters,
        "next_due": next((q for q in quarters if q["next"]), None),
        "deposits": [{"date": r["date"], "name": r["display_name"], "amount": _q(r["income"]),
                      "account": r["account_name"]} for r in rows[-12:]],
        "note": ("An estimate: about 14% self-employment tax plus income tax. Business expenses reduce it, "
                 "and a professional will do better than a flat rate."),
    }
