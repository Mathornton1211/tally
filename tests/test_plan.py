"""Payoff and runway math. Every expectation here is checkable by hand."""
from datetime import date, timedelta
from decimal import Decimal

from tally import plan
from tally.sync import _pick_apr

D = Decimal
TODAY = date(2026, 9, 17)


def card(name, balance, apr, minimum, limit=None, due=None, overdue=False, kind="credit"):
    return plan.Debt(account_id=name.lower(), name=name, mask="0000", kind=kind, balance=D(str(balance)),
                     apr=D(str(apr)) if apr is not None else None, apr_source="issuer",
                     minimum=D(str(minimum)), minimum_source="issuer", due_date=due, is_overdue=overdue,
                     credit_limit=D(str(limit)) if limit else None)


# ---------------------------------------------------------------- payoff

def test_single_card_matches_hand_calculation():
    """$1,000 at 12% APR, $100 a month.

    Month 1: interest 1000 * 0.01 = $10.00, balance 1010, pay 100 -> 910.
    Month 2: interest 9.10 -> 919.10, pay 100 -> 819.10.
    """
    p = plan.simulate([card("A", 1000, 12, 100)], D(0), "avalanche", TODAY)
    assert p.balances[0]["balance"] == D("910.00")
    assert p.balances[1]["balance"] == D("819.10")
    assert p.months == 11
    assert p.total_interest == D("58.98")   # checked against an independent loop


def test_zero_interest_is_just_division():
    p = plan.simulate([card("A", 1200, 0, 100)], D(0), "avalanche", TODAY)
    assert p.months == 12 and p.total_interest == D("0.00")


def test_extra_payment_shortens_and_saves():
    debts = [card("Big", 6000, 26.99, 180), card("Small", 1500, 19.99, 45)]
    base = plan.simulate(debts, D(0), "minimums", TODAY)
    with_extra = plan.simulate(debts, D(300), "avalanche", TODAY)
    assert with_extra.months < base.months
    assert with_extra.total_interest < base.total_interest
    assert with_extra.monthly_payment == D("525.00")  # 180 + 45 + 300


def test_avalanche_targets_the_highest_rate_and_snowball_the_smallest():
    debts = [card("Big", 6000, 19.99, 180), card("Small", 1500, 26.99, 45)]
    ava = plan.simulate(debts, D(200), "avalanche", TODAY)
    snow = plan.simulate(debts, D(200), "snowball", TODAY)
    assert ava.order[0]["name"] == "Small"     # higher rate, also smaller here
    assert snow.order[0]["name"] == "Small"
    debts2 = [card("Big", 6000, 26.99, 180), card("Small", 1500, 19.99, 45)]
    assert plan.simulate(debts2, D(200), "avalanche", TODAY).order[0]["name"] == "Big"
    assert plan.simulate(debts2, D(200), "snowball", TODAY).order[0]["name"] == "Small"


def test_avalanche_never_costs_more_than_snowball():
    debts = [card("A", 4000, 28.99, 120), card("B", 900, 14.99, 35), card("C", 2500, 22.99, 75)]
    ava = plan.simulate(debts, D(250), "avalanche", TODAY)
    snow = plan.simulate(debts, D(250), "snowball", TODAY)
    assert ava.total_interest <= snow.total_interest
    assert ava.months and snow.months


def test_freed_minimum_rolls_into_the_next_debt():
    """After the first card clears, its minimum is not lost: the monthly total
    stays the same, which is what makes a payoff plan accelerate."""
    debts = [card("A", 500, 20, 50), card("B", 3000, 20, 90)]
    p = plan.simulate(debts, D(100), "snowball", TODAY)
    assert p.monthly_payment == D("240.00")
    # A: 500 at 20%, paid 50 min + 100 extra = 150/month, so gone in month 4.
    first_gone = p.order[0]["paid_off_month"]
    assert first_gone == 4
    # Same total payment every month, so the whole 240 lands on B afterwards.
    drops = [p.balances[i]["balance"] - p.balances[i + 1]["balance"] for i in range(first_gone, len(p.balances) - 1)]
    assert all(x > D("180") for x in drops)


def test_minimum_that_cannot_beat_interest_is_reported_not_silently_wrong():
    # $8,000 at 29.99% accrues ~$200/month; a $150 minimum never catches up.
    p = plan.simulate([card("Stuck", 8000, 29.99, 150)], D(0), "minimums", TODAY)
    assert p.months is None and p.payoff_date is None
    assert p.stalled == ["Stuck"]


def test_unknown_rate_sorts_last_in_avalanche():
    debts = [card("Known", 2000, 18, 60), card("Unknown", 3000, None, 90)]
    p = plan.simulate(debts, D(100), "avalanche", TODAY)
    assert [o["name"] for o in p.order] == ["Known", "Unknown"]


def test_payoff_date_counts_from_the_start_month():
    p = plan.simulate([card("A", 1000, 0, 100)], D(0), "avalanche", date(2026, 9, 17))
    assert p.months == 10 and p.payoff_date == date(2027, 7, 17)


def test_assumed_minimum_covers_interest_plus_principal():
    m = plan.assumed_minimum(D("6000"), D("29.99"))
    interest = D("6000") * D("29.99") / D(1200)
    assert m > interest          # or the balance would never move
    assert plan.assumed_minimum(D(0), D(20)) == D(0)


# ---------------------------------------------------------------- APR choice

def test_apr_picks_the_rate_that_applies_to_the_carried_balance():
    aprs = [{"apr_type": "purchase_apr", "apr_percentage": 24.99, "balance_subject_to_apr": 0},
            {"apr_type": "balance_transfer_apr", "apr_percentage": 0, "balance_subject_to_apr": 1500}]
    assert _pick_apr(aprs, None) == 0.0
    assert _pick_apr([{"apr_type": "purchase_apr", "apr_percentage": 19.5}], None) == 19.5
    assert _pick_apr([], None) is None


# ---------------------------------------------------------------- runway (db)

def seed_cash(conn, checking=500, spend_per_day=20, days=60):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('ins', 'Bank') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc) "
                 "VALUES (1, 'it', 'ins', 'x') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance, available_balance)
                    VALUES ('chk', 1, 'Checking', 'depository', 'checking', %s, %s)
                    ON CONFLICT (id) DO UPDATE SET current_balance = EXCLUDED.current_balance""",
                 (checking, checking))
    for i in range(days):
        d = date.today() - timedelta(days=i + 1)
        conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
                        VALUES (%s, 'chk', %s, %s, 'STORE', 'FOOD_AND_DRINK', 'FOOD_AND_DRINK_GROCERIES', '{}')""",
                     (f"t{i}", spend_per_day, d))
    conn.commit()


def test_runway_counts_everyday_spending_not_just_bills(conn):
    seed_cash(conn, checking=600, spend_per_day=20)
    rw = plan.runway(conn)
    assert rw["cash"] == D("600.00")
    assert rw["daily_spending"] == D("20.00")
    assert rw["days_until_zero"] == 30        # 600 / 20, no bills in this fixture
    assert rw["income_expected"] is False


def test_runway_flags_the_payment_it_cannot_cover(conn):
    seed_cash(conn, checking=300, spend_per_day=5)
    due = date.today() + timedelta(days=5)
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance, credit_limit)
                    VALUES ('card', 1, 'Card', 'credit', 'credit card', 4000, 5000)
                    ON CONFLICT (id) DO NOTHING""")
    conn.execute("""INSERT INTO liabilities (account_id, kind, apr, minimum_payment, next_due_date, is_overdue, source)
                    VALUES ('card', 'credit', 24.99, 500, %s, false, 'demo')
                    ON CONFLICT (account_id) DO UPDATE SET minimum_payment = 500""", (due,))
    conn.commit()
    rw = plan.runway(conn)
    assert any(s["name"].startswith("Card") and s["amount"] == D("500.00") for s in rw["shortfalls"])
    ds = plan.debts(conn)
    assert plan.mode(conn, rw, ds)["mode"] == "survival"


def test_overdue_payment_appears_today_and_sets_survival(conn):
    seed_cash(conn, checking=5000, spend_per_day=1)
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance, credit_limit)
                    VALUES ('card', 1, 'Card', 'credit', 'credit card', 1000, 5000)
                    ON CONFLICT (id) DO NOTHING""")
    conn.execute("""INSERT INTO liabilities (account_id, kind, apr, minimum_payment, next_due_date, is_overdue, source)
                    VALUES ('card', 'credit', 19.99, 40, %s, true, 'demo')
                    ON CONFLICT (account_id) DO NOTHING""", (date.today() - timedelta(days=4),))
    conn.commit()
    rw = plan.runway(conn)
    assert rw["events"][0]["kind"] == "overdue" and rw["events"][0]["date"] == date.today()
    assert plan.mode(conn, rw, plan.debts(conn))["mode"] == "survival"


def test_growth_mode_when_no_cards_and_cash_lasts(conn):
    seed_cash(conn, checking=20000, spend_per_day=10)
    rw = plan.runway(conn)
    assert plan.mode(conn, rw, plan.debts(conn))["mode"] == "growth"


def test_python_and_postgres_agree_on_what_day_it_is(conn):
    """The app asks Python for today in some places and Postgres in others.
    A server in UTC and a household in California disagree for seven hours out
    of every twenty-four -- long enough to move a transaction into the wrong
    month, short enough that nobody notices for weeks.
    """
    from datetime import date as _date

    # The conn fixture configures the session the way tally/db.pool does.
    assert conn.execute("SELECT current_date").fetchone()["current_date"] == _date.today()
    # And a fixed offset is not a usable fallback. Postgres accepts the string,
    # SHOW reports it back, and the behaviour is UTC regardless -- a wrong
    # answer wearing the shape of a right one, which is why db.session_timezone
    # insists on a real IANA name.
    conn.execute("SELECT set_config('TimeZone', %s, false)", ("-07:00",))
    assert (conn.execute("SELECT now()").fetchone()["now"].utcoffset().total_seconds() == 0)
