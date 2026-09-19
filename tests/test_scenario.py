"""Questions about the future: "if I took a job at $120k, when am I debt free?"

Two things make this dangerous rather than merely hard.

The first is that a salary is gross and a budget is net. Somebody saying
"$120k" has around $7,200 a month, not $10,000. Planning on the $10,000 does
not produce a slightly optimistic date, it produces a date that is wrong by a
third of the money, delivered with a straight face.

The second is that there is no SQL for it. The figures are computed FROM the
history rather than found in it, which means nothing in the query path can
check them, and a projected payoff date is exactly the sort of number a model
will invent if it is asked to.
"""
from datetime import date, timedelta
from decimal import Decimal

import pytest

from tally import chat, plan, scenario

D = Decimal


# ---------------------------------------------------------------- take-home

def test_a_salary_is_not_a_budget():
    """The error this whole module exists to prevent."""
    t = scenario.take_home(D(120000))
    assert t["gross_monthly"] == D("10000.00")
    # Nowhere near it. If this ever drifts up to the gross figure, every payoff
    # date Tally gives is a lie.
    assert D("6500") < t["net_monthly"] < D("8000")
    assert t["estimate"] is True and t["tax_year"]


def test_the_estimate_can_be_argued_with():
    """A number nobody can take apart is one nobody should act on."""
    t = scenario.take_home(D(120000))
    total = t["federal"] + t["social_security"] + t["medicare"] + t["state"]
    assert t["net_annual"] == t["gross_annual"] - total
    assert "single filer" in t["assumes"] and "state tax" in t["assumes"]


def test_it_is_progressive_not_a_flat_rate():
    low, high = scenario.take_home(D(40000)), scenario.take_home(D(300000))
    assert low["effective_rate"] < high["effective_rate"]


def test_social_security_stops_at_the_wage_base():
    """Above the cap the extra salary pays no more social security, so a flat
    percentage would over-tax a high earner."""
    big = scenario.take_home(D(400000))
    assert big["social_security"] == (scenario.SOCIAL_SECURITY_WAGE_BASE
                                      * scenario.SOCIAL_SECURITY_RATE).quantize(D("0.01"))


def test_a_stated_take_home_is_used_as_given():
    """Somebody who knows their own payslip should not be second-guessed."""
    cols, rows = _facts_for({"monthly_take_home": 7000})
    line = _row(rows, "take-home pay")
    assert line["amount"] == D("7000.00") and "as stated" in line["note"]


# ---------------------------------------------------------------- the scenario

def base(conn):
    conn.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
    conn.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                    VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('chk',1,'plaid','Checking','depository','checking',500)
                    ON CONFLICT (id) DO NOTHING""")


def spend(conn, days_ago, amount, category, i=0):
    conn.execute("""INSERT INTO transactions (id, account_id, amount, date, name, category,
                        pfc_primary, pfc_detailed, raw)
                    VALUES (%s,'chk',%s,%s,'STORE',%s,'FOOD_AND_DRINK','FOOD_AND_DRINK_RESTAURANT','{}')""",
                 (f"s{days_ago}-{category}-{i}", amount, date.today() - timedelta(days=days_ago), category))


@pytest.fixture
def household(conn):
    """Three months of a real-ish life: $2,150 rent, some bills, and a card."""
    base(conn)
    for i in range(3):
        spend(conn, 30 * i + 1, 2150, "rent", i)
        spend(conn, 30 * i + 2, 300, "groceries", i)
        spend(conn, 30 * i + 3, 400, "dining", i)          # flexible
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance, credit_limit)
                    VALUES ('card',1,'plaid','Card','credit','credit card',8000,10000)""")
    conn.execute("""INSERT INTO liabilities (account_id, kind, apr, minimum_payment, next_due_date, source)
                    VALUES ('card','credit',24.99,200,current_date + 10,'test')""")
    conn.commit()
    return conn


_state = {}


def _facts_for(asked):
    return chat.scenario_facts(_state["conn"], asked)


def _row(rows, figure):
    return next(r for r in rows if r["figure"] == figure)


@pytest.fixture(autouse=True)
def _wire(conn):
    _state["conn"] = conn
    yield


def test_the_question_that_used_to_get_no_answer(household):
    """"If I make $120k and rent goes to $1,600, how long to pay off my debts
    while keeping my lifestyle?" -- the app said it did not have enough
    information while the planner sat one import away."""
    cols, rows = chat.scenario_facts(household, {"annual_salary": 120000, "rent": 1600})

    assert cols == ["figure", "amount", "note"]
    assert _row(rows, "debt free in")["amount"] > 0
    assert _row(rows, "debt free on")["amount"] > date.today()
    # The answer must carry its own caveat, not bury it.
    assert "ESTIMATED" in _row(rows, "take-home pay")["note"]


def test_the_new_rent_replaces_the_old_one_and_says_so(household):
    rows = chat.scenario_facts(household, {"annual_salary": 120000, "rent": 1600})[1]
    changed = _row(rows, "rent, changed")
    assert changed["amount"] == D("1600.00")
    assert "2150" in changed["note"]      # what it was measured at, so it is checkable


def test_changing_rent_leaves_every_other_measured_cost_alone(household):
    """Moving house changes rent. It does not change the grocery bill, and an
    app that quietly re-estimates everything is one whose numbers cannot be
    traced back to anything."""
    before = plan.what_if(household, D(7000), D(0), D(0))
    after = plan.what_if(household, D(7000), D(0), D(0), overrides={"rent": D(1600)})
    assert after["essentials_by_category"]["groceries"] == before["essentials_by_category"]["groceries"]
    assert before["essentials"] - after["essentials"] == D("550.00")   # 2150 - 1600


def test_keeping_your_lifestyle_means_cutting_nothing(household):
    rows = chat.scenario_facts(household, {"annual_salary": 120000, "rent": 1600})[1]
    assert "unchanged" in _row(rows, "everything else you spend")["note"]


def test_a_plan_that_does_not_balance_gets_no_payoff_date(household):
    """A cheerful date computed from money that is not there is worse than no
    answer at all."""
    rows = chat.scenario_facts(household, {"monthly_take_home": 1200})[1]
    assert _row(rows, "left over")["amount"] < 0
    assert not any(r["figure"] == "debt free on" for r in rows)


def test_more_money_pays_it_off_sooner(household):
    lean = chat.scenario_facts(household, {"monthly_take_home": 4000})[1]
    flush = chat.scenario_facts(household, {"monthly_take_home": 9000})[1]
    assert _row(flush, "debt free in")["amount"] < _row(lean, "debt free in")["amount"]


def test_it_refuses_rather_than_guessing_an_income(household):
    with pytest.raises(chat.ChatError):
        chat.scenario_facts(household, {"rent": 1600})


def test_every_figure_in_the_answer_is_checkable(household):
    """The whole point of returning rows: the existing verifier can hold a
    what-if answer to the same standard as a query answer."""
    from tally.llm import unverified_figures
    rows = chat.scenario_facts(household, {"annual_salary": 120000, "rent": 1600})[1]
    table = [{k: float(v) if isinstance(v, Decimal) else v for k, v in r.items()} for r in rows]
    take = _row(rows, "take-home pay")["amount"]
    assert not unverified_figures(f"You would take home about ${take:,.2f} a month.", table)
    assert unverified_figures("You would take home about $99,999.00 a month.", table)


# ---------------------------------------------------------------- what is not there

def test_it_notices_when_housing_is_missing_entirely(conn):
    """Found on real data: measured rent was $13.97 a month -- two charges on a
    rewards card that Plaid tags as rent. The rent itself was paid from an
    account Tally could not see. Nothing calculated anything wrongly; every
    projection was simply short by the largest bill there is, silently."""
    base(conn)
    for i in range(3):
        spend(conn, 30 * i + 1, 300, "groceries", i)
        spend(conn, 30 * i + 2, 20, "rent", i)        # a rewards card artefact
    conn.commit()

    gap = next(g for g in plan.data_gaps(conn) if g["key"] == "housing")
    assert gap["measured"] < plan.HOUSING_FLOOR
    assert "too optimistic" in gap["detail"]


def test_a_real_rent_is_not_reported_as_missing(household):
    """The false positive that would make this feature noise."""
    assert not any(g["key"] == "housing" for g in plan.data_gaps(household))


def test_a_mortgage_counts_as_housing(conn):
    """Somebody who owns is not missing a rent payment, and nagging them about
    it is how a warning gets ignored."""
    base(conn)
    conn.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                    VALUES ('m',1,'plaid','Home Loan','loan','mortgage',250000)""")
    conn.commit()
    assert not any(g["key"] == "housing" for g in plan.data_gaps(conn))


def test_the_gap_travels_with_the_answer(conn):
    base(conn)
    for i in range(3):
        spend(conn, 30 * i + 1, 300, "groceries", i)
    conn.commit()
    rows = chat.scenario_facts(conn, {"monthly_take_home": 5000})[1]
    assert any(r["figure"].startswith("MISSING") for r in rows)


def test_stating_the_rent_answers_the_gap(conn):
    """Someone who says "rent will be $1,600" has told Tally the thing it was
    missing, and repeating the warning back at them is noise."""
    base(conn)
    for i in range(3):
        spend(conn, 30 * i + 1, 300, "groceries", i)
    conn.commit()
    rows = chat.scenario_facts(conn, {"monthly_take_home": 5000, "rent": 1600})[1]
    assert not any(r["figure"].startswith("MISSING") for r in rows)
    assert any(r["figure"] == "rent, changed" for r in rows)
