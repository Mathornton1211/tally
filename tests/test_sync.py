import pytest

from tally import db, sync
from tally.plaid import PlaidError

from .conftest import make_account, make_txn


class FakePlaid:
    """Serves scripted /transactions/sync pages keyed by the cursor asked for."""

    def __init__(self, pages: dict, errors: dict | None = None):
        self.pages = pages
        self.errors = errors or {}
        self.calls: list = []

    def transactions_sync(self, access_token, cursor, count=500):
        self.calls.append(cursor)
        queued = self.errors.get(cursor)
        if queued:
            raise queued.pop(0)
        return self.pages[cursor]


def page(next_cursor, has_more=False, added=(), modified=(), removed=(), accounts=None,
         status="HISTORICAL_UPDATE_COMPLETE"):
    return {"added": list(added), "modified": list(modified),
            "removed": [{"transaction_id": r} for r in removed],
            "next_cursor": next_cursor, "has_more": has_more,
            "accounts": accounts if accounts is not None else [make_account()],
            "transactions_update_status": status}


def seed_item(conn, box, cursor=None):
    row = conn.execute(
        "INSERT INTO items (plaid_item_id, access_token_enc, cursor) VALUES ('it-1', %s, %s) RETURNING id",
        (box.seal("access-sandbox-secret"), cursor)).fetchone()
    conn.commit()
    return row["id"]


def plaid_error(code, status=400):
    return PlaidError(status, {"error_code": code, "error_message": code.lower()})


def test_migrate_is_idempotent(db_url):
    assert db.migrate(db_url) == []


def test_token_is_encrypted_at_rest(conn, box):
    seed_item(conn, box)
    blob = bytes(conn.execute("SELECT access_token_enc FROM items").fetchone()["access_token_enc"])
    assert b"access-sandbox-secret" not in blob
    assert box.open(blob) == "access-sandbox-secret"


def test_multi_page_sync_saves_rows_and_final_cursor(conn, box):
    item_id = seed_item(conn, box)
    fake = FakePlaid({
        None: page("c1", has_more=True, added=[make_txn("t1"), make_txn("t2")]),
        "c1": page("c2", added=[make_txn("t3")]),
    })
    result = sync.sync_item(conn, fake, box, item_id)
    assert result["added"] == 3 and result["pages"] == 2
    assert conn.execute("SELECT count(*) AS n FROM transactions").fetchone()["n"] == 3
    assert conn.execute("SELECT cursor FROM items").fetchone()["cursor"] == "c2"
    assert conn.execute("SELECT count(*) AS n FROM balances_daily").fetchone()["n"] == 1


def test_next_sync_starts_from_saved_cursor(conn, box):
    item_id = seed_item(conn, box, cursor="c2")
    fake = FakePlaid({"c2": page("c3", added=[make_txn("t9")])})
    sync.sync_item(conn, fake, box, item_id)
    assert fake.calls == ["c2"]


def test_modified_keeps_user_edits_and_removed_deletes(conn, box):
    item_id = seed_item(conn, box)
    sync.sync_item(conn, FakePlaid({None: page("c1", added=[make_txn("t1"), make_txn("t2")])}),
                   box, item_id)
    conn.execute("UPDATE transactions SET note = 'split with gf', category_source = 'user' WHERE id = 't1'")
    conn.commit()

    fake = FakePlaid({"c1": page("c2", modified=[make_txn("t1", amount=99.0, name="COFFEE CO")],
                                 removed=["t2"])})
    sync.sync_item(conn, fake, box, item_id)

    t1 = conn.execute("SELECT amount, name, note, category_source FROM transactions WHERE id='t1'").fetchone()
    assert float(t1["amount"]) == 99.0 and t1["name"] == "COFFEE CO"
    assert t1["note"] == "split with gf" and t1["category_source"] == "user"
    assert conn.execute("SELECT count(*) AS n FROM transactions WHERE id='t2'").fetchone()["n"] == 0


def test_mutation_during_pagination_restarts_from_original_cursor(conn, box):
    item_id = seed_item(conn, box, cursor="c0")
    fake = FakePlaid(
        {"c0": page("c1", has_more=True, added=[make_txn("stale")]),
         "c1": page("c2", added=[make_txn("t1")])},
        errors={"c1": [plaid_error("TRANSACTIONS_SYNC_MUTATION_DURING_PAGINATION")]},
    )
    result = sync.sync_item(conn, fake, box, item_id)
    assert fake.calls == ["c0", "c1", "c0", "c1"]
    # The first attempt's page was discarded, not double-counted.
    assert result["added"] == 2


def test_failed_write_keeps_old_cursor(conn, box):
    item_id = seed_item(conn, box, cursor="c0")
    # A transaction on an account Plaid never returned violates the FK.
    fake = FakePlaid({"c0": page("c1", added=[make_txn("t1"), make_txn("t2", account="ghost")])})
    with pytest.raises(Exception):
        sync.sync_item(conn, fake, box, item_id)
    assert conn.execute("SELECT cursor FROM items").fetchone()["cursor"] == "c0"
    assert conn.execute("SELECT count(*) AS n FROM transactions").fetchone()["n"] == 0
    run = conn.execute("SELECT ok, error FROM sync_runs ORDER BY id DESC LIMIT 1").fetchone()
    assert run["ok"] is False and run["error"]


def test_login_error_marks_item_and_sync_all_skips_it(db_url, conn, box):
    item_id = seed_item(conn, box, cursor="c0")
    fake = FakePlaid({}, errors={"c0": [plaid_error("ITEM_LOGIN_REQUIRED")]})
    with pytest.raises(PlaidError):
        sync.sync_item(conn, fake, box, item_id)
    item = conn.execute("SELECT status, error_code, cursor FROM items").fetchone()
    assert item == {"status": "login_required", "error_code": "ITEM_LOGIN_REQUIRED", "cursor": "c0"}

    pool = db.pool(db_url)
    try:
        assert sync.sync_all(pool, fake, box) == {}
    finally:
        pool.close()


def test_one_broken_item_does_not_stop_others(db_url, conn, box):
    bad = seed_item(conn, box, cursor="bad")
    good = conn.execute(
        "INSERT INTO items (plaid_item_id, access_token_enc, cursor) VALUES ('it-2', %s, 'good') RETURNING id",
        (box.seal("x"),)).fetchone()["id"]
    conn.commit()
    fake = FakePlaid({"good": page("g1", added=[make_txn("t1")])},
                     errors={"bad": [plaid_error("INTERNAL_SERVER_ERROR", 500)]})
    pool = db.pool(db_url)
    try:
        results = sync.sync_all(pool, fake, box)
    finally:
        pool.close()
    assert str(results[bad]).startswith("error")
    assert results[good]["added"] == 1
