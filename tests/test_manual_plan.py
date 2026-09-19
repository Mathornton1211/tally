"""Manual accounts, splits, what-if and the freelance tax estimate."""
from datetime import date, timedelta
from decimal import Decimal

from tally import income, plan

D = Decimal


def base(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('chk',1,'plaid','Checking','depository','checking',800)
                    ON CONFLICT (id) DO NOTHING""")
    conn.commit()


def manual_account(conn, balance="120", type_="depository", name="Cash"):
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance,
                        available_balance, institution_name)
                    VALUES ('cash', NULL, 'manual', %s, %s, 'cash', %s, %s, 'Cash')""",
                 (name, type_, balance, balance))
    conn.commit()


def spend(conn, days_ago, amount, category="dining", account="chk", i=0):
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, category,
                        pfc_primary, pfc_detailed, raw)
                    VALUES (%s,%s,%s,%s,'STORE',%s,'FOOD_AND_DRINK','FOOD_AND_DRINK_RESTAURANT','{}')""",
                 (f"t{days_ago}-{i}-{account}", account, amount, date.today() - timedelta(days=days_ago), category))


# ---------------------------------------------------------------- manual

def test_manual_account_counts_as_cash_and_needs_no_plaid_item(conn):
    base(conn)
    manual_account(conn, "120")
    rw = plan.runway(conn)
    assert rw["cash"] == D("920.00")               # 800 from the bank + 120 cash
    names = [a["name"] for a in rw["cash_accounts"]]
    assert "Cash" in names


def test_manual_credit_account_joins_the_payoff_plan(conn):
    base(conn)
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance,
                        institution_name)
                    VALUES ('owed', NULL, 'manual', 'Owed to Dad', 'loan', 'personal', 1500, 'Family')""")
    conn.commit()
    ds = plan.debts(conn)
    assert [d.name for d in ds] == ["Owed to Dad"]
    assert ds[0].apr is None and ds[0].apr_source == "unknown"
    p = plan.simulate(ds, D(250), "avalanche")
    assert p.months and p.months <= 7          # 1500 at no interest, ~215/month minimum + 250


# ---------------------------------------------------------------- splits

def test_split_children_replace_the_parent_in_totals(conn):
    base(conn)
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, category,
                        pfc_primary, pfc_detailed, raw)
                    VALUES ('big','chk',100,current_date,'COSTCO','shopping',
                            'GENERAL_MERCHANDISE','GENERAL_MERCHANDISE_SUPERSTORES','{}')""")
    conn.commit()
    before = conn.execute("SELECT coalesce(sum(spend),0) AS s FROM v_txn").fetchone()["s"]

    for i, (amount, category) in enumerate([(60, "groceries"), (40, "home")], 1):
        conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, category,
                            parent_id, source, pfc_primary, pfc_detailed, raw)
                        VALUES (%s,'chk',%s,current_date,'COSTCO',%s,'big','split',
                                'GENERAL_MERCHANDISE','GENERAL_MERCHANDISE_SUPERSTORES','{}')""",
                     (f"big-split-{i}", amount, category))
    conn.execute("UPDATE transactions SET is_split_parent = true WHERE id = 'big'")
    conn.commit()

    after = conn.execute("SELECT coalesce(sum(spend),0) AS s FROM v_txn").fetchone()["s"]
    assert after == before                       # the total is unchanged
    rows = conn.execute("SELECT id, category FROM v_txn ORDER BY id").fetchall()
    ids = [r["id"] for r in rows]
    assert "big" not in ids and "big-split-1" in ids and "big-split-2" in ids
    cats = {r["category"] for r in rows}
    assert {"groceries", "home"} <= cats
    # And the parent is still reachable for anything attached to it.
    assert conn.execute("SELECT is_split_parent FROM v_txn_any WHERE id = 'big'").fetchone()["is_split_parent"]


# ---------------------------------------------------------------- what if

def test_what_if_reports_a_shortfall_and_a_payoff_date(conn):
    base(conn)
    for i in range(12):
        spend(conn, i * 7 + 1, 100, "rent" if i % 2 else "dining", i=i)
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance, credit_limit)
                    VALUES ('card',1,'plaid','Card','credit','credit card',2000,5000) ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO liabilities (account_id, kind, apr, minimum_payment, next_due_date, source)
                    VALUES ('card','credit',22.0,60,current_date + 10,'demo') ON CONFLICT DO NOTHING""")
    conn.commit()

    poor = plan.what_if(conn, D(0), D(0), D(0))
    assert poor["covers_the_month"] is False and poor["shortfall"] > 0

    rich = plan.what_if(conn, D(6000), D(300), D(50))
    assert rich["covers_the_month"] is True
    assert rich["cut"] > 0 and rich["spending"] < poor["spending"]
    assert rich["debt_free"]["months"] and rich["debt_free"]["months"] < 12


def test_cutting_flexible_spending_never_touches_essentials(conn):
    base(conn)
    for i in range(6):
        spend(conn, i * 10 + 1, 200, "rent", i=i)          # essential
        spend(conn, i * 10 + 2, 100, "entertainment", i=i)  # flexible
    conn.commit()
    everything = plan.what_if(conn, D(5000), D(0), D(100))
    assert everything["cut"] == everything["flexible"]       # all of the flexible
    assert everything["spending"] == everything["essentials"]


# ---------------------------------------------------------------- freelance tax

def freelance_deposit(conn, when, amount, name, i):
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary,
                        pfc_detailed, pfc_confidence, raw)
                    VALUES (%s,'chk',%s,%s,%s,'INCOME','INCOME_OTHER_INCOME','HIGH',%s)""",
                 (f"fl{i}", -amount, when, name, f'{{"original_description": "{name}"}}'))


def test_platform_deposits_are_treated_as_self_employment(conn):
    base(conn)
    year = date.today().year
    freelance_deposit(conn, date(year, 2, 10), 1000, "UPWORK ESCROW RELEASE", 1)
    freelance_deposit(conn, date(year, 5, 2), 2000, "STRIPE TRANSFER *AUTOMATION", 2)
    freelance_deposit(conn, date(year, 5, 20), 500, "GUSTO PAY 847193 DIR DEP", 3)   # a paycheck
    conn.commit()

    s = income.summary(conn, year, D(27))
    assert s["freelance_income"] == D("3000.00")     # the paycheck is not in it
    assert s["other_income"] == D("500.00")
    assert s["should_set_aside"] == D("810.00")      # 27%
    q2 = next(q for q in s["quarters"] if q["quarter"] == "Q2")
    assert q2["income"] == D("2000.00") and q2["estimated_payment"] == D("540.00")
    # Biggest client first; the name is cleaned only as far as the bank text allows.
    assert [c["name"] for c in s["clients"]][0].startswith("Stripe Transfer")


def test_set_aside_shortfall_uses_the_nominated_account(conn):
    base(conn)
    year = date.today().year
    freelance_deposit(conn, date(year, 3, 1), 4000, "UPWORK ESCROW RELEASE", 1)
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('tax',1,'plaid','Tax savings','depository','savings',500) ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO app_settings (key, value) VALUES ('tax_account_id', '"tax"')
                    ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""")
    conn.commit()
    s = income.summary(conn, year, D(25))
    assert s["should_set_aside"] == D("1000.00")
    assert s["set_aside"] == D("500.00") and s["short_by"] == D("500.00")
