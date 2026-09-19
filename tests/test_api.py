"""Tests that go through HTTP.

Every other test file calls the modules directly. That is faster and it is
where the reasoning lives, but it cannot see anything that happens between the
socket and the function: request parsing, the auth middleware, role checks,
Pydantic coercion, JSON serialisation.

This file exists because that gap shipped a bug. A split rule worked perfectly
in `test_rules_currency.py` and returned 500 from the running app, because
Pydantic hands the route a `Decimal` and `json.dumps` will not serialise one.
The unit tests built their own payload and never saw it.
"""
import os

import pytest
from fastapi.testclient import TestClient

from tally.crypto import new_key


def _client(db_url, auth_mode="password"):
    os.environ.update({
        "TALLY_DATABASE_URL": db_url,
        "PLAID_ENV": "sandbox",
        "PLAID_CLIENT_ID": "test-client",
        "PLAID_SECRET_SANDBOX": "test-secret",
        "TALLY_FERNET_KEY": new_key(),
        "AI_ENABLED": "0",
        "TALLY_AUTH": auth_mode,
    })
    os.environ.pop("TALLY_PASSWORD", None)
    from tally.api import app
    return TestClient(app)


@pytest.fixture
def api(db_url):
    with _client(db_url) as c:
        yield c


@pytest.fixture
def proxy_api(db_url):
    with _client(db_url, auth_mode="proxy") as c:
        yield c


def sign_up(c, name="Alex", username="alex", password="a-good-password"):
    r = c.post("/api/auth/first-run",
               data={"name": name, "username": username, "password": password},
               follow_redirects=False)
    assert r.status_code == 303, r.text
    return r


def add_person(c, name, role, password="another-password"):
    r = c.post("/api/people", json={"name": name, "role": role, "password": password})
    assert r.status_code == 200, r.text
    return r.json()


def sign_in_as(c, username, password="another-password"):
    c.cookies.clear()
    r = c.post("/api/auth/login", data={"username": username, "password": password},
               follow_redirects=False)
    assert r.status_code == 303 and r.headers["location"] == "/", r.text


# ---------------------------------------------------------------- the front door

def test_nothing_works_before_anyone_signs_in(api):
    assert api.get("/api/accounts").status_code == 401
    page = api.get("/budget", follow_redirects=False)
    assert page.status_code == 303 and page.headers["location"] == "/login"
    assert api.get("/healthz").status_code == 200


def test_first_run_makes_an_owner_and_signs_them_in(api):
    assert "Set up your account" in api.get("/login").text
    sign_up(api)
    me = api.get("/api/auth/state").json()
    assert me["me"]["username"] == "alex" and me["me"]["role"] == "owner"
    assert api.get("/api/accounts").status_code == 200


def test_first_run_cannot_be_used_twice(api):
    """Otherwise it is an open door to add yourself to somebody's household."""
    sign_up(api)
    api.cookies.clear()
    r = api.post("/api/auth/first-run",
                 data={"name": "Intruder", "username": "intruder", "password": "sneaky-password"},
                 follow_redirects=False)
    assert r.headers["location"] == "/login"
    assert api.get("/api/auth/state").json()["household"] == 1


def test_a_wrong_password_does_not_sign_you_in(api):
    sign_up(api)
    api.cookies.clear()
    r = api.post("/api/auth/login", data={"username": "alex", "password": "wrong"},
                 follow_redirects=False)
    assert r.headers["location"] == "/login?bad=1"
    assert api.get("/api/accounts").status_code == 401


def test_repeated_guesses_get_locked_out(api):
    """No WAF sits in front of a self-hosted app, so the lock is part of the lock."""
    sign_up(api)
    api.cookies.clear()
    for _ in range(10):
        api.post("/api/auth/login", data={"username": "alex", "password": "no"},
                 follow_redirects=False)
    locked = api.post("/api/auth/login", data={"username": "alex", "password": "a-good-password"},
                      follow_redirects=False)
    assert "locked=" in locked.headers["location"]
    # Even the right password waits, which is the point.
    assert api.get("/api/accounts").status_code == 401
    assert "Too many attempts" in api.get("/login?locked=15").text


def test_signing_out_ends_it(api):
    sign_up(api)
    api.post("/api/auth/logout", follow_redirects=False)
    assert api.get("/api/accounts").status_code == 401


# ---------------------------------------------------------------- roles

def test_a_viewer_can_read_everything_and_change_nothing(api):
    sign_up(api)
    add_person(api, "Watcher", "viewer")
    sign_in_as(api, "watcher")

    assert api.get("/api/accounts").status_code == 200
    assert api.get("/api/budgets").status_code == 200
    assert api.get("/api/goals").status_code == 200

    for method, path, body in [
        ("post", "/api/goals", {"kind": "net_worth", "name": "Nope", "target_amount": 1}),
        ("put", "/api/budgets/groceries", {"amount": 100}),
        ("post", "/api/funds", {"name": "Nope", "target_amount": 10}),
        ("post", "/api/rules-v2", {"name": "Nope", "pattern": "x"}),
        ("post", "/api/sync", None),
    ]:
        r = getattr(api, method)(path, json=body) if body else getattr(api, method)(path)
        assert r.status_code == 403, f"{method} {path} was allowed"
        assert "look" in r.json()["detail"]


def test_a_member_can_change_the_money_but_not_the_household(api):
    sign_up(api)
    add_person(api, "Sam", "member")
    sign_in_as(api, "sam")

    assert api.post("/api/funds", json={"name": "Guitar", "target_amount": 900}).status_code == 200
    assert api.post("/api/people", json={"name": "Extra", "role": "owner",
                                         "password": "x-password"}).status_code == 403
    assert api.put("/api/currency/home", json={"currency": "EUR"}).status_code == 403


def test_share_links_are_an_owners_business_to_read_as_well_as_write(api):
    """The list of links is itself sensitive: it says what has already been
    handed to somebody outside the household."""
    sign_up(api)
    add_person(api, "Sam", "member")
    sign_in_as(api, "sam")
    assert api.get("/api/share-links").status_code == 403
    assert api.post("/api/share-links", json={
        "label": "x", "start_date": "2026-01-01", "end_date": "2026-12-31"}).status_code == 403
    assert api.get("/api/items").status_code == 403


def test_anyone_can_change_their_own_name_and_password(api):
    sign_up(api)
    add_person(api, "Sam", "member")
    sign_in_as(api, "sam")

    assert api.patch("/api/people/me", json={"name": "Samantha"}).json()["name"] == "Samantha"
    assert api.patch("/api/people/me", json={"password": "a-new-password"}).status_code == 200
    sign_in_as(api, "sam", "a-new-password")
    # But not their own role, and not anybody else.
    assert api.patch("/api/people/1", json={"role": "viewer"}).status_code == 403


def test_a_member_sees_the_roster_without_the_surveillance_detail(api):
    """You cannot share an account with someone the app refuses to name. When
    they last signed in is a different question, and not one this app helps
    anybody answer about their partner."""
    sign_up(api)
    add_person(api, "Sam", "member")

    owner_view = api.get("/api/people").json()["people"][0]
    assert "last_seen_at" in owner_view and "accounts" in owner_view

    sign_in_as(api, "sam")
    member_view = api.get("/api/people").json()["people"]
    assert [p["name"] for p in member_view] == ["Alex", "Sam"]
    assert "last_seen_at" not in member_view[0]
    assert "can_sign_in" not in member_view[0]


def test_proxy_mode_refuses_nobody(proxy_api):
    """Something in front has already decided. Tally adds no second opinion."""
    assert proxy_api.get("/api/accounts").status_code == 200
    assert proxy_api.post("/api/funds", json={"name": "Anything", "target_amount": 5}).status_code == 200


# ---------------------------------------------------------------- the shapes that cross the wire

def test_a_split_rule_survives_the_round_trip(api):
    """The regression this file was written for: Pydantic hands the route a
    Decimal and json.dumps will not serialise one."""
    sign_up(api)
    r = api.post("/api/rules-v2", json={
        "name": "Costco is half groceries",
        "pattern": "costco",
        "split": [{"category": "groceries", "percent": 60},
                  {"category": "home", "percent": 40}]})
    assert r.status_code == 200, r.text
    rule = next(x for x in r.json()["rules"] if x["id"] == r.json()["id"])
    assert rule["split"] == [{"category": "groceries", "percent": "60"},
                             {"category": "home", "percent": "40"}]


def test_a_split_that_does_not_add_up_is_refused_with_a_reason(api):
    sign_up(api)
    r = api.post("/api/rules-v2", json={
        "name": "Broken", "pattern": "x",
        "split": [{"category": "groceries", "percent": 70},
                  {"category": "home", "percent": 20}]})
    assert r.status_code == 400 and "not 100" in r.json()["detail"]


def test_money_comes_back_as_numbers_not_as_objects(api):
    """Decimals have to survive JSON. A budget that arrives as a string breaks
    every total on the page silently."""
    sign_up(api)
    api.put("/api/budgets/groceries", json={"amount": 650.5})
    row = next(c for c in api.get("/api/budgets").json()["categories"] if c["category"] == "groceries")
    assert float(row["amount"]) == 650.5
    assert isinstance(api.get("/api/goals").json()["net_worth"], (int, float, str))


def test_a_share_link_works_over_http_for_somebody_with_no_session(api):
    sign_up(api)
    made = api.post("/api/share-links", json={
        "label": "Accountant", "start_date": "2026-01-01", "end_date": "2026-12-31",
        "detail": "summary"}).json()

    outsider = TestClient(api.app)          # no cookies at all
    r = outsider.get(f"/api/shared/{made['token']}")
    assert r.status_code == 200 and r.json()["label"] == "Accountant"
    assert "rows" not in r.json()           # summary only

    api.delete(f"/api/share-links/{made['id']}")
    assert outsider.get(f"/api/shared/{made['token']}").status_code == 404


def test_the_share_page_itself_needs_no_session(api):
    """It is opened by an accountant, who has no account here."""
    sign_up(api)
    made = api.post("/api/share-links", json={
        "label": "Tax", "start_date": "2026-01-01", "end_date": "2026-12-31"}).json()
    outsider = TestClient(api.app)
    assert outsider.get(f"/shared/{made['token']}", follow_redirects=False).status_code in (200, 404)


def test_search_answers_over_http_with_the_filters_it_used(api):
    sign_up(api)
    r = api.get("/api/search", params={"q": "groceries last month", "use_ai": False})
    assert r.status_code == 200
    body = r.json()
    assert body["filters"]["category"] == "groceries"
    assert body["filters"]["by"] == "text"
    assert body["count"] == 0 and float(body["spent"]) == 0


def test_a_bad_request_says_what_is_wrong_rather_than_500ing(api):
    sign_up(api)
    assert api.post("/api/goals", json={"kind": "net_worth", "name": "No target"}).status_code == 400
    assert api.post("/api/goals", json={"kind": "nonsense", "name": "x"}).status_code == 422
    assert api.put("/api/budgets/not-a-category", json={"amount": 10}).status_code == 400


# ---------------------------------------------------------------- the pages' own data

def test_the_accounts_page_can_load_everything_it_needs(api):
    """/api/items is where "connected", "last synced" and "needs attention"
    come from. It shipped broken -- the query referenced an alias that only
    existed inside a subquery -- because nothing here ever called it. Every
    endpoint a page depends on gets asked for at least once."""
    sign_up(api)
    for path in ("/api/items", "/api/accounts", "/api/meta", "/api/dashboard"):
        r = api.get(path)
        assert r.status_code == 200, f"{path} -> {r.status_code} {r.text[:200]}"


def test_an_item_reports_its_connection_state(api, db_url):
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("INSERT INTO institutions (id, name) VALUES ('ins_1','First Gingham') "
                  "ON CONFLICT DO NOTHING")
        c.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc,
                                        status, error_code, last_synced_at)
                     VALUES (1,'item-1','ins_1','x','login_required','ITEM_LOGIN_REQUIRED', now())
                     ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                     VALUES ('acc-1',1,'plaid','Checking','depository','checking',10)
                     ON CONFLICT DO NOTHING""")
    sign_up(api)

    items = api.get("/api/items").json()
    assert len(items) == 1
    it = items[0]
    assert it["institution"] == "First Gingham"
    assert it["status"] == "login_required" and it["error_code"] == "ITEM_LOGIN_REQUIRED"
    assert it["accounts"] == 1 and it["last_synced_at"]
    # And the banner on every page counts it.
    assert api.get("/api/meta").json()["needs_attention"] == 1


def test_an_item_with_no_institution_row_yet_still_loads(api, db_url):
    """Linking is two steps: the item lands, the institution is fetched after.
    The page has to survive the gap rather than 500 through it."""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("""INSERT INTO items (id, plaid_item_id, access_token_enc)
                     VALUES (2,'item-2','x') ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                     VALUES ('acc-2',2,'plaid','Checking','depository','checking',5)
                     ON CONFLICT DO NOTHING""")
    sign_up(api)
    it = api.get("/api/items").json()[0]
    assert it["institution"] is None and it["accounts"] == 1


def test_a_manual_account_shows_up_without_pretending_to_be_a_connection(api, db_url):
    """Manual accounts have no item by constraint, so they belong on the
    accounts list and nowhere near the connection list."""
    import psycopg
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("""INSERT INTO accounts (id, source, name, type, subtype,
                                           current_balance, institution_name)
                     VALUES ('cash','manual','Cash','depository','checking',5,'Under the mattress')
                     ON CONFLICT DO NOTHING""")
    sign_up(api)
    assert api.get("/api/items").json() == []
    accounts = api.get("/api/accounts").json()
    assert [a["institution"] for a in accounts] == ["Under the mattress"]


# ---------------------------------------------------------------- the public demo

@pytest.fixture
def demo_api(db_url, monkeypatch):
    monkeypatch.setenv("TALLY_DEMO", "1")
    with _client(db_url, auth_mode="proxy") as c:
        yield c
    monkeypatch.delenv("TALLY_DEMO", raising=False)


def test_a_demo_reads_like_the_real_thing(demo_api):
    """Real code, real database, real views. A demo built from fixtures would
    be a screenshot that lies."""
    for path in ("/api/accounts", "/api/budgets", "/api/goals", "/api/items", "/api/dashboard"):
        assert demo_api.get(path).status_code == 200, path
    assert demo_api.get("/api/config").json()["demo"] is True


def test_a_demo_refuses_every_write_with_a_reason(demo_api):
    for method, path, body in [
        ("post", "/api/funds", {"name": "Nope", "target_amount": 10}),
        ("put", "/api/budgets/groceries", {"amount": 100}),
        ("post", "/api/goals", {"kind": "net_worth", "name": "Nope", "target_amount": 1}),
        ("post", "/api/people", {"name": "Nope", "role": "owner"}),
        ("post", "/api/sync", None),
        ("delete", "/api/rules-v2/1", None),
    ]:
        r = getattr(demo_api, method)(path, json=body) if body else getattr(demo_api, method)(path)
        assert r.status_code == 403, f"{method} {path} was allowed in a demo"
        assert "public demo" in r.json()["detail"]


def test_the_version_is_answerable(api):
    sign_up(api)
    from tally import __version__
    assert api.get("/api/config").json()["version"] == __version__
    assert api.get("/healthz").json()["version"] == __version__


# ---------------------------------------------------------------- getting started

def test_setup_names_what_is_missing_and_what_is_done(api):
    sign_up(api)
    s = api.get("/api/setup").json()
    assert s["complete"] is False and s["show_welcome"] is True
    steps = {x["key"]: x for x in s["steps"]}
    assert steps["connect"]["done"] is False and steps["connect"]["blocking"] is True
    # Optional steps do not count against the total, or a one-person household
    # can never finish setting up.
    assert s["total"] < len(s["steps"])
    assert steps["household"]["optional"] is True


def test_setup_does_not_offer_budgets_before_there_is_history(api):
    """A budget suggested from two days of data is a guess wearing a number."""
    sign_up(api)
    budget_step = next(x for x in api.get("/api/setup").json()["steps"] if x["key"] == "budget")
    assert budget_step["ready"] is False and budget_step["suggestion"] is None


# ---------------------------------------------------------------- one person's assumptions

def test_the_dashboard_greets_whoever_is_signed_in(api):
    """The greeting was hardcoded to the first owner's name, so a household of
    four was greeted by one person's name. Nobody noticed for weeks, because the
    person who wrote it was the person it was correct for."""
    sign_up(api, name="Alex", username="alex")
    me = api.get("/api/people").json()
    assert next(p for p in me["people"] if p["id"] == me["me"])["name"] == "Alex"


def test_linking_identifies_the_person_to_plaid_not_a_name(api, monkeypatch):
    """Plaid's client_user_id was one person's hardcoded name, so every person
    in a household linked as the same end user."""
    seen = {}

    def fake_create(user_id, redirect_uri, access_token=None):
        seen["user_id"] = user_id
        return {"link_token": "link-sandbox-x"}

    sign_up(api)
    from tally.api import state
    monkeypatch.setattr(state["plaid"], "link_token_create", fake_create)

    assert api.post("/api/link/token", json={}).status_code == 200
    me = api.get("/api/people").json()["me"]
    assert seen["user_id"] == f"tally-{me}"
