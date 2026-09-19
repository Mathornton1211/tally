"""Build a realistic demo household in Plaid Sandbox and sync it into a database.

Every transaction goes through the real path: Plaid Sandbox custom user ->
public token -> link_item -> /transactions/sync. Plaid enriches the raw bank
descriptions (merchant name, logo, category), so the UI is designed against the
same shapes production will send.

Sandbox only. Refuses to run with PLAID_ENV=production. Point it at a demo
database, never the real one:

    python scripts/seed_sandbox.py --database-url postgresql://.../tally_demo --reset
"""
import argparse
import json
import os
import random
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tally import db, sync  # noqa: E402
from tally.crypto import TokenBox  # noqa: E402
from tally.plaid import Plaid  # noqa: E402

TODAY = date.today()
START = TODAY - timedelta(days=330)
rng = random.Random(1211)

# Card payments leave checking AND land on the card, same amounts, or estimated
# card balances drift further wrong the further back they go.
CARD_PAYMENTS: dict[str, list[tuple[date, float]]] = {"chase": [], "amex": []}


def days(start=START, end=TODAY):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def tx(d: date, amount: float, desc: str, post_lag: int = 0):
    posted = min(d + timedelta(days=post_lag), TODAY)
    return {"date_transacted": d.isoformat(), "date_posted": posted.isoformat(),
            "amount": round(amount, 2), "description": desc, "currency": "USD"}


def monthly(day_of_month: int):
    d = START.replace(day=1)
    while d <= TODAY:
        try:
            hit = d.replace(day=day_of_month)
        except ValueError:
            hit = d.replace(day=28)
        if START <= hit <= TODAY:
            yield hit
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=1)


def jitter(base: float, pct: float) -> float:
    return base * (1 + rng.uniform(-pct, pct))


# ------------------------------------------------------------------ households

def credit_union():
    """The everyday credit union: the paycheck lands here and the bills leave from here."""
    checking, savings = [], []
    first_friday = START + timedelta(days=(4 - START.weekday()) % 7)
    d = first_friday
    while d <= TODAY:
        checking.append(tx(d, -2640.18, "GUSTO PAY 847193 DIR DEP"))
        d += timedelta(days=14)

    for d in monthly(1):
        checking.append(tx(d, 2150.00, "ZELLE PAYMENT TO HARBOURSIDE LETTINGS LLC"))
    for d in monthly(3):
        # the utility runs hot in summer.
        summer = d.month in (7, 8, 9)
        checking.append(tx(d, jitter(205 if summer else 112, 0.12), "the electricity company WEB PAYMENT"))
    for d in monthly(8):
        checking.append(tx(d, 79.99, "SPECTRUM 855-707-7328 CA"))
    for d in monthly(12):
        checking.append(tx(d, 140.00, "T-MOBILE PCS SVC WA"))
    for d in monthly(15):
        checking.append(tx(d, 128.40, "GEICO *AUTO 800-841-3000 DC"))
        checking.append(tx(d, 389.00, "CAPITAL ONE AUTO PYMT"))
    for d in monthly(2):
        checking.append(tx(d, 300.00, "ONLINE TRANSFER TO SAVINGS XXXXXX0925"))
        savings.append(tx(d, -300.00, "ONLINE TRANSFER FROM CHECKING XXXXXX4417"))
    for d in monthly(28):
        savings.append(tx(d, -0.41, "INTEREST PAYMENT"))
    for d in monthly(22):
        chase, amex = round(jitter(1150, 0.25), 2), round(jitter(620, 0.3), 2)
        checking.append(tx(d, chase, "CHASE CREDIT CRD AUTOPAY PPD ID: 4760039224", post_lag=1))
        checking.append(tx(d, amex, "AMEX EPAYMENT ACH PMT", post_lag=1))
        CARD_PAYMENTS["chase"].append((d, chase))
        CARD_PAYMENTS["amex"].append((d, amex))

    # Fees, the thing Tally exists to catch.
    for d in list(monthly(30))[2:5]:
        checking.append(tx(d, 12.00, "MONTHLY SERVICE FEE"))
    for m_back in (7, 2):
        d = TODAY - timedelta(days=30 * m_back + 4)
        checking.append(tx(d, 35.00, "OVERDRAFT ITEM FEE"))
    for d in rng.sample(list(days()), 5):
        checking.append(tx(d, 60.00, "ATM WITHDRAWAL 7-ELEVEN 3421 SEASIDE CA"))
        checking.append(tx(d, 3.00, "NON-NETWORK ATM FEE"))
    for d in rng.sample(list(days()), 9):
        checking.append(tx(d, rng.choice([25, 40, 18.5, 60, 32]), "VENMO PAYMENT 1043997712"))
    return [
        {"type": "depository", "subtype": "checking", "starting_balance": 1843.27,
         "meta": {"name": "Everyday Checking", "mask": "4417"}, "transactions": checking},
        {"type": "depository", "subtype": "savings", "starting_balance": 9215.60,
         "meta": {"name": "Regular Savings", "mask": "0925"}, "transactions": savings},
    ]


def online_bank():
    """An online bank: a high-yield vault that is mostly ignored, and an idle checking."""
    vault = [tx(d, -round(jitter(23.5, 0.05), 2), "INTEREST EARNED") for d in monthly(27)]
    vault.append(tx(START + timedelta(days=12), -1500.00, "DEPOSIT FROM EXTERNAL ACCOUNT"))
    idle = [tx(START + timedelta(days=20), 4.95, "PAPER STATEMENT FEE")]
    return [
        {"type": "depository", "subtype": "savings", "starting_balance": 6284.11,
         "meta": {"name": "High-Yield Vault", "mask": "7730"}, "transactions": vault},
        {"type": "depository", "subtype": "checking", "starting_balance": 41.18,
         "meta": {"name": "Checking", "mask": "2206"}, "transactions": idle},
    ]


GROCERY = ["VONS #2112 SAN DIEGO CA", "TRADER JOE S #021 SAN DIEGO CA", "COSTCO WHSE #0401 CHULA VISTA CA",
           "RALPHS #0133 CORONADO CA", "SPROUTS FARMERS MKT #412"]
DINING = ["CHIPOTLE 1734 CHULA VISTA CA", "STARBUCKS STORE 09281", "SWEETGREEN SAN DIEGO", "IN-N-OUT BURGER #214",
          "PANERA BREAD #601442", "SQ *COFFEE COAST SEASIDE", "DOORDASH*TACOS EL GORDO", "UBER *EATS PENDING"]
GAS = ["CHEVRON 0209183 SEASIDE", "ARCO #42117 CHULA VISTA CA", "SHELL OIL 57444219004"]
SHOP = ["AMAZON.COM*2K4LP0 AMZN.COM/BILL WA", "AMZN Mktp US*RT5YH1", "TARGET 00021782 CHULA VISTA CA",
        "HOME DEPOT #1861", "BEST BUY 00011015", "WALGREENS #7231"]


def everyday_card():
    """Stands in for Chase Freedom: groceries, gas, subscriptions, and a price creep."""
    t = []
    for d in days():
        if d.weekday() in (5, 6) and rng.random() < 0.8:
            t.append(tx(d, jitter(96, 0.45), rng.choice(GROCERY), post_lag=1))
        if rng.random() < 0.33:
            t.append(tx(d, jitter(21, 0.6), rng.choice(DINING), post_lag=1))
        if d.weekday() == 1 and rng.random() < 0.7:
            t.append(tx(d, jitter(58, 0.2), rng.choice(GAS), post_lag=1))
        if rng.random() < 0.12:
            t.append(tx(d, jitter(46, 0.8), rng.choice(SHOP), post_lag=2))
    increase = TODAY - timedelta(days=150)
    for d in monthly(6):
        t.append(tx(d, 15.49 if d < increase else 17.99, "NETFLIX.COM LOS GATOS CA"))
    for d in monthly(9):
        t.append(tx(d, 11.99, "SPOTIFY USA 877-778-1161"))
        t.append(tx(d, 2.99, "APPLE.COM/BILL 866-712-7753 CA"))
    for d in monthly(14):
        t.append(tx(d, 20.00, "OPENAI *CHATGPT SUBSCR"))
        t.append(tx(d, 24.99, "PLANET FITNESS CLUB FEES"))
    for d in monthly(19):
        t.append(tx(d, 18.99, "HULU 877-8244858 CA"))
    for d in monthly(24):
        t.append(tx(d, round(jitter(47, 0.3), 2), "INTEREST CHARGE ON PURCHASES"))
    t.append(tx(TODAY - timedelta(days=95), 32.00, "LATE FEE"))
    for d, amt in CARD_PAYMENTS["chase"]:
        t.append(tx(d, -amt, "AUTOMATIC PAYMENT - THANK YOU", post_lag=1))
    return [{"type": "credit", "subtype": "credit card", "starting_balance": 2318.44,
             "meta": {"name": "Freedom Unlimited", "mask": "8812", "limit": 9000}, "transactions": t}]


def travel_card():
    """Stands in for Amex: dining, travel, an annual fee, a Tijuana trip, and trouble."""
    t = []
    for d in days():
        if d.weekday() in (4, 5) and rng.random() < 0.55:
            t.append(tx(d, jitter(64, 0.5), rng.choice(["HODAD'S OCEAN BEACH", "PHIL'S BBQ SAN DIEGO",
                                                        "BARREL REPUBLIC PB", "PUESTO LA JOLLA"]), post_lag=1))
        if rng.random() < 0.14:
            t.append(tx(d, jitter(19, 0.5), rng.choice(["UBER *TRIP HELP.UBER.COM", "LYFT *RIDE SAT 8PM"]), post_lag=1))
    trip = TODAY - timedelta(days=120)
    for i, (amt, desc) in enumerate([(84.30, "OXXO TIJUANA BC MX"), (212.00, "HOTEL LUCERNA TIJUANA MX"),
                                     (46.75, "TELEFERICO RESTAURANTE TIJUANA MX"), (38.20, "MERCADO HIDALGO TIJUANA MX")]):
        t.append(tx(trip + timedelta(days=i), amt, desc, post_lag=1))
        t.append(tx(trip + timedelta(days=i), round(amt * 0.027, 2), "FOREIGN TRANSACTION FEE", post_lag=1))
    t.append(tx(TODAY - timedelta(days=60), 486.20, "DELTA AIR LINES ATLANTA"))
    t.append(tx(TODAY - timedelta(days=58), 612.00, "AIRBNB * HMQ42ZT8"))
    t.append(tx(START + timedelta(days=100), 250.00, "ANNUAL MEMBERSHIP FEE"))
    for d, amt in CARD_PAYMENTS["amex"]:
        t.append(tx(d, -amt, "ONLINE PAYMENT - THANK YOU", post_lag=1))
    for d in monthly(9):
        t.append(tx(d, 11.99, "SPOTIFY USA 877-778-1161"))  # same service, second card
    # A double charge and a card-testing pattern for the fraud rules.
    dup = TODAY - timedelta(days=9)
    t.append(tx(dup, 73.48, "BARREL REPUBLIC PB"))
    t.append(tx(dup, 73.48, "BARREL REPUBLIC PB"))
    probe = TODAY - timedelta(days=3)
    t.append(tx(probe, 1.00, "SQ *VRTL GIFT SVC"))
    t.append(tx(probe, 1.49, "PAYPAL *DIGIGOODS4U"))
    return [{"type": "credit", "subtype": "credit card", "starting_balance": 1106.93,
             "meta": {"name": "Gold Card", "mask": "1009", "limit": 15000}, "transactions": t}]


def auto_lender():
    """Stands in for Capital One: a car loan and a card that only exists."""
    card = [tx(START + timedelta(days=40), 12.99, "PARAMOUNT+ 888-274-5343")]
    return [
        {"type": "credit", "subtype": "credit card", "starting_balance": 0.00,
         "meta": {"name": "Quicksilver", "mask": "5521", "limit": 3500}, "transactions": card},
    ]


HOUSEHOLD = [
    ("ins_109509", credit_union),   # First Gingham Credit Union
    ("ins_109510", online_bank),    # Tattersall Federal Credit Union
    ("ins_109508", everyday_card),  # First Platypus Bank
    ("ins_109511", travel_card),    # Tartan Bank
    ("ins_109512", auto_lender),    # Houndstooth Bank
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    ap.add_argument("--reset", action="store_true", help="drop and recreate the schema first")
    args = ap.parse_args()

    if os.environ.get("PLAID_ENV", "sandbox") != "sandbox":
        sys.exit("refusing: PLAID_ENV is not sandbox")
    if "tally_demo" not in args.database_url and "5544" not in args.database_url:
        sys.exit("refusing: this does not look like a demo or dev database")

    if args.reset:
        with psycopg.connect(args.database_url, autocommit=True) as c:
            c.execute("DROP SCHEMA public CASCADE")
            c.execute("CREATE SCHEMA public")
    db.migrate(args.database_url)

    plaid = Plaid("https://sandbox.plaid.com", os.environ["PLAID_CLIENT_ID"], os.environ["PLAID_SECRET_SANDBOX"])
    box = TokenBox(os.environ["TALLY_FERNET_KEY"])

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        for inst, build in HOUSEHOLD:
            accounts = build()
            n = sum(len(a["transactions"]) for a in accounts)
            cfg = {"override_accounts": accounts}
            r = plaid._post("/sandbox/public_token/create", {
                "institution_id": inst, "initial_products": ["transactions"],
                "options": {"override_username": "user_custom", "override_password": json.dumps(cfg),
                            "transactions": {"days_requested": 730}}})
            item_id = sync.link_item(conn, plaid, box, r["public_token"])
            conn.commit()
            got = 0
            for _ in range(40):
                res = sync.sync_item(conn, plaid, box, item_id)
                got += res["added"]
                if res["update_status"] == "HISTORICAL_UPDATE_COMPLETE" and got:
                    break
                time.sleep(3)
            # Sandbox reports HISTORICAL_UPDATE_COMPLETE before the older pages
            # are actually served. Keep pulling until a pass adds nothing.
            while True:
                time.sleep(4)
                more = sync.sync_item(conn, plaid, box, item_id)["added"]
                got += more
                if not more:
                    break
            print(f"{inst} {build.__name__}: sent {n}, synced {got}")


if __name__ == "__main__":
    main()
