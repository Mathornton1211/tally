from datetime import date, timedelta
from decimal import Decimal

from tally import fees, insights, monitor

TODAY = date(2026, 9, 16)


def txn(i, d, amount, name, merchant=None, account="card", kind="expense", category="dining",
        pfc_primary="FOOD_AND_DRINK", pfc_detailed=None, bank_text=None, pending=False):
    merchant = merchant or name
    return {"id": f"t{i}", "date": d, "amount": Decimal(str(amount)), "pending": pending, "name": name,
            "bank_text": bank_text or name, "display_name": merchant, "merchant_key": merchant.lower(),
            "pfc_primary": pfc_primary, "pfc_detailed": pfc_detailed, "category": category, "kind": kind,
            "account_id": account, "account_name": account.title(), "account_mask": "0000", "institution": "Bank"}


# ---------------------------------------------------------------- fee classification

def test_classify_uses_bank_words_over_plaid_bucket():
    row = txn(1, TODAY, 250, "ANNUAL MEMBERSHIP FEE", category="fees", pfc_primary="BANK_FEES",
              pfc_detailed="BANK_FEES_OTHER_BANK_FEES")
    assert fees.classify(row) == "annual"


def test_classify_reads_original_description_when_plaid_renamed_it():
    row = txn(1, TODAY, 3, "Fee", category="fees", pfc_primary="BANK_FEES",
              pfc_detailed="BANK_FEES_OTHER_BANK_FEES", bank_text="NON-NETWORK ATM FEE")
    assert fees.classify(row) == "atm"


def test_merchant_with_fee_in_name_is_not_a_fee():
    assert fees.classify(txn(1, TODAY, 14, "Fee Fi Pizza", kind="expense")) is None


def test_refund_of_a_fee_is_not_a_fee():
    assert fees.classify(txn(1, TODAY, -35, "OVERDRAFT FEE REFUND", category="fees", pfc_primary="BANK_FEES")) is None


def test_plaid_detailed_fallback():
    row = txn(1, TODAY, 2.57, "FOREIGN TRANSACTION FEE", category="fees", pfc_primary="BANK_FEES",
              pfc_detailed="BANK_FEES_FOREIGN_TRANSACTION_FEES")
    assert fees.classify(row) == "foreign"
    assert fees.is_foreign("OXXO TIJUANA BC MX")
    assert not fees.is_foreign("VONS #2112 SAN DIEGO CA")


# ---------------------------------------------------------------- monitoring

def rules(found):
    return sorted(a["rule"] for a in found)


def test_double_charge_same_day_flags_once():
    d = TODAY - timedelta(days=5)
    rows = [txn(1, d, 73.48, "BARREL REPUBLIC"), txn(2, d, 73.48, "BARREL REPUBLIC")]
    found = monitor.evaluate(rows, rows, [], today=TODAY)
    assert rules(found) == ["duplicate_charge"]
    assert found[0]["txn_ids"] == ["t1", "t2"]


def test_same_amount_a_week_apart_is_not_a_duplicate():
    rows = [txn(1, TODAY - timedelta(days=9), 20, "SWEETGREEN"), txn(2, TODAY - timedelta(days=2), 20, "SWEETGREEN")]
    assert monitor.evaluate(rows, rows, [], today=TODAY) == []


def test_card_testing_cluster_is_high_and_includes_transfer_coded_probe():
    d = TODAY - timedelta(days=3)
    rows = [txn(1, d, 1.00, "SQ *VRTL GIFT SVC", category="shopping"),
            txn(2, d, 1.49, "PAYPAL *DIGIGOODS4U", kind="transfer", category="transfer")]
    found = [a for a in monitor.evaluate(rows, rows, [], today=TODAY) if a["rule"] == "card_testing"]
    assert len(found) == 1 and found[0]["severity"] == "high"
    assert found[0]["txn_ids"] == ["t1", "t2"]


def test_small_charge_from_known_merchant_is_fine():
    history = [txn(i, TODAY - timedelta(days=30 * i), 1.99, "APPLE.COM/BILL", merchant="Apple") for i in range(1, 4)]
    now = txn(9, TODAY - timedelta(days=1), 1.99, "APPLE.COM/BILL", merchant="Apple")
    found = monitor.evaluate([now], history + [now], [], today=TODAY)
    assert "card_testing" not in rules(found)


def test_outlier_needs_history_and_a_real_excess():
    history = [txn(i, TODAY - timedelta(days=7 * i), 20 + i % 3, "CHIPOTLE") for i in range(1, 7)]
    spike = txn(99, TODAY - timedelta(days=1), 118, "CHIPOTLE")
    found = monitor.evaluate([spike], history + [spike], [], today=TODAY)
    assert rules(found) == ["amount_outlier"]
    small = txn(98, TODAY - timedelta(days=1), 60, "CHIPOTLE")  # 3x but only ~$39 over
    assert monitor.evaluate([small], history + [small], [], today=TODAY) == []


def test_large_first_rent_payment_is_quiet():
    rent = txn(1, TODAY - timedelta(days=1), 2150, "ZELLE TO HARBOURSIDE LETTINGS", category="rent")
    assert monitor.evaluate([rent], [rent], [], today=TODAY) == []


def test_foreign_charges_group_into_one_alert_per_card_week():
    d = TODAY - timedelta(days=20)
    rows = [txn(i, d + timedelta(days=i), 40 + i, f"SHOP {i} TIJUANA BC MX", merchant=f"Shop {i}") for i in range(3)]
    found = [a for a in monitor.evaluate(rows, rows, [], today=TODAY) if a["rule"] == "foreign_activity"]
    assert 1 <= len(found) <= 2
    assert sum(len(a["txn_ids"]) for a in found) == 3


def test_fingerprint_is_stable_across_scans():
    d = TODAY - timedelta(days=5)
    rows = [txn(2, d, 9.99, "X"), txn(1, d, 9.99, "X")]
    a = monitor.evaluate(rows, rows, [], today=TODAY)
    b = monitor.evaluate(list(reversed(rows)), rows, [], today=TODAY)
    assert [x["fingerprint"] for x in a] == [x["fingerprint"] for x in b]


def test_old_events_outside_window_are_not_alerted():
    d = TODAY - timedelta(days=monitor.WINDOW_DAYS + 5)
    rows = [txn(1, d, 50, "X"), txn(2, d, 50, "X")]
    assert monitor.evaluate(rows, rows, [], today=TODAY) == []


# ---------------------------------------------------------------- insights

def test_estimate_rates_annualizes_ninety_days():
    accounts = [{"id": "vault", "current_balance": Decimal("6000")}, {"id": "reg", "current_balance": Decimal("9000")}]
    interest = [{"account_id": "vault", "amount": Decimal("-22.50")}] * 3 + [{"account_id": "reg", "amount": Decimal("-0.40")}] * 3
    rates = insights.estimate_rates(accounts, interest)
    assert rates["vault"]["rate"] == Decimal("4.50")
    assert rates["reg"]["rate"] == Decimal("0.05")
