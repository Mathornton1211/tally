"""Funds: gift cards and store credit count toward one purchase and nothing else."""
from datetime import date, timedelta
from decimal import Decimal

from tally import funds

D = Decimal


def make_fund(conn, name="3D printer", target="599", target_date=None):
    return conn.execute(
        "INSERT INTO funds (name, target_amount, target_date) VALUES (%s,%s,%s) RETURNING id",
        (name, target, target_date)).fetchone()["id"]


def credit(conn, fund_id, amount, kind="gift_card", label="Gift card", expires=None, used="0"):
    conn.execute(
        """INSERT INTO fund_credits (fund_id, kind, label, amount, used, expires_on)
           VALUES (%s,%s,%s,%s,%s,%s)""", (fund_id, kind, label, amount, used, expires))


def only(conn, **kw):
    return funds.list_funds(conn, **kw)[0]


def test_credits_and_cash_both_count_but_only_cash_travels(conn):
    fid = make_fund(conn, target="599")
    credit(conn, fid, "150", label="Amazon card")
    conn.execute("INSERT INTO fund_contributions (fund_id, amount) VALUES (%s, 80)", (fid,))
    conn.commit()

    f = only(conn)
    assert f["credits_total"] == D("150.00") and f["saved"] == D("80.00")
    assert f["still_needed"] == D("369.00")        # 599 - 150 - 80
    # The gift card cannot pay for anything else, so the cash needed at the
    # till ignores it only to the extent it is spendable there.
    assert f["cash_needed_at_till"] == D("449.00")  # 599 - 150
    assert f["complete"] is False


def test_partly_used_gift_card_leaves_the_rest(conn):
    fid = make_fund(conn, target="200")
    credit(conn, fid, "100", used="40")
    conn.commit()
    f = only(conn)
    assert f["credits_total"] == D("60.00")
    assert f["still_needed"] == D("140.00")


def test_real_purchases_count_toward_it(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('c',1,'plaid','Card','credit','credit card',0) ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, category,
                        pfc_primary, pfc_detailed, raw)
                    VALUES ('t1','c',250,current_date,'DISCOUNT TIRE','auto',
                            'TRANSPORTATION','TRANSPORTATION_OTHER_TRANSPORTATION','{}')""")
    fid = make_fund(conn, name="Truck tires", target="1250")
    credit(conn, fid, "300", kind="store_credit", label="Discount Tire credit")
    conn.execute("INSERT INTO fund_spends (fund_id, transaction_id) VALUES (%s, 't1')", (fid,))
    conn.commit()

    f = only(conn)
    assert f["spent"] == D("250.00")
    assert f["still_needed"] == D("700.00")        # 1250 - 300 credit - 250 spent
    assert [s["display_name"] for s in f["spends"]] == ["Discount Tire"]


def test_a_fund_is_complete_when_everything_is_covered(conn):
    fid = make_fund(conn, target="500")
    credit(conn, fid, "300", kind="store_credit", label="Store credit")
    conn.execute("INSERT INTO fund_contributions (fund_id, amount) VALUES (%s, 200)", (fid,))
    conn.commit()
    f = only(conn)
    assert f["complete"] and f["still_needed"] == D("0.00")
    ready = [a for a in funds.alerts(conn) if a["kind"] == "fund_ready"]
    assert ready and "fully funded" in ready[0]["title"]


def test_expiring_credit_warns_and_names_the_deadline(conn):
    fid = make_fund(conn, target="400")
    soon = date.today() + timedelta(days=10)
    credit(conn, fid, "75", label="Best Buy card", expires=soon)
    credit(conn, fid, "50", label="No expiry card")
    conn.commit()

    f = only(conn)
    assert [c["label"] for c in f["expiring_credits"]] == ["Best Buy card"]
    alerts = [a for a in funds.alerts(conn) if a["kind"] == "credit_expiring"]
    assert len(alerts) == 1
    assert "$75.00" in alerts[0]["detail"] and alerts[0]["severity"] == "medium"


def test_fully_used_credit_stops_warning(conn):
    fid = make_fund(conn, target="400")
    credit(conn, fid, "75", label="Spent card", expires=date.today() + timedelta(days=5), used="75")
    conn.commit()
    assert only(conn)["expiring_credits"] == []
    assert [a for a in funds.alerts(conn) if a["kind"] == "credit_expiring"] == []


def test_target_date_gives_a_monthly_number(conn):
    fid = make_fund(conn, target="1200", target_date=date.today() + timedelta(days=182))
    conn.commit()
    f = only(conn)
    assert f["needed_per_month_for_target_date"] == D("200.44")   # 1200 over ~6 months


def test_affordability_reads_against_the_runway(conn):
    fid = make_fund(conn, target="500")
    credit(conn, fid, "100")
    conn.commit()
    f = only(conn)

    flush = funds.affordability(conn, f, {"safe_to_spend": D("900"), "daily_spending": D("30"),
                                          "days_until_zero": 40})
    assert flush["affordable_now"] and flush["cash_needed"] == D("400.00")
    assert flush["days_of_cash_after"] == 26          # 40 - 400/30

    broke = funds.affordability(conn, f, {"safe_to_spend": D("50"), "daily_spending": D("30"),
                                          "days_until_zero": 8})
    assert broke["affordable_now"] is False
    assert "bills" in broke["note"]


def test_bought_funds_drop_out_of_the_alerts(conn):
    fid = make_fund(conn, target="100")
    credit(conn, fid, "100", expires=date.today() + timedelta(days=3))
    conn.execute("UPDATE funds SET bought_on = current_date WHERE id = %s", (fid,))
    conn.commit()
    assert funds.alerts(conn) == []
