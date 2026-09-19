"""The privacy rule.

An account with an owner is that person's alone -- not the household admin's,
not anyone else's. These tests exist because that promise is the kind that gets
quietly broken by a JOIN somewhere six features later, and a couple would only
find out afterwards.
"""
from datetime import date
from decimal import Decimal

import pytest

from tally import budgets, funds, people

D = Decimal


@pytest.fixture
def household(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    alex = people.create(conn, "Alex", "alex", "password123", role="owner")
    sam = people.create(conn, "Sam", "sam", "password123", role="member")

    def account(aid, owner):
        conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance, owner_id)
                        VALUES (%s,1,'plaid',%s,'depository','checking',100,%s)""", (aid, aid, owner))

    account("joint", None)
    account("alex-only", alex["id"])
    account("sam-only", sam["id"])
    conn.commit()
    return {"alex": alex["id"], "sam": sam["id"]}


def spend(conn, account, amount, tid, when=date(2026, 1, 5)):
    conn.execute(
        """INSERT INTO transactions (id, account_id, amount, date, name, pfc_primary, pfc_detailed, raw)
           VALUES (%s,%s,%s,%s,'STORE','FOOD_AND_DRINK','FOOD_AND_DRINK_GROCERIES','{}')""",
        (tid, account, amount, when))


def as_person(conn, person_id):
    """What scope.connection() does per request."""
    conn.execute("SELECT set_config('tally.viewer', %s, true)", (str(person_id) if person_id else "",))


def visible(conn):
    return {r["account_id"] for r in conn.execute("SELECT DISTINCT account_id FROM v_txn").fetchall()}


# ---------------------------------------------------------------- visibility

def test_each_person_sees_the_joint_account_and_only_their_own(conn, household):
    spend(conn, "joint", 10, "t-joint")
    spend(conn, "alex-only", 20, "t-alex")
    spend(conn, "sam-only", 30, "t-sam")
    conn.commit()

    as_person(conn, household["alex"])
    assert visible(conn) == {"joint", "alex-only"}

    as_person(conn, household["sam"])
    assert visible(conn) == {"joint", "sam-only"}


def test_the_household_admin_does_not_see_private_accounts(conn, household):
    """Alex is the owner role. That administers people; it does not read Sam's
    bank account. A privacy setting with an admin backdoor is not one."""
    spend(conn, "sam-only", 30, "t-sam")
    conn.commit()
    as_person(conn, household["alex"])
    assert visible(conn) == set()


def test_no_viewer_set_sees_everything(conn, household):
    """The sync worker and a one-person install have nobody to be, and both
    need the whole picture."""
    spend(conn, "joint", 10, "t1")
    spend(conn, "alex-only", 20, "t2")
    spend(conn, "sam-only", 30, "t3")
    conn.commit()
    as_person(conn, None)
    assert visible(conn) == {"joint", "alex-only", "sam-only"}


def test_totals_follow_the_same_rule(conn, household):
    spend(conn, "joint", 10, "t1")
    spend(conn, "sam-only", 500, "t2")
    conn.commit()

    as_person(conn, household["alex"])
    assert conn.execute("SELECT coalesce(sum(spend),0) AS s FROM v_txn").fetchone()["s"] == D("10")
    as_person(conn, household["sam"])
    assert conn.execute("SELECT coalesce(sum(spend),0) AS s FROM v_txn").fetchone()["s"] == D("510")


def test_a_category_rollup_cannot_leak_a_private_total(conn, household):
    """v_category_months reads through v_txn, so the filter applies once rather
    than having to be remembered in every aggregate."""
    spend(conn, "sam-only", 500, "t1")
    conn.commit()
    as_person(conn, household["alex"])
    assert conn.execute("SELECT count(*) AS n FROM v_category_months").fetchone()["n"] == 0


# ---------------------------------------------------------------- owned things

def test_a_personal_fund_is_invisible_to_the_other_person(conn, household):
    conn.execute("INSERT INTO funds (name, target_amount, owner_id) VALUES ('Guitar', 900, %s)",
                 (household["sam"],))
    conn.execute("INSERT INTO funds (name, target_amount) VALUES ('Holiday', 2000)")
    conn.commit()

    as_person(conn, household["alex"])
    assert [f["name"] for f in funds.list_funds(conn)] == ["Holiday"]
    as_person(conn, household["sam"])
    assert sorted(f["name"] for f in funds.list_funds(conn)) == ["Guitar", "Holiday"]


def test_a_personal_budget_wins_over_the_household_one_for_its_owner(conn, household):
    conn.execute("INSERT INTO budgets (category, month, amount) VALUES ('groceries','2026-01-01',600)")
    conn.execute("INSERT INTO budgets (category, month, amount, owner_id) VALUES ('groceries','2026-01-01',150,%s)",
                 (household["sam"],))
    conn.commit()

    as_person(conn, household["alex"])
    assert budgets.effective(conn, date(2026, 1, 1))["groceries"]["amount"] == D("600.00")
    as_person(conn, household["sam"])
    assert budgets.effective(conn, date(2026, 1, 1))["groceries"]["amount"] == D("150.00")


def test_the_household_and_one_person_can_budget_the_same_category(conn, household):
    """The unique index keys on COALESCE(owner_id, 0), so a shared budget and a
    personal one coexist instead of colliding."""
    conn.execute("INSERT INTO budgets (category, month, amount) VALUES ('dining','2026-01-01',300)")
    conn.execute("INSERT INTO budgets (category, month, amount, owner_id) VALUES ('dining','2026-01-01',80,%s)",
                 (household["sam"],))
    conn.commit()
    assert conn.execute("SELECT count(*) AS n FROM budgets").fetchone()["n"] == 2

    with pytest.raises(Exception):   # but not the same scope twice
        conn.execute("INSERT INTO budgets (category, month, amount) VALUES ('dining','2026-01-01',999)")


# ---------------------------------------------------------------- removing people

def test_an_account_owner_cannot_be_deleted_out_from_under_their_accounts(conn, household):
    """ON DELETE RESTRICT: removing a person has to say what happens to their
    bank history, rather than silently dropping it or silently sharing it."""
    with pytest.raises(Exception):
        conn.execute("DELETE FROM people WHERE id = %s", (household["sam"],))


# ---------------------------------------------------------------- the account-level leak

def test_balances_do_not_leak_through_the_account_reads(conn, household):
    """v_txn hid the transactions; net worth, the debt list, fees and the
    assistant all read balances straight off the accounts table and would have
    shown the balance anyway. v_acct is the one filtered way in."""
    as_person(conn, household["alex"])
    ids = {r["id"] for r in conn.execute("SELECT id FROM v_acct").fetchall()}
    assert ids == {"joint", "alex-only"}

    total = conn.execute("SELECT coalesce(sum(current_balance),0) AS t FROM v_acct").fetchone()["t"]
    assert total == D("200")          # two accounts at 100, not three


def test_net_worth_and_the_plan_agree_with_the_privacy_rule(conn, household):
    from tally import plan
    as_person(conn, household["sam"])
    cash = plan.runway(conn, horizon_days=30)["cash"]
    assert cash == D("200")           # joint + sam's own, not alex's
