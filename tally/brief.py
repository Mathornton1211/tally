"""The Monday brief: one message, the week ahead.

Deterministic. Every number is computed here, so a phone notification can be
trusted without opening anything, and it works with the model offline.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from . import plan

ZERO = Decimal(0)


def _m(v) -> str:
    v = Decimal(v or 0)
    return f"${v:,.0f}" if abs(v) >= 100 else f"${v:,.2f}"


def facts(conn) -> dict:
    today = date.today()
    week_end = today + timedelta(days=7)
    rw = plan.runway(conn, horizon_days=60)
    ds = plan.debts(conn)
    mode = plan.mode(conn, rw, ds)

    due = [e for e in rw["events"] if e["date"] <= week_end and e["amount"] > 0]
    income = [e for e in rw["events"] if e["date"] <= week_end and e["amount"] < 0]
    spent_last_week = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS s FROM v_txn
           WHERE kind = 'expense' AND date >= %s AND date < %s""",
        (today - timedelta(days=7), today)).fetchone()["s"]
    spent_prior = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS s FROM v_txn
           WHERE kind = 'expense' AND date >= %s AND date < %s""",
        (today - timedelta(days=14), today - timedelta(days=7))).fetchone()["s"]
    alerts = conn.execute(
        """SELECT count(*) AS open, count(*) FILTER (WHERE severity = 'high') AS high
           FROM alerts WHERE status = 'open'""").fetchone()
    fees = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS s FROM v_txn
           WHERE category = 'fees' AND date >= %s""", (today - timedelta(days=7),)).fetchone()["s"]

    return {
        "date": today, "mode": mode["mode"],
        "cash": rw["cash"], "days_until_zero": rw["days_until_zero"],
        "safe_to_spend": rw["safe_to_spend"], "committed_through": rw["committed_through"],
        "due_this_week": [{"name": e["name"], "amount": e["amount"], "date": e["date"], "kind": e["kind"]}
                          for e in due],
        "due_total": sum((Decimal(e["amount"]) for e in due), ZERO),
        "income_this_week": [{"name": e["name"], "amount": -Decimal(e["amount"]), "date": e["date"]} for e in income],
        "spent_last_week": Decimal(spent_last_week), "spent_week_before": Decimal(spent_prior),
        "debt_total": sum((d.balance for d in ds), ZERO),
        "monthly_interest": sum((d.monthly_interest for d in ds), ZERO),
        "overdue": [d.name for d in ds if d.is_overdue],
        "open_alerts": alerts["open"], "high_alerts": alerts["high"],
        "fees_last_week": Decimal(fees),
    }


def compose(f: dict) -> tuple[str, str]:
    """Title and body. Short enough to read on a lock screen."""
    lines: list[str] = []
    if f["days_until_zero"] is not None and f["days_until_zero"] <= 30:
        title = f"{_m(f['cash'])} left, {f['days_until_zero']} days at this rate"
    elif f["due_total"] > 0:
        title = f"{_m(f['due_total'])} going out this week"
    else:
        title = f"{_m(f['cash'])} on hand, nothing scheduled"

    if f["overdue"]:
        lines.append(f"PAST DUE: {', '.join(f['overdue'])}. Pay the minimum today if you can.")

    if f["due_this_week"]:
        items = ", ".join(f"{e['name']} {_m(e['amount'])} {e['date']:%a}" for e in f["due_this_week"][:5])
        lines.append(f"Due this week ({_m(f['due_total'])}): {items}")
    else:
        lines.append("Nothing scheduled to go out this week.")

    if f["income_this_week"]:
        lines.append("Coming in: " + ", ".join(
            f"{e['name']} {_m(e['amount'])} {e['date']:%a}" for e in f["income_this_week"][:3]))

    spent, before = f["spent_last_week"], f["spent_week_before"]
    if before > 0:
        diff = spent - before
        word = "more" if diff > 0 else "less"
        lines.append(f"Spent {_m(spent)} last week, {_m(abs(diff))} {word} than the week before.")
    else:
        lines.append(f"Spent {_m(spent)} last week.")

    if f["safe_to_spend"] < 0:
        lines.append(f"That leaves you {_m(abs(f['safe_to_spend']))} short of the bills through "
                     f"{f['committed_through']:%b %d}.")
    else:
        lines.append(f"{_m(f['safe_to_spend'])} spare after the bills through {f['committed_through']:%b %d}.")

    if f["fees_last_week"] > 0:
        lines.append(f"{_m(f['fees_last_week'])} in fees and interest hit last week.")
    if f["debt_total"] > 0:
        lines.append(f"Cards and loans: {_m(f['debt_total'])}, costing {_m(f['monthly_interest'])} a month.")
    if f["open_alerts"]:
        lines.append(f"{f['open_alerts']} alert(s) waiting" + (f", {f['high_alerts']} urgent." if f["high_alerts"] else "."))
    return title, "\n".join(lines)


def send_weekly(conn, pool, notifier, force: bool = False) -> dict:
    """Send on the first run of a new week. Bookkeeping lives in app_settings,
    so a restart cannot cause a second one."""
    today = date.today()
    week = f"{today.isocalendar().year}-W{today.isocalendar().week:02d}"
    row = conn.execute("SELECT value FROM app_settings WHERE key = 'last_brief_week'").fetchone()
    last = json.loads(json.dumps(row["value"])) if row else None
    if not force and last == week:
        return {"skipped": "already sent this week"}
    f = facts(conn)
    title, body = compose(f)
    ok = notifier.send(title, body, kind="brief", priority=3, tag="calendar", path="/plan")
    if ok:
        conn.execute(
            """INSERT INTO app_settings (key, value, updated_at) VALUES ('last_brief_week', %s, now())
               ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value, updated_at = now()""", (Jsonb(week),))
        conn.commit()
    return {"sent": ok, "week": week, "title": title, "body": body}
