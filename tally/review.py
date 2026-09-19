"""The short list of charges that actually need a person.

The hard part of a review queue is not building it, it is deciding what stays
out. "Everything since you last looked" is the transactions page, and nobody
reviews the transactions page -- a list with no end is one you never start.

So a charge earns a place here only if a human would change something about it:

  new_merchant    nothing from this merchant has ever been confirmed, so the
                  name is probably still shouting AMZN MKTP US*2K4XY and the
                  category is a guess. Deliberately "never confirmed" rather
                  than "chronologically first": what matters is whether anybody
                  has told Tally what this place is, and answering once covers
                  every charge from it
  low_confidence  Plaid says it is not sure
  uncategorised   it fell through to Other, which is the category that means
                  "we do not know"
  guessed         the local model chose it, and a model's guess is worth one
                  glance before it becomes a year of budget history
  large           above a threshold. Not because it is suspicious -- Alerts
                  does suspicion -- but because a big charge is usually the one
                  worth splitting, tagging or counting toward a fund

Everything else is left alone. A $4.50 coffee that Plaid filed as dining with
high confidence does not need anybody's attention, and putting it in the queue
is how the queue stops being opened.

Two things make it finishable. The window is recent by default, and a first run
can draw a line under the backlog -- somebody arriving with two years of
history needs a starting point, not two thousand decisions.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)
# Recent enough to still remember buying it.
DEFAULT_DAYS = 45
# Above this, a charge is worth a look even when everything about it is known:
# it is the one most likely to want a split, a tag or a fund.
LARGE = Decimal(250)
LOW_CONFIDENCE = ("LOW", "UNKNOWN")


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


REASONS = {
    "new_merchant": "Nothing from here has been checked yet — one answer covers them all",
    "uncategorised": "Landed in Other, which is where Tally puts what it cannot place",
    "low_confidence": "Plaid was not sure about this one",
    "guessed": "Categorised by the local model",
    "large": "Big enough to be worth splitting, tagging, or putting toward something",
}
# Which reason to show when several apply. Ordered by how much a person's
# answer is worth: naming a new merchant fixes every future charge from it.
PRIORITY = ("new_merchant", "uncategorised", "low_confidence", "guessed", "large")


def queue(conn, days: int = DEFAULT_DAYS, limit: int = 200, today: date | None = None) -> dict:
    today = today or date.today()
    rows = conn.execute(
        """WITH seen AS (
               SELECT merchant_key,
                      count(*) FILTER (WHERE reviewed) AS confirmed,
                      count(*) AS times
               FROM v_txn GROUP BY merchant_key
           )
           SELECT v.id, v.date, v.display_name, v.merchant_key, v.amount, v.currency,
                  v.foreign_currency, v.category, v.category_label, v.category_icon,
                  v.category_source, v.kind, v.logo_url, v.account_name, v.account_mask,
                  v.bank_text, v.name_source, v.tags, v.note, v.pfc_confidence,
                  v.owner_name, v.owner_color,
                  (s.confirmed = 0) AS new_merchant,
                  s.times AS merchant_seen
           FROM v_txn v JOIN seen s ON s.merchant_key = v.merchant_key
           WHERE NOT v.reviewed AND NOT v.pending
             AND v.kind = 'expense'
             AND v.date >= %s
           ORDER BY v.date DESC, abs(v.amount) DESC
           LIMIT %s""",
        (today - _days(days), limit * 3)).fetchall()

    items = []
    for r in rows:
        why = []
        if r["new_merchant"]:
            why.append("new_merchant")
        if r["category"] == "other":
            why.append("uncategorised")
        if (r["pfc_confidence"] or "UNKNOWN") in LOW_CONFIDENCE:
            why.append("low_confidence")
        if r["category_source"] == "ai":
            why.append("guessed")
        if abs(Decimal(r["amount"])) >= LARGE:
            why.append("large")
        if not why:
            continue
        reason = next(p for p in PRIORITY if p in why)
        items.append({**r, "amount": _q(r["amount"]), "reasons": why,
                      "reason": reason, "why": REASONS[reason]})

    # Grouped from everything that qualifies, BEFORE the display cap -- a
    # merchant with charges past the cap would otherwise offer to fix twelve
    # and quietly fix nine.
    by_merchant: dict[str, dict] = {}
    for i in items:
        g = by_merchant.setdefault(i["merchant_key"], {
            "merchant_key": i["merchant_key"], "display_name": i["display_name"],
            "logo_url": i["logo_url"], "category": i["category"],
            "category_label": i["category_label"], "category_icon": i["category_icon"],
            "ids": [], "total": ZERO, "reason": i["reason"], "why": i["why"]})
        g["ids"].append(i["id"])
        g["total"] = _q(g["total"] + abs(i["amount"]))
    groups = sorted((g for g in by_merchant.values() if len(g["ids"]) > 1),
                    key=lambda g: len(g["ids"]), reverse=True)

    shown = items[:limit]
    backlog = conn.execute(
        """SELECT count(*) AS n, min(date) AS oldest FROM v_txn
           WHERE NOT reviewed AND NOT pending AND kind = 'expense' AND date < %s""",
        (today - _days(days),)).fetchone()

    return {
        "items": shown,
        "groups": groups,
        # What is on the list, and what is being shown of it.
        "total": len(items),
        "shown": len(shown),
        "window_days": days,
        # What sits behind the window, so a first run can draw a line under it
        # rather than presenting two thousand decisions.
        "backlog": backlog["n"], "backlog_oldest": backlog["oldest"],
        "reasons": REASONS,
    }


def _days(n: int):
    from datetime import timedelta
    return timedelta(days=n)


def confirm(conn, ids: list[str], person: int | None = None) -> int:
    """Mark these as looked at. Idempotent, and it never un-reviews."""
    if not ids:
        return 0
    return conn.execute(
        """UPDATE transactions SET reviewed_at = now(), reviewed_by = %s
           WHERE id = ANY(%s) AND reviewed_at IS NULL""", (person, ids)).rowcount


def clear_backlog(conn, before: date, person: int | None = None) -> int:
    """Draw a line under everything older than a date.

    Somebody arriving with two years of history is not going to review two
    thousand charges, and an app that insists is one they close. The honest
    move is to let them start from today and say so.
    """
    return conn.execute(
        """UPDATE transactions SET reviewed_at = now(), reviewed_by = %s
           WHERE reviewed_at IS NULL AND date < %s""", (person, before)).rowcount


def apply(conn, ids: list[str], category: str | None = None, add_tags: list[str] | None = None,
          note: str | None = None, mark_reviewed: bool = True, person: int | None = None) -> dict:
    """One decision, applied to everything it was made about.

    Any change counts as a review. Correcting a category and then having to
    also click "reviewed" is the kind of double work that makes people stop.
    """
    if not ids:
        return {"changed": 0, "reviewed": 0}
    changed = 0
    if category is not None:
        if not conn.execute("SELECT 1 FROM categories WHERE key = %s", (category,)).fetchone():
            raise ValueError("unknown category")
        changed += conn.execute(
            "UPDATE transactions SET category = %s, updated_at = now() WHERE id = ANY(%s)",
            (category, ids)).rowcount
    if add_tags:
        clean = sorted({t.strip().lower() for t in add_tags if t.strip()})
        # Union, not replace: a bulk tag should never remove one somebody put
        # on a single transaction by hand.
        changed += conn.execute(
            """UPDATE transactions
                  SET tags = ARRAY(SELECT DISTINCT unnest(tags || %s::text[]) ORDER BY 1),
                      updated_at = now()
                WHERE id = ANY(%s)""", (clean, ids)).rowcount
    if note is not None:
        changed += conn.execute(
            "UPDATE transactions SET note = %s, updated_at = now() WHERE id = ANY(%s)",
            (note.strip() or None, ids)).rowcount
    reviewed = confirm(conn, ids, person) if mark_reviewed else 0
    return {"changed": changed, "reviewed": reviewed}


def progress(conn, today: date | None = None) -> dict:
    """Enough to say "you are done" and mean it."""
    today = today or date.today()
    # v_txn carries reviewed_at itself now, so no join -- and the join it used
    # to do made the column name ambiguous, since both sides have one.
    row = conn.execute(
        """SELECT count(*) FILTER (WHERE reviewed_at IS NOT NULL) AS reviewed,
                  count(*) AS total,
                  count(*) FILTER (WHERE reviewed_at::date = %s) AS today
           FROM v_txn WHERE kind = 'expense' AND NOT pending""", (today,)).fetchone()
    # Lifetime, deliberately: "1,847 of 1,902" is the satisfying number, while
    # the queue's own `total` is the to-do. Named apart so nothing reads them
    # as the same population.
    return {"reviewed": row["reviewed"], "total_ever": row["total"], "today": row["today"]}
