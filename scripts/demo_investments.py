"""Add a 401k and a small brokerage to the demo database.

Plaid's Sandbox custom users cannot express holdings, so the investment pages
are built against this instead. Demo databases only.

    python scripts/demo_investments.py --database-url postgresql://.../tally_demo
"""
import argparse
import sys
from datetime import date, timedelta

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

TODAY = date.today()

SECURITIES = [
    ("sec-vtsax", "VTSAX", "Vanguard Total Stock Market Index Admiral", "mutual fund", 129.44),
    ("sec-vbtlx", "VBTLX", "Vanguard Total Bond Market Index Admiral", "mutual fund", 9.62),
    ("sec-vtiax", "VTIAX", "Vanguard Total International Stock Index Admiral", "mutual fund", 34.18),
    ("sec-aapl", "AAPL", "Apple Inc.", "equity", 241.88),
    ("sec-nvda", "NVDA", "NVIDIA Corporation", "equity", 178.52),
    ("sec-vti", "VTI", "Vanguard Total Stock Market ETF", "etf", 312.07),
    ("sec-cash", None, "Cash", "cash", 1.0),
]

# account, security, quantity, cost basis
HOLDINGS_401K = [
    ("sec-vtsax", 61.4820, 6180.22),
    ("sec-vtiax", 44.1900, 1402.55),
    ("sec-vbtlx", 96.3100, 980.14),
]
HOLDINGS_BROKER = [
    ("sec-aapl", 9.0000, 1512.30),
    ("sec-nvda", 6.0000, 402.18),
    ("sec-vti", 4.2500, 1180.00),
    ("sec-cash", 214.7700, 214.77),
]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    args = ap.parse_args()
    if "tally_demo" not in args.database_url:
        sys.exit("refusing: demo database only")

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        item = conn.execute("SELECT id FROM items ORDER BY id LIMIT 1").fetchone()["id"]
        for aid, name, subtype, balance, mask in [
            ("inv-401k", "Fidelity 401(k)", "401k", 0, "8801"),
            ("inv-brok", "Brokerage", "brokerage", 0, "5512"),
        ]:
            conn.execute(
                """INSERT INTO accounts (id, item_id, name, mask, type, subtype, current_balance, iso_currency)
                   VALUES (%s,%s,%s,%s,'investment',%s,%s,'USD')
                   ON CONFLICT (id) DO UPDATE SET name = EXCLUDED.name, subtype = EXCLUDED.subtype""",
                (aid, item, name, mask, subtype, balance))

        for sid, ticker, name, kind, price in SECURITIES:
            conn.execute(
                """INSERT INTO securities (id, ticker, name, type, close_price, close_price_as_of,
                       iso_currency, is_cash_equivalent)
                   VALUES (%s,%s,%s,%s,%s,%s,'USD',%s)
                   ON CONFLICT (id) DO UPDATE SET close_price = EXCLUDED.close_price""",
                (sid, ticker, name, kind, price, TODAY, kind == "cash"))

        prices = {s[0]: s[4] for s in SECURITIES}
        totals = {}
        for account, rows in (("inv-401k", HOLDINGS_401K), ("inv-brok", HOLDINGS_BROKER)):
            total = 0.0
            for sid, qty, basis in rows:
                value = round(qty * prices[sid], 2)
                total += value
                conn.execute(
                    """INSERT INTO holdings (account_id, security_id, quantity, price, price_as_of, value,
                           cost_basis, iso_currency)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,'USD')
                       ON CONFLICT (account_id, security_id) DO UPDATE SET quantity = EXCLUDED.quantity,
                         price = EXCLUDED.price, value = EXCLUDED.value, cost_basis = EXCLUDED.cost_basis""",
                    (account, sid, qty, prices[sid], TODAY, value, basis))
            totals[account] = round(total, 2)
            conn.execute("UPDATE accounts SET current_balance = %s WHERE id = %s", (totals[account], account))

        # Contributions stopped when the job did: last one about two months ago.
        for i in range(10):
            d = TODAY - timedelta(days=60 + i * 14)
            conn.execute(
                """INSERT INTO investment_transactions (id, account_id, security_id, date, name, quantity,
                       amount, fees, type, subtype, iso_currency, raw)
                   VALUES (%s,'inv-401k','sec-vtsax',%s,'CONTRIBUTION',1.55,200.00,0,'buy','contribution','USD',%s)
                   ON CONFLICT (id) DO NOTHING""",
                (f"demo-contrib-{i}", d, Jsonb({"demo": True})))
        for i, (sid, name, amount, qty) in enumerate([
            ("sec-nvda", "BUY NVDA", 402.18, 6), ("sec-aapl", "BUY AAPL", 512.30, 2),
            ("sec-vti", "BUY VTI", 300.00, 1)]):
            conn.execute(
                """INSERT INTO investment_transactions (id, account_id, security_id, date, name, quantity,
                       amount, fees, type, subtype, iso_currency, raw)
                   VALUES (%s,'inv-brok',%s,%s,%s,%s,%s,0,'buy','buy','USD',%s)
                   ON CONFLICT (id) DO NOTHING""",
                (f"demo-buy-{i}", sid, TODAY - timedelta(days=120 + i * 30), name, qty, amount, Jsonb({"demo": True})))
        conn.commit()
    print(f"401k {totals['inv-401k']}, brokerage {totals['inv-brok']}")


if __name__ == "__main__":
    main()
