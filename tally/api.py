"""HTTP API and the static web build.

Authentication depends on the install. Behind Authentik (the homelab deploy)
this process adds nothing and its port is never published. A standalone install
has nothing in front of it, so TALLY_AUTH=password puts a front door on it --
see tally/auth.py.
"""
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse
from starlette.concurrency import run_in_threadpool
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import __version__, auth, config, db, people, scope, sync
from .routes_data import router as data_router
from .routes_protect import router as protect_router
from .routes_ai import router as ai_router
from .routes_budgets import router as budgets_router
from .routes_people import router as people_router
from .routes_more import router as more_router
from .routes_rules import router as rules_router
from .routes_plan import router as plan_router
from .routes_export import router as export_router
from .routes_funds import router as funds_router
from .routes_manual import router as manual_router
from .routes_receipts import router as receipts_router
from .llm import LLM
from .notify import Notifier
from .state import state
from .crypto import TokenBox
from .plaid import Plaid, PlaidError

log = logging.getLogger("tally.api")
WEB_DIST = Path(__file__).resolve().parent.parent / "web" / "dist"


@asynccontextmanager
async def lifespan(app: FastAPI):
    s = config.load()
    # Say it now, not during the deploy that first needs it.
    problem = db.check_dump_dir()
    if problem:
        log.warning("no rollback point available before the next schema change: %s. "
                    "The next migration will refuse to run.", problem)
    applied = db.migrate(s.database_url)
    if applied:
        log.info("applied migrations: %s", applied)
    state["settings"] = s
    state["pool"] = db.pool(s.database_url)
    state["plaid"] = Plaid(s.plaid_host, s.plaid_client_id, s.plaid_secret)
    state["box"] = TokenBox(s.fernet_key)
    state["auth"] = auth.Auth(s.auth_mode, state["box"])
    state["attempts"] = auth.Attempts()
    # An install that already had a single TALLY_PASSWORD becomes a household of
    # one, without anybody having to do anything. Runs only on an empty people
    # table, so it cannot resurrect a person who was deliberately removed.
    if s.auth_password:
        with state["pool"].connection() as conn:
            if people.bootstrap(conn, s.auth_password):
                log.info("created the first person from TALLY_PASSWORD")
    state["llm"] = LLM(pool=state["pool"]) if s.ai_enabled else None
    state["notifier"] = Notifier(pool=state["pool"])
    yield
    state["pool"].close()


app = FastAPI(title="Tally", lifespan=lifespan)


@app.middleware("http")
async def gate(request: Request, call_next):
    """The one place that decides three things: whether the request gets in at
    all, what the database will let it see, and whether its role may do it.

    All three were sprinkled across routes at some point in this app's life and
    all three got forgotten somewhere. Here they cannot be.
    """
    blocked, person = auth.guard(state["auth"], request)
    if blocked is not None:
        return blocked
    if state["settings"].demo:
        refusal = auth.demo_refusal(request.method, request.url.path)
        if refusal:
            return JSONResponse({"detail": refusal}, status_code=403)
    if person is not None:
        # Sync DB call from an async middleware, so off the event loop. Only
        # writes and admin paths reach it; ordinary reads never pay for it.
        refusal = await run_in_threadpool(
            auth.permission, state["pool"], person, request.method, request.url.path)
        if refusal:
            return JSONResponse({"detail": refusal}, status_code=403)
    token = scope.viewer.set(person)
    try:
        return await call_next(request)
    finally:
        scope.viewer.reset(token)


def _nobody_yet() -> bool:
    with state["pool"].connection() as conn:
        return people.count(conn) == 0


def _sign_in(person_id: int, to: str = "/"):
    r = RedirectResponse(to, status_code=303)
    r.set_cookie(auth.COOKIE, state["auth"].issue(person_id).decode(),
                 max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax")
    return r


@app.get("/login", include_in_schema=False)
def login_page(bad: int = 0, taken: int = 0, locked: int = 0):
    if not state["auth"].enabled:
        return RedirectResponse("/", status_code=303)
    first = _nobody_yet()
    error = ("That username is already taken." if taken
             else f"Too many attempts. Try again in about {locked} minutes." if locked
             else "Check the username and password." if bad else "")
    return HTMLResponse(auth.page(first, error))


@app.post("/api/auth/first-run", include_in_schema=False)
def first_run(name: str = Form(...), username: str = Form(...), password: str = Form(...)):
    """Only ever works on an empty people table, so it cannot be used to add an
    account to a household that already exists."""
    if not state["auth"].enabled:
        return RedirectResponse("/", status_code=303)
    username = username.strip().lower()
    if not people.USERNAME.match(username) or len(password) < 8:
        return RedirectResponse("/login?bad=1", status_code=303)
    with state["pool"].connection() as conn:
        if people.count(conn) > 0:
            return RedirectResponse("/login", status_code=303)
        person = people.create(conn, name, username, password, role="owner")
    return _sign_in(person["id"])


@app.post("/api/auth/login", include_in_schema=False)
def login(request: Request, username: str = Form(...), password: str = Form(...)):
    a = state["auth"]
    if not a.enabled:
        return RedirectResponse("/", status_code=303)
    who = auth.source(request)
    wait = state["attempts"].locked_for(who)
    if wait:
        log.warning("login locked out for %s, %ss remaining", who, wait)
        return RedirectResponse(f"/login?locked={wait // 60 + 1}", status_code=303)
    with state["pool"].connection() as conn:
        person = people.by_username(conn, username)
        # Verify even when the username is unknown, so a wrong username and a
        # wrong password take the same time to answer.
        ok = people.verify(person["password_hash"] if person else None, password)
        if not ok:
            state["attempts"].failed(who)
            return RedirectResponse("/login?bad=1", status_code=303)
        people.touch(conn, person["id"])
    state["attempts"].passed(who)
    return _sign_in(person["id"])


@app.post("/api/auth/logout", include_in_schema=False)
def logout():
    r = RedirectResponse("/login", status_code=303)
    r.delete_cookie(auth.COOKIE)
    return r


@app.get("/api/auth/state")
def auth_state(request: Request):
    a = state["auth"]
    person_id = a.person(request.cookies.get(auth.COOKIE))
    with state["pool"].connection() as conn:
        me = people.get(conn, person_id) if person_id else None
        household = people.count(conn)
    return {"mode": a.mode, "required": a.enabled, "me": me, "household": household}
app.include_router(data_router)
app.include_router(protect_router)
app.include_router(ai_router)
app.include_router(plan_router)
app.include_router(receipts_router)
app.include_router(manual_router)
app.include_router(export_router)
app.include_router(funds_router)
app.include_router(budgets_router)
app.include_router(people_router)
app.include_router(rules_router)
app.include_router(more_router)


def _plaid_http(e: PlaidError) -> HTTPException:
    return HTTPException(status_code=502, detail={"plaid_error": e.code, "message": str(e)})


@app.get("/healthz")
def healthz():
    with state["pool"].connection() as conn:
        conn.execute("SELECT 1")
    return {"ok": True, "version": __version__}


@app.get("/api/config")
def api_config():
    s = state["settings"]
    return {"version": __version__, "plaid_env": s.plaid_env,
            "oauth_ready": s.redirect_uri is not None,
            "timezone": db.session_timezone(),
            "ai_enabled": s.ai_enabled,
            "demo": s.demo}


# ---------------------------------------------------------------- linking

class LinkTokenIn(BaseModel):
    item_id: int | None = None


@app.post("/api/link/token")
def link_token(body: LinkTokenIn):
    s = state["settings"]
    access_token = None
    if body.item_id is not None:
        with state["pool"].connection() as conn:
            row = conn.execute("SELECT access_token_enc FROM items WHERE id = %s",
                               (body.item_id,)).fetchone()
        if not row:
            raise HTTPException(404, "no such item")
        access_token = state["box"].open(row["access_token_enc"])
    try:
        # Plaid wants a stable id for whoever is linking, not a display name.
        # It was hardcoded to the first owner's, so every person in a household
        # linked as the same end user.
        user_id = f"tally-{scope.viewer.get() or 'household'}"
        resp = state["plaid"].link_token_create(user_id, s.redirect_uri, access_token)
    except PlaidError as e:
        raise _plaid_http(e)
    return {"link_token": resp["link_token"]}


class ExchangeIn(BaseModel):
    public_token: str


@app.post("/api/link/exchange")
def link_exchange(body: ExchangeIn, background: BackgroundTasks):
    with state["pool"].connection() as conn:
        try:
            item_id = sync.link_item(conn, state["plaid"], state["box"], body.public_token)
        except PlaidError as e:
            raise _plaid_http(e)
    background.add_task(_sync_one, item_id)
    return {"item_id": item_id}


def _sync_one(item_id: int):
    with state["pool"].connection() as conn:
        try:
            sync.sync_item(conn, state["plaid"], state["box"], item_id)
        except Exception as e:
            log.error("background sync of item %s failed: %s", item_id, e)


# ---------------------------------------------------------------- sync

@app.post("/api/sync")
def sync_now(background: BackgroundTasks):
    background.add_task(sync.sync_all, state["pool"], state["plaid"], state["box"])
    return {"queued": True}


@app.post("/api/items/{item_id}/sync")
def sync_item_now(item_id: int):
    with state["pool"].connection() as conn:
        try:
            return sync.sync_item(conn, state["plaid"], state["box"], item_id)
        except PlaidError as e:
            raise _plaid_http(e)


# ---------------------------------------------------------------- reads

@app.get("/api/items")
def items():
    with scope.connection() as conn:
        return conn.execute(
            """SELECT i.id, i.status, i.error_code, i.error_message, i.update_status,
                      i.last_synced_at, i.created_at,
                      -- inst.name only. accounts.institution_name is for manual
                      -- accounts, and a manual account has no item by
                      -- constraint (accounts_item_ck), so it can never be the
                      -- name of one -- the COALESCE that used to be here was
                      -- unreachable, and referenced an alias that was not in
                      -- scope, which is how this endpoint 500'd.
                      inst.name AS institution,
                      inst.primary_color, inst.oauth,
                      (SELECT count(*) FROM accounts a
                        WHERE a.item_id = i.id AND tally_can_see(a.owner_id)) AS accounts,
                      (SELECT row_to_json(r) FROM (
                          SELECT started_at, finished_at, ok, error, added, modified, removed
                          FROM sync_runs WHERE item_id = i.id ORDER BY id DESC LIMIT 1) r) AS last_run
               FROM items i LEFT JOIN institutions inst ON inst.id = i.institution_id
               ORDER BY inst.name"""
        ).fetchall()


@app.get("/api/accounts")
def accounts():
    with scope.connection() as conn:
        return conn.execute(
            """SELECT a.id, a.item_id, a.name, a.official_name, a.mask, a.type, a.subtype,
                      a.current_balance, a.available_balance, a.credit_limit, a.iso_currency,
                      a.hidden, a.updated_at, COALESCE(inst.name, a.institution_name) AS institution,
                      a.owner_id, p.name AS owner_name, p.color AS owner_color
               FROM accounts a
               LEFT JOIN people p ON p.id = a.owner_id
               LEFT JOIN items i ON i.id = a.item_id
               LEFT JOIN institutions inst ON inst.id = i.institution_id
               WHERE tally_can_see(a.owner_id)
               ORDER BY inst.name, a.type, a.name"""
        ).fetchall()


# ---------------------------------------------------------------- web

if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        # /oauth included: Plaid returns here and the SPA resumes Link.
        if path.startswith("api/"):
            raise HTTPException(404)
        f = WEB_DIST / path
        if path and f.is_file() and WEB_DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(WEB_DIST / "index.html")
