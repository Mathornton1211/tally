"""The review queue.

The hard part is what stays out. A list with no end is one nobody starts, so
these tests are mostly about charges that should NOT be asked about.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import review

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


def spend(conn, tid, name, amount, when=None, confidence="VERY_HIGH",
          primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_RESTAURANT", **kw):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary,
                                     pfc_detailed, pfc_confidence, raw)
           VALUES (%s,'a',%s,%s,%s,%s,%s,%s,'{}')""",
        (tid, amount, when or TODAY - timedelta(days=2), name, primary, detailed, confidence))


def ids(q):
    return sorted(i["id"] for i in q["items"])


def reasons(q):
    return {i["id"]: i["reason"] for i in q["items"]}


# ---------------------------------------------------------------- what stays out

def test_a_confident_everyday_charge_is_not_worth_anybodys_time(conn, acct):
    """A $4.50 coffee Plaid is sure about needs no human, and putting it in the
    queue is how the queue stops being opened."""
    # Already confirmed once, so Tally knows what this place is.
    spend(conn, "old", "STARBUCKS", 4.50, TODAY - timedelta(days=40))
    conn.commit()
    review.confirm(conn, ["old"])
    spend(conn, "t1", "STARBUCKS", 4.50)
    conn.commit()
    assert ids(review.queue(conn)) == []


def test_a_merchant_nobody_has_confirmed_is_asked_about(conn, acct):
    """Naming it once fixes every future charge from it, which is why this
    reason outranks the others."""
    spend(conn, "t1", "SQ *NEW PLACE 4412", 18.00)
    conn.commit()
    q = review.queue(conn)
    assert ids(q) == ["t1"] and reasons(q)["t1"] == "new_merchant"


def test_confirming_one_charge_settles_the_whole_merchant(conn, acct):
    """The question is "what is this place", and it only has to be answered
    once. The rest stop being asked about without anybody clicking them."""
    for i in range(3):
        spend(conn, f"t{i}", "SQ *NEW PLACE", 18, TODAY - timedelta(days=i))
    conn.commit()
    assert len(review.queue(conn)["items"]) == 3

    review.apply(conn, ["t0"], category="dining")
    conn.commit()
    assert ids(review.queue(conn)) == []


def test_something_that_fell_through_to_other_is_asked_about(conn, acct):
    spend(conn, "old", "MYSTERY CO", 20, TODAY - timedelta(days=40),
          primary="OTHER", detailed="OTHER_OTHER")
    conn.commit(); review.confirm(conn, ["old"])
    spend(conn, "t1", "MYSTERY CO", 20, primary="OTHER", detailed="OTHER_OTHER")
    conn.commit()
    assert reasons(review.queue(conn))["t1"] == "uncategorised"


def test_a_low_confidence_guess_is_asked_about(conn, acct):
    spend(conn, "old", "AMBIGUOUS LTD", 30, TODAY - timedelta(days=40), confidence="LOW")
    conn.commit(); review.confirm(conn, ["old"])
    spend(conn, "t1", "AMBIGUOUS LTD", 30, confidence="LOW")
    conn.commit()
    assert reasons(review.queue(conn))["t1"] == "low_confidence"


def test_a_big_charge_is_asked_about_even_when_everything_is_known(conn, acct):
    """Not because it is suspicious -- Alerts does suspicion -- but because it
    is the one most likely to want a split, a tag or a fund."""
    spend(conn, "old", "BIG STORE", 900, TODAY - timedelta(days=40))
    conn.commit(); review.confirm(conn, ["old"])
    spend(conn, "t1", "BIG STORE", 900)
    conn.commit()
    assert reasons(review.queue(conn))["t1"] == "large"


def test_pending_charges_are_left_until_they_settle(conn, acct):
    spend(conn, "t1", "SOMEWHERE NEW", 50)
    conn.execute("UPDATE transactions SET pending = true WHERE id = 't1'")
    conn.commit()
    assert ids(review.queue(conn)) == []


def test_old_charges_sit_behind_the_window_and_are_counted(conn, acct):
    """They are not lost, they are just not today's problem."""
    spend(conn, "t1", "SOMEWHERE NEW", 50, TODAY - timedelta(days=200))
    conn.commit()
    q = review.queue(conn, days=45)
    assert ids(q) == [] and q["backlog"] == 1 and q["backlog_oldest"] is not None


# ---------------------------------------------------------------- clearing it

def test_confirming_takes_it_off_the_list_and_does_not_change_it(conn, acct):
    spend(conn, "t1", "SOMEWHERE NEW", 50)
    conn.commit()
    assert review.confirm(conn, ["t1"]) == 1
    conn.commit()
    assert ids(review.queue(conn)) == []
    assert conn.execute("SELECT category FROM transactions WHERE id='t1'").fetchone()["category"] is None


def test_confirming_twice_is_harmless_and_keeps_the_first_time(conn, acct):
    spend(conn, "t1", "SOMEWHERE NEW", 50)
    conn.commit()
    review.confirm(conn, ["t1"])
    first = conn.execute("SELECT reviewed_at FROM transactions WHERE id='t1'").fetchone()["reviewed_at"]
    assert review.confirm(conn, ["t1"]) == 0
    assert conn.execute(
        "SELECT reviewed_at FROM transactions WHERE id='t1'").fetchone()["reviewed_at"] == first


def test_one_decision_applies_to_the_whole_group(conn, acct):
    """Twelve Amazon charges one at a time is the difference between a habit
    and a chore."""
    for i in range(4):
        spend(conn, f"t{i}", "AMAZON MKTP", 20 + i, TODAY - timedelta(days=i),
              primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_OTHER")
    conn.commit()

    q = review.queue(conn)
    group = next(g for g in q["groups"] if g["display_name"] == "Amazon Mktp")
    assert len(group["ids"]) == 4

    out = review.apply(conn, group["ids"], category="shopping")
    conn.commit()
    assert out["reviewed"] == 4
    assert ids(review.queue(conn)) == []
    cats = {r["category"] for r in conn.execute(
        "SELECT category FROM transactions WHERE id = ANY(%s)", (group["ids"],)).fetchall()}
    assert cats == {"shopping"}


def test_a_bulk_tag_never_removes_one_somebody_added_by_hand(conn, acct):
    spend(conn, "t1", "SHOP A", 50)
    spend(conn, "t2", "SHOP B", 50)
    conn.execute("UPDATE transactions SET tags = ARRAY['personal'] WHERE id = 't1'")
    conn.commit()

    review.apply(conn, ["t1", "t2"], add_tags=["Reimbursable"])
    conn.commit()
    got = {r["id"]: r["tags"] for r in conn.execute(
        "SELECT id, tags FROM transactions WHERE id = ANY(%s)", (["t1", "t2"],)).fetchall()}
    assert got["t1"] == ["personal", "reimbursable"]
    assert got["t2"] == ["reimbursable"]


def test_an_unknown_category_is_refused_before_anything_is_written(conn, acct):
    spend(conn, "t1", "SHOP A", 50)
    conn.commit()
    with pytest.raises(ValueError, match="unknown category"):
        review.apply(conn, ["t1"], category="nonsense")
    conn.rollback()
    assert conn.execute(
        "SELECT reviewed_at FROM transactions WHERE id='t1'").fetchone()["reviewed_at"] is None


def test_the_backlog_can_be_drawn_a_line_under(conn, acct):
    """Two years of history is not two thousand decisions. The honest move is
    to let somebody start from today and say so."""
    for i in range(5):
        spend(conn, f"old{i}", f"SHOP {i}", 30, TODAY - timedelta(days=100 + i))
    spend(conn, "recent", "SOMEWHERE NEW", 40)
    conn.commit()

    assert review.clear_backlog(conn, TODAY - timedelta(days=45)) == 5
    conn.commit()
    q = review.queue(conn)
    assert q["backlog"] == 0 and ids(q) == ["recent"]


def test_progress_can_say_you_are_done_and_mean_it(conn, acct):
    spend(conn, "t1", "SOMEWHERE NEW", 50)
    spend(conn, "t2", "SOMEWHERE ELSE", 60)
    conn.commit()
    assert review.progress(conn)["reviewed"] == 0

    review.apply(conn, ["t1", "t2"], category="dining")
    conn.commit()
    p = review.progress(conn)
    assert p["reviewed"] == 2 and p["total_ever"] == 2 and p["today"] == 2
