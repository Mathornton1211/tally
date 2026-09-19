"""A front door, for installs that do not have one already.

Tally holds a complete picture of a household's money. On the home server it sits behind
Authentik and this module adds nothing. Anywhere else -- a laptop, a NAS, a VPS
with a published port -- there is no Authentik, and "it is only on my LAN" is
not access control.

Two modes, chosen by TALLY_AUTH:

  password   Tally asks. Each person in the household has their own login, and
             the session says which of them is asking -- which is what makes a
             private account actually private.
  proxy      something in front has already authenticated. Tally trusts it and
             adds nothing. IMPORTANT: in this mode the person switcher is a
             convenience, not a wall -- anyone past the proxy can view as
             anyone. That is the right trade for a single-admin homelab and the
             wrong one for a shared household, which should use password mode.

The session is a Fernet token in an HttpOnly cookie carrying the person's id.
Fernet already signs and timestamps, so the TTL is the expiry: no session table,
no new dependency, no hand-rolled crypto. Rotating the Fernet key signs everyone
out, which is the behaviour you want from it.
"""
import json
import logging
import time
from collections import defaultdict

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse

log = logging.getLogger("tally.auth")

COOKIE = "tally_session"
SESSION_DAYS = 30
# Paths that must work before there is a session: the login page and its form,
# the health probe, the assets the login page is made of, and a share link,
# which carries its own token instead of a session.
OPEN_PREFIXES = ("/login", "/api/auth/", "/healthz", "/assets/", "/icons/",
                 "/manifest.webmanifest", "/sw.js", "/favicon", "/shared", "/api/shared/")


class Auth:
    def __init__(self, mode: str, box):
        self.mode = mode
        self.box = box
        if mode == "proxy":
            log.warning("TALLY_AUTH=proxy: this process trusts whatever is in front of it. "
                        "Do not publish its port without an authenticating proxy.")

    @property
    def enabled(self) -> bool:
        return self.mode == "password"

    def issue(self, person_id: int) -> bytes:
        return self.box.seal(json.dumps({"p": int(person_id)}))

    def person(self, cookie: str | None) -> int | None:
        """The person id in a valid, unexpired session, or None."""
        if not cookie:
            return None
        try:
            return int(json.loads(self.box.open(cookie.encode(), ttl=SESSION_DAYS * 86400))["p"])
        except Exception:
            return None


# ---------------------------------------------------------------- guessing
#
# scrypt makes each attempt expensive, but "expensive" on a LAN is still
# thousands of tries a day against a password somebody picked in a hurry during
# an install script. There is no WAF in front of a self-hosted app, so the lock
# has to be part of the lock.

FAIL_WINDOW = 15 * 60
FAIL_LIMIT = 10


class Attempts:
    """Failed sign-ins per source address, in a sliding window.

    In memory on purpose: only the API process serves the login form, a restart
    clearing the counter costs an attacker more than it costs them to wait, and
    a table here would be a write path reachable before anyone has signed in.
    """

    def __init__(self, limit: int = FAIL_LIMIT, window: int = FAIL_WINDOW):
        self.limit, self.window = limit, window
        self._fails: dict[str, list[float]] = defaultdict(list)

    def _recent(self, who: str) -> list[float]:
        cutoff = time.monotonic() - self.window
        keep = [t for t in self._fails[who] if t > cutoff]
        self._fails[who] = keep
        return keep

    def locked_for(self, who: str) -> int:
        """Seconds still to wait, or 0."""
        recent = self._recent(who)
        if len(recent) < self.limit:
            return 0
        return max(1, int(self.window - (time.monotonic() - recent[0])))

    def failed(self, who: str) -> None:
        self._recent(who)
        self._fails[who].append(time.monotonic())

    def passed(self, who: str) -> None:
        self._fails.pop(who, None)


def source(request: Request) -> str:
    """Who is knocking. Behind a proxy the client address is the proxy, so the
    forwarded address is used when one is present -- it is only ever a rate
    limit key, never a permission, so a spoofed value costs nothing but its
    own bucket."""
    fwd = request.headers.get("x-forwarded-for", "")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def guard(auth: Auth, request: Request) -> tuple[object | None, int | None]:
    """Returns (response that stops the request, person id for the database).

    The person id can be present in proxy mode too -- there it came from a
    switcher rather than a password, and it scopes the view without pretending
    to be a security boundary.
    """
    person = auth.person(request.cookies.get(COOKIE))
    if not auth.enabled:
        return None, person
    path = request.url.path
    if path.startswith(OPEN_PREFIXES) or person is not None:
        return None, person
    if path.startswith("/api/"):
        return JSONResponse({"detail": "sign in"}, status_code=401), None
    return RedirectResponse("/login", status_code=303), None


# ---------------------------------------------------------------- what a role may do
#
# Checked in ONE place -- the middleware -- rather than remembered in each of
# the forty-odd routes that change something. The visibility rule already
# taught this lesson the expensive way: a guard you have to remember is a guard
# that gets forgotten, and the forgetting is silent.

WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# An owner only, to read OR write. Reading these is itself sensitive: a share
# link's range says what data has been handed outside the household, and the
# item list is the set of banks that can be disconnected.
ADMIN_PATHS = ("/api/share-links", "/api/link/", "/api/items")

# Reading is fine; changing them is the household's shape and belongs to an owner.
ADMIN_WRITE_PATHS = ("/api/people", "/api/currency/home")

# ...except this, which is how any person edits their own name and password.
SELF_SERVICE = ("/api/people/me",)


def demo_refusal(method: str, path: str) -> str | None:
    """A public demo is real data, real code and a real database that strangers
    can read and nobody can change.

    Enforced here rather than by making the database read-only, because the app
    still has to write the things that make it work -- sessions, alert scans --
    and a read-only replica would break those too. Everything a visitor could
    press is refused with a sentence that explains why, which is more useful
    than a button that silently does nothing.
    """
    if method not in WRITE_METHODS:
        return None
    if path.startswith(("/api/auth/", "/api/alerts/scan")):
        return None
    return ("This is a public demo, so nothing can be changed. Every number here is real "
            "data from Plaid's sandbox -- install your own copy to connect a bank.")


def permission(pool, person_id: int | None, method: str, path: str) -> str | None:
    """A refusal to show the person, or None to let the request through.

    With nobody signed in -- proxy mode, or a one-person install -- there is no
    one to refuse and the proxy (or the absence of anyone else) is the boundary.
    """
    if person_id is None:
        return None
    write = method in WRITE_METHODS
    admin_path = path.startswith(ADMIN_PATHS)
    # A plain read is governed by tally_can_see(), not by roles. Skipping the
    # role lookup here keeps every page load free of an extra query.
    if not write and not admin_path:
        return None

    with pool.connection() as conn:
        row = conn.execute("SELECT role FROM people WHERE id = %s", (person_id,)).fetchone()
    if not row:
        return None
    role = row["role"]

    if write and role == "viewer":
        return "This account can look, but not change anything."
    if admin_path and role != "owner":
        return "Only a household owner can see or change this."
    if (write and role != "owner" and path.startswith(ADMIN_WRITE_PATHS)
            and not path.startswith(SELF_SERVICE)):
        return "Only a household owner can change the household."
    return None


def require_admin(conn, person_id: int | None):
    """Kept for the few checks that are finer than a path prefix. The blanket
    rule lives in permission(), above."""
    if person_id is None:
        return
    row = conn.execute("SELECT role FROM people WHERE id = %s", (person_id,)).fetchone()
    if not row or row["role"] != "owner":
        raise HTTPException(403, "only a household owner can change this")


LOGIN_PAGE = """<!doctype html>
<html lang="en"><head>
<meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Tally</title>
<style>
  :root { color-scheme: light dark; --page:#f5f5f1; --surface:#fff; --ink:#17181a; --ink-3:#898781;
          --line:rgba(24,24,18,.14); --accent:#127a57; --accent-ink:#fff; --bad:#b4302c; }
  @media (prefers-color-scheme: dark) { :root {
          --page:#0e0f0e; --surface:#171816; --ink:#ededea; --ink-3:#8e8d86;
          --line:rgba(255,255,255,.13); --accent:#3fbf8a; --accent-ink:#07170f; --bad:#ff8a80; } }
  * { box-sizing: border-box; }
  body { margin:0; min-height:100dvh; display:grid; place-items:center; background:var(--page);
         color:var(--ink); font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif; padding:16px; }
  form { width:100%; max-width:340px; background:var(--surface); border:1px solid var(--line);
         border-radius:20px; padding:28px 24px; }
  .logo { display:flex; align-items:center; gap:10px; margin-bottom:22px; }
  .logo span { font-size:17px; font-weight:600; letter-spacing:-.01em; }
  h1 { font-size:15px; font-weight:600; margin:0 0 4px; }
  p.lead { margin:0 0 18px; font-size:13px; color:var(--ink-3); }
  label { display:block; font-size:13px; font-weight:500; margin:12px 0 6px; }
  input { width:100%; height:42px; padding:0 12px; font-size:15px; color:var(--ink);
          background:transparent; border:1px solid var(--line); border-radius:12px; }
  input:focus { outline:none; border-color:var(--ink-3); }
  button { width:100%; height:42px; margin-top:16px; font-size:14px; font-weight:500;
           color:var(--accent-ink); background:var(--accent); border:0; border-radius:999px; cursor:pointer; }
  button:active { transform:scale(.99); }
  .bad { margin-top:12px; font-size:13px; color:var(--bad); }
</style></head>
<body>
<form method="post" action="__ACTION__">
  <div class="logo">
    <svg width="28" height="28" viewBox="0 0 32 32" aria-hidden>
      <rect width="32" height="32" rx="9" fill="var(--accent)"/>
      <path d="M9 11.5h14M16 11.5V23" stroke="var(--accent-ink)" stroke-width="3.2" stroke-linecap="round"/>
    </svg><span>Tally</span>
  </div>
  __BODY__
  __ERROR__
</form>
</body></html>"""

SIGN_IN_FIELDS = """
  <label for="username">Who are you</label>
  <input id="username" name="username" autofocus autocapitalize="none" autocomplete="username" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="current-password" required>
  <button type="submit">Sign in</button>
"""

FIRST_RUN_FIELDS = """
  <h1>Set up your account</h1>
  <p class="lead">Nobody has signed in to this Tally yet. This first account
  administers the household; you can add other people afterwards.</p>
  <label for="name">Your name</label>
  <input id="name" name="name" autofocus autocomplete="name" required>
  <label for="username">Username</label>
  <input id="username" name="username" autocapitalize="none" autocomplete="username" required>
  <label for="password">Password</label>
  <input id="password" name="password" type="password" autocomplete="new-password" minlength="8" required>
  <button type="submit">Create it</button>
"""


def page(first_run: bool, error: str = "") -> str:
    return (LOGIN_PAGE
            .replace("__ACTION__", "/api/auth/first-run" if first_run else "/api/auth/login")
            .replace("__BODY__", FIRST_RUN_FIELDS if first_run else SIGN_IN_FIELDS)
            .replace("__ERROR__", f'<div class="bad">{error}</div>' if error else ""))
