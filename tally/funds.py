"""Saving up for a specific thing, with the store credit counted.

Three kinds of money can go toward a purchase and they are not interchangeable:

  cash      you set aside, spendable anywhere
  credits   gift cards, store credit, a rebate, a trade-in: real money, but only
            at one place, and sometimes with an expiry date
  spent     what has already gone out on it

"Still needed" is the target minus all three, and it is the only number worth
putting in large type. Whether it is a good idea to buy today is a separate
question, answered against the runway rather than the fund.
"""
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
EXPIRY_WARNING_DAYS = 45


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def list_funds(conn, include_archived: bool = False, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = conn.execute(
        f"""SELECT f.*,
                   coalesce((SELECT sum(amount - used) FROM fund_credits c WHERE c.fund_id = f.id), 0) AS credits,
                   coalesce((SELECT sum(amount) FROM fund_contributions n WHERE n.fund_id = f.id), 0) AS saved,
                   coalesce((SELECT sum(v.amount) FROM fund_spends s JOIN v_txn v ON v.id = s.transaction_id
                             WHERE s.fund_id = f.id), 0) AS spent
            FROM funds f
            WHERE tally_can_see(f.owner_id){'' if include_archived else ' AND NOT f.archived'}
            ORDER BY f.bought_on IS NOT NULL, f.priority DESC, f.created_at""").fetchall()

    out = []
    for f in rows:
        credits = conn.execute(
            """SELECT id, kind, label, amount, used, merchant, expires_on, note,
                      (amount - used) AS remaining,
                      CASE WHEN expires_on IS NOT NULL AND expires_on <= current_date + %s
                           THEN true ELSE false END AS expiring
               FROM fund_credits WHERE fund_id = %s ORDER BY expires_on NULLS LAST, id""",
            (EXPIRY_WARNING_DAYS, f["id"])).fetchall()
        spends = conn.execute(
            """SELECT v.id, v.date, v.display_name, v.amount, v.account_name, s.note
               FROM fund_spends s JOIN v_txn v ON v.id = s.transaction_id
               WHERE s.fund_id = %s ORDER BY v.date DESC""", (f["id"],)).fetchall()
        contributions = conn.execute(
            """SELECT id, date, amount, source, transaction_id, note
               FROM fund_contributions WHERE fund_id = %s ORDER BY date DESC, id DESC LIMIT 20""",
            (f["id"],)).fetchall()

        target = _q(f["target_amount"])
        credit_total, saved, spent = _q(f["credits"]), _q(f["saved"]), _q(f["spent"])
        have = credit_total + saved
        still_needed = max(target - have - spent, ZERO)
        # Only cash can be moved around; credit is stuck where it is.
        cash_needed_at_till = max(target - spent - credit_total, ZERO)

        pace = None
        if contributions:
            first = min(c["date"] for c in contributions)
            months = max(Decimal(1), Decimal((today - first).days or 1) / Decimal("30.4"))
            pace = _q(saved / months)
        months_left = None
        if still_needed > 0 and pace and pace > 0:
            months_left = int((still_needed / pace).to_integral_value(rounding=ROUND_HALF_UP))

        needed_per_month = None
        if f["target_date"] and still_needed > 0:
            months_to_date = max(Decimal(1), Decimal((f["target_date"] - today).days) / Decimal("30.4"))
            needed_per_month = _q(still_needed / months_to_date)

        out.append({
            **f,
            "target_amount": target, "credits_total": credit_total, "saved": saved, "spent": spent,
            "funded": have + spent,
            "still_needed": still_needed,
            "cash_needed_at_till": cash_needed_at_till,
            "percent": float(min((have + spent) / target, Decimal(1))) if target > 0 else None,
            "complete": still_needed <= 0,
            "bought": f["bought_on"] is not None,
            "pace_per_month": pace,
            "months_left_at_pace": months_left,
            "needed_per_month_for_target_date": needed_per_month,
            "expiring_credits": [c for c in credits if c["expiring"] and _q(c["remaining"]) > 0],
            "credits": credits, "spends": spends, "contributions": contributions,
        })
    return out


def affordability(conn, fund: dict, runway: dict) -> dict:
    """Could this be bought today without wrecking the month?

    Uses the same projection the Plan page uses: cash on hand, the bills before
    the next money, and everyday spending. Buying is a decision, so this
    reports the consequence rather than a verdict.
    """
    cash_needed = fund["cash_needed_at_till"]
    spare = Decimal(runway["safe_to_spend"])
    daily = Decimal(runway["daily_spending"]) or Decimal("0.01")
    days_now = runway["days_until_zero"]
    days_after = None
    if days_now is not None:
        days_after = max(0, int(days_now - (cash_needed / daily)))
    return {
        "cash_needed": cash_needed,
        "spare_after_bills": _q(spare),
        "affordable_now": bool(cash_needed <= spare),
        "days_of_cash_now": days_now,
        "days_of_cash_after": days_after,
        "note": ("Covered by credit and what you have set aside." if cash_needed <= 0
                 else "Fits after the bills that are already due." if cash_needed <= spare
                 else "Buying today would come out of money the bills need."),
    }


def alerts(conn, today: date | None = None) -> list[dict]:
    """Two things worth saying out loud: credit about to expire, and a fund
    that is fully funded so the waiting is over."""
    today = today or date.today()
    out = []
    for f in list_funds(conn, today=today):
        if f["bought"]:
            continue
        for c in f["expiring_credits"]:
            days = (c["expires_on"] - today).days
            out.append({
                "kind": "credit_expiring", "fund_id": f["id"], "fund": f["name"],
                "title": f"{c['label']} expires in {days} days",
                "detail": f"${_q(c['remaining']):,.2f} toward {f['name']}, gone after "
                          f"{c['expires_on']:%b %d} if it is not used.",
                "amount": _q(c["remaining"]), "occurred_on": today,
                "fingerprint": f"credit_expiring:{c['id']}:{c['expires_on']}",
                "severity": "medium" if days <= 14 else "low",
            })
        if f["complete"]:
            out.append({
                "kind": "fund_ready", "fund_id": f["id"], "fund": f["name"],
                "title": f"{f['name']} is fully funded",
                "detail": f"${f['target_amount']:,.2f} covered by ${f['credits_total']:,.2f} of credit "
                          f"and ${f['saved']:,.2f} set aside.",
                "amount": f["target_amount"], "occurred_on": today,
                "fingerprint": f"fund_ready:{f['id']}",
                "severity": "low",
            })
    return out


# ---------------------------------------------------------------- filling itself

def auto_fill(conn, today: date | None = None) -> dict:
    """Move money into funds when income lands.

    A fund that only fills when somebody remembers to move money does not fill.
    Three ways to say it:

      per_paycheck        a fixed amount out of every deposit
      percent_of_income   a share of every deposit, which scales with a variable income
      monthly             a fixed amount once a month, regardless

    `auto_through` records how far each fund has already taken its cut, so
    running this after every sync -- which is what the worker does -- cannot
    double-fill. It moves forward only, so backfilling old income is a decision
    somebody makes on purpose rather than a side effect of a re-sync.
    """
    today = today or date.today()
    funds_ = conn.execute(
        """SELECT id, name, auto_kind, auto_amount, auto_percent, auto_through, target_amount, owner_id
           FROM funds
           WHERE auto_kind IS NOT NULL AND NOT archived AND bought_on IS NULL
             AND tally_can_see(owner_id)
           ORDER BY priority DESC, id""").fetchall()
    if not funds_:
        return {"filled": 0, "moved": ZERO}

    filled, moved = 0, ZERO
    for f in funds_:
        # Never look further back than the fund has been set up to fill, and
        # never before the day the instruction was given.
        since = f["auto_through"] or (today - timedelta(days=31))
        if f["auto_kind"] == "monthly":
            due = _monthly_due(f, since, today)
        else:
            due = _income_due(conn, f, since, today)

        for when, amount, source_txn in due:
            if amount <= 0:
                continue
            # Never overshoot the target: a fund that is full stops taking.
            room = _room_left(conn, f["id"], f["target_amount"])
            amount = min(amount, room)
            if amount <= 0:
                break
            conn.execute(
                """INSERT INTO fund_contributions (fund_id, date, amount, source, transaction_id, note, automatic)
                   VALUES (%s,%s,%s,%s,%s,%s,true)""",
                (f["id"], when, amount, "auto", source_txn,
                 "set aside automatically"))
            filled += 1
            moved += amount
        conn.execute("UPDATE funds SET auto_through = %s WHERE id = %s", (today, f["id"]))
    conn.commit()
    return {"filled": filled, "moved": _q(moved)}


def _room_left(conn, fund_id: int, target) -> Decimal:
    row = conn.execute(
        """SELECT coalesce((SELECT sum(amount - used) FROM fund_credits WHERE fund_id = %s), 0)
                + coalesce((SELECT sum(amount) FROM fund_contributions WHERE fund_id = %s), 0)
                + coalesce((SELECT sum(v.amount) FROM fund_spends s JOIN v_txn v ON v.id = s.transaction_id
                            WHERE s.fund_id = %s), 0) AS have""",
        (fund_id, fund_id, fund_id)).fetchone()
    return max(_q(target) - _q(row["have"]), ZERO)


def _monthly_due(f: dict, since: date, today: date) -> list[tuple]:
    """One contribution per calendar month that has started since we last looked."""
    out = []
    month = date(since.year, since.month, 1)
    while month <= date(today.year, today.month, 1):
        if month > date(since.year, since.month, 1) or f["auto_through"] is None:
            out.append((max(month, since), _q(f["auto_amount"]), None))
        month = (month.replace(day=28) + timedelta(days=4)).replace(day=1)
    return out


def _income_due(conn, f: dict, since: date, today: date) -> list[tuple]:
    """A cut of each deposit that has landed since we last looked."""
    rows = conn.execute(
        """SELECT id, date, income FROM v_txn
           WHERE kind = 'income' AND NOT pending AND date > %s AND date <= %s AND income > 0
           ORDER BY date""", (since, today)).fetchall()
    out = []
    for r in rows:
        if f["auto_kind"] == "per_paycheck":
            amount = _q(f["auto_amount"])
        else:
            amount = _q(Decimal(r["income"]) * Decimal(f["auto_percent"]) / 100)
        out.append((r["date"], amount, r["id"]))
    return out


def auto_preview(conn, kind: str, amount=None, percent=None, months: int = 6) -> dict:
    """What an instruction would have set aside over the last few months, so the
    number is checked against real income before it is relied on."""
    since = date.today() - timedelta(days=int(30.4 * months))
    rows = conn.execute(
        """SELECT date, income FROM v_txn
           WHERE kind = 'income' AND NOT pending AND date >= %s AND income > 0 ORDER BY date""",
        (since,)).fetchall()
    if kind == "monthly":
        total = _q(Decimal(amount) * months)
        n = months
    elif kind == "per_paycheck":
        total, n = _q(Decimal(amount) * len(rows)), len(rows)
    else:
        total = _q(sum((Decimal(r["income"]) * Decimal(percent) / 100 for r in rows), ZERO))
        n = len(rows)
    return {"over_months": months, "deposits": len(rows), "contributions": n,
            "total": total, "per_month": _q(total / months) if months else ZERO}
