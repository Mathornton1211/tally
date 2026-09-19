"""The part that keeps working while nobody is looking.

Every other module answers a question the moment it is asked. This one runs
after each sync, applies the same rules to whatever is now true, and
accumulates what it finds. The accumulation is the point: "Netflix went up $3"
is worth nothing, and "Netflix has gone up three times since 2024, $84 a year
more than when you signed up" is worth a phone call.

Two rules the findings obey, because a list of savings advice is worthless the
moment one entry turns out to be invented:

  every number is arithmetic on something the bank reported. No estimates of
  what a "typical" household spends, no averages from somewhere else.

  a finding says how sure it is. `certain` is arithmetic on facts. `likely`
  adds one stated assumption. `worth_checking` is a question Tally cannot
  answer from the data -- and it is phrased as a question, not advice.

A model is never asked to produce a finding or a figure. At most it rewords one,
and `llm.py` already refuses output containing figures it was not given.
"""
import json
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

from psycopg.types.json import Jsonb

from . import analytics, bills, plan

ZERO = Decimal(0)
# Below this a year of effort is not worth a phone call.
WORTH_RAISING = Decimal(25)

# "Is this still worth paying for?" is only a question about things you could
# actually stop. Asked about rent or a car loan it is not insight, it is noise
# at the top of the list -- and a list whose loudest entries are useless is one
# people stop opening. Rent, loans, insurance and utilities can still be
# NEGOTIATED (bills.py), and a price rise on them is still worth flagging; they
# just cannot be cancelled.
CANCELLABLE = {"entertainment", "services", "health", "shopping"}


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _m(v) -> str:
    return f"${Decimal(v or 0):,.2f}"


def _finding(kind, fingerprint, title, detail, annual, confidence="likely",
             evidence=None, action=None, account_id=None, merchant_key=None) -> dict:
    return {"kind": kind, "fingerprint": fingerprint, "title": title, "detail": detail,
            "annual_saving": _q(annual) if annual is not None else None,
            "confidence": confidence, "evidence": evidence or {}, "action": action,
            "account_id": account_id, "merchant_key": merchant_key}


# ---------------------------------------------------------------- the rules

def price_creep(conn, streams) -> list[dict]:
    """A subscription that has quietly gone up, measured against the first
    price actually observed rather than against last month."""
    out = []
    for s in streams:
        if s.kind != "expense" or not s.active or s.count < 4:
            continue
        rows = conn.execute(
            """SELECT date, amount FROM v_txn
               WHERE merchant_key = %s AND kind = 'expense' AND NOT pending
               ORDER BY date""", (s.key.split("|")[0] if "|" in s.key else s.name.lower(),)).fetchall()
        if len(rows) < 4:
            continue
        first, latest = _q(rows[0]["amount"]), _q(rows[-1]["amount"])
        if first <= 0 or latest <= first * Decimal("1.05"):
            continue
        per_year = (latest - first) * Decimal("30.4") / Decimal(s.interval_days) * 12
        if per_year < WORTH_RAISING:
            continue
        months = max(1, (rows[-1]["date"] - rows[0]["date"]).days // 30)
        out.append(_finding(
            "price_creep", f"price_creep:{s.name.lower()}",
            f"{s.name} has gone from {_m(first)} to {_m(latest)}",
            f"Since {rows[0]['date']:%B %Y}, over {months} months. That is {_m(per_year)} a year more "
            f"than you signed up for, and the increase was never announced to you personally.",
            per_year, "certain",
            {"first": str(first), "latest": str(latest), "since": str(rows[0]["date"]),
             "charges": len(rows)},
            # What to do about it depends on what can be done about it. A rise
            # on something cancellable gets the cancellation ladder; a rise on
            # the electricity bill gets the letter that asks for a better rate.
            (bills.cancel_script(s.name, latest, months) if s.category in CANCELLABLE
             else bills.lower_email(s.name, s.monthly_cost, rows[0]["date"], first)
             if s.category in bills.NEGOTIABLE else None),
            merchant_key=s.name.lower()))
    return out


def long_running_subscription(conn, streams, today: date) -> list[dict]:
    """What a subscription has cost in total, which is the number nobody ever
    sees. Phrased as a question, because Tally cannot know whether it is used.

    Only for things that can actually be stopped. Telling somebody their rent
    has cost tens of thousands is true, useless, and loud enough to bury the
    findings that are neither.
    """
    out = []
    for s in streams:
        if s.kind != "expense" or not s.active or s.count < 10:
            continue
        if s.category not in CANCELLABLE:
            continue
        paid = _q(s.typical_amount * s.count)
        annual = _q(s.monthly_cost * 12)
        if annual < WORTH_RAISING or paid < 100:
            continue
        months = max(1, (today - s.first_date).days // 30)
        out.append(_finding(
            "long_running", f"long_running:{s.name.lower()}",
            f"{s.name} has cost {_m(paid)} so far",
            f"{_m(s.typical_amount)} every {s.cadence[:-2] if s.cadence.endswith('ly') else s.cadence}, "
            f"{s.count} times since {s.first_date:%B %Y} -- {months} months. It renews whether or not "
            f"it gets used, which is the only reason this is worth a look.",
            annual, "worth_checking",
            {"paid_so_far": str(paid), "charges": s.count, "since": str(s.first_date)},
            bills.cancel_script(s.name, s.typical_amount, months),
            merchant_key=s.name.lower()))
    return out


def overlapping_services(conn, streams) -> list[dict]:
    """Two subscriptions doing the same job. Grouped by category, which is a
    blunt instrument -- hence `worth_checking`, and the names are listed so the
    answer is obvious at a glance."""
    by_category: dict[str, list] = {}
    for s in streams:
        if s.kind == "expense" and s.active and s.category in ("entertainment", "services"):
            by_category.setdefault(s.category, []).append(s)
    out = []
    for category, group in by_category.items():
        if len(group) < 2:
            continue
        annual = _q(sum((s.monthly_cost for s in group), ZERO) * 12)
        if annual < WORTH_RAISING:
            continue
        names = ", ".join(sorted(s.name for s in group))
        label = group[0].category_label
        out.append(_finding(
            "overlapping", f"overlapping:{category}",
            f"{len(group)} {label.lower()} subscriptions running at once",
            f"{names}. Together {_m(annual)} a year. Tally cannot tell which of these you actually "
            f"open -- it can only tell you that you are paying for all of them.",
            None, "worth_checking",
            {"names": sorted(s.name for s in group), "annual": str(annual)}))
    return out


def annual_fee_not_earning(conn) -> list[dict]:
    """A card charging a yearly fee. Whether it earns out depends on rewards
    Tally cannot see, so it reports the fee and what the card is actually used
    for, and leaves the conclusion where it belongs."""
    rows = conn.execute(
        """SELECT a.id, a.name, a.mask, s.annual_fee, s.reward_rate,
                  (SELECT coalesce(sum(spend), 0) FROM v_txn v
                    WHERE v.account_id = a.id AND v.date >= current_date - 365) AS spent_year,
                  (SELECT count(*) FROM v_txn v
                    WHERE v.account_id = a.id AND v.date >= current_date - 365) AS uses
           FROM v_acct a JOIN account_settings s ON s.account_id = a.id
           WHERE NOT a.hidden AND s.annual_fee > 0""").fetchall()
    out = []
    for r in rows:
        fee = _q(r["annual_fee"])
        spent = _q(r["spent_year"])
        rate = Decimal(r["reward_rate"] or 0) / 100
        earned = _q(spent * rate) if rate else None
        if earned is not None and earned >= fee:
            continue
        gap = _q(fee - earned) if earned is not None else fee
        if gap < WORTH_RAISING:
            continue
        if earned is not None:
            detail = (f"{_m(fee)} a year. At {r['reward_rate']}% on the {_m(spent)} you put through it "
                      f"in the last year, it earned about {_m(earned)} -- {_m(gap)} short of its own fee.")
            confidence = "likely"
        else:
            detail = (f"{_m(fee)} a year, and {r['uses']} transactions on it in the last 12 months "
                      f"totalling {_m(spent)}. Set the rewards rate on the account to see whether it "
                      f"earns its fee back.")
            confidence = "worth_checking"
        out.append(_finding(
            "annual_fee", f"annual_fee:{r['id']}",
            f"{r['name']} charges {_m(fee)} a year",
            detail, gap, confidence,
            {"fee": str(fee), "spent_year": str(spent), "uses": r["uses"]},
            bills.cancel_card_script(r["name"], fee),
            account_id=r["id"]))
    return out


def expensive_balance(conn) -> list[dict]:
    """A balance sitting on a high rate while another card has room at a lower
    one. Arithmetic on APRs and limits the issuer reported."""
    debts = [d for d in plan.debts(conn) if d.balance > 0 and d.apr]
    if len(debts) < 2:
        return []
    cheapest = min(debts, key=lambda d: d.apr)
    out = []
    for d in debts:
        if d.account_id == cheapest.account_id or not d.apr or not cheapest.apr:
            continue
        gap = Decimal(d.apr) - Decimal(cheapest.apr)
        if gap < 3:
            continue
        room = Decimal(cheapest.credit_limit or 0) - Decimal(cheapest.balance or 0)
        movable = min(Decimal(d.balance), max(room, ZERO))
        if movable <= 0:
            continue
        saving = _q(movable * gap / 100)
        if saving < WORTH_RAISING:
            continue
        out.append(_finding(
            "expensive_balance", f"expensive_balance:{d.account_id}:{cheapest.account_id}",
            f"{_m(movable)} is sitting at {d.apr}% while {cheapest.name} charges {cheapest.apr}%",
            f"Moving it would save about {_m(saving)} a year in interest. {cheapest.name} has "
            f"{_m(room)} of room. A balance transfer usually costs 3-5% up front, so check that the "
            f"fee is less than the saving before doing it -- on this amount that is "
            f"{_m(movable * Decimal('0.04'))} or so.",
            saving, "likely",
            {"from": d.name, "to": cheapest.name, "amount": str(movable),
             "apr_gap": str(gap), "transfer_fee_estimate": str(_q(movable * Decimal("0.04")))},
            account_id=d.account_id))
    return out


def recurring_fees(conn) -> list[dict]:
    """A fee that keeps happening is a standing cost, not an accident."""
    rows = conn.execute(
        """SELECT display_name, merchant_key, count(*) AS n, coalesce(sum(spend), 0) AS total,
                  min(date) AS first, max(date) AS last
           FROM v_txn WHERE category = 'fees' AND date >= current_date - 365 AND spend > 0
           GROUP BY 1, 2 HAVING count(*) >= 3 ORDER BY 4 DESC""").fetchall()
    out = []
    for r in rows:
        total = _q(r["total"])
        if total < WORTH_RAISING:
            continue
        out.append(_finding(
            "recurring_fee", f"recurring_fee:{r['merchant_key']}",
            f"{r['display_name']} has charged you {r['n']} fees, {_m(total)}",
            f"Between {r['first']:%b %Y} and {r['last']:%b %Y}. A fee that happens three times is a "
            f"standing arrangement rather than bad luck -- the Fees page says which kind this is and "
            f"what stops it.",
            total, "certain",
            {"count": r["n"], "total": str(total)},
            merchant_key=r["merchant_key"]))
    return out


RULES = ("price_creep", "long_running", "overlapping", "annual_fee",
         "expensive_balance", "recurring_fee")


def evaluate(conn, today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income')
             AND date >= current_date - 800""").fetchall()
    streams = analytics.detect_recurring(rows)

    found: list[dict] = []
    found += price_creep(conn, streams)
    found += long_running_subscription(conn, streams, today)
    found += overlapping_services(conn, streams)
    found += annual_fee_not_earning(conn)
    found += expensive_balance(conn)
    found += recurring_fees(conn)
    return found


def run(conn, today: date | None = None) -> dict:
    """Apply the rules and fold the results into what is already known.

    Anything previously open that no rule found this time has stopped being
    true, so it expires rather than lingering. Dismissed stays dismissed --
    being told again about something you have already decided against is how a
    useful list becomes noise somebody stops reading.
    """
    today = today or date.today()
    found = evaluate(conn, today)
    seen = {f["fingerprint"] for f in found}

    added = updated = 0
    for f in found:
        row = conn.execute(
            """INSERT INTO findings (kind, fingerprint, title, detail, annual_saving, confidence,
                                     evidence, action, account_id, merchant_key)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (fingerprint) DO UPDATE
                 SET title = EXCLUDED.title,
                     detail = EXCLUDED.detail,
                     annual_saving = EXCLUDED.annual_saving,
                     confidence = EXCLUDED.confidence,
                     evidence = EXCLUDED.evidence,
                     action = EXCLUDED.action,
                     last_seen = current_date,
                     times_seen = findings.times_seen + 1,
                     -- Something that expired and came back is open again.
                     -- Something dismissed or acted on stays where it was put.
                     status = CASE WHEN findings.status = 'expired' THEN 'open'
                                   ELSE findings.status END
               RETURNING (xmax = 0) AS inserted""",
            (f["kind"], f["fingerprint"], f["title"], f["detail"], f["annual_saving"],
             f["confidence"], Jsonb(json.loads(json.dumps(f["evidence"], default=str))),
             f["action"], f["account_id"], f["merchant_key"])).fetchone()
        if row["inserted"]:
            added += 1
        else:
            updated += 1

    expired = conn.execute(
        """UPDATE findings SET status = 'expired', resolved_on = current_date
           WHERE status = 'open' AND NOT (fingerprint = ANY(%s))""",
        (list(seen),)).rowcount
    conn.commit()
    return {"found": len(found), "new": added, "still_true": updated, "expired": expired}


def listing(conn, status: str = "open") -> dict:
    where = "true" if status == "all" else "f.status = %s"
    params = [] if status == "all" else [status]
    rows = conn.execute(
        f"""SELECT f.*, a.name AS account_name, a.mask AS account_mask
            FROM findings f LEFT JOIN v_acct a ON a.id = f.account_id
            WHERE {where} AND tally_can_see(f.owner_id)
            ORDER BY f.annual_saving DESC NULLS LAST, f.id""", params).fetchall()
    # Scoped the same way the rows are. A header that counts somebody else's
    # findings while the list below cannot show them is the visibility rule
    # leaking through a total -- the same shape as the bug v_acct had to fix.
    totals = conn.execute(
        """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                  count(*) FILTER (WHERE status = 'acted') AS acted,
                  coalesce(sum(annual_saving) FILTER (WHERE status = 'open'), 0) AS on_the_table,
                  coalesce((SELECT sum(o.saved) FROM finding_outcomes o
                             JOIN findings f2 ON f2.id = o.finding_id
                            WHERE tally_can_see(f2.owner_id)), 0) AS actually_saved
           FROM findings WHERE tally_can_see(owner_id)""").fetchone()
    return {"findings": rows, **totals}
