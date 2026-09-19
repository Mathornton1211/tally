"""Receipts: store the photo, read what it says, find the transaction.

Matching is deterministic and conservative. An amount that appears once in the
right few days is linked automatically; anything less certain becomes a short
list to choose from, because a receipt silently attached to the wrong charge is
worse than one left unattached.
"""
import hashlib
import logging
import os
import re
import shutil
import subprocess
import tempfile
import uuid
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

log = logging.getLogger("tally.receipts")

MAX_BYTES = 12 * 1024 * 1024
ALLOWED = {
    "image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp",
    "image/heic": ".heic", "image/heif": ".heif", "application/pdf": ".pdf",
}


def store_dir() -> Path:
    p = Path(os.environ.get("RECEIPTS_DIR", "/data/receipts"))
    p.mkdir(parents=True, exist_ok=True)
    return p


def save_file(data: bytes, content_type: str, filename: str) -> dict:
    if len(data) > MAX_BYTES:
        raise ValueError(f"file is larger than {MAX_BYTES // (1024 * 1024)}MB")
    if content_type not in ALLOWED:
        raise ValueError(f"unsupported file type {content_type}")
    digest = hashlib.sha256(data).hexdigest()
    stored = f"{digest[:16]}-{uuid.uuid4().hex[:8]}{ALLOWED[content_type]}"
    (store_dir() / stored).write_bytes(data)
    return {"stored_name": stored, "sha256": digest, "bytes": len(data),
            "content_type": content_type, "filename": filename[:120]}


# ---------------------------------------------------------------- reading

_AMOUNT = re.compile(r"(?:total|amount|balance due|charged|paid)\D{0,12}?(\d{1,5}[.,]\d{2})", re.I)
_ANY_AMOUNT = re.compile(r"(?<![\d.])(\d{1,5}\.\d{2})(?![\d])")
_DATES = [
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](20\d{2})\b"), "mdy"),
    (re.compile(r"\b(20\d{2})-(\d{1,2})-(\d{1,2})\b"), "ymd"),
    (re.compile(r"\b(\d{1,2})[/-](\d{1,2})[/-](\d{2})\b"), "mdy2"),
]


def ocr_available() -> bool:
    return shutil.which("tesseract") is not None


def read_text(path: Path) -> tuple[str | None, str]:
    """Text off the image, when tesseract is installed. Never fatal."""
    if path.suffix.lower() == ".pdf" or not ocr_available():
        return None, "none"
    try:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "out"
            subprocess.run(["tesseract", str(path), str(out), "--psm", "6"],
                           check=True, capture_output=True, timeout=45)
            return out.with_suffix(".txt").read_text(encoding="utf-8", errors="replace"), "tesseract"
    except Exception as e:
        log.info("ocr failed for %s: %s", path.name, e)
        return None, "none"


def parse(text: str | None) -> dict:
    """Amount, date and a guess at the merchant. Any of them may be None."""
    if not text:
        return {"amount": None, "receipt_date": None, "merchant": None}
    amounts = [Decimal(m.replace(",", ".")) for m in _AMOUNT.findall(text)]
    if not amounts:
        # No "total" line: the largest money-looking number is the usual answer.
        amounts = [Decimal(m) for m in _ANY_AMOUNT.findall(text)]
    amount = max(amounts) if amounts else None

    found = None
    for rx, kind in _DATES:
        m = rx.search(text)
        if not m:
            continue
        try:
            a, b, c = (int(x) for x in m.groups())
            found = date(c, a, b) if kind == "mdy" else date(a, b, c) if kind == "ymd" else date(2000 + c, a, b)
        except ValueError:
            found = None
        if found and found <= date.today() + timedelta(days=1):
            break
        found = None

    merchant = None
    for line in (text.splitlines() if text else []):
        s = line.strip()
        if len(s) >= 3 and not re.fullmatch(r"[\d\W]+", s):
            merchant = re.sub(r"\s{2,}", " ", s)[:48]
            break
    return {"amount": amount, "receipt_date": found, "merchant": merchant}


# ---------------------------------------------------------------- matching

def _similar(a: str, b: str) -> float:
    a, b = re.sub(r"[^a-z0-9]", "", (a or "").lower()), re.sub(r"[^a-z0-9]", "", (b or "").lower())
    if not a or not b:
        return 0.0
    if a in b or b in a:
        return 1.0
    common = len(set(a[i:i + 3] for i in range(len(a) - 2)) & set(b[i:i + 3] for i in range(len(b) - 2)))
    return common / max(1, len(a) - 2)


def candidates(conn, amount: Decimal | None, when: date | None, merchant: str | None,
               days: int = 7, limit: int = 8) -> list[dict]:
    """Transactions this receipt could belong to, best first."""
    when = when or date.today()
    rows = conn.execute(
        """SELECT id, date, amount, display_name, bank_text, account_name, account_mask,
                  category_label, logo_url, category_icon
           FROM v_txn
           WHERE kind <> 'income' AND amount > 0 AND date BETWEEN %s AND %s
             AND (%s::numeric IS NULL OR abs(amount - %s::numeric) <= greatest(0.02, amount * 0.02))
           ORDER BY date DESC LIMIT 60""",
        (when - timedelta(days=days), when + timedelta(days=days), amount, amount)).fetchall()
    scored = []
    for r in rows:
        exact = amount is not None and abs(Decimal(r["amount"]) - amount) <= Decimal("0.02")
        day_gap = abs((r["date"] - when).days)
        name_score = max(_similar(merchant or "", r["display_name"] or ""),
                         _similar(merchant or "", r["bank_text"] or ""))
        score = (2.0 if exact else 0.0) + max(0.0, 1.0 - day_gap / 8) + name_score
        scored.append({**r, "score": round(score, 3), "exact_amount": exact, "days_apart": day_gap})
    scored.sort(key=lambda r: -r["score"])
    return scored[:limit]


AUTO_SCORE = 2.6          # exact amount, within a couple of days
AUTO_MARGIN = 0.6         # and clearly ahead of the runner-up


def best_match(cands: list[dict]) -> dict | None:
    """Only when it is obvious: one exact-amount candidate, well clear of the rest."""
    if not cands:
        return None
    top = cands[0]
    if not top["exact_amount"] or top["score"] < AUTO_SCORE:
        return None
    runner = cands[1]["score"] if len(cands) > 1 else 0
    return top if top["score"] - runner >= AUTO_MARGIN else None
