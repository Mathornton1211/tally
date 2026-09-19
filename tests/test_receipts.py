"""Reading a receipt and finding its transaction."""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import receipts

D = Decimal

SAMPLE = """VONS #2112
3450 SPORTS ARENA BLVD
SAN DIEGO CA

MILK          4.29
EGGS          6.49
COFFEE       12.99
SUBTOTAL     23.77
TAX           1.84
TOTAL        84.12

VISA ************4417
09/11/2026  14:32
THANK YOU
"""


def test_parse_prefers_the_total_line():
    p = receipts.parse(SAMPLE)
    assert p["amount"] == D("84.12")        # not the 23.77 subtotal, not the 12.99 item
    assert p["receipt_date"] == date(2026, 9, 11)
    assert p["merchant"].startswith("VONS")


def test_parse_falls_back_to_the_largest_amount():
    p = receipts.parse("CORNER STORE\n3.50\n19.75\n7.10\n")
    assert p["amount"] == D("19.75")


def test_parse_handles_nothing():
    assert receipts.parse(None) == {"amount": None, "receipt_date": None, "merchant": None}
    assert receipts.parse("   \n\n")["amount"] is None


def test_future_dates_are_ignored():
    year = date.today().year + 3
    p = receipts.parse(f"STORE\nTOTAL 10.00\n01/02/{year}\n")
    assert p["receipt_date"] is None


def test_rejects_oversized_and_unsupported_files():
    with pytest.raises(ValueError, match="larger"):
        receipts.save_file(b"x" * (receipts.MAX_BYTES + 1), "image/png", "big.png")
    with pytest.raises(ValueError, match="unsupported"):
        receipts.save_file(b"MZ", "application/x-msdownload", "nope.exe")


# ---------------------------------------------------------------- matching

def rows(*txns):
    return [{"id": t[0], "date": t[1], "amount": D(str(t[2])), "display_name": t[3], "bank_text": t[3],
             "account_name": "Card", "account_mask": "0000", "category_label": "Groceries",
             "logo_url": None, "category_icon": "ShoppingCart"} for t in txns]


def score(cands, txn_id):
    return next(c["score"] for c in cands if c["id"] == txn_id)


def test_exact_amount_same_day_beats_a_near_miss(conn):
    today = date.today()
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc) VALUES (1,'it','i','x') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance)
                    VALUES ('c',1,'Card','credit','credit card',100) ON CONFLICT DO NOTHING""")
    for tid, d, amt, name in [("t1", today, "84.12", "Vons"), ("t2", today - timedelta(days=1), "84.50", "Ralphs")]:
        conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, merchant_name,
                            pfc_primary, pfc_detailed, raw)
                        VALUES (%s,'c',%s,%s,%s,%s,'FOOD_AND_DRINK','FOOD_AND_DRINK_GROCERIES','{}')""",
                     (tid, amt, d, name, name))
    conn.commit()

    cands = receipts.candidates(conn, D("84.12"), today, "VONS #2112")
    assert cands[0]["id"] == "t1"
    match = receipts.best_match(cands)
    assert match and match["id"] == "t1"


def test_two_identical_amounts_are_not_auto_matched(conn):
    """Two charges for the same amount on the same day: ask, never guess."""
    today = date.today()
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc) VALUES (1,'it','i','x') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance)
                    VALUES ('c',1,'Card','credit','credit card',100) ON CONFLICT DO NOTHING""")
    for tid in ("t1", "t2"):
        conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, merchant_name,
                            pfc_primary, pfc_detailed, raw)
                        VALUES (%s,'c',73.48,%s,'BARREL REPUBLIC','Barrel Republic',
                                'FOOD_AND_DRINK','FOOD_AND_DRINK_RESTAURANT','{}')""", (tid, today))
    conn.commit()
    cands = receipts.candidates(conn, D("73.48"), today, "Barrel Republic")
    assert len(cands) == 2
    assert receipts.best_match(cands) is None


def test_income_is_never_a_candidate(conn):
    today = date.today()
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','B') ON CONFLICT DO NOTHING")
    conn.execute("INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc) VALUES (1,'it','i','x') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO accounts (id, item_id, name, type, subtype, current_balance)
                    VALUES ('chk',1,'Checking','depository','checking',100) ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
                    VALUES ('pay','chk',-500,%s,'PAYCHECK','INCOME','INCOME_WAGES','{}')""", (today,))
    conn.commit()
    assert receipts.candidates(conn, D("500"), today, "Payroll") == []


def test_merchant_similarity_is_forgiving():
    assert receipts._similar("VONS #2112 SAN DIEGO", "Vons") == 1.0
    assert receipts._similar("TRADER JOES", "Trader Joe's") > 0.5
    assert receipts._similar("Chevron", "Airbnb") < 0.3
