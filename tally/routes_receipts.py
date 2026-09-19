"""Receipt upload, matching and retrieval."""
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel

from . import receipts, scope
from .state import state

router = APIRouter(prefix="/api")


def _conn():
    # Scoped to whoever is signed in; see tally/scope.py.
    return scope.connection()


@router.post("/receipts")
async def upload(file: UploadFile = File(...), transaction_id: str | None = Form(default=None)):
    data = await file.read()
    try:
        saved = receipts.save_file(data, file.content_type or "", file.filename or "receipt")
    except ValueError as e:
        raise HTTPException(400, str(e))

    path = receipts.store_dir() / saved["stored_name"]
    text, source = receipts.read_text(path)
    parsed = receipts.parse(text)

    with _conn() as conn:
        dup = conn.execute("SELECT id FROM receipts WHERE sha256 = %s", (saved["sha256"],)).fetchone()
        if dup:
            path.unlink(missing_ok=True)      # the stored copy we just wrote, not the original
            raise HTTPException(409, {"message": "this receipt is already uploaded", "receipt_id": dup["id"]})

        matched_by = None
        if transaction_id:
            matched_by = "user"
        else:
            cands = receipts.candidates(conn, parsed["amount"], parsed["receipt_date"], parsed["merchant"])
            auto = receipts.best_match(cands)
            if auto:
                transaction_id, matched_by = auto["id"], "auto"

        row = conn.execute(
            """INSERT INTO receipts (filename, stored_name, content_type, bytes, sha256, amount,
                   receipt_date, merchant, ocr_text, ocr_source, transaction_id, matched_by)
               VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id""",
            (saved["filename"], saved["stored_name"], saved["content_type"], saved["bytes"], saved["sha256"],
             parsed["amount"], parsed["receipt_date"], parsed["merchant"], (text or "")[:20000], source,
             transaction_id, matched_by)).fetchone()
        return _one(conn, row["id"])


def _one(conn, receipt_id: int) -> dict:
    r = conn.execute(
        """SELECT r.*, v.display_name, v.date AS txn_date, v.amount AS txn_amount,
                  v.account_name, v.account_mask
           FROM receipts r LEFT JOIN v_txn_any v ON v.id = r.transaction_id
           WHERE r.id = %s""", (receipt_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such receipt")
    r.pop("ocr_text", None)
    if not r["transaction_id"]:
        r["candidates"] = receipts.candidates(conn, r["amount"], r["receipt_date"], r["merchant"])
    return r


@router.get("/receipts")
def list_receipts(unmatched: bool = False, transaction_id: str | None = None, limit: int = 60):
    where, params = ["true"], []
    if unmatched:
        where.append("r.transaction_id IS NULL")
    if transaction_id:
        where.append("r.transaction_id = %s"); params.append(transaction_id)
    with _conn() as conn:
        rows = conn.execute(
            f"""SELECT r.id, r.filename, r.content_type, r.bytes, r.amount, r.receipt_date, r.merchant,
                       r.ocr_source, r.transaction_id, r.matched_by, r.created_at,
                       v.display_name, v.date AS txn_date, v.amount AS txn_amount,
                       v.account_name, v.account_mask
                FROM receipts r LEFT JOIN v_txn_any v ON v.id = r.transaction_id
                WHERE {' AND '.join(where)} ORDER BY r.created_at DESC LIMIT %s""",
            params + [limit]).fetchall()
        counts = conn.execute(
            """SELECT count(*) AS total, count(*) FILTER (WHERE transaction_id IS NULL) AS unmatched,
                      coalesce(sum(amount), 0) AS total_amount FROM receipts""").fetchone()
    return {"receipts": rows, **counts, "ocr": receipts.ocr_available()}


@router.get("/receipts/{receipt_id}/file")
def get_file(receipt_id: int):
    with _conn() as conn:
        r = conn.execute("SELECT stored_name, content_type, filename FROM receipts WHERE id = %s",
                         (receipt_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such receipt")
    path = receipts.store_dir() / r["stored_name"]
    if not path.exists():
        raise HTTPException(410, "the file is gone from disk")
    return FileResponse(path, media_type=r["content_type"], filename=r["filename"])


@router.get("/receipts/{receipt_id}/candidates")
def get_candidates(receipt_id: int):
    with _conn() as conn:
        r = conn.execute("SELECT amount, receipt_date, merchant FROM receipts WHERE id = %s",
                         (receipt_id,)).fetchone()
        if not r:
            raise HTTPException(404, "no such receipt")
        return receipts.candidates(conn, r["amount"], r["receipt_date"], r["merchant"], days=21, limit=12)


class ReceiptPatch(BaseModel):
    transaction_id: str | None = None
    detach: bool = False
    amount: Decimal | None = None
    receipt_date: date | None = None
    merchant: str | None = None
    note: str | None = None


@router.patch("/receipts/{receipt_id}")
def patch(receipt_id: int, body: ReceiptPatch):
    sets, params = [], []
    if body.detach:
        sets += ["transaction_id = NULL", "matched_by = NULL"]
    elif body.transaction_id:
        sets += ["transaction_id = %s", "matched_by = 'user'"]; params.append(body.transaction_id)
    for field in ("amount", "receipt_date", "merchant", "note"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = %s"); params.append(v)
    if not sets:
        raise HTTPException(400, "nothing to change")
    with _conn() as conn:
        n = conn.execute(f"UPDATE receipts SET {', '.join(sets)} WHERE id = %s", params + [receipt_id]).rowcount
        if not n:
            raise HTTPException(404, "no such receipt")
        return _one(conn, receipt_id)


@router.delete("/receipts/{receipt_id}")
def delete(receipt_id: int):
    """Removes the row and the stored file. Only ever the copy Tally made."""
    with _conn() as conn:
        r = conn.execute("DELETE FROM receipts WHERE id = %s RETURNING stored_name", (receipt_id,)).fetchone()
    if not r:
        raise HTTPException(404, "no such receipt")
    (receipts.store_dir() / r["stored_name"]).unlink(missing_ok=True)
    return {"ok": True}
