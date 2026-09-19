"""Monthly summary. Facts are computed here; the model only turns them into
a few readable sentences (invariant 3), and every figure it writes is checked
against the facts before the digest is marked verified.
"""
import json
from datetime import date, timedelta
from decimal import Decimal

from psycopg.types.json import Jsonb

from . import analytics, fees
from .llm import LLM, unverified_figures


def _month_bounds(month: date) -> tuple[date, date]:
    start = month.replace(day=1)
    end = (start.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    return start, end


def _f(v) -> float:
    return round(float(v or 0), 2)


def facts(conn, month: date) -> dict:
    start, end = _month_bounds(month)
    pstart, pend = _month_bounds(start - timedelta(days=1))
    tot = conn.execute(
        """SELECT coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS spend,
                  coalesce(sum(income) FILTER (WHERE date BETWEEN %s AND %s), 0) AS income,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS prev_spend,
                  coalesce(sum(income) FILTER (WHERE date BETWEEN %s AND %s), 0) AS prev_income
           FROM v_txn""", (start, end, start, end, pstart, pend, pstart, pend)).fetchone()
    cats = conn.execute(
        """SELECT category_label AS category,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS this_month,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS last_month
           FROM v_txn WHERE kind = 'expense' AND date BETWEEN %s AND %s
           GROUP BY 1 ORDER BY 2 DESC""", (start, end, pstart, pend, pstart, end)).fetchall()
    big = conn.execute(
        """SELECT display_name AS merchant, amount, date FROM v_txn
           WHERE kind = 'expense' AND date BETWEEN %s AND %s AND category NOT IN ('rent', 'loans', 'bills', 'insurance', 'fees')
           ORDER BY amount DESC LIMIT 3""", (start, end)).fetchall()
    fee_rep = fees.report(conn, start, end)
    stream_rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income') AND date <= %s AND date >= %s - 400""",
        (end, end)).fetchall()
    streams = analytics.detect_recurring(stream_rows, today=end)
    new_subs = [s for s in streams if s.kind == "expense" and start <= s.first_date <= end and s.active]
    increases = [s for s in streams if s.previous_amount is not None and s.price_changed_on
                 and start <= s.price_changed_on <= end]
    paychecks = conn.execute(
        """SELECT count(*) FILTER (WHERE date BETWEEN %s AND %s) AS now, count(*) FILTER (WHERE date BETWEEN %s AND %s) AS prev
           FROM v_txn WHERE category = 'income' AND income >= 500""", (start, end, pstart, pend)).fetchone()
    alerts = conn.execute(
        "SELECT count(*) AS n, count(*) FILTER (WHERE severity = 'high') AS high FROM alerts WHERE occurred_on BETWEEN %s AND %s",
        (start, end)).fetchone()

    spend, income = _f(tot["spend"]), _f(tot["income"])
    movers = sorted(
        [{"category": c["category"], "this_month": _f(c["this_month"]), "last_month": _f(c["last_month"]),
          "change": _f(Decimal(c["this_month"]) - Decimal(c["last_month"]))} for c in cats],
        key=lambda c: abs(c["change"]), reverse=True)[:3]
    return {
        "month": start.strftime("%B %Y"),
        "spending": spend, "spending_last_month": _f(tot["prev_spend"]),
        "spending_change": _f(Decimal(str(spend)) - Decimal(str(_f(tot["prev_spend"])))),
        "income": income, "income_last_month": _f(tot["prev_income"]),
        "paycheck_count": paychecks["now"], "paycheck_count_last_month": paychecks["prev"],
        "saved": _f(Decimal(str(income)) - Decimal(str(spend))),
        "savings_rate_percent": round((income - spend) / income * 100) if income else None,
        "top_categories": [{"category": c["category"], "amount": _f(c["this_month"])} for c in cats[:4]],
        "biggest_changes": movers,
        "largest_purchases": [{"merchant": b["merchant"], "amount": _f(b["amount"]), "date": b["date"].isoformat()} for b in big],
        "fees": {"total": _f(fee_rep["total"]), "count": fee_rep["count"],
                 "types": [{"type": p["label"], "amount": _f(p["total"])} for p in fee_rep["playbook"]]},
        "new_subscriptions": [{"name": s.name, "amount": _f(s.last_amount)} for s in new_subs],
        "price_increases": [{"name": s.name, "from": _f(s.previous_amount), "to": _f(s.last_amount)} for s in increases],
        "alerts": {"count": alerts["n"], "high": alerts["high"]},
    }


def write(conn, llm: LLM, month: date) -> dict:
    f = facts(conn, month)
    schema = {"type": "object", "required": ["headline", "body"], "properties": {
        "headline": {"type": "string"}, "body": {"type": "string"}}}
    system = (
        "You write a short monthly money recap addressed directly to the person (\"you\", never \"they\"), like a thoughtful friend who is good with money.\n"
        "- headline: under 10 words, the single most useful takeaway.\n"
        "- body: 3 to 5 sentences. First: what they kept (saved and savings rate), or that they spent more than came in.\n"
        "  Then: the main reason spending moved, naming the category from biggest_changes (a trip last month, a big grocery month).\n"
        "  If income changed a lot, mention paycheck_count vs paycheck_count_last_month when they differ.\n"
        "  End with one specific, doable suggestion drawn from the facts (a fee type, a category that jumped, a price increase).\n"
        "- Use ONLY numbers present in the facts JSON, written like $1,234 or $1,234.56. Never compute new numbers, "
        "never abbreviate to k, never guess.\n"
        "- Plain language, no lists, no markdown, no emojis, no em dashes. Don't moralize.")
    out = None
    bad: list[str] = []
    for attempt in range(2):
        note = "" if attempt == 0 else (
            f"\n\nYour last draft used figures not in the facts: {', '.join(bad)}. Use only figures from the facts.")
        out = llm.json("digest", [
            {"role": "system", "content": system},
            {"role": "user", "content": f"Facts:\n{json.dumps(f, indent=1)}{note}"},
        ], schema, temperature=0.3)
        bad = unverified_figures(out.get("headline", "") + " " + out.get("body", ""), f)
        if not bad:
            break
    row = {"month": month.replace(day=1), "facts": f, "headline": out["headline"].strip(),
           "body": out["body"].strip(), "verified": not bad, "unverified": bad, "model": llm.model}
    conn.execute(
        """INSERT INTO digests (month, facts, headline, body, verified, model) VALUES (%s,%s,%s,%s,%s,%s)
           ON CONFLICT (month) DO UPDATE SET facts = EXCLUDED.facts, headline = EXCLUDED.headline,
             body = EXCLUDED.body, verified = EXCLUDED.verified, model = EXCLUDED.model, created_at = now()""",
        (row["month"], Jsonb(f), row["headline"], row["body"], row["verified"], llm.model))
    conn.commit()
    return row
