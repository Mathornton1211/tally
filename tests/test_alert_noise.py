"""Whether an alert has earned the right to interrupt somebody.

Every rule here was already true. What they lacked was a meaningful baseline
and a reason to still matter, and without those the page reached 44 urgent
items of which seven were real -- which is worse than no alerts, because the
reversible fee sitting in the pile never gets called about.
"""
from datetime import date, timedelta
from decimal import Decimal

from tally import monitor

D = Decimal
TODAY = date(2026, 9, 17)


def txn(tid, name, amount, when, account="card", category="shopping", kind="expense",
        pending=False, institution="Bank"):
    return {
        "id": tid, "date": when, "amount": D(str(amount)), "pending": pending,
        "name": name.upper(), "display_name": name, "merchant_key": name.lower(),
        "bank_text": name.upper(), "pfc_primary": "GENERAL_MERCHANDISE",
        "pfc_detailed": "GENERAL_MERCHANDISE_OTHER", "category": category, "kind": kind,
        "account_id": account, "account_name": "Card", "account_mask": "4417",
        "institution": institution,
    }


def fire(rows, history=None, streams=None, today=TODAY):
    return monitor.evaluate(rows, history if history is not None else rows,
                            streams or [], today=today)


def rules(alerts):
    return sorted(a["rule"] for a in alerts)


# ---------------------------------------------------------------- the usual

def test_a_merchant_with_no_usual_price_cannot_have_an_outlier():
    """Shell: a packet of crisps and a tank of fuel. The median is meaningless,
    so 3.8x the median is meaningless too."""
    history = [txn(f"h{i}", "Shell", a, TODAY - timedelta(days=60 - i * 5), category="auto")
               for i, a in enumerate([8, 62, 14, 71, 9, 55, 12, 68])]
    charge = txn("new", "Shell", 78, TODAY - timedelta(days=2), category="auto")
    assert "amount_outlier" not in rules(fire([charge], history + [charge]))


def test_a_merchant_that_always_charges_the_same_trips_at_once():
    """The other side of it: a spread near zero means anything unusual is."""
    history = [txn(f"h{i}", "Streamflix", "15.99", TODAY - timedelta(days=60 - i * 7))
               for i in range(8)]
    charge = txn("new", "Streamflix", "215.99", TODAY - timedelta(days=1))
    alerts = [a for a in fire([charge], history + [charge]) if a["rule"] == "amount_outlier"]
    assert len(alerts) == 1
    assert "215.99" in alerts[0]["detail"] or "215.99" in str(alerts[0]["inputs"]["amount"])


def test_a_usage_billed_service_does_not_trip_on_a_busy_month():
    """Anthropic, Digital Ocean: the amount is supposed to move."""
    history = [txn(f"h{i}", "Anthropic", a, TODAY - timedelta(days=200 - i * 30),
                   category="services")
               for i, a in enumerate([20, 45, 18, 90, 32, 120, 25])]
    charge = txn("new", "Anthropic", 210, TODAY - timedelta(days=3), category="services")
    assert "amount_outlier" not in rules(fire([charge], history + [charge]))


# ---------------------------------------------------------------- a busy day

def test_a_busy_saturday_is_not_a_burst_for_somebody_who_has_busy_saturdays():
    history = []
    for week in range(8):                       # eight Saturdays of nine charges
        day = TODAY - timedelta(days=60 - week * 7)
        history += [txn(f"h{week}-{i}", f"Shop {i}", 12, day) for i in range(9)]
    today_rows = [txn(f"t{i}", f"Shop {i}", 12, TODAY - timedelta(days=1)) for i in range(10)]
    assert "velocity" not in rules(fire(today_rows, history + today_rows))


def test_a_burst_well_above_that_persons_own_busiest_day_still_fires():
    history = []
    for week in range(8):
        day = TODAY - timedelta(days=60 - week * 7)
        history += [txn(f"h{week}-{i}", f"Shop {i}", 12, day) for i in range(2)]
    today_rows = [txn(f"t{i}", f"Shop {i}", 12, TODAY - timedelta(days=1)) for i in range(11)]
    alerts = [a for a in fire(today_rows, history + today_rows) if a["rule"] == "velocity"]
    assert len(alerts) == 1
    assert alerts[0]["inputs"]["personal_busiest"] == 2


# ---------------------------------------------------------------- card testing

def test_one_small_charge_at_a_new_shop_is_a_coffee():
    """It was the single biggest source of false fraud alerts, and the thing
    it describes is buying something small somewhere new."""
    rows = [txn("t1", "Some Cafe", "1.50", TODAY - timedelta(days=2), category="dining")]
    assert "card_testing" not in rules(fire(rows, rows))


def test_a_burst_of_tiny_charges_from_new_merchants_is_card_testing():
    rows = [txn("t1", "Odd Shop A", "0.99", TODAY - timedelta(days=2)),
            txn("t2", "Odd Shop B", "1.20", TODAY - timedelta(days=2)),
            txn("t3", "Odd Shop C", "1.75", TODAY - timedelta(days=1))]
    alerts = [a for a in fire(rows, rows) if a["rule"] == "card_testing"]
    assert len(alerts) == 1
    assert alerts[0]["severity"] == "high" and alerts[0]["inputs"]["pattern"] == "burst"


def test_a_tiny_charge_followed_by_a_big_one_is_card_testing():
    """The classic shape: check the card works, then use it."""
    rows = [txn("t1", "Odd Shop", "1.00", TODAY - timedelta(days=3)),
            txn("t2", "Electronics Co", "890.00", TODAY - timedelta(days=2))]
    alerts = [a for a in fire(rows, rows) if a["rule"] == "card_testing"]
    assert len(alerts) == 1 and alerts[0]["inputs"]["pattern"] == "followed"


# ---------------------------------------------------------------- still worth saying

def test_fraud_from_months_ago_is_history_not_a_to_do():
    """On a fresh install with two years of backfill, the difference between a
    page of history and a page of things to do."""
    old = TODAY - timedelta(days=90)
    rows = [txn("t1", "Odd Shop A", "0.99", old), txn("t2", "Odd Shop B", "1.20", old)]
    assert "card_testing" not in rules(fire(rows, rows))


def test_a_reversible_fee_from_months_ago_is_still_worth_a_call():
    """An issuer will still reverse it, and this is the rule that pays for the
    whole page."""
    fee = txn("f1", "Late Payment Fee", "40.00", TODAY - timedelta(days=80), category="fees")
    fee["pfc_detailed"] = "BANK_FEES_LATE_PAYMENT"
    fee["pfc_primary"] = "BANK_FEES"
    assert "reversible_fee" in rules(fire([fee], [fee]))


# ---------------------------------------------------------------- retirement

def test_an_alert_a_fixed_rule_no_longer_raises_is_retired(conn):
    """Otherwise a rule can be fixed and the page it was polluting stays
    polluted until somebody clicks every item."""
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('a',1,'plaid','Card','credit','credit card',0) ON CONFLICT DO NOTHING""")
    conn.execute(
        """INSERT INTO alerts (fingerprint, rule, severity, title, detail, inputs, txn_ids,
                               account_id, occurred_on)
           VALUES ('card_testing:ghost','card_testing','high','Old noise','d','{}','{}','a',
                   current_date - 5)""")
    conn.commit()

    out = monitor.scan(conn)
    assert out["retired"] == 1
    row = conn.execute("SELECT status, expired_reason FROM alerts").fetchone()
    # Expired, not dismissed: the app decided, not the person, and the two must
    # never be confused when somebody asks why they were not told.
    assert row["status"] == "expired" and "no longer" in row["expired_reason"]


def test_something_a_person_dismissed_is_left_exactly_as_they_left_it(conn):
    conn.execute("""INSERT INTO alerts (fingerprint, rule, severity, title, detail, inputs,
                                        txn_ids, occurred_on, status)
                    VALUES ('card_testing:mine','card_testing','high','t','d','{}','{}',
                            current_date - 5, 'dismissed')""")
    conn.commit()
    monitor.scan(conn)
    assert conn.execute("SELECT status FROM alerts").fetchone()["status"] == "dismissed"


def test_a_perishable_alert_that_got_old_is_retired_too(conn):
    """A rule fixed today does not reach back past its own window, so without
    this the alerts the old version raised stay open forever -- which is how a
    $1.00 coffee was still being called card testing three months later."""
    conn.execute(
        """INSERT INTO alerts (fingerprint, rule, severity, title, detail, inputs, txn_ids, occurred_on)
           VALUES ('card_testing:stale','card_testing','high','a coffee shop $1.00','d','{}','{}',
                   current_date - 90)""")
    conn.commit()
    assert monitor.scan(conn)["retired"] == 1
    row = conn.execute("SELECT status, expired_reason FROM alerts").fetchone()
    assert row["status"] == "expired" and row["expired_reason"] == "too old to act on"


def test_money_still_missing_is_not_quietly_closed_for_being_old(conn):
    """A duplicate charge and a reversible fee are the two most likely to be
    worth real money. Ageing them out would hide exactly those."""
    conn.execute(
        """INSERT INTO alerts (fingerprint, rule, severity, title, detail, inputs, txn_ids, occurred_on)
           VALUES ('duplicate_charge:old','duplicate_charge','medium','$300 twice at Target','d','{}','{}',
                   current_date - 200),
                  ('reversible_fee:old','reversible_fee','medium','Late fee $40','d','{}','{}',
                   current_date - 200)""")
    conn.commit()
    monitor.scan(conn)
    assert conn.execute(
        "SELECT count(*) AS n FROM alerts WHERE status = 'open'").fetchone()["n"] == 2


def test_a_reworded_rule_updates_the_alerts_it_already_raised(conn):
    """Otherwise a fixed rule keeps explaining itself in the sentence it was
    written with."""
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('a',1,'plaid','Card','credit','credit card',0) ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary,
                                              pfc_detailed, raw)
                    VALUES ('f1','a',40,current_date - 3,'LATE PAYMENT FEE','BANK_FEES',
                            'BANK_FEES_LATE_PAYMENT','{}')""")
    conn.commit()
    monitor.scan(conn)

    conn.execute("UPDATE alerts SET detail = 'the old wording' WHERE rule = 'reversible_fee'")
    conn.commit()
    out = monitor.scan(conn)
    assert out["refreshed"] >= 1
    assert conn.execute(
        "SELECT detail FROM alerts WHERE rule = 'reversible_fee'").fetchone()["detail"] != "the old wording"
