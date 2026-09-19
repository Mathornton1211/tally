import os
from datetime import datetime, timedelta

import psycopg
import pytest
from psycopg.rows import dict_row

from tally import db
from tally.crypto import TokenBox, new_key


_ZONE_CACHE: list[str] = []


def _local_zone_name(conn) -> str:
    """An IANA zone whose current offset matches this machine's.

    Production sets TALLY_TIMEZONE explicitly and both layers use it. A dev
    machine usually has not, and on Windows there is no portable way to ask the
    OS for its IANA name -- so ask Postgres for one that agrees with the clock.
    Which name it picks does not matter; only that current_date and
    date.today() land on the same day, the way they do in production.
    """
    configured = os.environ.get("TALLY_TIMEZONE", "").strip() or os.environ.get("TZ", "").strip()
    if configured:
        return configured
    # pg_timezone_names reads the whole tzdata set. Once per session, not once
    # per test -- doing it per test took the suite from two minutes to twelve.
    if _ZONE_CACHE:
        return _ZONE_CACHE[0]
    offset = datetime.now().astimezone().utcoffset() or timedelta(0)
    row = conn.execute(
        """SELECT name FROM pg_timezone_names
           WHERE utc_offset = make_interval(mins => %s) AND NOT name LIKE 'posix/%%'
           ORDER BY length(name) LIMIT 1""",
        (int(offset.total_seconds() // 60),)).fetchone()
    name = (row[0] if isinstance(row, tuple) else row["name"]) if row else "UTC"
    _ZONE_CACHE.append(name)
    return name

@pytest.fixture(scope="session", autouse=True)
def _aligned_timezone():
    """Do what the pool does in production, before any test reads a date.

    CI set TALLY_TIMEZONE=America/Los_Angeles on a UTC runner and six tests
    failed -- including the regression test for the original timezone bug --
    because Postgres was told and Python was not. Production aligns both in
    db.pool(); the suite has to start from the same place or it is testing a
    configuration that never runs.
    """
    db.align_process_timezone()


DEV_URL = os.environ.get("TALLY_TEST_DATABASE_URL",
                         "postgresql://tally:tallydev@127.0.0.1:5544/tally")


@pytest.fixture
def db_url():
    with psycopg.connect(DEV_URL, autocommit=True) as c:
        c.execute("DROP SCHEMA public CASCADE")
        c.execute("CREATE SCHEMA public")
    db.migrate(DEV_URL)
    return DEV_URL


@pytest.fixture
def conn(db_url):
    with psycopg.connect(db_url, row_factory=dict_row) as c:
        # The pool sets this on every connection in production (tally/db.pool).
        # Without it here, current_date is the server's day and date.today() is
        # the test machine's, and the suite only notices for the few hours a
        # day they happen to differ -- which is exactly how the bug shipped.
        c.execute("SELECT set_config('TimeZone', %s, false)", (_local_zone_name(c),))
        yield c


@pytest.fixture
def box():
    return TokenBox(new_key())


def make_txn(tid, account="acc-1", amount=12.34, name="COFFEE", date="2026-09-01", **extra):
    return {"transaction_id": tid, "account_id": account, "amount": amount, "name": name,
            "date": date, "iso_currency_code": "USD", "pending": False,
            "personal_finance_category": {"primary": "FOOD_AND_DRINK",
                                          "detailed": "FOOD_AND_DRINK_COFFEE",
                                          "confidence_level": "VERY_HIGH"},
            **extra}


def make_account(aid="acc-1", current=100.0):
    return {"account_id": aid, "name": "Checking", "mask": "0000", "type": "depository",
            "subtype": "checking", "balances": {"current": current, "available": current,
                                                "limit": None, "iso_currency_code": "USD"}}
