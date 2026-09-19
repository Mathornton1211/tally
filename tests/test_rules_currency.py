"""Rules that rename, tag and split; and money that is not all in one currency."""
from datetime import date
from decimal import Decimal

import pytest
from psycopg.types.json import Jsonb

from tally import money, rules

D = Decimal


@pytest.fixture
def acct(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance, iso_currency)
                    VALUES ('a',1,'plaid','Checking','depository','checking',500,'USD')""")
    return "a"


def txn(conn, tid, name, amount=50, when=date(2026, 1, 5), account="a", currency=None,
        primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_OTHER"):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, iso_currency,
                                     pfc_primary, pfc_detailed, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,%s,'{}')""",
        (tid, account, amount, when, name, currency, primary, detailed))


def rule(conn, **kw):
    kw.setdefault("name", "r"); kw.setdefault("match_field", "display_name")
    kw.setdefault("match_type", "contains")
    cols = ", ".join(kw); vals = ", ".join(["%s"] * len(kw))
    return conn.execute(f"INSERT INTO rules ({cols}) VALUES ({vals}) RETURNING id",
                        list(kw.values())).fetchone()["id"]


def one(conn, tid="t1"):
    return conn.execute("SELECT * FROM v_txn WHERE id = %s", (tid,)).fetchone()


# ---------------------------------------------------------------- renaming

def test_a_rule_renames_the_merchant(conn, acct):
    txn(conn, "t1", "SQ *COFFEE 4412 SEATTLE")
    rule(conn, pattern="SQ *COFFEE", set_name="Victrola Coffee")
    conn.commit()
    r = one(conn)
    assert r["display_name"] == "Victrola Coffee" and r["name_source"] == "rule"
    # The key follows the visible name, so category rules and grouping agree
    # with what is on screen.
    assert r["merchant_key"] == "victrola coffee"


def test_a_name_typed_by_hand_beats_a_rule(conn, acct):
    txn(conn, "t1", "SQ *COFFEE 4412")
    conn.execute("""INSERT INTO merchant_aliases (raw_key, clean_name, source)
                    VALUES (tally_raw_key('SQ *COFFEE 4412'), 'My Coffee Place', 'user')""")
    rule(conn, pattern="SQ *COFFEE", set_name="Victrola Coffee")
    conn.commit()
    r = one(conn)
    assert r["display_name"] == "My Coffee Place" and r["name_source"] == "user"


# ---------------------------------------------------------------- matching

def test_the_three_match_types(conn, acct):
    txn(conn, "t1", "WHOLE FOODS MKT 123")
    conn.commit()
    for kind, pattern, hit in [("contains", "whole foods", True), ("contains", "trader", False),
                               ("equals", "Whole Foods Mkt", True), ("equals", "whole", False),
                               ("regex", r"^WHOLE.*\d+$", False),      # display_name is title-cased
                               ("regex", r"(?i)whole\s+foods", True)]:
        assert conn.execute(
            "SELECT tally_rule_match(%s,%s,'Whole Foods Mkt') AS m", (pattern, kind)).fetchone()["m"] is hit, \
            (kind, pattern)


def test_a_broken_regex_matches_nothing_instead_of_breaking_every_query(conn, acct):
    """One malformed rule must not take down the transactions page."""
    txn(conn, "t1", "ANYTHING")
    rule(conn, pattern="([unclosed", match_type="regex", set_name="Nope")
    conn.commit()
    assert one(conn)["display_name"] == "Anything"


def test_amount_and_account_narrow_a_rule(conn, acct):
    txn(conn, "t1", "AMAZON", amount=9)
    txn(conn, "t2", "AMAZON", amount=200)
    rule(conn, pattern="amazon", min_amount=100, set_name="Amazon (big)")
    conn.commit()
    assert one(conn, "t1")["display_name"] == "Amazon"
    assert one(conn, "t2")["display_name"] == "Amazon (big)"


def test_priority_decides_and_ties_go_to_the_older_rule(conn, acct):
    txn(conn, "t1", "TARGET")
    first = rule(conn, pattern="target", set_name="First", priority=0)
    rule(conn, pattern="target", set_name="Second", priority=0)
    conn.commit()
    assert one(conn)["display_name"] == "First"

    rule(conn, pattern="target", set_name="Louder", priority=10)
    conn.commit()
    assert one(conn)["display_name"] == "Louder"
    assert first  # the low-priority rule still exists, it just lost


# ---------------------------------------------------------------- tags

def test_rule_tags_and_hand_tags_merge_without_duplicates(conn, acct):
    txn(conn, "t1", "SHELL OIL")
    conn.execute("UPDATE transactions SET tags = ARRAY['work','fuel'] WHERE id = 't1'")
    rule(conn, pattern="shell", add_tags=["fuel", "reimbursable"])
    conn.commit()
    assert one(conn)["tags"] == ["fuel", "reimbursable", "work"]


def test_tags_survive_with_no_rule_at_all(conn, acct):
    txn(conn, "t1", "SHELL OIL")
    conn.execute("UPDATE transactions SET tags = ARRAY['work'] WHERE id = 't1'")
    conn.commit()
    assert one(conn)["tags"] == ["work"]


# ---------------------------------------------------------------- categories and notes

def test_a_rule_sets_the_category_but_a_hand_edit_still_wins(conn, acct):
    txn(conn, "t1", "SPOTIFY")
    rule(conn, pattern="spotify", set_category="entertainment")
    conn.commit()
    assert one(conn)["category"] == "entertainment" and one(conn)["category_source"] == "rule"

    conn.execute("UPDATE transactions SET category = 'services' WHERE id = 't1'")
    conn.commit()
    assert one(conn)["category"] == "services" and one(conn)["category_source"] == "user"


def test_a_rule_note_shows_only_where_there_is_no_note_already(conn, acct):
    txn(conn, "t1", "IRS PAYMENT")
    txn(conn, "t2", "IRS PAYMENT")
    conn.execute("UPDATE transactions SET note = 'Q3, already filed' WHERE id = 't2'")
    rule(conn, pattern="irs", set_note="Quarterly estimated tax")
    conn.commit()
    assert one(conn, "t1")["note"] == "Quarterly estimated tax"
    assert one(conn, "t2")["note"] == "Q3, already filed"


# ---------------------------------------------------------------- splitting

def test_a_percentage_split_makes_children_that_add_back_exactly(conn, acct):
    txn(conn, "t1", "COSTCO", amount=100.01)
    conn.execute("""INSERT INTO rules (name, pattern, match_field, match_type, split)
                    VALUES ('costco','costco','display_name','contains',%s)""",
                 (Jsonb([{"category": "groceries", "percent": 70},
                         {"category": "home", "percent": 30}]),))
    conn.commit()

    assert rules.apply_splits(conn)["split"] == 1
    kids = conn.execute(
        "SELECT amount, category FROM transactions WHERE parent_id = 't1' ORDER BY id").fetchall()
    assert [k["amount"] for k in kids] == [D("70.01"), D("30.00")]   # remainder on the last part
    assert sum(k["amount"] for k in kids) == D("100.01")
    assert conn.execute("SELECT is_split_parent FROM transactions WHERE id='t1'").fetchone()["is_split_parent"]
    # The parent drops out of v_txn so nothing is double counted.
    assert one(conn) is None


def test_splitting_twice_does_not_duplicate(conn, acct):
    txn(conn, "t1", "COSTCO", amount=100)
    conn.execute("""INSERT INTO rules (name, pattern, match_field, match_type, split)
                    VALUES ('costco','costco','display_name','contains',%s)""",
                 (Jsonb([{"category": "groceries", "percent": 50},
                         {"category": "home", "percent": 50}]),))
    conn.commit()
    rules.apply_splits(conn)
    rules.apply_splits(conn)
    assert conn.execute("SELECT count(*) AS n FROM transactions WHERE parent_id='t1'").fetchone()["n"] == 2


def test_a_hand_edited_split_is_left_alone(conn, acct):
    """Having the computer undo your correction every six hours is worse than
    not automating it."""
    txn(conn, "t1", "COSTCO", amount=100)
    conn.execute("UPDATE transactions SET split_locked = true WHERE id = 't1'")
    conn.execute("""INSERT INTO rules (name, pattern, match_field, match_type, split)
                    VALUES ('costco','costco','display_name','contains',%s)""",
                 (Jsonb([{"category": "groceries", "percent": 100}]),))
    conn.commit()
    assert rules.apply_splits(conn)["split"] == 0


def test_turning_a_split_rule_off_puts_the_transaction_back(conn, acct):
    txn(conn, "t1", "COSTCO", amount=100)
    rid = conn.execute("""INSERT INTO rules (name, pattern, match_field, match_type, split)
                          VALUES ('costco','costco','display_name','contains',%s) RETURNING id""",
                       (Jsonb([{"category": "groceries", "percent": 100}]),)).fetchone()["id"]
    conn.commit()
    rules.apply_splits(conn)
    assert rules.unsplit_rule(conn, rid) == 1
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM transactions WHERE parent_id='t1'").fetchone()["n"] == 0
    assert one(conn)["amount"] == D("100.00")


def test_a_split_that_does_not_add_up_is_refused():
    with pytest.raises(ValueError, match="not 100"):
        rules.validate_split([{"percent": 70}, {"percent": 20}])
    with pytest.raises(ValueError, match="percent"):
        rules.validate_split([{"percent": 50}, {"amount": 10}])
    rules.validate_split([{"percent": 70}, {"percent": 30}])


# ---------------------------------------------------------------- currency

def test_without_a_rate_a_foreign_amount_is_left_alone_and_flagged(conn, acct):
    """Converting at a rate nobody supplied would invent a total. Showing the
    raw number and marking it is honest; silently multiplying by 1 is not."""
    txn(conn, "t1", "CAFE PARIS", amount=20, currency="EUR")
    conn.commit()
    r = one(conn)
    assert r["currency"] == "EUR" and r["foreign_currency"] is True
    assert r["amount"] == D("20.00") and r["fx"] == 1


def test_a_rate_converts_the_amount_but_keeps_the_original(conn, acct):
    txn(conn, "t1", "CAFE PARIS", amount=20, currency="EUR")
    money.set_rate(conn, "EUR", D("1.08"), date(2026, 1, 1))
    conn.commit()
    r = one(conn)
    assert r["amount"] == D("21.60") and r["original_amount"] == D("20.00")
    assert r["spend"] == D("21.60")


def test_the_rate_in_force_is_the_one_on_the_day(conn, acct):
    """A rate typed in today must not rewrite what last year's holiday cost."""
    txn(conn, "t1", "HOTEL", amount=100, currency="EUR", when=date(2026, 1, 15))
    txn(conn, "t2", "HOTEL", amount=100, currency="EUR", when=date(2026, 6, 15))
    money.set_rate(conn, "EUR", D("1.05"), date(2026, 1, 1))
    money.set_rate(conn, "EUR", D("1.20"), date(2026, 6, 1))
    conn.commit()
    assert one(conn, "t1")["amount"] == D("105.00")
    assert one(conn, "t2")["amount"] == D("120.00")


def test_changing_the_home_currency_reverses_what_counts_as_foreign(conn, acct):
    txn(conn, "t1", "CAFE PARIS", amount=20, currency="EUR")
    txn(conn, "t2", "DINER", amount=30, currency="USD")
    money.set_rate(conn, "USD", D("0.93"), date(2026, 1, 1))
    money.set_home(conn, "EUR")
    conn.commit()
    assert one(conn, "t1")["foreign_currency"] is False
    assert one(conn, "t2")["foreign_currency"] is True
    assert one(conn, "t2")["amount"] == D("27.90")


def test_status_names_the_currencies_with_no_rate(conn, acct):
    txn(conn, "t1", "CAFE", amount=20, currency="EUR")
    txn(conn, "t2", "PUB", amount=20, currency="GBP")
    money.set_rate(conn, "EUR", D("1.08"))
    conn.commit()
    s = money.status(conn)
    assert s["home"] == "USD" and s["multi"] is True
    assert s["missing"] == ["GBP"]


def test_a_split_survives_the_trip_through_the_api_shape(conn, acct):
    """The API hands Pydantic Decimals to jsonb, which json.dumps cannot
    serialise. They go in as strings and have to come back out as exact money."""
    from tally.routes_rules import RuleIn, _clean
    cleaned = _clean(RuleIn(name="Costco", pattern="costco",
                            split=[{"category": "groceries", "percent": "60.5"},
                                   {"category": "home", "percent": "39.5"}]))
    assert cleaned["split"] == [{"category": "groceries", "percent": "60.5"},
                                {"category": "home", "percent": "39.5"}]

    txn(conn, "t1", "COSTCO", amount=200)
    conn.execute("""INSERT INTO rules (name, pattern, match_field, match_type, split)
                    VALUES ('c','costco','display_name','contains',%s)""", (Jsonb(cleaned["split"]),))
    conn.commit()
    rules.apply_splits(conn)
    kids = conn.execute(
        "SELECT amount FROM transactions WHERE parent_id = 't1' ORDER BY id").fetchall()
    assert [k["amount"] for k in kids] == [D("121.00"), D("79.00")]
    assert sum(k["amount"] for k in kids) == D("200.00")
