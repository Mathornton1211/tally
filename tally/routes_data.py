"""Read and edit routes behind the dashboard, spending, cash flow, net worth,
recurring, and transactions pages.

Every total is computed in SQL or analytics.py. Amounts leave here as numbers
with Plaid's sign already resolved: `spend` is positive money out, `income`
is positive money in.
"""
import datetime
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from . import analytics, auth, review, scope, sync
from .state import state

router = APIRouter(prefix="/api")


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


def _month_start(d: date) -> date:
    return d.replace(day=1)


def _prev_month_start(d: date) -> date:
    return (d.replace(day=1) - timedelta(days=1)).replace(day=1)


class Filters:
    """Shared filter set. Every list page and chart takes the same parameters,
    so a URL copied from one page means the same thing on another."""

    def __init__(self, start: date | None = None, end: date | None = None,
                 account: list[str] = Query(default=[]), category: list[str] = Query(default=[]),
                 kind: str | None = None, q: str | None = None,
                 min_amount: float | None = None, max_amount: float | None = None):
        self.start, self.end, self.account, self.category = start, end, account, category
        self.kind, self.q, self.min_amount, self.max_amount = kind, q, min_amount, max_amount

    def where(self, alias: str = "v", dates: bool = True) -> tuple[str, list]:
        w, p = ["true"], []
        if dates and self.start:
            w.append(f"{alias}.date >= %s"); p.append(self.start)
        if dates and self.end:
            w.append(f"{alias}.date <= %s"); p.append(self.end)
        if self.account:
            w.append(f"{alias}.account_id = ANY(%s)"); p.append(self.account)
        if self.category:
            w.append(f"{alias}.category = ANY(%s)"); p.append(self.category)
        if self.kind in ("expense", "income", "transfer"):
            w.append(f"{alias}.kind = %s"); p.append(self.kind)
        if self.q:
            w.append(f"({alias}.display_name ILIKE %s OR {alias}.name ILIKE %s)")
            p += [f"%{self.q}%", f"%{self.q}%"]
        if self.min_amount is not None:
            w.append(f"abs({alias}.amount) >= %s"); p.append(self.min_amount)
        if self.max_amount is not None:
            w.append(f"abs({alias}.amount) <= %s"); p.append(self.max_amount)
        return " AND ".join(w), p


def _range(f: Filters, default_days: int = 30) -> tuple[date, date]:
    end = f.end or date.today()
    start = f.start or (end - timedelta(days=default_days - 1))
    return start, end


def _stream_dict(s: analytics.Stream) -> dict:
    d = asdict(s)
    d["monthly_cost"] = s.monthly_cost
    return d


def _recurring_streams(conn) -> list[analytics.Stream]:
    rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income')
             AND date >= current_date - 400"""
    ).fetchall()
    return analytics.detect_recurring(rows)


# ---------------------------------------------------------------- meta

@router.get("/meta")
def meta():
    with _conn() as conn:
        categories = conn.execute("SELECT key, label, kind, icon FROM categories ORDER BY sort").fetchall()
        accounts = conn.execute(
            """SELECT a.id, a.name, a.mask, a.type, a.subtype, COALESCE(inst.name, a.institution_name) AS institution
               FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
               LEFT JOIN institutions inst ON inst.id = i.institution_id
               WHERE NOT a.hidden ORDER BY inst.name, a.type, a.name""").fetchall()
        sync_row = conn.execute(
            """SELECT max(last_synced_at) AS last_synced_at,
                      count(*) FILTER (WHERE status <> 'ok') AS needs_attention
               FROM items""").fetchone()
        span = conn.execute("SELECT min(date) AS first, max(date) AS last FROM v_txn").fetchone()
    return {"plaid_env": state["settings"].plaid_env, "categories": categories, "accounts": accounts,
            **sync_row, "first_date": span["first"], "last_date": span["last"]}


# ---------------------------------------------------------------- dashboard

@router.get("/dashboard")
def dashboard():
    today = date.today()
    m0, lm0 = _month_start(today), _prev_month_start(today)
    lm_end = m0 - timedelta(days=1)
    with _conn() as conn:
        daily = conn.execute(
            """SELECT date, sum(spend) AS spend, sum(income) AS income FROM v_txn
               WHERE date BETWEEN %s AND %s GROUP BY date""", (lm0, today)).fetchall()
        by_day = {r["date"]: r for r in daily}

        def cumulative(start: date, end: date):
            out, run, d = [], 0.0, start
            while d <= end:
                run += float(by_day.get(d, {}).get("spend") or 0)
                out.append(round(run, 2))
                d += timedelta(days=1)
            return out

        this_month = cumulative(m0, today)
        last_month = cumulative(lm0, lm_end)
        same_point = last_month[min(today.day, len(last_month)) - 1] if last_month else 0.0
        income_mtd = sum(float(r["income"] or 0) for d, r in by_day.items() if d >= m0)

        cats = conn.execute(
            """SELECT category AS key, category_label AS label, category_icon AS icon,
                      sum(spend) FILTER (WHERE date >= %s) AS amount,
                      sum(spend) FILTER (WHERE date < %s AND date <= %s) AS last_month_same_point
               FROM v_txn WHERE kind = 'expense' AND date >= %s
               GROUP BY 1,2,3 HAVING sum(spend) FILTER (WHERE date >= %s) > 0
               ORDER BY 4 DESC""",
            (m0, m0, lm0 + timedelta(days=today.day - 1), lm0, m0)).fetchall()

        accounts = conn.execute(
            """SELECT a.id, a.name, a.mask, a.type, a.subtype, a.current_balance, a.available_balance,
                      a.credit_limit, COALESCE(inst.name, a.institution_name) AS institution
               FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
               LEFT JOIN institutions inst ON inst.id = i.institution_id
               WHERE NOT a.hidden ORDER BY a.type, a.current_balance DESC""").fetchall()
        nw_start = today - timedelta(days=89)
        flows = conn.execute(
            """SELECT account_id, date, sum(amount) AS amount FROM v_txn
               WHERE date >= %s GROUP BY 1,2""", (nw_start,)).fetchall()

        fees = conn.execute(
            """SELECT coalesce(sum(spend) FILTER (WHERE date >= current_date - 29), 0) AS last_30,
                      count(*) FILTER (WHERE date >= current_date - 29) AS count_30,
                      coalesce(sum(spend) FILTER (WHERE date >= date_trunc('year', current_date)), 0) AS ytd
               FROM v_txn WHERE category = 'fees'""").fetchone()

        recent = conn.execute(
            """SELECT id, date, amount, pending, display_name, name, logo_url, category, category_label,
                      category_icon, kind, account_name, account_mask
               FROM v_txn ORDER BY date DESC, id LIMIT 8""").fetchall()
        streams = _recurring_streams(conn)
        alerts = conn.execute(
            """SELECT count(*) FILTER (WHERE status = 'open') AS open,
                      count(*) FILTER (WHERE status = 'open' AND severity IN ('high','medium')) AS urgent,
                      (array_agg(title ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END,
                                 occurred_on DESC) FILTER (WHERE status = 'open'))[1] AS top
               FROM alerts""").fetchone()

    nw = analytics.estimate_balance_history(accounts, flows, nw_start, today)
    upcoming = [s for s in streams if s.active and s.kind == "expense"
                and today - timedelta(days=2) <= s.next_date <= today + timedelta(days=30)]
    return {
        "today": today,
        "spending": {"month_to_date": round(this_month[-1], 2) if this_month else 0,
                     "last_month_same_point": round(same_point, 2),
                     "last_month_total": round(last_month[-1], 2) if last_month else 0,
                     "this_month": this_month, "last_month": last_month,
                     "income_month_to_date": round(income_mtd, 2)},
        "categories": cats,
        "net_worth": {"current": nw[-1]["net_worth"] if nw else 0,
                      "thirty_days_ago": nw[-31]["net_worth"] if len(nw) > 30 else None,
                      "series": [{"date": r["date"], "value": r["net_worth"]} for r in nw]},
        "accounts": accounts,
        "fees": fees,
        "alerts": alerts,
        "upcoming": [_stream_dict(s) for s in upcoming],
        "recent": recent,
    }


# ---------------------------------------------------------------- spending

@router.get("/spending")
def spending(f: Filters = Depends()):
    start, end = _range(f, 30)
    span = (end - start).days + 1
    prev_start, prev_end = start - timedelta(days=span), start - timedelta(days=1)
    where, params = f.where(dates=False)
    by_month = span > 62
    with _conn() as conn:
        base = f"FROM v_txn v WHERE v.kind = 'expense' AND {where}"
        totals = conn.execute(
            f"""SELECT coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS total,
                       coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS previous,
                       count(*) FILTER (WHERE date BETWEEN %s AND %s) AS count {base}""",
            [start, end, prev_start, prev_end, start, end] + params).fetchone()
        essentials = conn.execute(
            f"""SELECT essential, coalesce(sum(spend), 0) AS amount, count(*) AS count
                {base} AND date BETWEEN %s AND %s GROUP BY 1""", params + [start, end]).fetchall()
        categories = conn.execute(
            f"""SELECT category AS key, category_label AS label, category_icon AS icon, max(essential::int) AS essential,
                       coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS amount,
                       coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) AS previous,
                       count(*) FILTER (WHERE date BETWEEN %s AND %s) AS count
                {base} GROUP BY 1,2,3
                HAVING coalesce(sum(spend) FILTER (WHERE date BETWEEN %s AND %s), 0) > 0
                ORDER BY 4 DESC""",
            [start, end, prev_start, prev_end, start, end] + params + [start, end]).fetchall()
        bucket = "date_trunc('month', date)::date" if by_month else "date"
        series = conn.execute(
            f"""SELECT {bucket} AS bucket, sum(spend) AS amount {base} AND date BETWEEN %s AND %s
                GROUP BY 1 ORDER BY 1""", params + [start, end]).fetchall()
        merchants = conn.execute(
            f"""SELECT display_name AS name, max(logo_url) AS logo_url, max(category_icon) AS icon,
                       sum(spend) AS amount, count(*) AS count
                {base} AND date BETWEEN %s AND %s
                GROUP BY display_name HAVING sum(spend) > 0 ORDER BY 4 DESC LIMIT 10""",
            params + [start, end]).fetchall()
        first = conn.execute("SELECT min(date) AS d FROM v_txn").fetchone()["d"]
    # A comparison against a period with no data behind it is a fake +100%.
    if first is None or prev_start < first:
        totals["previous"] = None
        for c in categories:
            c["previous"] = None
    return {"start": start, "end": end, "previous_start": prev_start, "previous_end": prev_end,
            "bucket": "month" if by_month else "day", **totals, "categories": categories,
            "series": series, "merchants": merchants,
            # What could actually be cut, which is the useful split when money is tight.
            "essential": next((Decimal(e["amount"]) for e in essentials if e["essential"]), Decimal(0)),
            "flexible": next((Decimal(e["amount"]) for e in essentials if not e["essential"]), Decimal(0))}


# ---------------------------------------------------------------- cash flow

@router.get("/cashflow")
def cashflow(f: Filters = Depends()):
    start, end = _range(f, 365)
    where, params = f.where(dates=False)
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT date_trunc('month', date)::date AS month,
                       coalesce(sum(income), 0) AS income, coalesce(sum(spend), 0) AS spending
                FROM v_txn v WHERE {where} AND date BETWEEN %s AND %s
                GROUP BY 1 ORDER BY 1""", params + [start, end]).fetchall()
    for r in rows:
        r["net"] = r["income"] - r["spending"]
        r["savings_rate"] = float(r["net"] / r["income"]) if r["income"] else None
    inc = sum(r["income"] for r in rows)
    spd = sum(r["spending"] for r in rows)
    return {"start": start, "end": end, "months": rows,
            "income": inc, "spending": spd, "net": inc - spd,
            "savings_rate": float((inc - spd) / inc) if inc else None}


# ---------------------------------------------------------------- net worth

@router.get("/networth")
def networth(f: Filters = Depends()):
    start, end = _range(f, 180)
    with _conn() as conn:
        accounts = conn.execute(
            """SELECT a.id, a.name, a.mask, a.type, a.subtype, a.current_balance, a.credit_limit,
                      COALESCE(inst.name, a.institution_name) AS institution
               FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
               LEFT JOIN institutions inst ON inst.id = i.institution_id
               WHERE NOT a.hidden ORDER BY a.type, a.current_balance DESC""").fetchall()
        flows = conn.execute(
            "SELECT account_id, date, sum(amount) AS amount FROM v_txn WHERE date >= %s GROUP BY 1,2",
            (start,)).fetchall()
    series = analytics.estimate_balance_history(accounts, flows, start, end)
    per_account = {}
    for a in accounts:
        hist = analytics.estimate_balance_history([a], flows, start, end)
        per_account[a["id"]] = hist[0]["assets"] - hist[0]["liabilities"] if hist else 0
    for a in accounts:
        signed_now = -a["current_balance"] if a["type"] in analytics.LIABILITY_TYPES else a["current_balance"]
        a["change"] = (signed_now or 0) - per_account[a["id"]]
    return {"start": start, "end": end, "estimated": True,
            "series": series, "accounts": accounts}


# ---------------------------------------------------------------- recurring

@router.get("/recurring")
def recurring():
    today = date.today()
    with _conn() as conn:
        streams = _recurring_streams(conn)
    active = [s for s in streams if s.active]
    names: dict[str, list[analytics.Stream]] = {}
    for s in active:
        names.setdefault(s.name.lower(), []).append(s)
    duplicates = {k for k, v in names.items() if len({s.account_id for s in v}) > 1}
    out = []
    for s in streams:
        d = _stream_dict(s)
        d["duplicate"] = s.active and s.name.lower() in duplicates
        d["days_until"] = (s.next_date - today).days
        out.append(d)
    expense = [s for s in active if s.kind == "expense"]
    return {
        "streams": out,
        "monthly_expense": sum(s.monthly_cost for s in expense),
        "monthly_income": sum(s.monthly_cost for s in active if s.kind == "income"),
        "next_30_days": sum(s.typical_amount for s in expense if 0 <= (s.next_date - today).days <= 30),
        "price_changes": sum(1 for s in expense if s.previous_amount is not None),
        "duplicates": len(duplicates),
    }


# ---------------------------------------------------------------- transactions

@router.get("/transactions")
def transactions(f: Filters = Depends(), limit: int = Query(default=100, le=1000), offset: int = 0):
    where, params = f.where()
    with _conn() as conn:
        totals = conn.execute(
            f"""SELECT count(*) AS total, coalesce(sum(spend), 0) AS spending,
                       coalesce(sum(income), 0) AS income FROM v_txn v WHERE {where}""",
            params).fetchone()
        rows = conn.execute(
            f"""SELECT id, date, amount, pending, name, display_name, logo_url, website, note,
                       category, category_label, category_icon, category_overridden, kind,
                       pfc_detailed, payment_channel, account_id, account_name, account_mask,
                       account_type, institution, merchant_key, category_from_rule, bank_text, category_source, name_source
                FROM v_txn v WHERE {where}
                ORDER BY date DESC, id LIMIT %s OFFSET %s""",
            params + [limit, offset]).fetchall()
    return {**totals, "rows": rows}


class TxnPatch(BaseModel):
    category: str | None = None
    note: str | None = None
    reset_category: bool = False


@router.patch("/transactions/{txn_id}")
def patch_transaction(txn_id: str, body: TxnPatch):
    sets, params = [], []
    if body.reset_category:
        sets.append("category = NULL")
    elif body.category is not None:
        sets.append("category = %s"); params.append(body.category)
    if body.note is not None:
        sets.append("note = %s"); params.append(body.note.strip() or None)
    if not sets:
        raise HTTPException(400, "nothing to change")
    with _conn() as conn:
        if body.category and not conn.execute("SELECT 1 FROM categories WHERE key = %s",
                                              (body.category,)).fetchone():
            raise HTTPException(400, "unknown category")
        n = conn.execute(
            f"UPDATE transactions SET {', '.join(sets)}, updated_at = now(), "
            f"reviewed_at = coalesce(reviewed_at, now()) WHERE id = %s",
            params + [txn_id]).rowcount
        if not n:
            raise HTTPException(404, "no such transaction")
        return conn.execute(
            """SELECT id, category, category_label, category_icon, category_overridden, category_from_rule, category_source, kind, note
               FROM v_txn WHERE id = %s""", (txn_id,)).fetchone()

# ---------------------------------------------------------------- the review queue

@router.get("/review")
def review_queue(days: int = Query(default=review.DEFAULT_DAYS, ge=1, le=400),
                 limit: int = Query(default=200, ge=1, le=500)):
    with _conn() as conn:
        return {**review.queue(conn, days, limit), "progress": review.progress(conn)}


class ReviewIn(BaseModel):
    ids: list[str] = Field(min_length=1, max_length=500)
    # Which window the caller is looking at, so the queue that comes back
    # matches their screen instead of silently narrowing to the default.
    days: int = Field(default=review.DEFAULT_DAYS, ge=1, le=400)
    category: str | None = None
    add_tags: list[str] = []
    note: str | None = None
    # A plain confirmation changes nothing and still takes the row off the list.
    mark_reviewed: bool = True


@router.post("/review/apply")
def review_apply(body: ReviewIn, request: Request):
    me = state["auth"].person(request.cookies.get(auth.COOKIE))
    with _conn() as conn:
        try:
            out = review.apply(conn, body.ids, body.category, body.add_tags,
                               body.note, body.mark_reviewed, me)
        except ValueError as e:
            raise HTTPException(400, str(e))
        return {**out, **review.queue(conn, body.days), "progress": review.progress(conn)}


class BacklogIn(BaseModel):
    before: datetime.date
    days: int = Field(default=review.DEFAULT_DAYS, ge=1, le=400)


@router.post("/review/clear-backlog")
def review_clear_backlog(body: BacklogIn, request: Request):
    """Draw a line under the history. Somebody arriving with two years of it is
    not going to review two thousand charges, and an app that insists is one
    they close."""
    me = state["auth"].person(request.cookies.get(auth.COOKIE))
    with _conn() as conn:
        n = review.clear_backlog(conn, body.before, me)
        return {"cleared": n, **review.queue(conn, body.days), "progress": review.progress(conn)}


@router.get("/removals")
def removals(limit: int = Query(default=100, ge=1, le=500)):
    """What sync has been asked to delete, and what it did about it.

    Deleting a transaction is the only irreversible thing sync does, so it
    leaves a record either way -- including of the ones it obeyed, which is what
    makes "where did that go" a question with an answer.
    """
    with _conn() as conn:
        rows = conn.execute(
            """SELECT r.id, r.account_id, r.occurred_on, r.amount, r.name, r.removed_at,
                      r.age_days, r.obeyed, a.name AS account_name, a.mask AS account_mask
               FROM removed_transactions r LEFT JOIN v_acct a ON a.id = r.account_id
               ORDER BY r.removed_at DESC LIMIT %s""", (limit,)).fetchall()
        counts = conn.execute(
            """SELECT count(*) FILTER (WHERE obeyed) AS deleted,
                      count(*) FILTER (WHERE NOT obeyed) AS kept
               FROM removed_transactions""").fetchone()
        return {"removals": rows, **counts, "obey_under_days": sync.OBEY_REMOVAL_DAYS}
