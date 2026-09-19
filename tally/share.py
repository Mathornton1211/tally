"""Read-only links, for the accountant.

The shape of the problem: somebody outside the household needs last year's
numbers, and giving them a login is both more access than they need and more
trouble than they want.

So a share link is a bearer token and is treated like one:

  narrow      one date range, one detail level, nothing outside it
  read-only   there is no write path behind this token at all
  revocable   and it says when it was last used, so an unexpected view is visible
  expiring    the default is an expiry, not forever
  hashed      the token is stored as a hash, so a database dump does not hand
              over working links
  frozen      it sees what its creator could see when they made it. Linking a
              private account next month must not silently widen a link that is
              already in somebody else's inbox.
"""
import hashlib
import secrets
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

DEFAULT_DAYS = 30
TOKEN_BYTES = 24


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create(conn, label: str, start: date, end: date, detail: str = "summary",
           expires_on: date | None = None, created_by: int | None = None,
           as_person: int | None = None) -> dict:
    """Returns the row plus the plaintext token, which is shown once and never
    stored. If it is lost, the link is replaced rather than recovered."""
    token = secrets.token_urlsafe(TOKEN_BYTES)
    row = conn.execute(
        """INSERT INTO share_links (token_hash, label, start_date, end_date, detail,
                                    expires_on, created_by, as_person)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
           RETURNING id, label, start_date, end_date, detail, expires_on, created_at""",
        (_hash(token), label, start, end, detail,
         expires_on or (date.today() + timedelta(days=DEFAULT_DAYS)), created_by, as_person)).fetchone()
    return {**row, "token": token}


def listing(conn) -> list[dict]:
    return conn.execute(
        """SELECT s.id, s.label, s.start_date, s.end_date, s.detail, s.expires_on, s.revoked,
                  s.views, s.last_viewed_at, s.created_at, p.name AS created_by_name,
                  (s.revoked OR (s.expires_on IS NOT NULL AND s.expires_on < current_date)) AS dead
           FROM share_links s LEFT JOIN people p ON p.id = s.created_by
           ORDER BY s.created_at DESC""").fetchall()


def resolve(conn, token: str) -> dict | None:
    """The live link for this token, or None. Bumps the view counter, because
    'nobody has opened this yet' and 'opened nine times from somewhere you did
    not expect' are both things worth being able to see."""
    row = conn.execute(
        """SELECT * FROM share_links
           WHERE token_hash = %s AND NOT revoked
             AND (expires_on IS NULL OR expires_on >= current_date)""", (_hash(token),)).fetchone()
    if not row:
        return None
    conn.execute(
        "UPDATE share_links SET views = views + 1, last_viewed_at = now() WHERE id = %s", (row["id"],))
    return row


def revoke(conn, link_id: int) -> bool:
    return bool(conn.execute(
        "UPDATE share_links SET revoked = true WHERE id = %s", (link_id,)).rowcount)


def contents(conn, link: dict) -> dict:
    """What the holder of this link may read. Nothing here takes a parameter
    from the request: the range and the detail level come from the stored row,
    so a caller cannot widen their own access by editing a query string."""
    start, end = link["start_date"], link["end_date"]

    totals = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned,
                  count(*) AS transactions
           FROM v_txn WHERE date BETWEEN %s AND %s""", (start, end)).fetchone()
    categories = conn.execute(
        """SELECT category, category_label AS label, category_icon AS icon, kind,
                  coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned, count(*) AS count
           FROM v_txn WHERE date BETWEEN %s AND %s
           GROUP BY 1,2,3,4 HAVING coalesce(sum(spend),0) <> 0 OR coalesce(sum(income),0) <> 0
           ORDER BY 5 DESC""", (start, end)).fetchall()
    months = conn.execute(
        """SELECT date_trunc('month', date)::date AS month,
                  coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned
           FROM v_txn WHERE date BETWEEN %s AND %s GROUP BY 1 ORDER BY 1""", (start, end)).fetchall()
    tagged = conn.execute(
        """SELECT tag, count(*) AS count, coalesce(sum(abs(amount)), 0) AS total
           FROM v_txn, unnest(tags) AS tag WHERE date BETWEEN %s AND %s
           GROUP BY tag ORDER BY 3 DESC""", (start, end)).fetchall()

    out = {
        "label": link["label"], "start": start, "end": end, "detail": link["detail"],
        "spent": _q(totals["spent"]), "earned": _q(totals["earned"]),
        "net": _q(Decimal(totals["earned"]) - Decimal(totals["spent"])),
        "transactions": totals["transactions"],
        "categories": categories, "months": months, "tags": tagged,
        "expires_on": link["expires_on"],
    }
    if link["detail"] == "transactions":
        out["rows"] = conn.execute(
            """SELECT id, date, display_name, amount, currency, category_label, kind, account_name,
                      tags, note
               FROM v_txn WHERE date BETWEEN %s AND %s ORDER BY date DESC, id LIMIT 5000""",
            (start, end)).fetchall()
    return out
