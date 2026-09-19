"""The long view, and the part that keeps working while nobody is looking."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import bills, research, trends

D = Decimal
TODAY = date.today()


@pytest.fixture
def accounts(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('chk',1,'plaid','Checking','depository','checking',2000),
                           ('card',1,'plaid','Rewards Card','credit','credit card',4000),
                           ('card2',1,'plaid','Plain Card','credit','credit card',500)""")
    conn.commit()


def spend(conn, tid, name, amount, when, account="chk",
          primary="GENERAL_MERCHANDISE", detailed="GENERAL_MERCHANDISE_OTHER"):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'{}')""",
        (tid, account, amount, when, name, primary, detailed))


def monthly(conn, name, amounts, start, prefix, **kw):
    """One charge a month, so detect_recurring sees a stream."""
    for i, amount in enumerate(amounts):
        spend(conn, f"{prefix}{i}", name, amount, start + timedelta(days=30 * i), **kw)


# ---------------------------------------------------------------- looking outwards

def test_a_price_that_crept_up_is_measured_from_the_first_one(conn, accounts):
    """Against last month it is $3. Against what you signed up for it is the
    number worth a phone call."""
    monthly(conn, "STREAMFLIX", [9.99] * 6 + [12.99] * 6 + [15.99] * 6,
            TODAY - timedelta(days=30 * 18), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    conn.commit()

    found = {f["kind"]: f for f in research.evaluate(conn)}
    creep = found.get("price_creep")
    assert creep, "a 60% rise over 18 months should be found"
    assert "$9.99" in creep["title"] and "$15.99" in creep["title"]
    assert creep["confidence"] == "certain"
    assert creep["annual_saving"] == D("72.00")          # (15.99 - 9.99) * 12
    assert "cancel" in creep["action"].lower()


def test_a_steady_subscription_is_a_question_not_an_accusation(conn, accounts):
    """Tally cannot see whether something is used, so it does not pretend to."""
    monthly(conn, "GYM MEMBERSHIP", [45.00] * 14, TODAY - timedelta(days=30 * 14), "gym",
            primary="PERSONAL_CARE", detailed="PERSONAL_CARE_GYMS_AND_FITNESS_CENTERS")
    conn.commit()

    found = {f["kind"]: f for f in research.evaluate(conn)}
    sub = found.get("long_running")
    assert sub and sub["confidence"] == "worth_checking"
    assert "$630.00" in sub["title"]                      # 45 x 14, the unseen number
    assert "whether or not" in sub["detail"]


def test_a_card_fee_that_does_not_earn_out(conn, accounts):
    conn.execute("""INSERT INTO account_settings (account_id, annual_fee, reward_rate)
                    VALUES ('card', 95, 1.5)""")
    for i in range(12):
        spend(conn, f"c{i}", "SHOP", 200, TODAY - timedelta(days=30 * i), account="card")
    conn.commit()

    fee = next(f for f in research.evaluate(conn) if f["kind"] == "annual_fee")
    # 2400 spent x 1.5% = 36 earned against a 95 fee.
    assert fee["annual_saving"] == D("59.00")
    assert fee["confidence"] == "likely"
    assert "product change" in fee["action"]


def test_a_card_fee_with_no_known_rewards_rate_asks_instead_of_guessing(conn, accounts):
    conn.execute("INSERT INTO account_settings (account_id, annual_fee) VALUES ('card', 95)")
    conn.commit()
    fee = next(f for f in research.evaluate(conn) if f["kind"] == "annual_fee")
    assert fee["confidence"] == "worth_checking"
    assert "Set the rewards rate" in fee["detail"]


def test_a_balance_on_the_expensive_card_names_the_transfer_fee_too(conn, accounts):
    """Advice that ignores the 3-5% transfer fee is advice that loses money."""
    conn.execute("""INSERT INTO liabilities (account_id, kind, apr, minimum_payment)
                    VALUES ('card','credit', 27.99, 100),
                           ('card2','credit', 12.99, 25)""")
    conn.execute("UPDATE accounts SET credit_limit = 6000 WHERE id = 'card'")
    conn.execute("UPDATE accounts SET credit_limit = 9000 WHERE id = 'card2'")
    conn.commit()

    found = [f for f in research.evaluate(conn) if f["kind"] == "expensive_balance"]
    assert found, "a 15-point APR gap with room to move should be found"
    f = found[0]
    assert "transfer" in f["detail"].lower() and "fee" in f["detail"].lower()
    assert f["evidence"]["transfer_fee_estimate"]


def test_findings_accumulate_rather_than_being_recomputed(conn, accounts):
    """The whole reason this is a table and not a query."""
    monthly(conn, "STREAMFLIX", [9.99] * 6 + [15.99] * 6, TODAY - timedelta(days=30 * 12), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    conn.commit()

    first = research.run(conn)
    assert first["new"] >= 1 and first["still_true"] == 0

    again = research.run(conn)
    assert again["new"] == 0 and again["still_true"] >= 1
    row = conn.execute("SELECT times_seen, first_seen FROM findings LIMIT 1").fetchone()
    assert row["times_seen"] == 2 and row["first_seen"] == TODAY


def test_something_dismissed_is_never_raised_again(conn, accounts):
    """Being told again about something you already decided against is how a
    useful list becomes noise somebody stops reading."""
    monthly(conn, "STREAMFLIX", [9.99] * 6 + [15.99] * 6, TODAY - timedelta(days=30 * 12), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    conn.commit()
    research.run(conn)

    conn.execute("UPDATE findings SET status = 'dismissed'")
    conn.commit()
    research.run(conn)
    assert conn.execute("SELECT status FROM findings LIMIT 1").fetchone()["status"] == "dismissed"
    assert research.listing(conn, "open")["findings"] == []


def test_something_that_stops_being_true_expires_rather_than_lingering(conn, accounts):
    monthly(conn, "STREAMFLIX", [9.99] * 6 + [15.99] * 6, TODAY - timedelta(days=30 * 12), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    conn.commit()
    research.run(conn)
    assert research.listing(conn)["open"] >= 1

    conn.execute("DELETE FROM transactions")
    conn.commit()
    out = research.run(conn)
    assert out["expired"] >= 1
    # Kept as history: "this used to be a problem" is worth being able to see.
    assert conn.execute("SELECT count(*) AS n FROM findings").fetchone()["n"] >= 1
    assert research.listing(conn, "open")["findings"] == []


def test_what_was_actually_saved_is_recorded(conn, accounts):
    """Without this the app can claim it saves money and never has to prove it."""
    conn.execute("""INSERT INTO findings (kind, fingerprint, title, detail, annual_saving)
                    VALUES ('x','f1','t','d', 120)""")
    fid = conn.execute("SELECT id FROM findings").fetchone()["id"]
    conn.execute("UPDATE findings SET status = 'acted' WHERE id = %s", (fid,))
    conn.execute("INSERT INTO finding_outcomes (finding_id, saved, note) VALUES (%s, 96, 'got a discount')",
                 (fid,))
    conn.commit()
    listing = research.listing(conn, "all")
    assert listing["actually_saved"] == D("96.00") and listing["acted"] == 1


# ---------------------------------------------------------------- looking backwards

def test_year_over_year_compares_the_same_dates(conn, accounts):
    """September against a whole year is not a comparison, it is a smaller
    number -- and an app that reports 'spending down 68%' every January has
    taught its user to ignore it."""
    today = date(2026, 9, 17)
    # Same span both years, plus a Q4 chunk last year that must NOT be counted.
    spend(conn, "a", "SHOP", 1000, date(2026, 3, 1))
    spend(conn, "b", "SHOP", 800, date(2025, 3, 1))
    spend(conn, "c", "SHOP", 5000, date(2025, 11, 1))
    conn.commit()

    y = trends.year_over_year(conn, today=today)
    assert y["spent"] == D("1000.00")
    assert y["spent_before"] == D("800.00")        # not 5800
    assert y["last_year"]["to"] == date(2025, 9, 17)
    assert round(y["spent_percent"], 3) == 0.25


def test_a_leap_day_does_not_break_the_comparison(conn, accounts):
    conn.commit()
    y = trends.year_over_year(conn, today=date(2028, 2, 29))
    assert y["last_year"]["to"] == date(2027, 2, 28)


def test_a_tiny_swing_is_not_reported_as_a_trend(conn, accounts):
    """A 300% rise on $12 is arithmetic on noise."""
    today = date(2026, 9, 17)
    spend(conn, "a", "SHOP", 48, date(2026, 3, 1))
    spend(conn, "b", "SHOP", 12, date(2025, 3, 1))
    conn.commit()
    y = trends.year_over_year(conn, today=today)
    shopping = next(c for c in y["categories"] if c["category"] == "shopping")
    assert shopping["percent"] == 3.0 and shopping["material"] is False
    assert shopping not in y["risen"]


def test_no_prior_year_says_so_instead_of_comparing_against_nothing(conn, accounts):
    spend(conn, "a", "SHOP", 100, date(2026, 3, 1))
    conn.commit()
    assert trends.year_over_year(conn, today=date(2026, 9, 17))["comparable"] is False


def test_a_partial_year_is_labelled(conn, accounts):
    """A half year drawn next to whole ones reads as a collapse in spending."""
    spend(conn, "a", "SHOP", 100, date(2025, 2, 1))
    spend(conn, "b", "SHOP", 100, date(2025, 11, 1))
    spend(conn, "c", "SHOP", 100, TODAY)
    conn.commit()
    by_year = {y["year_number"]: y for y in trends.years(conn)}
    assert by_year[TODAY.year]["partial"] is True      # still running
    assert by_year[2025]["partial"] is True            # history starts in February


def test_the_annual_review_includes_what_the_year_cost_to_carry(conn, accounts):
    """A review that shows where the money went but not what carrying it cost
    is a highlight reel."""
    spend(conn, "a", "RENT", 2000, date(2026, 1, 5),
          primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT")
    spend(conn, "b", "INTEREST CHARGE", 58.98, date(2026, 2, 5),
          primary="BANK_FEES", detailed="BANK_FEES_INTEREST_CHARGE")
    spend(conn, "c", "OVERDRAFT FEE", 35, date(2026, 3, 5),
          primary="BANK_FEES", detailed="BANK_FEES_OVERDRAFT_FEES")
    conn.commit()

    r = trends.annual_review(conn, 2026)
    assert r["spent"] == D("2093.98")
    assert r["cost_of_carrying"]["fees"] == D("93.98") and r["cost_of_carrying"]["count"] == 2
    assert r["cost_of_carrying"]["interest"] == D("58.98")
    assert r["biggest_single"]["name"] == "Rent"
    assert r["categories"][0]["label"] == "Rent & mortgage"


def test_lifetime_merchant_totals(conn, accounts):
    for i in range(5):
        spend(conn, f"m{i}", "COSTCO", 120, TODAY - timedelta(days=40 * i))
    conn.commit()
    top = trends.merchants(conn)[0]
    assert top["name"] == "Costco" and top["total"] == D("600.00")
    assert top["times"] == 5 and top["average"] == D("120.00")


# ---------------------------------------------------------------- getting out

def test_a_cancel_script_expects_the_offers(conn, accounts):
    """The retention ladder is the advantage: the first offer is never the last."""
    script = bills.cancel_script("Streamflix", D("15.99"), 18)
    assert "cancel my subscription" in script
    for rung in bills.RETENTION_LADDER:
        assert rung in script
    assert "reference number" in script


def test_the_card_script_leads_with_a_product_change_not_a_closure(conn, accounts):
    """Closing shortens your history and drops your total limit, which moves
    utilisation the wrong way the same day."""
    script = bills.cancel_card_script("Rewards Card", D("95"))
    assert script.index("product change") < script.index("clos")
    assert "utilisation" in script


def test_every_recurring_charge_gets_a_way_out(conn, accounts):
    monthly(conn, "STREAMFLIX", [15.99] * 12, TODAY - timedelta(days=30 * 12), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    monthly(conn, "CITY POWER", [140.00] * 12, TODAY - timedelta(days=30 * 12), "pw",
            primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_GAS_AND_ELECTRICITY")
    conn.commit()

    monthly(conn, "HARBOURSIDE LETTINGS", [1875.00] * 12, TODAY - timedelta(days=30 * 12), "rt",
            primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT")
    conn.commit()

    help_ = bills.cancellation_help(conn)
    names = {s["name"]: s for s in help_["subscriptions"]}
    assert {"Streamflix", "City Power", "Harbourside Lettings"} <= set(names)

    # Cancellable: both scripts.
    assert names["Streamflix"]["cancel_script"] and names["Streamflix"]["cancel_email"]
    assert names["Streamflix"]["paid_so_far"] == D("191.88")

    # Negotiable but not cancellable: the letter, not the cancellation. Utilities
    # do not do retention offers, but they do have programmes.
    assert names["City Power"]["lower_email"] and not names["City Power"]["cancel_script"]

    # Neither: listed so the total is the real one, and said so.
    rent = names["Harbourside Lettings"]
    assert not rent["cancel_script"] and not rent["lower_email"]
    assert "total is the real one" in rent["note"]
    # And it still counts toward what the recurring charges actually cost.
    assert help_["monthly_total"] > D("2000")
    assert help_["tips"] and help_["ladder"]


def test_the_totals_are_scoped_like_the_rows(conn, accounts):
    """A header that counts somebody else's findings while the list below
    cannot show them is the privacy rule leaking through a total."""
    from tally import people
    sam = people.create(conn, "Sam", "sam", "password123", role="member")
    alex = people.create(conn, "Alex", "alex", "password123", role="owner")
    conn.execute("""INSERT INTO findings (kind, fingerprint, title, detail, annual_saving, owner_id)
                    VALUES ('x','mine','Mine','d', 100, %s),
                           ('x','theirs','Theirs','d', 500, %s),
                           ('x','shared','Shared','d', 50, NULL)""", (alex["id"], sam["id"]))
    conn.commit()

    conn.execute("SELECT set_config('tally.viewer', %s, true)", (str(alex["id"]),))
    seen = research.listing(conn, "open")
    assert sorted(f["title"] for f in seen["findings"]) == ["Mine", "Shared"]
    assert seen["open"] == 2
    assert seen["on_the_table"] == D("150.00")      # not 650


def test_rent_is_not_offered_as_a_subscription_to_cancel(conn, accounts):
    """True, useless, and loud enough to bury the findings that are neither."""
    monthly(conn, "HARBOURSIDE LETTINGS", [1875.00] * 12, TODAY - timedelta(days=30 * 12), "rent",
            primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_RENT")
    monthly(conn, "CAPITAL ONE AUTO", [389.00] * 12, TODAY - timedelta(days=30 * 12), "auto",
            primary="LOAN_PAYMENTS", detailed="LOAN_PAYMENTS_CAR_PAYMENT")
    monthly(conn, "STREAMFLIX", [15.99] * 12, TODAY - timedelta(days=30 * 12), "sf",
            primary="ENTERTAINMENT", detailed="ENTERTAINMENT_OTHER")
    conn.commit()

    names = {f["title"] for f in research.evaluate(conn) if f["kind"] == "long_running"}
    assert any("Streamflix" in n for n in names)
    assert not any("Harbourside" in n or "Capital One" in n for n in names)


def test_a_rise_on_a_bill_gets_the_letter_not_the_cancellation(conn, accounts):
    """You cannot cancel the electricity. You can ask what rate you are on."""
    monthly(conn, "CITY POWER WEB PAYMENT", [106.41] * 6 + [188.13] * 6,
            TODAY - timedelta(days=30 * 12), "citypower",
            primary="RENT_AND_UTILITIES", detailed="RENT_AND_UTILITIES_GAS_AND_ELECTRICITY")
    conn.commit()

    creep = next(f for f in research.evaluate(conn) if f["kind"] == "price_creep")
    assert "Subject: Reviewing my plan" in creep["action"]
    assert "cancel my subscription" not in creep["action"]


def test_history_that_starts_mid_year_is_not_comparable_to_last_year(conn, accounts):
    """The window is the same dates, and it is empty. Comparing against an
    empty window reports +100% on everything, which is the same dates and still
    nonsense."""
    spend(conn, "a", "SHOP", 100, date(2025, 10, 15))   # history begins in October
    spend(conn, "b", "SHOP", 400, date(2026, 3, 1))
    conn.commit()

    y = trends.year_over_year(conn, today=date(2026, 9, 17))
    assert y["comparable"] is False
    assert y["history_starts"] == date(2025, 10, 15)


def test_a_full_prior_year_is_comparable(conn, accounts):
    spend(conn, "a", "SHOP", 100, date(2025, 3, 1))
    spend(conn, "b", "SHOP", 400, date(2026, 3, 1))
    conn.commit()
    assert trends.year_over_year(conn, today=date(2026, 9, 17))["comparable"] is True
