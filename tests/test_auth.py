"""The front door, and the privacy rule behind it."""
import time

import pytest
from cryptography.fernet import Fernet

from tally import auth, people
from tally.crypto import TokenBox, new_key


def make(mode="password"):
    return auth.Auth(mode, TokenBox(new_key()))


class FakeRequest:
    def __init__(self, path, cookies=None):
        self.url = type("U", (), {"path": path})()
        self.cookies = cookies or {}


# ---------------------------------------------------------------- passwords

def test_the_right_password_opens_it_and_a_near_miss_does_not():
    h = people.make_hash("correct horse")
    assert people.verify(h, "correct horse")
    assert not people.verify(h, "correct hors")
    assert not people.verify(h, "")
    assert not people.verify(None, "anything")


def test_the_same_password_twice_gives_different_hashes():
    """Per-person salt: two people who pick the same password must not end up
    with the same row, and a leaked hash must not answer for both."""
    assert people.make_hash("same") != people.make_hash("same")
    assert people.verify(people.make_hash("same"), "same")


def test_a_hash_from_a_different_scheme_is_refused_rather_than_crashing():
    assert not people.verify("bcrypt$whatever", "x")
    assert not people.verify("garbage", "x")


# ---------------------------------------------------------------- sessions

def test_a_session_carries_the_person_and_survives_a_round_trip():
    a = make()
    assert a.person(a.issue(7).decode()) == 7
    assert a.person("not-a-token") is None
    assert a.person(None) is None


def test_a_session_from_another_install_is_rejected():
    a, b = make(), make()
    assert b.person(a.issue(1).decode()) is None


def test_an_expired_session_does_not_pass():
    k = new_key()
    a = auth.Auth("password", TokenBox(k))
    stale = Fernet(k.encode()).encrypt_at_time(
        b'{"p": 1}', int(time.time()) - auth.SESSION_DAYS * 86400 - 60)
    assert a.person(stale.decode()) is None
    assert a.person(Fernet(k.encode()).encrypt_at_time(b'{"p": 1}', int(time.time())).decode()) == 1


# ---------------------------------------------------------------- the guard

def test_proxy_mode_lets_everything_through():
    a = make("proxy")
    assert not a.enabled
    assert auth.guard(a, FakeRequest("/api/accounts")) == (None, None)


def test_proxy_mode_still_reads_who_is_being_viewed_as():
    """The switcher scopes the view; the proxy is the actual wall."""
    a = make("proxy")
    _, person = auth.guard(a, FakeRequest("/api/budgets", {auth.COOKIE: a.issue(3).decode()}))
    assert person == 3


def test_an_unauthenticated_page_goes_to_login_and_the_api_gets_a_401():
    a = make()
    page, _ = auth.guard(a, FakeRequest("/budget"))
    assert page.status_code == 303 and page.headers["location"] == "/login"
    api, _ = auth.guard(a, FakeRequest("/api/budgets"))
    assert api.status_code == 401


def test_the_login_page_health_check_and_share_links_stay_open():
    a = make()
    for path in ("/login", "/api/auth/login", "/healthz", "/assets/index-abc.js",
                 "/shared/abc123", "/api/shared/abc123/summary"):
        assert auth.guard(a, FakeRequest(path))[0] is None, path


def test_a_signed_in_request_passes_and_names_the_person():
    a = make()
    blocked, person = auth.guard(a, FakeRequest("/api/budgets", {auth.COOKIE: a.issue(42).decode()}))
    assert blocked is None and person == 42


# ---------------------------------------------------------------- roles

class FakePool:
    """permission() takes the pool rather than a connection, because it runs in
    the middleware before any route has opened one."""

    def __init__(self, conn):
        self._conn = conn

    def connection(self):
        from contextlib import contextmanager

        @contextmanager
        def held():
            yield self._conn
        return held()


def test_a_viewer_may_read_but_not_write(conn):
    viewer = people.create(conn, "Viewer", "viewer", "password123", role="viewer")
    conn.commit()
    pool = FakePool(conn)
    assert auth.permission(pool, viewer["id"], "GET", "/api/budgets") is None
    assert "look" in auth.permission(pool, viewer["id"], "POST", "/api/goals")
    assert "look" in auth.permission(pool, viewer["id"], "DELETE", "/api/funds/1")


def test_only_an_owner_reaches_the_household_and_the_share_links(conn):
    boss = people.create(conn, "Boss", "boss", "password123", role="owner")
    member = people.create(conn, "Member", "member", "password123", role="member")
    conn.commit()
    pool = FakePool(conn)

    # Reading a share link list is itself sensitive: it says what has already
    # gone outside the household.
    assert auth.permission(pool, member["id"], "GET", "/api/share-links")
    assert auth.permission(pool, member["id"], "POST", "/api/people") 
    assert auth.permission(pool, boss["id"], "GET", "/api/share-links") is None
    assert auth.permission(pool, boss["id"], "POST", "/api/people") is None

    # A member still runs their own money, and still edits themselves.
    assert auth.permission(pool, member["id"], "POST", "/api/funds") is None
    assert auth.permission(pool, member["id"], "PATCH", "/api/people/me") is None


def test_nobody_signed_in_is_not_refused(conn):
    """Proxy mode and one-person installs have no person to check, and the
    proxy (or the absence of anyone else) is the boundary there."""
    pool = FakePool(conn)
    assert auth.permission(pool, None, "DELETE", "/api/people/1") is None
    auth.require_admin(conn, None)


def test_the_limiter_locks_after_enough_wrong_guesses():
    a = auth.Attempts(limit=3, window=900)
    assert a.locked_for("1.2.3.4") == 0
    for _ in range(3):
        a.failed("1.2.3.4")
    assert a.locked_for("1.2.3.4") > 0
    # One address being locked does not lock anybody else out.
    assert a.locked_for("5.6.7.8") == 0
    # And a success clears the slate.
    a.passed("1.2.3.4")
    assert a.locked_for("1.2.3.4") == 0


def test_bootstrap_runs_once(conn):
    first = people.bootstrap(conn, "install-time-password")
    assert first and first["role"] == "owner"
    assert people.verify(people.by_username(conn, "me")["password_hash"], "install-time-password")
    # A second call must not resurrect a person who was deliberately removed.
    assert people.bootstrap(conn, "different") is None
