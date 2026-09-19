"""Bend the demo household into a tight month: no steady paycheck, cards near
their limits, one payment overdue.

Demo databases only (refuses anything else). This exists so runway, payment
warnings and the payoff planner can be built and checked against the hard case
rather than a comfortable one.

    python scripts/demo_tight.py --database-url postgresql://.../tally_demo
"""
import argparse
import random
import sys
from datetime import date, timedelta
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

TODAY = date.today()
rng = random.Random(4417)

# Freelance work: lumpy, and it stopped a few weeks ago.
FREELANCE = [
    (62, 1450.00, "UPWORK ESCROW RELEASE"),
    (48, 600.00, "STRIPE TRANSFER *AUTOMATION"),
    (39, 925.00, "UPWORK ESCROW RELEASE"),
    (24, 350.00, "ZELLE FROM R MARTINEZ"),
]

CARDS = {  # name -> (balance, limit, apr, minimum, due in N days, overdue)
    "Freedom Unlimited": (6841.22, 7500, "26.99", 205.00, 9, False),
    "Gold Card": (4118.65, 5000, "24.24", 124.00, -3, True),
    "Quicksilver": (2980.44, 3000, "29.99", 89.00, 18, False),
}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", required=True)
    args = ap.parse_args()
    if "tally_demo" not in args.database_url:
        sys.exit("refusing: demo database only")

    with psycopg.connect(args.database_url, row_factory=dict_row) as conn:
        accounts = {r["name"]: r for r in conn.execute(
            "SELECT id, name, type, subtype, current_balance FROM accounts").fetchall()}

        # Cash: what is actually in the account, not a comfortable buffer.
        for name, balance in [("Everyday Checking", 412.88), ("Regular Savings", 120.55),
                              ("High-Yield Vault", 0.00), ("Checking", 41.18)]:
            if name in accounts:
                conn.execute("UPDATE accounts SET current_balance = %s, available_balance = %s WHERE id = %s",
                             (balance, balance, accounts[name]["id"]))

        # Cards near their limits, with issuer terms.
        for name, (balance, limit, apr, minimum, due_in, overdue) in CARDS.items():
            a = accounts.get(name)
            if not a:
                continue
            conn.execute("UPDATE accounts SET current_balance = %s, credit_limit = %s WHERE id = %s",
                         (balance, limit, a["id"]))
            due = TODAY + timedelta(days=due_in)
            conn.execute(
                """INSERT INTO liabilities (account_id, kind, apr, aprs, last_statement_balance,
                       last_statement_date, minimum_payment, next_due_date, is_overdue, source, raw)
                   VALUES (%s,'credit',%s,%s,%s,%s,%s,%s,%s,'demo','{}')
                   ON CONFLICT (account_id) DO UPDATE SET apr = EXCLUDED.apr, aprs = EXCLUDED.aprs,
                     last_statement_balance = EXCLUDED.last_statement_balance,
                     last_statement_date = EXCLUDED.last_statement_date,
                     minimum_payment = EXCLUDED.minimum_payment, next_due_date = EXCLUDED.next_due_date,
                     is_overdue = EXCLUDED.is_overdue, source = 'demo', updated_at = now()""",
                (a["id"], apr, Jsonb([{"apr_type": "purchase_apr", "apr_percentage": float(apr)}]),
                 round(balance * 0.98, 2), TODAY - timedelta(days=12), minimum, due, overdue))

        # The job ended: no paycheck in the last 45 days.
        gone = conn.execute(
            """DELETE FROM transactions WHERE date >= %s
                 AND (raw->>'original_description' ILIKE '%%GUSTO%%' OR name ILIKE '%%Gusto%%')""",
            (TODAY - timedelta(days=45),)).rowcount

        # Freelance money instead, irregular and drying up.
        checking = accounts["Everyday Checking"]["id"]
        for days_ago, amount, desc in FREELANCE:
            d = TODAY - timedelta(days=days_ago)
            tid = f"demo-freelance-{days_ago}"
            conn.execute(
                """INSERT INTO transactions (id, account_id, amount, iso_currency, date, name, pending,
                       pfc_primary, pfc_detailed, pfc_confidence, raw)
                   VALUES (%s,%s,%s,'USD',%s,%s,false,'INCOME','INCOME_OTHER_INCOME','HIGH',%s)
                   ON CONFLICT (id) DO NOTHING""",
                (tid, checking, -amount, d, desc,
                 Jsonb({"original_description": desc, "demo": True})))

        # A few small overdraft-adjacent realities.
        conn.execute(
            """INSERT INTO transactions (id, account_id, amount, iso_currency, date, name, pending,
                   pfc_primary, pfc_detailed, pfc_confidence, raw)
               VALUES (%s,%s,35.00,'USD',%s,'OVERDRAFT ITEM FEE',false,'BANK_FEES',
                       'BANK_FEES_OVERDRAFT_FEES','VERY_HIGH',%s)
               ON CONFLICT (id) DO NOTHING""",
            ("demo-od-recent", checking, TODAY - timedelta(days=6),
             Jsonb({"original_description": "OVERDRAFT ITEM FEE", "demo": True})))
        conn.commit()

    print(f"tight profile applied: paycheck rows removed {gone}, {len(FREELANCE)} freelance deposits, "
          f"{len(CARDS)} cards with issuer terms (one overdue)")


if __name__ == "__main__":
    main()
