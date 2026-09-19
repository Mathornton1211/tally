"""Ask Tally a question about your money. HANDOFF section 10, invariants 3 and 4.

Two model steps with real computation between them:
  1. plan:   question -> one read-only SQL query (structured output)
  2. run:    Postgres executes it as tally_reader, read-only, 5s timeout
  3. answer: question + the actual result rows -> a short reply, streamed

The model never sees raw tables it could misread and never does arithmetic the
query did not already do. Every dollar figure in the reply is checked against
the result rows; anything that does not trace back is flagged to Mat.
"""
import json
import re
import time
from collections.abc import Iterator
from datetime import date, timedelta
from decimal import Decimal

from .llm import LLM, LLMUnavailable, unverified_figures

MAX_ROWS = 200
ROWS_TO_MODEL = 20

SCHEMA = """PostgreSQL. You may only read these three relations.

chat_transactions  (one row per bank transaction)
  date            date
  spend           numeric  money spent, positive. 0 unless kind = 'expense'. Refunds are negative.
  income          numeric  money received, positive. 0 unless kind = 'income'.
  plaid_amount    numeric  raw signed amount: positive = out of the account, negative = in.
  pending         boolean
  merchant        text     cleaned payee name, e.g. 'Trader Joe''s', 'Netflix'
  description     text     raw bank text
  category        text     category key (see list)
  category_label  text
  kind            text     'expense' | 'income' | 'transfer'  (transfers are neither spending nor income)
  account_name    text     e.g. 'Freedom Unlimited', 'Everyday Checking'
  account_mask    text     last 4 digits
  account_type    text     'depository' | 'credit' | 'loan' | 'investment'
  institution     text

chat_accounts  (current balances)
  account_name, account_mask, account_type, subtype, current_balance, available_balance, credit_limit, institution
  For credit and loan accounts current_balance is the amount owed.

categories (key, label, kind, icon, sort)

Rules:
- Spending questions: SUM(spend) with kind = 'expense'. Income questions: SUM(income) with kind = 'income'.
- Match merchants with ILIKE '%name%' on merchant, never exact equality.
- A named or relative month means exactly that one month: date >= its first day AND date < the next month's first day.
  Copy the dates from the MONTHS table given below; never compute month boundaries with intervals.
- Use date_trunc('month', date) only to GROUP BY month.
- Round money with round(x, 2). Always ORDER BY something meaningful. Always LIMIT (max 50) for lists.
- Name columns plainly: month, category, merchant, total, count, average.
- One SELECT statement. No semicolons. No writes. Nothing outside these three relations.
"""

EXAMPLES = [
    ("How much did I spend eating out in March?",
     "SELECT round(sum(spend), 2) AS total, count(*) AS count FROM chat_transactions "
     "WHERE kind = 'expense' AND category = 'dining' AND date >= DATE 'MARCH_START' AND date < DATE 'MARCH_NEXT'"),
    ("(follow-up) What about February?",
     "SELECT round(sum(spend), 2) AS total, count(*) AS count FROM chat_transactions "
     "WHERE kind = 'expense' AND category = 'dining' AND date >= DATE 'FEB_START' AND date < DATE 'MARCH_START'"),
    ("Top 5 merchants this year",
     "SELECT merchant, round(sum(spend), 2) AS total, count(*) AS count FROM chat_transactions "
     "WHERE kind = 'expense' AND date >= date_trunc('year', DATE 'TODAY') GROUP BY merchant ORDER BY total DESC LIMIT 5"),
    ("Did Spotify go up in price?",
     "SELECT date, merchant, spend, account_name FROM chat_transactions "
     "WHERE merchant ILIKE '%spotify%' AND kind = 'expense' ORDER BY date LIMIT 50"),
    ("Groceries by month",
     "SELECT date_trunc('month', date)::date AS month, round(sum(spend), 2) AS total FROM chat_transactions "
     "WHERE kind = 'expense' AND category = 'groceries' GROUP BY 1 ORDER BY 1"),
]

_FORBIDDEN = re.compile(
    r"\b(insert|update|delete|drop|alter|create|grant|revoke|truncate|copy|call|do|execute|prepare|listen|notify|"
    r"vacuum|analyze|lock|set|reset|comment|security|pg_\w+|dblink|lo_\w+|current_setting|set_config)\b", re.I)
_ALLOWED_RELATIONS = {"chat_transactions", "chat_accounts", "categories"}


class ChatError(Exception):
    pass


def validate_sql(sql: str) -> str:
    """Belt to the database role's braces. The role and read-only transaction are
    what actually stop a write; this rejects nonsense early with a clear reason."""
    s = sql.strip().rstrip(";").strip()
    if ";" in s:
        raise ChatError("only one statement is allowed")
    if not re.match(r"^(select|with)\b", s, re.I):
        raise ChatError("query must start with SELECT or WITH")
    if _FORBIDDEN.search(s):
        raise ChatError(f"query uses a forbidden keyword: {_FORBIDDEN.search(s).group(0)}")
    # EXTRACT(day FROM date) and friends use FROM without naming a relation.
    scan = re.sub(r"\b(extract|substring|trim|overlay|position)\s*\([^()]*\)", "", s, flags=re.I)
    # A name followed by "(" is a set-returning function (generate_series), not a table.
    relations = {m.lower() for m in re.findall(r"\b(?:from|join)\s+([a-z_][\w.]*)\b(?!\s*\()", scan, re.I)}
    ctes = {m.lower() for m in re.findall(r"\b([a-z_]\w*)\s+as\s*\(", s, re.I)}
    unknown = relations - _ALLOWED_RELATIONS - ctes
    if unknown:
        raise ChatError(f"query reads something it may not: {', '.join(sorted(unknown))}")
    if not re.search(r"\blimit\s+\d+\s*$", s, re.I):
        s = f"SELECT * FROM ({s}) q LIMIT {MAX_ROWS}"
    return s


def run_readonly(conn, sql: str) -> tuple[list[str], list[dict]]:
    with conn.transaction():
        conn.execute("SET TRANSACTION READ ONLY")
        conn.execute("SET LOCAL ROLE tally_reader")
        conn.execute("SET LOCAL statement_timeout = '5s'")
        cur = conn.execute(sql)
        cols = [d.name for d in cur.description] if cur.description else []
        rows = cur.fetchmany(MAX_ROWS)
    return cols, rows


def _jsonable(v):
    if isinstance(v, Decimal):
        return float(v)
    if isinstance(v, date):
        return v.isoformat()
    return v


def _csv(cols: list[str], rows: list[dict]) -> str:
    """Rows as CSV for the model. Prompt tokens are the slow part on a CPU box;
    CSV is about half the tokens of the same rows as JSON."""
    def fmt(v):
        if v is None:
            return ""
        s = str(v)
        return f'"{s}"' if "," in s else s
    return "\n".join([",".join(cols)] + [",".join(fmt(r.get(c)) for c in cols) for r in rows])


def _context(conn) -> str:
    cats = conn.execute("SELECT key, label, kind FROM categories ORDER BY sort").fetchall()
    accts = conn.execute(
        "SELECT a.name, a.mask, a.type FROM v_acct a WHERE NOT a.hidden ORDER BY a.type, a.name").fetchall()
    span = conn.execute("SELECT min(date) AS a, max(date) AS b FROM transactions").fetchone()
    return ("Category keys: " + ", ".join(f"{c['key']} ({c['label']}, {c['kind']})" for c in cats)
            + "\nAccounts: " + ", ".join(f"{a['name']} ··{a['mask']} ({a['type']})" for a in accts)
            + f"\nData covers {span['a']} to {span['b']}.")


def _months(today: date, n: int = 14) -> list[tuple[date, date]]:
    out, start = [], today.replace(day=1)
    for _ in range(n):
        nxt = (start.replace(day=28) + timedelta(days=4)).replace(day=1)
        out.append((start, nxt))
        start = (start - timedelta(days=1)).replace(day=1)
    return out


def _fill(s: str, values: dict) -> str:
    for k in sorted(values, key=len, reverse=True):
        s = s.replace(k, values[k])
    return s


def _system_prompt(context: str, today: date) -> str:
    """Everything that is the same for every question today, in one stable
    prefix. ollama reuses its prompt cache for an identical prefix, so after
    the first question only the question itself has to be read."""
    months = _months(today)
    march = next((m for m in months if m[0].month == 3), months[-1])
    feb = next((m for m in months if m[0].month == 2), months[-1])
    fill = {"TODAY": today.isoformat(), "MARCH_START": march[0].isoformat(), "MARCH_NEXT": march[1].isoformat(),
            "FEB_START": feb[0].isoformat()}
    shots = "\n\n".join(f"Q: {q}\nSQL: {_fill(s, fill)}" for q, s in EXAMPLES)
    table = "\n".join(f"{a:%B %Y}: {a.isoformat()} to before {b.isoformat()}"
                      + (" (this month, so far)" if i == 0 else " (last month)" if i == 1 else "")
                      for i, (a, b) in enumerate(months))
    return ("You answer questions about one person's own bank data by writing a single PostgreSQL query.\n\n"
            + SCHEMA
            + "\nAlmost everything is mode 'sql': any question naming a merchant, account, category, "
              "amount, date, bill, subscription, price, or balance can be answered from the data, so query it.\n"
              "Use mode 'reply' only for greetings, thanks, or requests to change data (which you cannot do), "
              "with one short sentence and no numbers.\n\n"
            + f"TODAY is {today.isoformat()} ({today:%A}).\n{context}\n\nMONTHS:\n{table}\n\nExamples:\n{shots}")


def _plan(llm: LLM, question: str, history: list[dict], system: str, error: str | None = None,
          previous_sql: str | None = None) -> dict:
    convo = "\n".join(f"{h['role'].upper()}: {h['content']}" for h in history[-6:])
    user = (f"Conversation so far:\n{convo}\n\n" if convo else "") + f"Question: {question}"
    if error:
        user += f"\n\nYour previous query failed.\nSQL: {previous_sql}\nError: {error}\nWrite a corrected query."
    schema = {"type": "object", "required": ["mode"], "properties": {
        "mode": {"type": "string", "enum": ["sql", "reply"]},
        "sql": {"type": "string"},
        "reply": {"type": "string"},
    }}
    return llm.json("chat_plan", [{"role": "system", "content": system}, {"role": "user", "content": user}], schema)

def ask(conn, llm: LLM, question: str, history: list[dict] | None = None) -> Iterator[dict]:
    """Yields events: status, sql, table, token, done, error."""
    started = time.monotonic()
    history = history or []
    today = date.today()
    sql = answer = error = None
    rows: list[dict] = []
    verified = None
    try:
        yield {"type": "status", "text": "Reading your question"}
        system = _system_prompt(_context(conn), today)
        plan = _plan(llm, question, history, system)

        if plan.get("mode") == "reply" or not plan.get("sql"):
            answer = plan.get("reply") or "Ask me about your spending, income, merchants, categories, or balances."
            yield {"type": "token", "text": answer}
            yield {"type": "done", "verified": True, "unverified": []}
            return

        cols: list[str] = []
        for attempt in range(2):
            try:
                sql = validate_sql(plan["sql"])
                yield {"type": "sql", "sql": sql}
                yield {"type": "status", "text": "Running the numbers"}
                cols, rows = run_readonly(conn, sql)
                break
            except Exception as e:  # validation or database error: one repair attempt
                if attempt == 1:
                    raise ChatError(f"couldn't build a working query: {e}") from e
                yield {"type": "status", "text": "Fixing the query"}
                plan = _plan(llm, question, history, system, error=str(e), previous_sql=plan.get("sql"))
                if plan.get("mode") != "sql" or not plan.get("sql"):
                    raise ChatError("couldn't turn that into a query")

        table = [{k: _jsonable(v) for k, v in r.items()} for r in rows]
        yield {"type": "table", "columns": cols, "rows": table, "truncated": len(rows) >= MAX_ROWS}

        yield {"type": "status", "text": "Writing the answer"}
        shown = table[:ROWS_TO_MODEL]
        pieces: list[str] = []
        for piece in llm.stream("chat_answer", [
            {"role": "system", "content":
                "You explain query results about the person's own money in plain, friendly language.\n"
                "- Use ONLY numbers that appear in the result rows. Do not add, subtract, average, or estimate.\n"
                "- Write money like $1,234.56 (never abbreviate to k). At most 4 sentences. No tables, no markdown headers.\n"
                "- For more than 4 rows, don't list them all (the person sees the full table): give the total picture, the highest and lowest, and any trend.\n"
                "- For price questions, compare the earliest and latest charges and say when it changed.\n"
                "- Say which period the numbers cover, read from the SQL date filter (e.g. \"in July 2026\").\n"
                "- If the result is empty, say you found no matching transactions and suggest how to rephrase.\n"
                "- Spending is positive money out; don't call it negative."},
            {"role": "user", "content":
                f"Today is {today.isoformat()}.\nQuestion: {question}\nSQL used: {sql}\n"
                f"Result ({len(table)} rows{', first ' + str(ROWS_TO_MODEL) + ' shown' if len(table) > ROWS_TO_MODEL else ''}):\n"
                f"{_csv(cols, shown)}"},
        ]):
            pieces.append(piece)
            yield {"type": "token", "text": piece}
        answer = "".join(pieces).strip()
        bad = unverified_figures(answer, table)
        verified = not bad
        yield {"type": "done", "verified": verified, "unverified": bad}
    except (ChatError, LLMUnavailable) as e:
        error = str(e)
        msg = ("The local model isn't reachable right now." if isinstance(e, LLMUnavailable)
               else f"Sorry, I {error}.")
        yield {"type": "error", "text": msg}
    except Exception as e:
        error = repr(e)
        yield {"type": "error", "text": "Something went wrong answering that."}
    finally:
        try:
            conn.execute(
                "INSERT INTO chat_log (question, sql, row_count, answer, verified, ms, error) VALUES (%s,%s,%s,%s,%s,%s,%s)",
                (question, sql, len(rows) if sql else None, answer, verified,
                 int((time.monotonic() - started) * 1000), error))
            conn.commit()
        except Exception:
            pass
