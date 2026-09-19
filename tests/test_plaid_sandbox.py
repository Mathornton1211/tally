"""End to end against the real Plaid Sandbox. Skipped without sandbox keys.

Uses a Sandbox test bank (First Platypus Bank), so no real account is touched.
"""
import os
import time

import pytest

from tally import sync
from tally.plaid import Plaid

SANDBOX = os.environ.get("PLAID_SECRET_SANDBOX")
pytestmark = pytest.mark.skipif(not (SANDBOX and os.environ.get("PLAID_CLIENT_ID")),
                                reason="no Plaid sandbox keys in env")


@pytest.fixture
def plaid():
    return Plaid("https://sandbox.plaid.com", os.environ["PLAID_CLIENT_ID"], SANDBOX)


def test_link_token_creates(plaid):
    assert plaid.link_token_create("test", None)["link_token"].startswith("link-sandbox-")


def test_link_and_sync_real_sandbox_item(conn, box, plaid):
    public = plaid.sandbox_public_token_create("ins_109508", ["transactions"])["public_token"]
    item_id = sync.link_item(conn, plaid, box, public)
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM accounts").fetchone()["n"] > 0

    # Sandbox builds history asynchronously; the first calls can be NOT_READY.
    deadline = time.monotonic() + 90
    total = 0
    while time.monotonic() < deadline:
        result = sync.sync_item(conn, plaid, box, item_id)
        total += result["added"]
        if result["update_status"] == "HISTORICAL_UPDATE_COMPLETE" and total:
            break
        time.sleep(3)
    assert total > 0, "sandbox never returned transactions"
    n = conn.execute("SELECT count(*) AS n FROM transactions").fetchone()["n"]
    assert n == total
    inst = conn.execute("SELECT name FROM institutions").fetchone()["name"]
    assert inst
