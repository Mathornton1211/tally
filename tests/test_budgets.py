"""Budgets: one row keeps applying, rollover carries, and the month is judged
while it is still running rather than after it is over."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import budgets

D = Decimal
JAN, FEB, MAR = date(2026, 1, 1), date(2026, 2, 1), date(2026, 3, 1)


@pytest.fixture
def acct(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('a',1,'plaid','Checking','depository','checking',500)
                    ON CONFLICT DO NOTHING""")
    return "a"


def spend(conn, acct, amount, when, detailed="FOOD_AND_DRINK_GROCERIES",
          primary="FOOD_AND_DRINK", name="STORE", tid=None):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
           VALUES (%s,%s,%s,%s,%s,%s,%s,'{}')""",
        (tid or f"t{when}{amount}{name}", acct, amount, when, name, primary, detailed))


def budget(conn, category="groceries", month=JAN, amount="500", rollover=False):
    conn.execute("INSERT INTO budgets (category, month, amount, rollover) VALUES (%s,%s,%s,%s)",
                 (category, month, amount, rollover))


def cat(s, key="groceries"):
    return next(c for c in s["categories"] if c["category"] == key)


# ---------------------------------------------------------------- the amount in force

def test_one_row_keeps_applying_to_later_months(conn, acct):
    budget(conn, month=JAN, amount="500")
    conn.commit()
    for m in (JAN, FEB, MAR):
        assert cat(budgets.status(conn, m, today=date(2026, 4, 1)))["amount"] == D("500.00")


def test_a_later_row_replaces_it_without_rewriting_history(conn, acct):
    budget(conn, month=JAN, amount="500")
    budget(conn, month=MAR, amount="900")
    conn.commit()
    today = date(2026, 4, 1)
    assert cat(budgets.status(conn, JAN, today=today))["amount"] == D("500.00")
    assert cat(budgets.status(conn, FEB, today=today))["amount"] == D("500.00")
    # March's change does not make January retroactively a $900 month.
    assert cat(budgets.status(conn, MAR, today=today))["amount"] == D("900.00")


# ---------------------------------------------------------------- rollover

def test_leftover_carries_forward_only_with_rollover_on(conn, acct):
    budget(conn, month=JAN, amount="500", rollover=True)
    spend(conn, acct, 300, JAN)
    conn.commit()

    feb = cat(budgets.status(conn, FEB, today=MAR))
    assert feb["carry_in"] == D("200.00")           # 500 budgeted, 300 spent
    assert feb["available"] == D("700.00")

    conn.execute("UPDATE budgets SET rollover = false")
    conn.commit()
    assert cat(budgets.status(conn, FEB, today=MAR))["available"] == D("500.00")


def test_an_overspend_carries_forward_too(conn, acct):
    """Rollover that only ever hands out money is a slot machine, not a budget."""
    budget(conn, month=JAN, amount="500", rollover=True)
    spend(conn, acct, 620, JAN)
    conn.commit()
    feb = cat(budgets.status(conn, FEB, today=MAR))
    assert feb["carry_in"] == D("-120.00")
    assert feb["available"] == D("380.00")


def test_rollover_does_not_invent_a_balance_for_unbudgeted_months(conn, acct):
    """Turning rollover on in March does not gift three months of unspent
    budget for a category that had no budget until then."""
    budget(conn, month=MAR, amount="500", rollover=True)
    conn.commit()
    assert cat(budgets.status(conn, MAR, today=MAR))["carry_in"] == D("0.00")


# ---------------------------------------------------------------- the running month

def test_committed_recurring_is_subtracted_from_what_is_left(conn, acct):
    """The subscription that has not hit yet is not spending money you have."""
    today = date(2026, 1, 10)
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 100, date(2026, 1, 5))
    conn.commit()

    class Stream:                                   # what detect_recurring yields
        kind, active, category = "expense", True, "groceries"
        cadence, interval_days = "monthly", 30.4
        last_date, next_date = date(2025, 12, 21), date(2026, 1, 20)
        typical_amount, name, logo_url = D("60"), "Milk box", None

    s = budgets.status(conn, JAN, today=today, streams=[Stream()])
    c = cat(s)
    assert c["spent"] == D("100.00") and c["committed"] == D("60.00")
    assert c["remaining"] == D("400.00")
    assert c["left_after_commitments"] == D("340.00")
    assert c["upcoming"][0]["name"] == "Milk box"


def test_projection_counts_a_bill_that_has_not_landed_yet(conn, acct):
    """Ten quiet days then a $400 bill due on the 20th: a plain run-rate
    projection calls the month cheap right up until it is not."""
    today = date(2026, 1, 10)
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 30, date(2026, 1, 2))
    conn.commit()

    class Stream:
        kind, active, category = "expense", True, "groceries"
        cadence, interval_days = "monthly", 30.4
        last_date, next_date = date(2025, 12, 21), date(2026, 1, 20)
        typical_amount, name, logo_url = D("400"), "Big bill", None

    c = cat(budgets.status(conn, JAN, today=today, streams=[Stream()]))
    # 30 spent + 400 still due + 30/10 a day across the remaining 21 days.
    assert c["projected"] == D("493.00")            # not 30/10*31 = 93
    assert c["state"] == "under"                    # still fits inside 500


def test_a_bill_already_paid_is_not_extrapolated(conn, acct):
    """Rent goes out on the 1st. Multiplying it by the month is how a budget
    app decides a category that is exactly on target is heading for trouble."""
    today = date(2026, 1, 17)
    conn.execute("INSERT INTO budgets (category, month, amount) VALUES ('rent', %s, 2150)", (JAN,))
    spend(conn, acct, 2150, date(2026, 1, 1), detailed="RENT_AND_UTILITIES_RENT",
          primary="RENT_AND_UTILITIES", name="LANDLORD")
    conn.commit()

    class Stream:
        kind, active, category = "expense", True, "rent"
        cadence, interval_days = "monthly", 30.4
        last_date, next_date = date(2026, 1, 1), date(2026, 1, 31)
        typical_amount, name, logo_url = D("2150"), "Landlord", None

    c = cat(budgets.status(conn, JAN, today=today, streams=[Stream()]), "rent")
    assert c["spent"] == D("2150.00")
    assert c["projected"] == D("2150.00")           # not 2150/17*31 = 3921
    assert c["state"] == "under"


def test_pace_flags_a_category_heading_over(conn, acct):
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 300, date(2026, 1, 8))
    conn.commit()
    c = cat(budgets.status(conn, JAN, today=date(2026, 1, 10)))
    assert c["projected"] == D("930.00")             # 300/10 * 31
    assert c["state"] == "watch"
    assert c["per_day"] == D("9.52")                 # 200 left over 21 days


def test_already_over_beats_on_pace(conn, acct):
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 560, date(2026, 1, 8))
    conn.commit()
    assert cat(budgets.status(conn, JAN, today=date(2026, 1, 10)))["state"] == "over"


def test_a_finished_month_has_no_pace_or_commitments(conn, acct):
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 300, date(2026, 1, 8))
    conn.commit()
    s = budgets.status(conn, JAN, today=MAR)
    assert not s["current"] and s["days_left"] == 0
    assert cat(s)["committed"] == D("0.00") and cat(s)["projected"] == D("300.00")


# ---------------------------------------------------------------- the leak

def test_spending_with_no_budget_behind_it_is_named(conn, acct):
    budget(conn, month=JAN, amount="500")
    spend(conn, acct, 100, date(2026, 1, 5))
    spend(conn, acct, 75, date(2026, 1, 6), detailed="ENTERTAINMENT_OTHER",
          primary="ENTERTAINMENT", name="CINEMA")
    conn.commit()
    s = budgets.status(conn, JAN, today=date(2026, 1, 20))
    assert [u["category"] for u in s["unbudgeted"]] == ["entertainment"]
    assert s["unbudgeted_spent"] == D("75.00")
    assert s["spent"] == D("100.00") and s["total_spent"] == D("175.00")


# ---------------------------------------------------------------- suggestions

def test_suggestions_use_the_median_of_complete_months(conn, acct):
    for m, amount in ((date(2026, 1, 5), 380), (date(2026, 2, 5), 412), (date(2026, 3, 5), 990)):
        spend(conn, acct, amount, m)
    # The current, half-finished month must not drag the suggestion down.
    spend(conn, acct, 40, date(2026, 4, 2))
    conn.commit()

    s = next(x for x in budgets.suggest(conn, months=3, today=date(2026, 4, 10))
             if x["category"] == "groceries")
    assert s["median"] == D("412.00")                # not the 445.5 mean, not the 40
    assert s["amount"] == D("410")                   # rounded to something sayable
    assert s["worst"] == D("990.00") and s["months"] == 3


def test_tiny_categories_are_not_suggested(conn, acct):
    spend(conn, acct, 4, date(2026, 1, 5))
    spend(conn, acct, 6, date(2026, 2, 5))
    conn.commit()
    assert budgets.suggest(conn, months=3, today=date(2026, 3, 10)) == []


def test_lumpy_categories_are_suggested_with_rollover_on(conn, acct):
    spend(conn, acct, 300, date(2026, 1, 5), detailed="HOME_IMPROVEMENT_OTHER",
          primary="HOME_IMPROVEMENT", name="HARDWARE")
    spend(conn, acct, 200, date(2026, 2, 5), detailed="HOME_IMPROVEMENT_OTHER",
          primary="HOME_IMPROVEMENT", name="HARDWARE")
    conn.commit()
    s = next(x for x in budgets.suggest(conn, months=3, today=date(2026, 3, 10))
             if x["category"] == "home")
    assert s["rollover"] is True


def test_suggestions_say_what_is_already_budgeted(conn, acct):
    budget(conn, month=JAN, amount="500")
    for m in (date(2026, 1, 5), date(2026, 2, 5)):
        spend(conn, acct, 400, m)
    conn.commit()
    s = next(x for x in budgets.suggest(conn, months=3, today=date(2026, 3, 10))
             if x["category"] == "groceries")
    assert s["already_budgeted"] is True


# ---------------------------------------------------------------- alerts

def test_over_and_on_pace_raise_one_alert_each(conn, acct):
    today = date.today().replace(day=10)
    budget(conn, category="groceries", month=budgets.month_start(today), amount="500")
    budget(conn, category="dining", month=budgets.month_start(today), amount="200")
    spend(conn, acct, 560, today - timedelta(days=2))
    spend(conn, acct, 150, today - timedelta(days=1), detailed="FOOD_AND_DRINK_RESTAURANT",
          primary="FOOD_AND_DRINK", name="DINER")
    conn.commit()

    got = {a["kind"]: a for a in budgets.alerts(conn, today=today, streams=[])}
    assert "budget_over" in got and "budget_pace" in got
    assert "$60.00 over budget" in got["budget_over"]["title"]
    assert got["budget_pace"]["category"] == "dining"
    assert got["budget_pace"]["fingerprint"] == f"budget_pace:dining:{today:%Y-%m}"


def test_a_finished_month_raises_nothing(conn, acct):
    budget(conn, month=JAN, amount="100")
    spend(conn, acct, 400, date(2026, 1, 8))
    conn.commit()
    assert budgets.alerts(conn, today=MAR, streams=[]) == []


def test_a_monthly_bill_lands_once_in_a_31_day_month(conn, acct):
    """30.4 days rounded to 30 fits twice inside January. Stepping a monthly
    bill by calendar months instead is the difference between $2,150 of rent
    and $4,300 of it."""
    class Rent:
        kind, active, category = "expense", True, "rent"
        cadence, interval_days = "monthly", 30.4
        last_date, next_date = date(2026, 1, 1), date(2026, 1, 31)
        typical_amount, name, logo_url = D("2150"), "Landlord", None

    totals, _ = budgets.upcoming([Rent()], date(2026, 1, 1), date(2026, 1, 31))
    assert totals["rent"] == D("2150.00")

    # A weekly stream still steps in days, and January really does hold five.
    class Gym:
        kind, active, category = "expense", True, "health"
        cadence, interval_days = "weekly", 7.0
        last_date, next_date = date(2026, 1, 2), date(2026, 1, 9)
        typical_amount, name, logo_url = D("10"), "Gym", None

    totals, _ = budgets.upcoming([Gym()], date(2026, 1, 1), date(2026, 1, 31))
    assert totals["health"] == D("50.00")


def test_a_bill_due_at_month_end_is_not_borrowed_from_next_month(conn, acct):
    """January 31 is in January; February 1 is not."""
    class Sub:
        kind, active, category = "expense", True, "entertainment"
        cadence, interval_days = "monthly", 30.4
        last_date, next_date = date(2025, 12, 31), date(2026, 1, 30)
        typical_amount, name, logo_url = D("12"), "Streaming", None

    jan, _ = budgets.upcoming([Sub()], date(2026, 1, 1), date(2026, 1, 31))
    feb, _ = budgets.upcoming([Sub()], date(2026, 2, 1), date(2026, 2, 28))
    assert jan["entertainment"] == D("12.00") and feb["entertainment"] == D("12.00")


def test_a_category_the_bills_alone_blow_says_so(conn, acct):
    """"$0.00 a day keeps it inside" is false when what is still due is more
    than what is left. Telling someone to be careful cannot fix that."""
    today = date.today().replace(day=10)
    m = budgets.month_start(today)
    conn.execute("INSERT INTO budgets (category, month, amount) VALUES ('fees', %s, 65)", (m,))
    spend(conn, acct, 38, today - timedelta(days=1), detailed="BANK_FEES_INTEREST_CHARGE",
          primary="BANK_FEES", name="INTEREST")
    conn.commit()

    class Interest:
        kind, active, category = "expense", True, "fees"
        cadence, interval_days = "monthly", 30.4
        last_date = m.replace(day=24) - timedelta(days=30)
        next_date = m.replace(day=24)
        typical_amount, name, logo_url = D("56.65"), "Interest Charge", None

    a = next(x for x in budgets.alerts(conn, today=today, streams=[Interest()])
             if x["kind"] == "budget_pace")
    assert "$0.00 a day" not in a["detail"]
    assert "bigger budget" in a["detail"]
