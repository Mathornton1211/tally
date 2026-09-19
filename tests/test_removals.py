"""Deleting a transaction is the only irreversible thing sync does.

Past Plaid's ~24-month window Tally is the only copy, so a removal instruction
for something old would destroy history that cannot be fetched again from
anywhere -- silently, on one line of JSON, with nobody watching.

The bias here is deliberate and it is not symmetric. A transaction wrongly kept
is a discrepancy somebody can see and fix. A transaction wrongly deleted is
gone.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import sync

D = Decimal
TODAY = date.today()


@pytest.fixture
def acct(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('a',1,'plaid','Card','credit','credit card',0)""")
    return "a"


def spend(conn, tid, amount, when):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary,
                                     pfc_detailed, raw)
           VALUES (%s,'a',%s,%s,'SHOP','GENERAL_MERCHANDISE','GENERAL_MERCHANDISE_OTHER','{}')""",
        (tid, amount, when))


def exists(conn, tid):
    return bool(conn.execute("SELECT 1 FROM transactions WHERE id = %s", (tid,)).fetchone())


# ---------------------------------------------------------------- obeying

def test_a_recent_reversal_is_obeyed(conn, acct):
    """A charge reversed last week did not happen and should not be in any
    total. This is the case the removed list is actually for."""
    spend(conn, "t1", 40, TODAY - timedelta(days=5))
    conn.commit()
    assert sync.apply_removals(conn, ["t1"]) == {"removed": 1, "withheld": 0}
    assert not exists(conn, "t1")


def test_even_an_obeyed_removal_leaves_a_copy(conn, acct):
    """"Where did that go" should be a question with an answer."""
    spend(conn, "t1", 40, TODAY - timedelta(days=5))
    conn.commit()
    sync.apply_removals(conn, ["t1"])

    kept = conn.execute("SELECT * FROM removed_transactions WHERE id = 't1'").fetchone()
    assert kept["obeyed"] is True and kept["amount"] == D("40.00")
    # The whole row, so putting it back is possible rather than theoretical.
    assert kept["row"]["account_id"] == "a" and kept["row"]["name"] == "SHOP"


# ---------------------------------------------------------------- refusing

def test_an_old_removal_is_refused_and_the_transaction_stays(conn, acct):
    spend(conn, "old", 40, TODAY - timedelta(days=400))
    conn.commit()
    assert sync.apply_removals(conn, ["old"]) == {"removed": 0, "withheld": 1}
    assert exists(conn, "old")


def test_a_refused_removal_is_flagged_so_a_mismatch_has_an_explanation(conn, acct):
    """It still counts in every total, so a statement will not agree with it.
    That needs a reason attached, not a mystery."""
    spend(conn, "old", 40, TODAY - timedelta(days=400))
    conn.commit()
    sync.apply_removals(conn, ["old"])

    row = conn.execute(
        "SELECT removal_withheld_at FROM transactions WHERE id = 'old'").fetchone()
    assert row["removal_withheld_at"] is not None
    archived = conn.execute("SELECT obeyed, age_days FROM removed_transactions").fetchone()
    assert archived["obeyed"] is False and archived["age_days"] >= 400


def test_a_refused_removal_raises_an_alert(conn, acct):
    """Finding out from a chart looking odd is not good enough."""
    from tally import monitor
    spend(conn, "old", 40, TODAY - timedelta(days=400))
    conn.commit()
    sync.apply_removals(conn, ["old"])
    conn.commit()

    alert = next(a for a in monitor.plan_alerts(conn) if a["rule"] == "removal_withheld")
    assert "only copy" in alert["detail"]
    assert alert["inputs"]["count"] == 1


def test_the_boundary_is_where_it_says_it_is(conn, acct):
    spend(conn, "inside", 10, TODAY - timedelta(days=sync.OBEY_REMOVAL_DAYS))
    spend(conn, "outside", 10, TODAY - timedelta(days=sync.OBEY_REMOVAL_DAYS + 1))
    conn.commit()
    assert sync.apply_removals(conn, ["inside", "outside"]) == {"removed": 1, "withheld": 1}
    assert not exists(conn, "inside") and exists(conn, "outside")


# ---------------------------------------------------------------- the edges

def test_a_removal_for_something_that_is_not_here_is_harmless(conn, acct):
    """Plaid can name a transaction this install never had."""
    assert sync.apply_removals(conn, ["never-seen"]) == {"removed": 0, "withheld": 0}


def test_nothing_to_remove_does_nothing(conn, acct):
    assert sync.apply_removals(conn, []) == {"removed": 0, "withheld": 0}
    assert conn.execute("SELECT count(*) AS n FROM removed_transactions").fetchone()["n"] == 0


def test_the_same_removal_twice_does_not_pile_up(conn, acct):
    """A resync can repeat a removal, and the archive should hold one row for
    one transaction."""
    spend(conn, "t1", 40, TODAY - timedelta(days=5))
    conn.commit()
    sync.apply_removals(conn, ["t1"])
    sync.apply_removals(conn, ["t1"])
    assert conn.execute("SELECT count(*) AS n FROM removed_transactions").fetchone()["n"] == 1
