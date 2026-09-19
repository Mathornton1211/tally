"""Search that takes a sentence.

"how much did I spend at Costco last year" should not require building a filter
out of four dropdowns. This turns a question into the same filters the
Transactions page uses, runs them, and -- importantly -- shows what it decided
so a wrong reading is obvious and correctable rather than silently wrong.

Two layers, and the order matters:

  1. Parsing that needs no model at all. Dates, amounts, categories, tags,
     accounts and quoted phrases are regular enough to read directly, and doing
     so means search works with AI_ENABLED=0, answers instantly, and gives the
     model less to get wrong.
  2. The model, for what is left. Only when step 1 found nothing useful, and
     only ever to produce filters -- never to produce an answer. Totals are
     computed in SQL from the rows, so the number on screen cannot be a
     hallucination.
"""
import calendar
import json
import re
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)

MONTHS = {m.lower(): i for i, m in enumerate(calendar.month_name) if m}
MONTHS.update({m.lower(): i for i, m in enumerate(calendar.month_abbr) if m})

FILTER_SCHEMA = {
    "type": "object",
    "properties": {
        "merchant": {"type": "string"},
        "category": {"type": "string"},
        "start": {"type": "string"},
        "end": {"type": "string"},
        "min_amount": {"type": "number"},
        "max_amount": {"type": "number"},
        "kind": {"type": "string", "enum": ["expense", "income", "transfer", "any"]},
    },
    "required": ["merchant", "category", "start", "end", "kind"],
}


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def _month_range(year: int, month: int) -> tuple[date, date]:
    return date(year, month, 1), date(year, month, calendar.monthrange(year, month)[1])


def parse_dates(text: str, today: date) -> tuple[date | None, date | None, str | None]:
    """Everything people actually type, without asking a model.

    Checked longest-phrase-first: "last year" must not be read as the word
    "year" with a stray "last".
    """
    t = text.lower()

    if m := re.search(r"\b(in|during|for)?\s*(20\d{2})\b", t):
        year = int(m.group(2))
        if not re.search(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", t):
            return date(year, 1, 1), date(year, 12, 31), str(year)

    for name, num in MONTHS.items():
        if re.search(rf"\b{name}\b", t):
            year = int(m.group(2)) if (m := re.search(r"\b(20\d{2})\b", t)) else today.year
            # A month later than today with no year meant last year.
            if not m and num > today.month:
                year -= 1
            s, e = _month_range(year, num)
            return s, e, f"{calendar.month_name[num]} {year}"

    if "last year" in t:
        return date(today.year - 1, 1, 1), date(today.year - 1, 12, 31), f"{today.year - 1}"
    if "this year" in t or "year to date" in t or "ytd" in t:
        return date(today.year, 1, 1), today, "this year"
    if "last month" in t:
        prev = today.replace(day=1) - timedelta(days=1)
        s, e = _month_range(prev.year, prev.month)
        return s, e, "last month"
    if "this month" in t:
        return today.replace(day=1), today, "this month"
    if "last week" in t:
        start = today - timedelta(days=today.weekday() + 7)
        return start, start + timedelta(days=6), "last week"
    if "this week" in t:
        return today - timedelta(days=today.weekday()), today, "this week"
    if "yesterday" in t:
        return today - timedelta(days=1), today - timedelta(days=1), "yesterday"
    if "today" in t:
        return today, today, "today"
    if m := re.search(r"last (\d+) (day|week|month|year)s?", t):
        n, unit = int(m.group(1)), m.group(2)
        days = {"day": 1, "week": 7, "month": 30, "year": 365}[unit] * n
        return today - timedelta(days=days), today, f"the last {n} {unit}{'s' if n > 1 else ''}"
    return None, None, None


def parse_amounts(text: str) -> tuple[Decimal | None, Decimal | None]:
    t = text.lower().replace(",", "")
    lo = hi = None
    if m := re.search(r"(over|above|more than|at least|>)\s*\$?(\d+(?:\.\d+)?)", t):
        lo = Decimal(m.group(2))
    if m := re.search(r"(under|below|less than|at most|<)\s*\$?(\d+(?:\.\d+)?)", t):
        hi = Decimal(m.group(2))
    if m := re.search(r"between\s*\$?(\d+(?:\.\d+)?)\s*(?:and|-)\s*\$?(\d+(?:\.\d+)?)", t):
        lo, hi = Decimal(m.group(1)), Decimal(m.group(2))
    return lo, hi


STOPWORDS = {
    "how", "much", "did", "do", "i", "we", "spend", "spent", "pay", "paid", "cost", "on", "at",
    "in", "for", "the", "a", "an", "my", "our", "total", "show", "me", "all", "of", "was", "were",
    "last", "this", "year", "month", "week", "day", "days", "weeks", "months", "years", "and",
    "from", "to", "what", "when", "where", "is", "are", "get", "got", "buy", "bought", "between",
    "over", "under", "above", "below", "more", "less", "than", "least", "most", "any", "find",
    "search", "look", "up", "everything", "anything", "money", "transactions", "transaction",
}


def parse(conn, question: str, today: date | None = None) -> dict:
    """Read the question with no model involved."""
    today = today or date.today()
    start, end, when = parse_dates(question, today)
    lo, hi = parse_amounts(question)

    lowered = question.lower()
    category = tag = None
    for row in conn.execute("SELECT key, label FROM categories").fetchall():
        for candidate in (row["label"].lower(), row["key"].replace("_", " ")):
            if re.search(rf"\b{re.escape(candidate)}\b", lowered):
                category = row["key"]
                break
        if category:
            break
    for row in conn.execute("SELECT DISTINCT unnest(tags) AS tag FROM v_txn").fetchall():
        if re.search(rf"\b{re.escape(row['tag'])}\b", lowered):
            tag = row["tag"]
            break

    # A quoted phrase is an exact ask and beats any guessing.
    if m := re.search(r'"([^"]+)"', question):
        merchant = m.group(1)
    else:
        words = [w for w in re.findall(r"[a-z0-9'&.-]+", lowered)
                 if w not in STOPWORDS and not w.isdigit() and len(w) > 2
                 and w not in MONTHS]
        merchant = " ".join(words) if words else None
        if category and merchant:
            # The category name itself is not also a merchant to search for.
            label = conn.execute("SELECT label FROM categories WHERE key = %s",
                                 (category,)).fetchone()["label"].lower()
            merchant = " ".join(w for w in merchant.split() if w not in label) or None

    kind = "income" if re.search(r"\b(earn|earned|income|paid me|deposit)", lowered) else None
    return {"merchant": merchant, "category": category, "tag": tag, "start": start, "end": end,
            "when": when, "min_amount": lo, "max_amount": hi, "kind": kind, "by": "text"}


def run(conn, filters: dict, limit: int = 200) -> dict:
    """Run the filters and total them. Both come from SQL over real rows, so
    the number on screen is never a model's arithmetic."""
    where, params = ["true"], []
    if filters.get("merchant"):
        # Every word must appear somewhere, in any order: "costco gas" finds
        # "COSTCO GAS #114" without needing the exact string.
        for word in str(filters["merchant"]).split():
            where.append("(v.display_name ILIKE %s OR v.bank_text ILIKE %s)")
            params += [f"%{word}%", f"%{word}%"]
    if filters.get("category"):
        where.append("v.category = %s"); params.append(filters["category"])
    if filters.get("tag"):
        where.append("%s = ANY(v.tags)"); params.append(filters["tag"])
    if filters.get("start"):
        where.append("v.date >= %s"); params.append(filters["start"])
    if filters.get("end"):
        where.append("v.date <= %s"); params.append(filters["end"])
    if filters.get("min_amount") is not None:
        where.append("abs(v.amount) >= %s"); params.append(filters["min_amount"])
    if filters.get("max_amount") is not None:
        where.append("abs(v.amount) <= %s"); params.append(filters["max_amount"])
    if filters.get("kind") in ("expense", "income", "transfer"):
        where.append("v.kind = %s"); params.append(filters["kind"])

    clause = " AND ".join(where)
    totals = conn.execute(
        f"""SELECT count(*) AS count, coalesce(sum(spend), 0) AS spent,
                   coalesce(sum(income), 0) AS earned, min(date) AS first, max(date) AS last
            FROM v_txn v WHERE {clause}""", params).fetchone()
    rows = conn.execute(
        f"""SELECT v.id, v.date, v.display_name, v.amount, v.currency, v.foreign_currency,
                   v.category, v.category_label, v.category_icon, v.kind, v.logo_url,
                   v.account_name, v.account_mask, v.tags, v.pending, v.owner_name
            FROM v_txn v WHERE {clause} ORDER BY v.date DESC, v.id LIMIT %s""",
        params + [limit]).fetchall()
    merchants = conn.execute(
        f"""SELECT v.display_name AS name, count(*) AS count, coalesce(sum(abs(v.amount)), 0) AS total
            FROM v_txn v WHERE {clause} GROUP BY 1 ORDER BY 3 DESC LIMIT 8""", params).fetchall()
    months = conn.execute(
        f"""SELECT date_trunc('month', v.date)::date AS month,
                   coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned
            FROM v_txn v WHERE {clause} GROUP BY 1 ORDER BY 1""", params).fetchall()

    return {
        "count": totals["count"], "spent": _q(totals["spent"]), "earned": _q(totals["earned"]),
        "first": totals["first"], "last": totals["last"],
        "average": _q(Decimal(totals["spent"]) / totals["count"]) if totals["count"] else ZERO,
        "rows": rows, "merchants": merchants, "months": months,
    }


def _thin(filters: dict) -> bool:
    """Did reading the text alone find anything worth running?"""
    return not any(filters.get(k) for k in ("merchant", "category", "tag", "start", "min_amount"))


SYSTEM = """You turn a question about someone's bank transactions into search filters.
Reply with JSON only.

- merchant: words likely to appear in the merchant's name. "" if the question names none.
- category: one of the listed category keys, or "".
- start, end: YYYY-MM-DD, or "" if the question gives no period.
- kind: "expense", "income", "transfer", or "any".
- min_amount / max_amount: numbers, only if the question states a limit.

Never invent a merchant that is not implied by the question."""


def ask(conn, question: str, llm=None, today: date | None = None) -> dict:
    """Read the question, falling back to the model only for what text parsing
    could not get. The filters used are always returned, so a wrong reading is
    visible and fixable rather than a silently wrong total."""
    today = today or date.today()
    filters = parse(conn, question, today)

    if llm and _thin(filters):
        cats = [r["key"] for r in conn.execute(
            "SELECT key FROM categories WHERE kind = 'expense' ORDER BY sort").fetchall()]
        try:
            got = llm.json("search", [
                {"role": "system", "content": f"{SYSTEM}\n\nCategory keys: {', '.join(cats)}\n"
                                              f"Today is {today:%Y-%m-%d}."},
                {"role": "user", "content": question},
            ], FILTER_SCHEMA)
            parsed = got if isinstance(got, dict) else json.loads(got)
            filters = {
                "merchant": parsed.get("merchant") or None,
                "category": parsed.get("category") if parsed.get("category") in cats else None,
                "tag": None,
                "start": date.fromisoformat(parsed["start"]) if parsed.get("start") else None,
                "end": date.fromisoformat(parsed["end"]) if parsed.get("end") else None,
                "when": None,
                "min_amount": Decimal(str(parsed["min_amount"])) if parsed.get("min_amount") else None,
                "max_amount": Decimal(str(parsed["max_amount"])) if parsed.get("max_amount") else None,
                "kind": parsed.get("kind") if parsed.get("kind") in ("expense", "income", "transfer") else None,
                "by": "model",
            }
        except Exception:
            # A model that is down, slow or confused must not break search.
            # The text-parsed filters still work.
            pass

    return {"question": question, "filters": filters, **run(conn, filters)}
