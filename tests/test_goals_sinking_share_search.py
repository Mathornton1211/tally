"""Goals with a trajectory, funds that fill themselves, share links, and search."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import funds, goals, search, share

D = Decimal
TODAY = date.today()


@pytest.fixture
def accounts(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('chk',1,'plaid','Checking','depository','checking',4000),
                           ('sav',1,'plaid','Savings','depository','savings',6000),
                           ('card',1,'plaid','Card','credit','credit card',3000)""")
    conn.commit()


def txn(conn, tid, name, amount, when=None, account="chk",
        primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_OTHER"):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'{}')""",
        (tid, account, amount, when or TODAY, name, primary, detailed))


def income(conn, tid, amount, when):
    txn(conn, tid, "ACME PAYROLL", -amount, when, primary="INCOME", detailed="INCOME_WAGES")


# ---------------------------------------------------------------- goals

def test_net_worth_is_assets_minus_debts(conn, accounts):
    conn.commit()
    assert goals.evaluate(conn)["net_worth"] == D("7000")     # 4000 + 6000 - 3000


def test_a_goal_with_a_deadline_says_what_it_needs_a_month(conn, accounts):
    conn.execute("""INSERT INTO goals (kind, name, target_amount, target_date)
                    VALUES ('net_worth','Ten grand',10000,%s)""", (TODAY + timedelta(days=304),))
    conn.commit()
    g = goals.evaluate(conn)["goals"][0]
    assert g["remaining"] == D("3000.00")
    assert g["required_per_month"] == D("300.00")            # 3000 over ten months


def test_months_of_spending_resolves_to_a_number_that_moves(conn, accounts):
    """An emergency fund target in months must track what life actually costs,
    or it goes stale the moment rent rises."""
    for i in range(3):
        txn(conn, f"s{i}", "RENT", 2000, TODAY - timedelta(days=30 * i),
            primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT")
    conn.execute("""INSERT INTO goals (kind, name, target_months) VALUES ('emergency_fund','Cushion',3)""")
    conn.commit()
    g = goals.evaluate(conn)["goals"][0]
    assert g["target"] == D("6000.00")                        # 3 x 2000/month
    assert g["current"] == D("10000.00")                      # all depository cash
    assert g["done"] is True


def test_debt_free_reads_the_other_way_up(conn, accounts):
    """Progress on debt is the number going down, so 'remaining' is the debt
    itself rather than a shortfall against a target."""
    conn.execute("INSERT INTO goals (kind, name) VALUES ('debt_free','No cards')")
    conn.commit()
    g = goals.evaluate(conn)["goals"][0]
    assert g["target"] == D("0.00") and g["remaining"] == D("3000") and g["done"] is False

    conn.execute("UPDATE accounts SET current_balance = 0 WHERE id = 'card'")
    conn.commit()
    assert goals.evaluate(conn)["goals"][0]["done"] is True


def test_a_flat_trajectory_gives_no_arrival_date(conn, accounts):
    """Net worth that has not moved does not arrive anywhere. Printing an ETA
    from a zero slope would mean printing a date in the year 4000."""
    conn.execute("""INSERT INTO goals (kind, name, target_amount, target_date)
                    VALUES ('net_worth','Soon',99999,%s)""", (TODAY + timedelta(days=90),))
    conn.commit()
    g = goals.evaluate(conn)["goals"][0]
    assert g["pace_per_month"] == D("0.00")
    assert g["eta"] is None and g["months_at_pace"] is None
    assert g["state"] == "behind" and g["shortfall_per_month"] > 0


def test_a_goal_with_no_deadline_is_not_scored_as_behind(conn, accounts):
    conn.execute("INSERT INTO goals (kind, name, target_amount) VALUES ('net_worth','Someday',50000)")
    conn.commit()
    assert goals.evaluate(conn)["goals"][0]["state"] == "no_deadline"


def test_suggestions_only_offer_what_is_missing(conn, accounts):
    conn.commit()
    kinds = {s["kind"] for s in goals.suggestions(conn)}
    assert "debt_free" in kinds                               # there is a card balance
    conn.execute("INSERT INTO goals (kind, name) VALUES ('debt_free','No cards')")
    conn.commit()
    assert "debt_free" not in {s["kind"] for s in goals.suggestions(conn)}


# ---------------------------------------------------------------- sinking funds

def test_a_percentage_of_each_paycheck_goes_in(conn, accounts):
    income(conn, "p1", 2000, TODAY - timedelta(days=14))
    income(conn, "p2", 2000, TODAY - timedelta(days=1))
    conn.execute("""INSERT INTO funds (name, target_amount, auto_kind, auto_percent, auto_through)
                    VALUES ('Truck', 5000, 'percent_of_income', 10, %s)""",
                 (TODAY - timedelta(days=30),))
    conn.commit()

    assert funds.auto_fill(conn) == {"filled": 2, "moved": D("400.00")}
    assert funds.list_funds(conn)[0]["saved"] == D("400.00")


def test_running_it_twice_does_not_fill_twice(conn, accounts):
    """The worker calls this after every sync, so idempotence is the whole
    requirement -- a fund that doubles every six hours is worse than manual."""
    income(conn, "p1", 1000, TODAY - timedelta(days=2))
    conn.execute("""INSERT INTO funds (name, target_amount, auto_kind, auto_amount, auto_through)
                    VALUES ('Tyres', 2000, 'per_paycheck', 50, %s)""", (TODAY - timedelta(days=10),))
    conn.commit()
    assert funds.auto_fill(conn)["filled"] == 1
    assert funds.auto_fill(conn)["filled"] == 0
    assert funds.list_funds(conn)[0]["saved"] == D("50.00")


def test_it_stops_at_the_target_instead_of_overshooting(conn, accounts):
    income(conn, "p1", 5000, TODAY - timedelta(days=2))
    conn.execute("""INSERT INTO funds (name, target_amount, auto_kind, auto_percent, auto_through)
                    VALUES ('Small', 100, 'percent_of_income', 50, %s)""", (TODAY - timedelta(days=10),))
    conn.commit()
    funds.auto_fill(conn)
    f = funds.list_funds(conn)[0]
    assert f["saved"] == D("100.00") and f["complete"] is True   # not 2500


def test_a_bought_fund_stops_taking(conn, accounts):
    income(conn, "p1", 1000, TODAY - timedelta(days=2))
    conn.execute("""INSERT INTO funds (name, target_amount, auto_kind, auto_amount, auto_through, bought_on)
                    VALUES ('Done', 500, 'per_paycheck', 50, %s, current_date)""",
                 (TODAY - timedelta(days=10),))
    conn.commit()
    assert funds.auto_fill(conn)["filled"] == 0


def test_the_preview_uses_real_past_income(conn, accounts):
    for i in range(6):
        income(conn, f"p{i}", 2000, TODAY - timedelta(days=14 * i))
    conn.commit()
    p = funds.auto_preview(conn, "percent_of_income", percent=D("10"), months=3)
    assert p["deposits"] == 6                                  # fortnightly pay inside ~91 days
    assert p["total"] == D("1200.00")                          # 10% of six 2000 deposits
    assert p["per_month"] == D("400.00")


# ---------------------------------------------------------------- share links

def test_a_link_works_once_created_and_stops_when_revoked(conn, accounts):
    link = share.create(conn, "Accountant 2026", date(2026, 1, 1), date(2026, 12, 31))
    conn.commit()
    assert share.resolve(conn, link["token"])["label"] == "Accountant 2026"
    share.revoke(conn, link["id"])
    conn.commit()
    assert share.resolve(conn, link["token"]) is None


def test_the_token_is_not_stored_in_the_clear(conn, accounts):
    """A database dump must not hand over working links."""
    link = share.create(conn, "Tax", date(2026, 1, 1), date(2026, 12, 31))
    conn.commit()
    stored = conn.execute("SELECT token_hash FROM share_links").fetchone()["token_hash"]
    assert link["token"] not in stored and len(stored) == 64


def test_an_expired_link_is_refused(conn, accounts):
    link = share.create(conn, "Old", date(2026, 1, 1), date(2026, 12, 31),
                        expires_on=TODAY - timedelta(days=1))
    conn.commit()
    assert share.resolve(conn, link["token"]) is None


def test_a_link_shows_only_its_own_date_range(conn, accounts):
    txn(conn, "inside", "SHOP", 100, date(2026, 3, 5))
    txn(conn, "outside", "SHOP", 999, date(2025, 3, 5))
    link = share.create(conn, "2026", date(2026, 1, 1), date(2026, 12, 31))
    conn.commit()
    c = share.contents(conn, share.resolve(conn, link["token"]))
    assert c["spent"] == D("100.00") and c["transactions"] == 1


def test_a_summary_link_does_not_include_the_transactions(conn, accounts):
    txn(conn, "t1", "SHOP", 100, date(2026, 3, 5))
    summary = share.create(conn, "Totals", date(2026, 1, 1), date(2026, 12, 31), detail="summary")
    detailed = share.create(conn, "Everything", date(2026, 1, 1), date(2026, 12, 31), detail="transactions")
    conn.commit()
    assert "rows" not in share.contents(conn, share.resolve(conn, summary["token"]))
    assert len(share.contents(conn, share.resolve(conn, detailed["token"]))["rows"]) == 1


def test_views_are_counted_so_an_unexpected_one_is_visible(conn, accounts):
    link = share.create(conn, "Tax", date(2026, 1, 1), date(2026, 12, 31))
    conn.commit()
    share.resolve(conn, link["token"])
    share.resolve(conn, link["token"])
    conn.commit()
    assert share.listing(conn)[0]["views"] == 2


# ---------------------------------------------------------------- search

def test_dates_are_read_without_a_model():
    today = date(2026, 9, 17)
    for phrase, expect in [
        ("last year", (date(2025, 1, 1), date(2025, 12, 31))),
        ("in 2024", (date(2024, 1, 1), date(2024, 12, 31))),
        ("this month", (date(2026, 9, 1), date(2026, 9, 17))),
        ("last month", (date(2026, 8, 1), date(2026, 8, 31))),
        ("in march", (date(2026, 3, 1), date(2026, 3, 31))),
        ("last 30 days", (date(2026, 8, 18), date(2026, 9, 17))),
    ]:
        start, end, _ = search.parse_dates(phrase, today)
        assert (start, end) == expect, phrase


def test_a_month_later_than_today_means_last_year():
    """In September, "in November" is almost always the one that already
    happened, not the one in ten weeks."""
    start, _, _ = search.parse_dates("spending in november", date(2026, 9, 17))
    assert start == date(2025, 11, 1)


def test_amounts_are_read_without_a_model():
    assert search.parse_amounts("over $100") == (D("100"), None)
    assert search.parse_amounts("under 50") == (None, D("50"))
    assert search.parse_amounts("between $20 and $60") == (D("20"), D("60"))


def test_a_plain_question_finds_the_right_rows(conn, accounts):
    txn(conn, "c1", "COSTCO WHOLESALE", 120, date(2025, 4, 2))
    txn(conn, "c2", "COSTCO WHOLESALE", 80, date(2025, 8, 9))
    txn(conn, "c3", "COSTCO WHOLESALE", 200, date(2026, 2, 1))
    txn(conn, "t1", "TARGET", 40, date(2025, 5, 5))
    conn.commit()

    r = search.ask(conn, "how much did I spend at Costco last year", today=date(2026, 9, 17))
    assert r["filters"]["merchant"] == "costco"
    assert r["count"] == 2 and r["spent"] == D("200.00")       # 2025 only, no Target


def test_a_quoted_phrase_is_taken_exactly(conn, accounts):
    txn(conn, "t1", "THE COFFEE HOUSE", 12)
    txn(conn, "t2", "COFFEE BEAN CO", 8)
    conn.commit()
    r = search.ask(conn, 'spending at "coffee bean"')
    assert r["count"] == 1 and r["rows"][0]["display_name"] == "Coffee Bean Co"


def test_a_category_name_in_the_question_filters_by_category(conn, accounts):
    txn(conn, "g1", "SAFEWAY", 60, primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_GROCERIES")
    txn(conn, "d1", "PIZZA", 20, primary="FOOD_AND_DRINK", detailed="FOOD_AND_DRINK_RESTAURANT")
    conn.commit()
    r = search.ask(conn, "groceries this month")
    assert r["filters"]["category"] == "groceries" and r["count"] == 1


def test_an_amount_limit_narrows_it(conn, accounts):
    txn(conn, "a1", "SHOP", 10)
    txn(conn, "a2", "SHOP", 500)
    conn.commit()
    r = search.ask(conn, "shop over $100")
    assert r["count"] == 1 and r["rows"][0]["id"] == "a2"


def test_totals_come_from_sql_not_from_a_model(conn, accounts):
    """The filters may be a guess; the number never is."""
    txn(conn, "a1", "SHOP", 33.33)
    txn(conn, "a2", "SHOP", 66.67)
    conn.commit()
    r = search.ask(conn, "shop")
    assert r["spent"] == D("100.00") and r["average"] == D("50.00")


def test_search_works_with_the_model_switched_off(conn, accounts):
    txn(conn, "a1", "NETFLIX", 15.99)
    conn.commit()
    r = search.ask(conn, "netflix", llm=None)
    assert r["count"] == 1 and r["filters"]["by"] == "text"
