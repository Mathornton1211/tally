"""Exports: a CSV of transactions, and a tax pack with the receipts in it.

Tax time should be a download, not an archaeology dig.
"""
import csv
import io
import zipfile
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse

from . import receipts as receipts_mod, scope
from .state import state

router = APIRouter(prefix="/api/export")

COLUMNS = ["date", "merchant", "description", "amount_out", "amount_in", "category", "category_label",
           "kind", "essential", "account", "account_mask", "institution", "note", "pending", "id"]


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


def _rows(conn, start: date, end: date):
    return conn.execute(
        """SELECT id, date, display_name, bank_text, amount, category, category_label, kind, essential,
                  account_name, account_mask, institution, note, pending
           FROM v_txn WHERE date BETWEEN %s AND %s ORDER BY date, id""", (start, end)).fetchall()


def _csv(rows) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(COLUMNS)
    for r in rows:
        amount = Decimal(r["amount"])
        w.writerow([
            r["date"].isoformat(), r["display_name"], r["bank_text"],
            f"{amount:.2f}" if amount > 0 else "", f"{-amount:.2f}" if amount < 0 else "",
            r["category"], r["category_label"], r["kind"], "yes" if r["essential"] else "no",
            r["account_name"], r["account_mask"] or "", r["institution"] or "",
            r["note"] or "", "yes" if r["pending"] else "no", r["id"],
        ])
    return buf.getvalue()


@router.get("/transactions.csv")
def transactions_csv(start: date | None = None, end: date | None = None):
    end = end or date.today()
    start = start or date(end.year, 1, 1)
    with _conn() as conn:
        body = _csv(_rows(conn, start, end))
    return StreamingResponse(
        iter([body]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="tally-{start}-to-{end}.csv"'})


@router.get("/tax-pack.zip")
def tax_pack(year: int | None = None):
    """Everything an accountant asks for: the year's transactions, a category
    summary, the income split, and every receipt filed under its transaction."""
    year = year or date.today().year
    start, end = date(year, 1, 1), date(year, 12, 31)
    with _conn() as conn:
        rows = _rows(conn, start, end)
        if not rows:
            raise HTTPException(404, f"no transactions in {year}")
        summary = conn.execute(
            """SELECT category_label, kind, essential, round(sum(spend), 2) AS spent,
                      round(sum(income), 2) AS received, count(*) AS n
               FROM v_txn WHERE date BETWEEN %s AND %s GROUP BY 1,2,3 ORDER BY 4 DESC NULLS LAST""",
            (start, end)).fetchall()
        rec = conn.execute(
            """SELECT r.id, r.filename, r.stored_name, r.amount, r.receipt_date, r.merchant,
                      v.display_name, v.date AS txn_date
               FROM receipts r LEFT JOIN v_txn_any v ON v.id = r.transaction_id
               WHERE coalesce(r.receipt_date, r.created_at::date) BETWEEN %s AND %s""",
            (start, end)).fetchall()

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr(f"{year}/transactions.csv", _csv(rows))

        sbuf = io.StringIO()
        w = csv.writer(sbuf, lineterminator="\n")
        w.writerow(["category", "kind", "essential", "spent", "received", "transactions"])
        for s in summary:
            w.writerow([s["category_label"], s["kind"], "yes" if s["essential"] else "no",
                        s["spent"] or "", s["received"] or "", s["n"]])
        z.writestr(f"{year}/summary-by-category.csv", sbuf.getvalue())

        listed = []
        for r in rec:
            path = receipts_mod.store_dir() / r["stored_name"]
            if not path.exists():
                continue
            # Named so a human can find one without opening the CSV.
            when = (r["receipt_date"] or r["txn_date"] or start).isoformat()
            who = (r["merchant"] or r["display_name"] or "receipt").replace("/", "-")[:40]
            z.write(path, f"{year}/receipts/{when}-{who}-{r['id']}{path.suffix}")
            listed.append((when, who, r["amount"], r["display_name"], r["txn_date"]))

        rbuf = io.StringIO()
        w = csv.writer(rbuf, lineterminator="\n")
        w.writerow(["date", "merchant", "amount", "matched_transaction", "transaction_date"])
        for row in listed:
            w.writerow([row[0], row[1], row[2] or "", row[3] or "unmatched", row[4] or ""])
        z.writestr(f"{year}/receipts.csv", rbuf.getvalue())

        z.writestr(f"{year}/README.txt", (
            f"Tally export for {year}\n"
            f"{'=' * 30}\n\n"
            f"transactions.csv         every transaction, one row each. amount_out is money spent,\n"
            f"                         amount_in is money received.\n"
            f"summary-by-category.csv  totals per category.\n"
            f"receipts/                the receipt images, named by date and merchant.\n"
            f"receipts.csv             which receipt belongs to which transaction.\n\n"
            f"Categories are Tally's own, edited by hand where they were wrong. Transfers between\n"
            f"your own accounts and credit card payments are marked 'transfer' and are neither\n"
            f"spending nor income.\n"))
    buf.seek(0)
    return StreamingResponse(
        iter([buf.getvalue()]), media_type="application/zip",
        headers={"Content-Disposition": f'attachment; filename="tally-tax-pack-{year}.zip"'})
