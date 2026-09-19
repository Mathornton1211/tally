"""The long view: what has changed over years rather than weeks.

The discipline this module needs is comparing like with like. September against
a full year is not a comparison, it is a smaller number — and an app that shows
"spending down 68%!" every January has taught its user to ignore it.

So every comparison here is date-bounded to the same span in both periods. When
the current year is nine months old, last year is nine months old too.
"""
from calendar import monthrange
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
# Below this, a percentage change is arithmetic on noise.
MATERIAL = Decimal(150)


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _pct(now: Decimal, before: Decimal) -> float | None:
    if before <= 0:
        return None
    return float((now - before) / before)


def _same_day_last_year(d: date) -> date:
    """Feb 29 does not exist in most years, and neither does the 31st of most
    months. Clamp rather than raise."""
    year = d.year - 1
    return date(year, d.month, min(d.day, monthrange(year, d.month)[1]))


def years(conn) -> list[dict]:
    """Every year there is data for, whole. The oldest and newest are usually
    partial, and say so, because a half year drawn next to whole ones reads as
    a collapse in spending."""
    rows = conn.execute(
        """SELECT date_trunc('year', date)::date AS year,
                  coalesce(sum(spend), 0)  AS spent,
                  coalesce(sum(income), 0) AS earned,
                  count(*) AS transactions,
                  min(date) AS first, max(date) AS last
           FROM v_txn GROUP BY 1 ORDER BY 1""").fetchall()
    today = date.today()
    out = []
    for r in rows:
        y = r["year"].year
        full_start, full_end = date(y, 1, 1), date(y, 12, 31)
        covered = (r["last"] - r["first"]).days + 1
        out.append({
            **r, "year_number": y,
            "spent": _q(r["spent"]), "earned": _q(r["earned"]),
            "net": _q(Decimal(r["earned"]) - Decimal(r["spent"])),
            # Partial either because the year is still running, or because the
            # bank's history did not go back that far.
            "partial": r["first"] > full_start or (r["last"] < full_end and y < today.year)
                       or y == today.year,
            "days_covered": covered,
        })
    return out


def year_over_year(conn, today: date | None = None) -> dict:
    """This year against last, to the same day.

    The clamp is what makes it honest. On 17 September, "last year" means
    1 January to 17 September, not the whole of it.
    """
    today = today or date.today()
    start_now = date(today.year, 1, 1)
    start_before = date(today.year - 1, 1, 1)
    end_before = _same_day_last_year(today)

    rows = conn.execute(
        """SELECT category, category_label AS label, category_icon AS icon, essential,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS now,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS before
           FROM v_txn WHERE kind = 'expense'
           GROUP BY 1,2,3,4""",
        (start_now, today, start_before, end_before)).fetchall()

    categories = []
    for r in rows:
        now, before = _q(r["now"]), _q(r["before"])
        if now <= 0 and before <= 0:
            continue
        categories.append({
            "category": r["category"], "label": r["label"], "icon": r["icon"],
            "essential": r["essential"], "now": now, "before": before,
            "change": _q(now - before), "percent": _pct(now, before),
            # A 300% rise on $12 is not news.
            "material": abs(now - before) >= MATERIAL,
        })
    categories.sort(key=lambda c: abs(c["change"]), reverse=True)

    totals = conn.execute(
        """SELECT coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS spent_now,
                  coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS spent_before,
                  coalesce(sum(income) FILTER (WHERE date BETWEEN %s AND %s), 0) AS earned_now,
                  coalesce(sum(income) FILTER (WHERE date BETWEEN %s AND %s), 0) AS earned_before
           FROM v_txn""",
        (start_now, today, start_before, end_before,
         start_now, today, start_before, end_before)).fetchone()

    # Whether there is data in the COMPARISON WINDOW, not merely somewhere
    # earlier. History that begins in October makes "Jan 1 to Sep 17 last year"
    # an empty window, and comparing against an empty window produces "+100% on
    # everything" -- technically the same dates, and still nonsense.
    comparable = conn.execute(
        "SELECT EXISTS (SELECT 1 FROM v_txn WHERE date BETWEEN %s AND %s) AS x",
        (start_before, end_before)).fetchone()["x"]
    earliest = conn.execute("SELECT min(date) AS d FROM v_txn").fetchone()["d"]

    return {
        "this_year": {"from": start_now, "to": today},
        "last_year": {"from": start_before, "to": end_before},
        "comparable": bool(comparable),
        # So the page can say why rather than just going quiet.
        "history_starts": earliest,
        "spent": _q(totals["spent_now"]), "spent_before": _q(totals["spent_before"]),
        "earned": _q(totals["earned_now"]), "earned_before": _q(totals["earned_before"]),
        "spent_change": _q(Decimal(totals["spent_now"]) - Decimal(totals["spent_before"])),
        "spent_percent": _pct(_q(totals["spent_now"]), _q(totals["spent_before"])),
        "categories": categories,
        "risen": [c for c in categories if c["material"] and c["change"] > 0][:6],
        "fallen": [c for c in categories if c["material"] and c["change"] < 0][:6],
    }


def by_month(conn, months: int = 36) -> list[dict]:
    """A long monthly series, for a chart that shows a shape rather than a
    quarter."""
    rows = conn.execute(
        """SELECT date_trunc('month', date)::date AS month,
                  coalesce(sum(spend), 0) AS spent,
                  coalesce(sum(income), 0) AS earned
           FROM v_txn
           WHERE date >= date_trunc('month', current_date) - make_interval(months => %s)
           GROUP BY 1 ORDER BY 1""", (months,)).fetchall()
    return [{**r, "spent": _q(r["spent"]), "earned": _q(r["earned"]),
             "net": _q(Decimal(r["earned"]) - Decimal(r["spent"]))} for r in rows]


def merchants(conn, limit: int = 15) -> list[dict]:
    """Lifetime totals per merchant. The number nobody has ever seen for
    themselves, and the one that changes behaviour."""
    rows = conn.execute(
        """SELECT display_name AS name, max(logo_url) AS logo_url, max(category_icon) AS icon,
                  count(*) AS times, coalesce(sum(spend), 0) AS total,
                  min(date) AS first, max(date) AS last
           FROM v_txn WHERE kind = 'expense'
           GROUP BY 1 HAVING coalesce(sum(spend), 0) > 0
           ORDER BY 5 DESC LIMIT %s""", (limit,)).fetchall()
    return [{**r, "total": _q(r["total"]),
             "average": _q(Decimal(r["total"]) / r["times"]) if r["times"] else ZERO}
            for r in rows]


def annual_review(conn, year: int | None = None) -> dict:
    """The year in one page.

    Deliberately includes the unflattering numbers -- fees and interest -- next
    to the ordinary ones. A review that only shows where the money went and not
    what it cost to carry is a highlight reel.
    """
    today = date.today()
    year = year or today.year
    start, end = date(year, 1, 1), min(date(year, 12, 31), today)

    totals = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned,
                  count(*) AS transactions, count(DISTINCT display_name) AS merchants
           FROM v_txn WHERE date BETWEEN %s AND %s""", (start, end)).fetchone()
    categories = conn.execute(
        """SELECT category_label AS label, category_icon AS icon,
                  coalesce(sum(spend), 0) AS total, count(*) AS times
           FROM v_txn WHERE kind = 'expense' AND date BETWEEN %s AND %s
           GROUP BY 1,2 HAVING coalesce(sum(spend), 0) > 0 ORDER BY 3 DESC""",
        (start, end)).fetchall()
    top_merchants = conn.execute(
        """SELECT display_name AS name, max(logo_url) AS logo_url,
                  coalesce(sum(spend), 0) AS total, count(*) AS times
           FROM v_txn WHERE kind = 'expense' AND date BETWEEN %s AND %s
           GROUP BY 1 HAVING coalesce(sum(spend), 0) > 0 ORDER BY 3 DESC LIMIT 8""",
        (start, end)).fetchall()
    months = conn.execute(
        """SELECT date_trunc('month', date)::date AS month, coalesce(sum(spend), 0) AS spent
           FROM v_txn WHERE kind = 'expense' AND date BETWEEN %s AND %s
           GROUP BY 1 ORDER BY 2 DESC""", (start, end)).fetchall()
    cost_of_carrying = conn.execute(
        """SELECT coalesce(sum(spend) FILTER (WHERE category = 'fees'), 0) AS fees,
                  count(*) FILTER (WHERE category = 'fees') AS fee_count,
                  coalesce(sum(spend) FILTER (
                      WHERE category = 'fees' AND display_name ILIKE '%%interest%%'), 0) AS interest
           FROM v_txn WHERE date BETWEEN %s AND %s""", (start, end)).fetchone()
    biggest = conn.execute(
        """SELECT date, display_name AS name, spend AS amount, category_label AS category
           FROM v_txn WHERE kind = 'expense' AND date BETWEEN %s AND %s
           ORDER BY spend DESC LIMIT 1""", (start, end)).fetchone()

    spent = _q(totals["spent"])
    days = (end - start).days + 1
    return {
        "year": year, "from": start, "to": end, "complete": end >= date(year, 12, 31),
        "days": days,
        "spent": spent, "earned": _q(totals["earned"]),
        "net": _q(Decimal(totals["earned"]) - spent),
        "transactions": totals["transactions"], "merchants": totals["merchants"],
        "per_day": _q(spent / days) if days else ZERO,
        "per_month": _q(spent / Decimal(days) * Decimal("30.4")) if days else ZERO,
        "categories": [{**c, "total": _q(c["total"]),
                        "share": float(Decimal(c["total"]) / spent) if spent > 0 else None}
                       for c in categories],
        "top_merchants": [{**m, "total": _q(m["total"])} for m in top_merchants],
        "most_expensive_month": (
            {"month": months[0]["month"], "spent": _q(months[0]["spent"])} if months else None),
        "cheapest_month": (
            {"month": months[-1]["month"], "spent": _q(months[-1]["spent"])} if months else None),
        "cost_of_carrying": {
            "fees": _q(cost_of_carrying["fees"]),
            "count": cost_of_carrying["fee_count"],
            "interest": _q(cost_of_carrying["interest"]),
        },
        "biggest_single": ({**biggest, "amount": _q(biggest["amount"])} if biggest else None),
    }


def available_years(conn) -> list[int]:
    rows = conn.execute(
        "SELECT DISTINCT extract(year FROM date)::int AS y FROM v_txn ORDER BY 1 DESC").fetchall()
    return [r["y"] for r in rows]
