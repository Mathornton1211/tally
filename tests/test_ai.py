"""The AI guard rails: what the chat may run, what the database lets it read,
and the check that every figure the model writes came from real data."""
from datetime import date

import psycopg
import pytest

from tally import chat, enrich, llm


# ---------------------------------------------------------------- SQL validation

@pytest.mark.parametrize("sql", [
    "SELECT round(sum(spend), 2) AS total FROM chat_transactions WHERE kind = 'expense'",
    "WITH m AS (SELECT date_trunc('month', date) AS month, sum(spend) AS s FROM chat_transactions GROUP BY 1) "
    "SELECT * FROM m ORDER BY month LIMIT 12",
    "SELECT extract(day FROM date) AS dom, count(*) FROM chat_transactions GROUP BY 1 LIMIT 31",
    "SELECT a.account_name, a.current_balance FROM chat_accounts a JOIN categories c ON true LIMIT 5",
    "SELECT d::date FROM generate_series(DATE '2026-01-01', DATE '2026-02-01', interval '1 day') d LIMIT 40",
])
def test_valid_queries_pass(sql):
    assert chat.validate_sql(sql)


@pytest.mark.parametrize("sql,reason", [
    ("DELETE FROM transactions", "SELECT"),
    ("SELECT 1; DROP TABLE items", "one statement"),
    ("SELECT access_token_enc FROM items", "may not"),
    ("SELECT * FROM transactions", "may not"),
    ("SELECT * FROM chat_transactions t JOIN account_settings s ON true", "may not"),
    ("SELECT pg_read_file('/etc/passwd')", "forbidden"),
    ("SELECT set_config('role', 'tally', false)", "forbidden"),
    ("WITH x AS (UPDATE transactions SET note = 'x' RETURNING 1) SELECT * FROM x", "forbidden"),
])
def test_dangerous_queries_rejected(sql, reason):
    with pytest.raises(chat.ChatError, match=reason):
        chat.validate_sql(sql)


def test_unbounded_query_gets_a_limit():
    assert chat.validate_sql("SELECT merchant FROM chat_transactions").endswith(f"LIMIT {chat.MAX_ROWS}")


# ---------------------------------------------------------------- database role

def test_reader_role_cannot_see_tokens_or_write(conn):
    """The real wall. Even SQL that slips past validate_sql runs as tally_reader."""
    cols, rows = chat.run_readonly(conn, "SELECT count(*) AS n FROM chat_transactions")
    assert cols == ["n"]
    for sql in ("SELECT access_token_enc FROM items", "SELECT * FROM transactions",
                "SELECT * FROM account_settings"):
        with pytest.raises(psycopg.errors.InsufficientPrivilege):
            chat.run_readonly(conn, sql)
    with pytest.raises((psycopg.errors.ReadOnlySqlTransaction, psycopg.errors.InsufficientPrivilege)):
        chat.run_readonly(conn, "INSERT INTO categories (key, label, kind, icon, sort) VALUES ('x','x','expense','x',1)")


def test_reader_role_times_out(conn):
    with pytest.raises(psycopg.errors.QueryCanceled):
        chat.run_readonly(conn, "SELECT pg_sleep(8)")


# ---------------------------------------------------------------- number check

def test_figures_traced_to_rows_pass_including_rounding():
    rows = [{"total": 1318.36, "count": 13}, {"month": "2026-08-01", "total": 887.64}]
    text = "You spent $1,318.36 at Costco, about $1,318 across 13 visits, and $887.64 on groceries."
    assert llm.unverified_figures(text, rows) == []


def test_invented_figure_is_caught():
    rows = [{"total": 435.70}, {"total": 440.45}]
    text = "August was $435.70 and July was $440.45, so $876.15 over the two months."
    assert llm.unverified_figures(text, rows) == ["$876.15"]


def test_percent_from_fraction_is_allowed():
    facts = {"savings_rate": 0.07, "saved": 357.33}
    assert llm.unverified_figures("You kept $357.33, 7% of income.", facts) == []


def test_non_local_model_url_is_refused():
    with pytest.raises(ValueError, match="not local"):
        llm.LLM(url="https://api.openai.com")
    assert llm.LLM(url="http://hl-ollama:11434").url.endswith(":11434")
    assert llm.LLM(url="http://10.0.0.10:11434")


# ---------------------------------------------------------------- helpers

def test_month_table_has_exact_boundaries():
    months = chat._months(date(2026, 9, 16), n=3)
    assert months[0] == (date(2026, 9, 1), date(2026, 10, 1))
    assert months[1] == (date(2026, 8, 1), date(2026, 9, 1))
    assert months[2] == (date(2026, 7, 1), date(2026, 8, 1))


def test_model_names_are_sanity_checked():
    assert enrich._clean_name('  "Zelle to a landlord" ') == "Zelle to a landlord"
    assert enrich._clean_name("") is None
    assert enrich._clean_name("ACH 4760039224 PPD") is None
    assert enrich._clean_name("x" * 60) is None


def test_echoed_payee_must_match():
    assert enrich._same("Best Buy", "Best Buy")
    assert enrich._same("Hodads", "Hodad's Ocean Beach")
    assert not enrich._same("Phil's BBQ", "Best Buy")
    assert not enrich._same("", "Best Buy")


def test_csv_quotes_commas():
    assert chat._csv(["m", "t"], [{"m": "Joe, Inc", "t": 1.5}, {"m": "Vons", "t": None}]) == 'm,t\n"Joe, Inc",1.5\nVons,'
