"""Transaction monitoring. HANDOFF section 8.

Rules only. Each alert stores the rule, what it saw, and the threshold it
crossed (invariant 7), plus a fingerprint so a rescan never recreates an alert
the user already dismissed.

Honest limit, repeated from the spec: Plaid data lands hours after a charge.
This is a second net behind each bank's own push alerts, not a replacement.

Every rule here has to clear two bars, and the second one was missing for a
long time:

  1. Is the thing true?
  2. Is the BASELINE it is measured against meaningful, and is it still
     actionable?

Skipping the second is how this page reached 44 urgent alerts of which seven
were real. "Shell charged 3.8x the usual" is arithmetic on a merchant that has
no usual -- a tank of fuel against a packet of crisps -- and "12 charges in one
day" is a Saturday for somebody whose normal Saturday is ten. A list that is
mostly noise is one people stop opening, and then the reversible fee sitting in
it never gets called about. That is a worse outcome than having no alerts.

So: a merchant needs a tight spread before "the usual" means anything, a burst
is measured against that person's own busiest days, and a lone small charge is
not card testing.
"""
import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal
from statistics import median

from psycopg.types.json import Jsonb

from . import analytics, budgets, fees, funds, plan

log = logging.getLogger("tally.monitor")

WINDOW_DAYS = 120
# How recently a thing has to have happened to be worth interrupting somebody
# about. Fraud is a phone call you make today; a reversible fee is one you can
# still make in two months, and on a fresh install with two years of backfill
# the difference is a page of history versus a page of things to do.
ACTIONABLE_WITHIN = {
    "card_testing": 30,
    "velocity": 30,
    "duplicate_charge": 60,
    "foreign_activity": 45,
    "new_merchant_large": 45,
    # Deliberately long: an issuer will still reverse a fee from a few months
    # back, and this is the rule that pays for the whole page.
    "reversible_fee": 120,
}

# Rules whose alerts describe a single past event rather than a standing state.
# They are retired the same way, but on the long window: a duplicate charge from
# eleven weeks ago is still a duplicate charge.
ONE_OFF_RULES = ("amount_outlier", "price_increase")

# Which alerts are worth nothing once they are stale, and which are a problem
# until somebody deals with them.
#
# Nobody can act on a burst of charges from three months ago, or on a $1 test
# charge that never turned into fraud -- those are history the moment they age
# out, and leaving them open is how the list refills with things nobody will
# ever click.
#
# A duplicate charge and a reversible fee are the opposite: the money is still
# missing, and an app that quietly closed them would be hiding the two items
# most likely to be worth real money.
PERISHABLE = ("card_testing", "velocity", "foreign_activity", "new_merchant_large")

THRESHOLDS = {
    "duplicate_window_days": 2,
    "duplicate_min_amount": Decimal("5"),
    "card_test_max_amount": Decimal("2.00"),
    "outlier_multiple": Decimal("3"),
    "outlier_min_excess": Decimal("40"),
    "outlier_min_history": 4,
    # It also has to beat the most this merchant has EVER charged, by a
    # margin. That is the question a person actually asks -- "is this more than
    # I have ever spent there?" -- and it is the whole fix for "Shell charged
    # 3.8x the usual": a tank of fuel is not news when a previous tank cost
    # nearly as much. A median alone cannot see that; the maximum can.
    "outlier_over_max": Decimal("2"),
    "new_merchant_amount": Decimal("250"),
    # A floor. Above it, compared against this person's own busiest days.
    "velocity_per_day": 8,
    "velocity_over_personal": 4,
    # One tiny charge at a new merchant is a coffee. Card testing is a burst,
    # or a small charge followed by a big one on the same card.
    "card_test_min_cluster": 2,
    "card_test_followed_by": Decimal("100"),
    "card_test_follow_days": 3,
}

# Categories where a large first-time payment is normal life, not a signal.
_NEW_MERCHANT_QUIET = {"rent", "loans", "card_payment", "transfer", "income", "interest", "insurance"}


def _fmt(v) -> str:
    return f"${Decimal(v):,.2f}"



def _alert(rule, severity, title, detail, inputs, txns, occurred_on, amount=None):
    ids = sorted(t["id"] for t in txns)
    first = txns[0] if txns else {}
    return {
        "fingerprint": f"{rule}:{','.join(ids) if ids else inputs.get('key', '')}",
        "rule": rule, "severity": severity, "title": title, "detail": detail,
        "inputs": inputs, "txn_ids": ids, "account_id": first.get("account_id"),
        "merchant_key": first.get("merchant_key"), "amount": amount, "occurred_on": occurred_on,
    }


def evaluate(rows: list[dict], history: list[dict], streams: list[analytics.Stream],
             today: date | None = None) -> list[dict]:
    """Pure: rows in the alert window, a year of history for baselines, recurring streams."""
    today = today or date.today()
    out: list[dict] = []
    T = THRESHOLDS
    expenses = [r for r in rows if r["kind"] == "expense" and Decimal(r["amount"]) > 0 and not r["pending"]]

    # Merchant baselines from history (strictly before each row is checked).
    by_merchant: dict[str, list[dict]] = defaultdict(list)
    for h in history:
        if h["kind"] == "expense" and Decimal(h["amount"]) > 0:
            by_merchant[h["merchant_key"]].append(h)
    for v in by_merchant.values():
        v.sort(key=lambda r: r["date"])

    def prior(r):
        return [h for h in by_merchant.get(r["merchant_key"], []) if h["date"] < r["date"]]

    recurring_keys = {(s.name.lower(), s.account_id) for s in streams if s.active}

    # 1. Duplicate charge: same card, same merchant, same amount, within 2 days.
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for r in expenses:
        if Decimal(r["amount"]) >= T["duplicate_min_amount"]:
            groups[(r["account_id"], r["merchant_key"], Decimal(r["amount"]))].append(r)
    for (acct, mk, amt), g in groups.items():
        g.sort(key=lambda r: (r["date"], r["id"]))
        for a, b in zip(g, g[1:]):
            gap = (b["date"] - a["date"]).days
            if gap <= T["duplicate_window_days"] and (b["display_name"].lower(), acct) not in recurring_keys:
                out.append(_alert(
                    "duplicate_charge", "medium",
                    f"Possible double charge at {a['display_name']}",
                    f"{_fmt(amt)} was charged twice on {a['account_name']} ··{a['account_mask']}"
                    f"{' the same day' if gap == 0 else f' {gap} day apart' if gap == 1 else f' {gap} days apart'}. "
                    f"If you only bought once, ask the merchant or card issuer to reverse one.",
                    {"amount": str(amt), "days_apart": gap, "window_days": T["duplicate_window_days"]},
                    [a, b], b["date"], amt))

    # 2. Card testing: tiny charges from merchants never seen before.
    # Any small debit counts here, not just "expense": card testers run through
    # PayPal and gift-card sellers that Plaid files under transfers.
    def seen_before(r):
        return any(h["merchant_key"] == r["merchant_key"] and h["date"] < r["date"] for h in history)
    tiny = [r for r in rows if not r["pending"] and Decimal(0) < Decimal(r["amount"]) <= T["card_test_max_amount"]
            and r["category"] not in ("card_payment", "fees", "interest", "income") and not seen_before(r)]
    tiny_by_acct: dict[str, list[dict]] = defaultdict(list)
    for r in tiny:
        tiny_by_acct[r["account_id"]].append(r)
    for acct, g in tiny_by_acct.items():
        g.sort(key=lambda r: r["date"])
        cluster = [r for r in g if (g[-1]["date"] - r["date"]).days <= T["card_test_follow_days"]]

        # The pattern is what makes it card testing, not the size. One $1.50
        # charge at a shop you have not used before is a coffee. Two things
        # actually look like a stolen card: a burst of them, or a small one
        # followed by a large one on the same card.
        if len(cluster) >= T["card_test_min_cluster"]:
            chunk, why = cluster, "burst"
        else:
            chunk, why = [], None
            for r in g:
                big = [e for e in expenses
                       if e["account_id"] == acct
                       and 0 <= (e["date"] - r["date"]).days <= T["card_test_follow_days"]
                       and Decimal(e["amount"]) >= T["card_test_followed_by"]]
                if big:
                    chunk, why = [r] + big[:1], "followed"
                    break
        if not chunk:
            continue

        first = chunk[0]
        names = ", ".join(f"{r['display_name']} {_fmt(r['amount'])}" for r in chunk)
        detail = (f"{names}. Thieves check a stolen card with a tiny purchase before a big one. "
                  if why == "followed" else
                  f"{names}. Several tiny charges from merchants you have not used before, close "
                  f"together. ")
        out.append(_alert(
            "card_testing", "high",
            f"Small test charges on {first['account_name']}",
            detail + f"If you do not recognise these, lock the card in the "
                     f"{first['institution'] or 'bank'} app and ask for a new number.",
            {"max_amount": str(T["card_test_max_amount"]), "count": len(chunk),
             "pattern": why, "first_time_merchant": True},
            chunk, chunk[-1]["date"], sum(Decimal(r["amount"]) for r in chunk)))

    # 3. Amount far above what this merchant normally charges.
    for r in expenses:
        p = prior(r)
        if len(p) < T["outlier_min_history"]:
            continue
        recent = [Decimal(h["amount"]) for h in p[-12:]]
        med = Decimal(median(recent))
        amt = Decimal(r["amount"])
        if med <= 0 or amt < med * T["outlier_multiple"] or amt - med < T["outlier_min_excess"]:
            continue

        # The bar that was missing. A merchant whose charges already range
        # widely -- fuel, anything billed by usage -- has no "usual", and three
        # times its median says nothing. Beating its own previous maximum by a
        # margin does.
        biggest = max(recent)
        if amt < biggest * T["outlier_over_max"]:
            continue

        out.append(_alert(
            "amount_outlier", "medium",
            f"{r['display_name']} charged {(amt / med):.1f}x the usual",
            f"{_fmt(amt)} on {r['date']:%b} {r['date'].day}. Your last {len(recent)} charges there "
            f"were around {_fmt(med)}, and the largest was {_fmt(biggest)}.",
            {"amount": str(amt), "median": str(med), "previous_max": str(biggest),
             "multiple": str(T["outlier_multiple"]), "history": len(recent)},
            [r], r["date"], amt))

    # 4. Large first charge from a merchant never seen before.
    for r in expenses:
        amt = Decimal(r["amount"])
        if amt >= T["new_merchant_amount"] and not prior(r) and r["category"] not in _NEW_MERCHANT_QUIET:
            out.append(_alert(
                "new_merchant_large", "low",
                f"First charge from {r['display_name']}: {_fmt(amt)}",
                f"No earlier transactions with this merchant on any account. Expected if you just booked "
                f"or bought something big.",
                {"amount": str(amt), "threshold": str(T["new_merchant_amount"])},
                [r], r["date"], amt))

    # 5. Card-present charges abroad, one alert per card per week.
    abroad: dict[tuple, list[dict]] = defaultdict(list)
    for r in expenses:
        if fees.is_foreign(r.get("bank_text") or r["name"]):
            abroad[(r["account_id"], r["date"].isocalendar()[:2])].append(r)
    for (acct, _), g in abroad.items():
        total = sum(Decimal(r["amount"]) for r in g)
        out.append(_alert(
            "foreign_activity", "low",
            f"Charges outside the US on {g[0]['account_name']}",
            f"{len(g)} charge{'s' if len(g) > 1 else ''} totaling {_fmt(total)} "
            f"({', '.join(r['display_name'] for r in g[:3])}). Fine if you were traveling.",
            {"count": len(g), "total": str(total)}, g, max(r["date"] for r in g), total))

    # 6. Velocity: a burst of charges on one card in a day.
    # What a busy day looks like FOR THIS PERSON, on this card. Eight charges
    # is a lot for somebody who averages two and an ordinary Saturday for
    # somebody who averages nine, and a fixed threshold cannot tell them apart.
    hist_per_day: dict[tuple, int] = defaultdict(int)
    for h in history:
        if h["kind"] == "expense" and Decimal(h["amount"]) > 0:
            hist_per_day[(h["account_id"], h["date"])] += 1

    def busiest_other_day(acct: str, day: date) -> int:
        """The busiest day on this card that is NOT the one being judged.
        Including it would let a busy day raise its own bar, and nothing would
        ever fire."""
        return max((n for (a, d), n in hist_per_day.items() if a == acct and d != day),
                   default=0)

    per_day: dict[tuple, list[dict]] = defaultdict(list)
    for r in expenses:
        per_day[(r["account_id"], r["date"])].append(r)
    for (acct, d), g in per_day.items():
        # Above the floor AND meaningfully above this card's own busiest day,
        # which the history already contains.
        personal = busiest_other_day(acct, d)
        bar = max(T["velocity_per_day"], personal + T["velocity_over_personal"])
        if len(g) < bar:
            continue
        total = sum(Decimal(r["amount"]) for r in g)
        out.append(_alert(
            "velocity", "medium", f"{len(g)} charges in one day on {g[0]['account_name']}",
            f"{_fmt(total)} across {len(g)} charges on {d:%b} {d.day}. The busiest day on this card "
            f"before now was {personal}.",
            {"count": len(g), "threshold": bar, "personal_busiest": personal}, g, d, total))

    # 7. Bank fees the user can often get reversed.
    for r in rows:
        kind = fees.classify(r) if Decimal(r["amount"]) > 0 else None
        if kind in ("overdraft", "nsf", "late"):
            label = fees.FEE_TYPES[kind]["label"]
            out.append(_alert(
                "reversible_fee", "medium", f"{label} fee: {_fmt(r['amount'])}",
                f"Charged on {r['account_name']} ··{r['account_mask']}. A polite call often gets a first "
                f"{label.lower()} fee reversed. The Fees page has a script.",
                {"fee_type": kind}, [r], r["date"], Decimal(r["amount"])))

    # 8. Subscription price went up.
    for s in streams:
        if s.active and s.kind == "expense" and s.previous_amount is not None and s.price_changed_on:
            out.append(_alert(
                "price_increase", "low", f"{s.name} raised its price",
                f"From {_fmt(s.previous_amount)} to {_fmt(s.last_amount)} on {s.account_name}, "
                f"{_fmt((s.last_amount - s.previous_amount) * 12)} more a year.",
                {"from": str(s.previous_amount), "to": str(s.last_amount), "key": f"{s.key}:{s.account_id}:{s.price_changed_on}"},
                [], s.price_changed_on, s.last_amount - s.previous_amount))
            out[-1]["merchant_key"] = s.name.lower()
            out[-1]["account_id"] = s.account_id

    # Per-rule recency. Everything here is true; only some of it is still
    # something a person can do anything about.
    kept = []
    for a in out:
        days = ACTIONABLE_WITHIN.get(a["rule"], WINDOW_DAYS)
        if (today - a["occurred_on"]).days <= days:
            kept.append(a)
    return kept


def plan_alerts(conn) -> list[dict]:
    """Alerts that come from the plan rather than from a transaction: a missed
    payment, a payment the balance will not cover, a short runway, a maxed card.

    These are the expensive ones. A late fee plus the credit hit costs more than
    almost anything else in this app, and it is entirely avoidable with notice.
    """
    today = date.today()
    ds = plan.debts(conn)
    rw = plan.runway(conn, horizon_days=45)
    balance_on = {p["date"]: p["balance"] for p in rw["series"]}
    out: list[dict] = []

    for d in ds:
        if d.is_overdue:
            out.append(_alert(
                "payment_overdue", "high", f"{d.name} payment is past due",
                f"The issuer reports {_fmt(d.minimum)} overdue on {d.name} ··{d.mask}. Paying even the minimum "
                f"today stops further late fees, and a payment 30 days late is what reaches your credit report.",
                {"minimum": str(d.minimum), "due_date": str(d.due_date)}, [], today, d.minimum))
            out[-1]["account_id"] = d.account_id
            out[-1]["fingerprint"] = f"payment_overdue:{d.account_id}:{d.due_date}"
        elif d.due_date and 0 <= (d.due_date - today).days <= 10:
            projected = balance_on.get(d.due_date)
            if projected is not None and projected < d.minimum:
                out.append(_alert(
                    "payment_shortfall", "high",
                    f"{d.name} needs {_fmt(d.minimum)} on {d.due_date:%b %d}",
                    f"Projected cash that day is {_fmt(projected)}, which does not cover it. Moving money, "
                    f"paying early while cash is there, or calling the issuer beats a late fee.",
                    {"minimum": str(d.minimum), "projected_balance": str(projected),
                     "due_date": str(d.due_date)}, [], d.due_date, d.minimum))
                out[-1]["account_id"] = d.account_id
                out[-1]["fingerprint"] = f"payment_shortfall:{d.account_id}:{d.due_date}"

    # Gift cards and store credit expire; a funded purchase is worth knowing about.
    for a in funds.alerts(conn, today):
        out.append(_alert(a["kind"], a["severity"], a["title"], a["detail"],
                          {"fund_id": a["fund_id"], "amount": str(a["amount"])}, [], a["occurred_on"], a["amount"]))
        out[-1]["fingerprint"] = a["fingerprint"]

    # A category already over, or heading over with time left to steer.
    for a in budgets.alerts(conn, today):
        out.append(_alert(a["kind"], a["severity"], a["title"], a["detail"],
                          {"category": a["category"], "amount": str(a["amount"])}, [], a["occurred_on"], a["amount"]))
        out[-1]["fingerprint"] = a["fingerprint"]

    # Plaid asked to delete something old and Tally refused. Rare enough that
    # it should never be background noise, and important enough that finding
    # out from a chart looking odd is not good enough: the transaction is still
    # in every total, and a statement will not agree with it.
    withheld = conn.execute(
        """SELECT count(*) AS n, min(date) AS oldest, max(removal_withheld_at) AS latest
           FROM transactions WHERE removal_withheld_at IS NOT NULL""").fetchone()
    if withheld["n"]:
        out.append(_alert(
            "removal_withheld", "medium",
            f"{withheld['n']} transaction{'s' if withheld['n'] > 1 else ''} your bank says should be gone",
            f"Plaid asked Tally to delete {'them' if withheld['n'] > 1 else 'it'}, going back to "
            f"{withheld['oldest']:%b %Y}. Tally kept {'them' if withheld['n'] > 1 else 'it'} because "
            f"past about two years it is the only copy there is, and a deletion that old cannot be "
            f"undone. They still count in every total, so a statement may not agree.",
            {"count": withheld["n"], "oldest": str(withheld["oldest"])},
            [], today, None))
        out[-1]["fingerprint"] = f"removal_withheld:{withheld['latest']}"

    days = rw["days_until_zero"]
    if days is not None and days <= 21:
        out.append(_alert(
            "runway_short", "high" if days <= 10 else "medium",
            f"Cash runs out in {days} days at this rate",
            f"{_fmt(rw['cash'])} on hand, about {_fmt(rw['daily_spending'])} a day of everyday spending, "
            f"plus the bills due before then. The Plan page shows what is coming and what can move.",
            {"days": days, "cash": str(rw["cash"]), "daily_spending": str(rw["daily_spending"])},
            [], today, rw["cash"]))
        out[-1]["fingerprint"] = f"runway_short:{today.isocalendar()[:2]}"

    for d in ds:
        u = d.utilization
        if u is not None and u >= 0.9:
            out.append(_alert(
                "utilization_high", "low", f"{d.name} is at {u * 100:.0f}% of its limit",
                f"{_fmt(d.balance)} of {_fmt(d.credit_limit)}. Above about 30% starts to weigh on a credit "
                f"score, and there is little room left for an emergency.",
                {"utilization": round(u, 3), "balance": str(d.balance), "limit": str(d.credit_limit)},
                [], today, d.balance))
            out[-1]["account_id"] = d.account_id
            out[-1]["fingerprint"] = f"utilization_high:{d.account_id}:{today:%Y-%m}"
    return out


def scan(conn) -> dict:
    """Evaluate rules and insert new alerts. Commits. Returns counts."""
    cols = """id, date, amount, pending, name, bank_text, display_name, merchant_key, pfc_primary, pfc_detailed,
              category, kind, account_id, account_name, account_mask, institution"""
    rows = conn.execute(f"SELECT {cols} FROM v_txn WHERE date >= current_date - %s", (WINDOW_DAYS,)).fetchall()
    history = conn.execute(f"SELECT {cols} FROM v_txn WHERE date >= current_date - 480").fetchall()
    stream_rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income') AND date >= current_date - 400""").fetchall()
    streams = analytics.detect_recurring(stream_rows)
    trusted = {(r["rule"], r["merchant_key"]) for r in conn.execute("SELECT rule, merchant_key FROM alert_trust")}

    found = evaluate(rows, history, streams) + plan_alerts(conn)

    # An alert the rules would no longer raise should stop being shown. Without
    # this, every alert ever generated stays open until somebody clicks it --
    # including the ones a rule produced before it was fixed, which is exactly
    # how this page reached 44 urgent items with seven real ones in it.
    #
    # Only alerts still inside their own actionable window are retired. An old
    # one is not wrong, it has simply stopped being something to do, and it
    # keeps its status as history.
    live = {a["fingerprint"] for a in found}
    retired = 0
    for rule, days in {**{r: WINDOW_DAYS for r in ONE_OFF_RULES}, **ACTIONABLE_WITHIN}.items():
        rows_open = conn.execute(
            """SELECT fingerprint FROM alerts
               WHERE status = 'open' AND rule = %s AND occurred_on >= current_date - %s""",
            (rule, days)).fetchall()
        gone = [r["fingerprint"] for r in rows_open if r["fingerprint"] not in live]
        if gone:
            retired += conn.execute(
                """UPDATE alerts SET status = 'expired', resolved_at = now(),
                          expired_reason = 'the rule that raised this no longer does'
                   WHERE fingerprint = ANY(%s)""", (gone,)).rowcount

    # And the ones that simply got old. A rule fixed today does not reach back
    # past its own window, so without this the alerts raised by the old version
    # of it stay open forever -- which is how a $1.00 coffee was still being
    # called card testing three months later.
    for rule in PERISHABLE:
        days = ACTIONABLE_WITHIN.get(rule, WINDOW_DAYS)
        retired += conn.execute(
            """UPDATE alerts SET status = 'expired', resolved_at = now(),
                      expired_reason = 'too old to act on'
               WHERE status = 'open' AND rule = %s AND occurred_on < current_date - %s""",
            (rule, days)).rowcount

    inserted = refreshed = skipped = 0
    for a in found:
        if (a["rule"], a["merchant_key"]) in trusted:
            skipped += 1
            continue
        cur = conn.execute(
            """INSERT INTO alerts (fingerprint, rule, severity, title, detail, inputs, txn_ids, account_id,
                                   merchant_key, amount, occurred_on)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (fingerprint) DO UPDATE
                 SET title = EXCLUDED.title, detail = EXCLUDED.detail,
                     inputs = EXCLUDED.inputs, severity = EXCLUDED.severity
                 -- Only what is still on the list. Something already dealt
                 -- with keeps the words it was dealt with under.
                 WHERE alerts.status = 'open'
               RETURNING (xmax = 0) AS is_new""",
            (a["fingerprint"], a["rule"], a["severity"], a["title"], a["detail"], Jsonb(json.loads(json.dumps(a["inputs"], default=str))),
             a["txn_ids"], a["account_id"], a["merchant_key"], a["amount"], a["occurred_on"]))
        # xmax distinguishes the insert from the refresh. Counting a reworded
        # alert as a new one would report a flood every time a rule's wording changed.
        row = cur.fetchone()
        if row and row["is_new"]:
            inserted += 1
        elif row:
            refreshed += 1
    conn.commit()
    return {"evaluated": len(found), "inserted": inserted, "refreshed": refreshed,
            "trusted_skips": skipped, "retired": retired}
