"""Linking Items and pulling their data from Plaid into Postgres.

The cursor rule that everything here is built around: a cursor is only saved
in the SAME database transaction as the rows it covers. If the write fails, the
old cursor stays and the next run re-reads the same pages. Upserts make that
re-read harmless. Saving the cursor first and the rows second is how a sync
silently loses a page forever.
"""
import json
import logging
from datetime import date, timedelta

from psycopg.types.json import Jsonb

from .crypto import TokenBox
from .plaid import Plaid, PlaidError

log = logging.getLogger("tally.sync")

MAX_PAGINATION_RESTARTS = 3

# Errors that need the user to re-login through Link update mode. Retrying these
# on a timer does nothing but fill the log.
LOGIN_ERRORS = {"ITEM_LOGIN_REQUIRED", "PENDING_EXPIRATION", "PENDING_DISCONNECT",
                "INVALID_CREDENTIALS", "INVALID_MFA", "USER_SETUP_REQUIRED"}


# ---------------------------------------------------------------- linking

def link_item(conn, plaid: Plaid, box: TokenBox, public_token: str) -> int:
    exchanged = plaid.public_token_exchange(public_token)
    access_token = exchanged["access_token"]
    item = plaid.item_get(access_token)["item"]

    inst_id = item.get("institution_id")
    if inst_id:
        inst = plaid.institution_get(inst_id)["institution"]
        conn.execute(
            """INSERT INTO institutions (id, name, url, primary_color, oauth)
               VALUES (%s, %s, %s, %s, %s)
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, url = EXCLUDED.url,
                 primary_color = EXCLUDED.primary_color, oauth = EXCLUDED.oauth""",
            (inst_id, inst["name"], inst.get("url"), inst.get("primary_color"), inst.get("oauth")),
        )

    row = conn.execute(
        """INSERT INTO items (plaid_item_id, institution_id, access_token_enc, products)
           VALUES (%s, %s, %s, %s)
           ON CONFLICT (plaid_item_id) DO UPDATE SET access_token_enc = EXCLUDED.access_token_enc,
             status = 'ok', error_code = NULL, error_message = NULL
           RETURNING id""",
        (item["item_id"], inst_id, box.seal(access_token), item.get("products") or []),
    ).fetchone()
    item_id = row["id"] if isinstance(row, dict) else row[0]

    upsert_accounts(conn, item_id, plaid.accounts_get(access_token)["accounts"])
    return item_id


# ---------------------------------------------------------------- writes

def upsert_accounts(conn, item_id: int, accounts: list[dict]) -> None:
    today = date.today()
    for a in accounts:
        b = a.get("balances") or {}
        conn.execute(
            """INSERT INTO accounts (id, item_id, name, official_name, mask, type, subtype,
                 current_balance, available_balance, credit_limit, iso_currency, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name,
                 official_name = EXCLUDED.official_name, mask = EXCLUDED.mask,
                 type = EXCLUDED.type, subtype = EXCLUDED.subtype,
                 current_balance = EXCLUDED.current_balance,
                 available_balance = EXCLUDED.available_balance,
                 credit_limit = EXCLUDED.credit_limit,
                 iso_currency = EXCLUDED.iso_currency, updated_at = now()""",
            (a["account_id"], item_id, a["name"], a.get("official_name"), a.get("mask"),
             a["type"], a.get("subtype"), b.get("current"), b.get("available"),
             b.get("limit"), b.get("iso_currency_code")),
        )
        conn.execute(
            """INSERT INTO balances_daily (account_id, day, current_balance, available_balance, credit_limit)
               VALUES (%s,%s,%s,%s,%s)
               ON CONFLICT (account_id, day) DO UPDATE SET current_balance = EXCLUDED.current_balance,
                 available_balance = EXCLUDED.available_balance, credit_limit = EXCLUDED.credit_limit""",
            (a["account_id"], today, b.get("current"), b.get("available"), b.get("limit")),
        )


def upsert_transaction(conn, t: dict) -> None:
    pfc = t.get("personal_finance_category") or {}
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, iso_currency, date, authorized_date,
             authorized_datetime, name, merchant_name, merchant_entity_id, logo_url, website,
             payment_channel, pending, pending_transaction_id, pfc_primary, pfc_detailed,
             pfc_confidence, location, counterparties, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
           ON CONFLICT (id) DO UPDATE SET account_id = EXCLUDED.account_id,
             amount = EXCLUDED.amount, iso_currency = EXCLUDED.iso_currency,
             date = EXCLUDED.date, authorized_date = EXCLUDED.authorized_date,
             authorized_datetime = EXCLUDED.authorized_datetime, name = EXCLUDED.name,
             merchant_name = EXCLUDED.merchant_name,
             merchant_entity_id = EXCLUDED.merchant_entity_id, logo_url = EXCLUDED.logo_url,
             website = EXCLUDED.website, payment_channel = EXCLUDED.payment_channel,
             pending = EXCLUDED.pending, pending_transaction_id = EXCLUDED.pending_transaction_id,
             pfc_primary = EXCLUDED.pfc_primary, pfc_detailed = EXCLUDED.pfc_detailed,
             pfc_confidence = EXCLUDED.pfc_confidence, location = EXCLUDED.location,
             counterparties = EXCLUDED.counterparties, raw = EXCLUDED.raw, updated_at = now()""",
        # User-owned columns (category_id, category_source, note) are absent from
        # the UPDATE on purpose: Plaid re-sending a transaction must not wipe an edit.
        (t["transaction_id"], t["account_id"], t["amount"], t.get("iso_currency_code"),
         t["date"], t.get("authorized_date"), t.get("authorized_datetime"), t["name"],
         t.get("merchant_name"), t.get("merchant_entity_id"), t.get("logo_url"),
         t.get("website"), t.get("payment_channel"), bool(t.get("pending")),
         t.get("pending_transaction_id"), pfc.get("primary"), pfc.get("detailed"),
         pfc.get("confidence_level"), Jsonb(t.get("location")),
         Jsonb(t.get("counterparties")), Jsonb(t)),
    )


# ---------------------------------------------------------------- sync

def _fetch_all_pages(plaid: Plaid, access_token: str, cursor: str | None) -> dict:
    """Read every page from `cursor` to the end. Nothing is written here.

    Plaid requires restarting from the ORIGINAL cursor, not the last page's,
    when data changes mid-pagination. Accumulated pages are thrown away.
    """
    for attempt in range(MAX_PAGINATION_RESTARTS + 1):
        added, modified, removed, pages = [], [], [], 0
        page_cursor = cursor
        try:
            while True:
                resp = plaid.transactions_sync(access_token, page_cursor)
                pages += 1
                added += resp["added"]
                modified += resp["modified"]
                removed += resp["removed"]
                page_cursor = resp["next_cursor"]
                if not resp["has_more"]:
                    return {"added": added, "modified": modified, "removed": removed,
                            "next_cursor": page_cursor, "pages": pages,
                            "accounts": resp.get("accounts") or [],
                            "update_status": resp.get("transactions_update_status")}
        except PlaidError as e:
            if e.code == "TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION" and attempt < MAX_PAGINATION_RESTARTS:
                log.warning("mutation during pagination, restarting (attempt %d)", attempt + 1)
                continue
            raise
    raise RuntimeError("unreachable")


# How old a transaction can be and still be deleted on Plaid's say-so.
#
# A reversal, a correction, or a pending row being replaced by its posted twin
# all happen within days. A genuine institution-side deletion of something from
# last year is vanishingly rare -- and past Plaid's ~24-month window, Tally is
# the only copy of it. Ninety days is generous for every legitimate case and
# refuses the one that cannot be undone.
OBEY_REMOVAL_DAYS = 90


def apply_removals(conn, removed_ids: list[str]) -> dict:
    """Archive every removal, obey the recent ones, refuse the old ones.

    The bias is deliberate and it is not symmetric. A transaction wrongly kept
    is a discrepancy against a statement that somebody can see and fix. A
    transaction wrongly deleted is gone, and if it is older than Plaid's window
    it cannot be fetched again from anywhere.
    """
    if not removed_ids:
        return {"removed": 0, "withheld": 0}

    rows = conn.execute(
        """SELECT t.*, (current_date - t.date) AS age_days
           FROM transactions t WHERE t.id = ANY(%s)""", (removed_ids,)).fetchall()

    obey, withhold = [], []
    for r in rows:
        (obey if (r["age_days"] or 0) <= OBEY_REMOVAL_DAYS else withhold).append(r)

    for r in rows:
        payload = {k: v for k, v in r.items() if k != "age_days"}
        conn.execute(
            """INSERT INTO removed_transactions
                   (id, account_id, occurred_on, amount, name, row, age_days, obeyed)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s)
               ON CONFLICT (id) DO UPDATE SET removed_at = now(), obeyed = EXCLUDED.obeyed""",
            (r["id"], r["account_id"], r["date"], r["amount"], r["name"],
             Jsonb(json.loads(json.dumps(payload, default=str))),
             r["age_days"], r in obey))

    if obey:
        conn.execute("DELETE FROM transactions WHERE id = ANY(%s)", ([r["id"] for r in obey],))
    if withhold:
        ids = [r["id"] for r in withhold]
        conn.execute(
            "UPDATE transactions SET removal_withheld_at = now() WHERE id = ANY(%s)", (ids,))
        # Loud on purpose. This is rare, and if it is ever common something is
        # wrong that nobody should find out about from a chart looking odd.
        log.warning("refused to delete %d transaction(s) older than %d days on Plaid's "
                    "instruction: %s", len(withhold), OBEY_REMOVAL_DAYS, ", ".join(ids[:5]))
    return {"removed": len(obey), "withheld": len(withhold)}


def sync_item(conn, plaid: Plaid, box: TokenBox, item_id: int) -> dict:
    """Sync one Item. `conn` must NOT be in autocommit; this commits or rolls back."""
    item = conn.execute("SELECT id, access_token_enc, cursor FROM items WHERE id = %s",
                        (item_id,)).fetchone()
    run_id = _start_run(conn, item_id)
    try:
        access_token = box.open(item["access_token_enc"])
        data = _fetch_all_pages(plaid, access_token, item["cursor"])
    except PlaidError as e:
        conn.rollback()
        status = "login_required" if e.code in LOGIN_ERRORS else "error"
        conn.execute("UPDATE items SET status = %s, error_code = %s, error_message = %s WHERE id = %s",
                     (status, e.code, e.body.get("error_message"), item_id))
        _finish_run(conn, run_id, ok=False, error=str(e))
        conn.commit()
        raise
    except Exception as e:
        conn.rollback()
        _finish_run(conn, run_id, ok=False, error=repr(e))
        conn.commit()
        raise

    try:
        # Accounts first: transactions reference them.
        if data["accounts"]:
            upsert_accounts(conn, item_id, data["accounts"])
        for t in data["added"] + data["modified"]:
            upsert_transaction(conn, t)
        removed_ids = [r["transaction_id"] for r in data["removed"]]
        removals = apply_removals(conn, removed_ids)
        conn.execute(
            """UPDATE items SET cursor = %s, update_status = %s, last_synced_at = now(),
                 status = 'ok', error_code = NULL, error_message = NULL WHERE id = %s""",
            (data["next_cursor"] or None, data["update_status"], item_id),
        )
        counts = {"added": len(data["added"]), "modified": len(data["modified"]),
                  "removed": removals["removed"], "pages": data["pages"]}
        _finish_run(conn, run_id, ok=True, **counts)
        conn.commit()
        return {**counts, "withheld": removals["withheld"],
                "update_status": data["update_status"]}
    except Exception as e:
        conn.rollback()
        _finish_run(conn, run_id, ok=False, error=repr(e))
        conn.commit()
        raise


# Banks that simply do not offer the product. Not errors, and not worth a retry
# loop or an alert: the app falls back to estimated rates and says so.
NO_LIABILITIES = {"PRODUCTS_NOT_SUPPORTED", "NO_LIABILITY_ACCOUNTS", "NO_ACCOUNTS",
                  "INVALID_PRODUCT", "PRODUCT_NOT_READY", "INSUFFICIENT_CREDENTIALS"}

_APR_PREFERENCE = ["balance_transfer_apr", "purchase_apr", "cash_apr", "special_apr"]


def _pick_apr(aprs: list[dict], balance) -> float | None:
    """The rate that actually applies to what is being carried.

    Plaid reports several APRs per card, each with the balance it applies to.
    The one with a non-zero balance_subject_to_apr is the real cost; otherwise
    fall back to the purchase APR, which is what a new carried balance costs.
    """
    with_balance = [a for a in aprs if (a.get("balance_subject_to_apr") or 0) > 0]
    if with_balance:
        return max(float(a["apr_percentage"]) for a in with_balance if a.get("apr_percentage") is not None)
    by_type = {str(a.get("apr_type", "")).lower(): a for a in aprs}
    for key in _APR_PREFERENCE:
        a = by_type.get(key)
        if a and a.get("apr_percentage") is not None:
            return float(a["apr_percentage"])
    rates = [float(a["apr_percentage"]) for a in aprs if a.get("apr_percentage") is not None]
    return max(rates) if rates else None


def sync_liabilities(conn, plaid: Plaid, box: TokenBox, item_id: int) -> int:
    """Store issuer terms for this Item's cards and loans. Returns rows written."""
    item = conn.execute("SELECT access_token_enc FROM items WHERE id = %s", (item_id,)).fetchone()
    try:
        data = plaid.liabilities_get(box.open(item["access_token_enc"]))["liabilities"]
    except PlaidError as e:
        if e.code in NO_LIABILITIES:
            log.info("item %s: no liabilities (%s)", item_id, e.code)
            return 0
        raise

    known = {r["id"] for r in conn.execute(
        "SELECT id FROM accounts WHERE item_id = %s", (item_id,)).fetchall()}
    written = 0
    for kind, rows in (("credit", data.get("credit") or []), ("student", data.get("student") or []),
                       ("mortgage", data.get("mortgage") or [])):
        for r in rows:
            acct = r.get("account_id")
            if acct not in known:
                continue
            aprs = r.get("aprs") or []
            interest = r.get("interest_rate") or {}
            apr = _pick_apr(aprs, None) if aprs else interest.get("percentage")
            conn.execute(
                """INSERT INTO liabilities (account_id, kind, apr, aprs, last_statement_balance,
                       last_statement_date, minimum_payment, next_due_date, is_overdue,
                       last_payment_amount, last_payment_date, source, raw, updated_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'plaid',%s, now())
                   ON CONFLICT (account_id) DO UPDATE SET kind = EXCLUDED.kind, apr = EXCLUDED.apr,
                     aprs = EXCLUDED.aprs, last_statement_balance = EXCLUDED.last_statement_balance,
                     last_statement_date = EXCLUDED.last_statement_date,
                     minimum_payment = EXCLUDED.minimum_payment, next_due_date = EXCLUDED.next_due_date,
                     is_overdue = EXCLUDED.is_overdue, last_payment_amount = EXCLUDED.last_payment_amount,
                     last_payment_date = EXCLUDED.last_payment_date, source = 'plaid',
                     raw = EXCLUDED.raw, updated_at = now()""",
                (acct, kind, apr, Jsonb(aprs), r.get("last_statement_balance"),
                 r.get("last_statement_issue_date"), r.get("minimum_payment_amount"),
                 r.get("next_payment_due_date") or r.get("next_monthly_payment_due_date"),
                 r.get("is_overdue"), r.get("last_payment_amount"), r.get("last_payment_date"),
                 Jsonb(r)))
            written += 1
    conn.commit()
    return written


def sync_investments(conn, plaid: Plaid, box: TokenBox, item_id: int, days: int = 365) -> dict:
    """Holdings and investment activity for brokerages and 401k providers.

    Same rule as liabilities: a bank that does not offer the product is not an
    error. Securities are upserted first because holdings reference them.
    """
    item = conn.execute("SELECT access_token_enc FROM items WHERE id = %s", (item_id,)).fetchone()
    token = box.open(item["access_token_enc"])
    try:
        data = plaid.investments_holdings_get(token)
    except PlaidError as e:
        if e.code in NO_LIABILITIES or e.code == "NO_INVESTMENT_ACCOUNTS":
            return {"holdings": 0}
        raise

    known = {r["id"] for r in conn.execute("SELECT id FROM accounts WHERE item_id = %s", (item_id,)).fetchall()}
    for s in data.get("securities") or []:
        conn.execute(
            """INSERT INTO securities (id, ticker, name, type, close_price, close_price_as_of,
                   iso_currency, is_cash_equivalent, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (id) DO UPDATE SET ticker = EXCLUDED.ticker, name = EXCLUDED.name,
                 type = EXCLUDED.type, close_price = EXCLUDED.close_price,
                 close_price_as_of = EXCLUDED.close_price_as_of, iso_currency = EXCLUDED.iso_currency,
                 is_cash_equivalent = EXCLUDED.is_cash_equivalent, updated_at = now()""",
            (s["security_id"], s.get("ticker_symbol"), s.get("name"), s.get("type"),
             s.get("close_price"), s.get("close_price_as_of"), s.get("iso_currency_code"),
             s.get("is_cash_equivalent")))

    held = 0
    seen: set[tuple[str, str]] = set()
    for h in data.get("holdings") or []:
        if h["account_id"] not in known:
            continue
        seen.add((h["account_id"], h["security_id"]))
        conn.execute(
            """INSERT INTO holdings (account_id, security_id, quantity, price, price_as_of, value,
                   cost_basis, iso_currency, updated_at)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s, now())
               ON CONFLICT (account_id, security_id) DO UPDATE SET quantity = EXCLUDED.quantity,
                 price = EXCLUDED.price, price_as_of = EXCLUDED.price_as_of, value = EXCLUDED.value,
                 cost_basis = EXCLUDED.cost_basis, updated_at = now()""",
            (h["account_id"], h["security_id"], h["quantity"], h.get("institution_price"),
             h.get("institution_price_as_of"), h.get("institution_value"), h.get("cost_basis"),
             h.get("iso_currency_code")))
        held += 1
    # A position that is gone is sold, not stale: drop what this sync did not return.
    for acct in {a for a, _ in seen} or known:
        rows = conn.execute("SELECT security_id FROM holdings WHERE account_id = %s", (acct,)).fetchall()
        for r in rows:
            if (acct, r["security_id"]) not in seen:
                conn.execute("DELETE FROM holdings WHERE account_id = %s AND security_id = %s",
                             (acct, r["security_id"]))

    moves = 0
    start = (date.today() - timedelta(days=days)).isoformat()
    end = date.today().isoformat()
    try:
        offset, total = 0, None
        while total is None or offset < total:
            page = plaid.investments_transactions_get(token, start, end, offset)
            total = page.get("total_investment_transactions", 0)
            for s in page.get("securities") or []:
                conn.execute(
                    """INSERT INTO securities (id, ticker, name, type, iso_currency, is_cash_equivalent)
                       VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT (id) DO NOTHING""",
                    (s["security_id"], s.get("ticker_symbol"), s.get("name"), s.get("type"),
                     s.get("iso_currency_code"), s.get("is_cash_equivalent")))
            rows = page.get("investment_transactions") or []
            for t in rows:
                if t["account_id"] not in known:
                    continue
                conn.execute(
                    """INSERT INTO investment_transactions (id, account_id, security_id, date, name,
                           quantity, amount, fees, type, subtype, iso_currency, raw)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
                       ON CONFLICT (id) DO UPDATE SET amount = EXCLUDED.amount, quantity = EXCLUDED.quantity,
                         type = EXCLUDED.type, subtype = EXCLUDED.subtype, raw = EXCLUDED.raw""",
                    (t["investment_transaction_id"], t["account_id"], t.get("security_id"), t["date"],
                     t.get("name"), t.get("quantity"), t.get("amount"), t.get("fees"), t.get("type"),
                     t.get("subtype"), t.get("iso_currency_code"), Jsonb(t)))
                moves += 1
            offset += len(rows)
            if not rows:
                break
    except PlaidError as e:
        if e.code not in NO_LIABILITIES:
            log.warning("item %s investment transactions failed: %s", item_id, e)
    conn.commit()
    return {"holdings": held, "investment_transactions": moves}


def sync_all(pool, plaid: Plaid, box: TokenBox) -> dict[int, dict | str]:
    results = {}
    with pool.connection() as conn:
        ids = [r["id"] for r in conn.execute(
            "SELECT id FROM items WHERE status IN ('ok', 'error') ORDER BY id")]
    for item_id in ids:
        with pool.connection() as conn:
            try:
                results[item_id] = sync_item(conn, plaid, box, item_id)
            except Exception as e:  # one broken bank must not stop the others
                log.error("item %s sync failed: %s", item_id, e)
                results[item_id] = f"error: {e}"
    return results


def _start_run(conn, item_id: int) -> int:
    row = conn.execute("INSERT INTO sync_runs (item_id) VALUES (%s) RETURNING id", (item_id,)).fetchone()
    conn.commit()
    return row["id"] if isinstance(row, dict) else row[0]


def _finish_run(conn, run_id: int, ok: bool, error: str | None = None,
                added: int = 0, modified: int = 0, removed: int = 0, pages: int = 0) -> None:
    conn.execute(
        """UPDATE sync_runs SET finished_at = now(), ok = %s, error = %s,
             added = %s, modified = %s, removed = %s, pages = %s WHERE id = %s""",
        (ok, error, added, modified, removed, pages, run_id),
    )
