"""The household: who is in it, and who owns which accounts."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from . import auth, people, scope
from .state import state

router = APIRouter(prefix="/api/people")


def _who(request: Request) -> int | None:
    return state["auth"].person(request.cookies.get(auth.COOKIE))


@router.get("")
def list_people(request: Request):
    # Unscoped on purpose: the household roster is not private, only the money
    # is. Non-owners get names and roles without the administrative detail.
    me = _who(request)
    with scope.unscoped() as conn:
        return {"people": people.listing(conn, full=people.is_owner(conn, me)), "me": me,
                "auth_mode": state["auth"].mode}


class SelfPatch(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    color: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


@router.patch("/me")
def edit_myself(body: SelfPatch, request: Request):
    """Your own name, colour and password. Declared before /{person_id} so that
    "me" is not parsed as an id -- the same trap /alerts/scan fell into."""
    me = _who(request)
    if me is None:
        raise HTTPException(400, "nobody is signed in")
    sets, params = [], []
    for field in ("name", "color"):
        v = getattr(body, field)
        if v is not None:
            sets.append(f"{field} = %s"); params.append(v)
    if body.password:
        sets.append("password_hash = %s"); params.append(people.make_hash(body.password))
    if not sets:
        raise HTTPException(400, "nothing to change")
    with scope.unscoped() as conn:
        conn.execute(f"UPDATE people SET {', '.join(sets)} WHERE id = %s", params + [me])
        return people.get(conn, me)


class PersonIn(BaseModel):
    name: str = Field(min_length=1, max_length=40)
    username: str | None = Field(default=None, max_length=31)
    password: str | None = Field(default=None, min_length=8, max_length=200)
    role: str = Field(default="member", pattern="^(owner|member|viewer)$")
    color: str | None = None


@router.post("")
def add_person(body: PersonIn, request: Request):
    username = (body.username or people.normalise_username(body.name)).lower()
    if not people.USERNAME.match(username):
        raise HTTPException(400, "a username is 2-31 characters: letters, digits, dot, dash, underscore")
    with scope.unscoped() as conn:
        if people.by_username(conn, username):
            raise HTTPException(409, "that username is taken")
        if state["auth"].enabled and not body.password:
            raise HTTPException(400, "this install signs in with a password, so a new person needs one")
        return people.create(conn, body.name, username, body.password, body.role, body.color)


class PersonPatch(BaseModel):
    name: str | None = Field(default=None, max_length=40)
    role: str | None = Field(default=None, pattern="^(owner|member|viewer)$")
    color: str | None = None
    password: str | None = Field(default=None, min_length=8, max_length=200)


@router.patch("/{person_id}")
def edit_person(person_id: int, body: PersonPatch, request: Request):
    with scope.unscoped() as conn:
        # Editing anybody -- including yourself -- through this route is an
        # owner's job; the middleware has already enforced that. Editing your
        # own name or password without being an owner goes through /me above.
        sets, params = [], []
        for field in ("name", "role", "color"):
            v = getattr(body, field)
            if v is not None:
                sets.append(f"{field} = %s"); params.append(v)
        if body.password:
            sets.append("password_hash = %s"); params.append(people.make_hash(body.password))
        if not sets:
            raise HTTPException(400, "nothing to change")
        if body.role and body.role != "owner":
            others = conn.execute(
                "SELECT count(*) AS n FROM people WHERE role = 'owner' AND id <> %s", (person_id,)).fetchone()
            if not others["n"]:
                raise HTTPException(400, "the household needs at least one owner")
        n = conn.execute(f"UPDATE people SET {', '.join(sets)} WHERE id = %s", params + [person_id]).rowcount
        if not n:
            raise HTTPException(404, "no such person")
        return people.get(conn, person_id)


@router.delete("/{person_id}")
def remove_person(person_id: int, request: Request, reassign_to: int | None = None):
    """Removing someone has to say what happens to their accounts.

    Silently making them shared would expose exactly the accounts they chose to
    keep private, and silently deleting them would throw away bank history. So
    the caller states which, and the default is to refuse.
    """
    with scope.unscoped() as conn:
        if _who(request) == person_id:
            raise HTTPException(400, "you cannot remove yourself")
        owned = conn.execute(
            "SELECT count(*) AS n FROM accounts WHERE owner_id = %s", (person_id,)).fetchone()["n"]
        if owned and reassign_to is None:
            raise HTTPException(
                400, f"{owned} account(s) belong to this person. Say who they go to "
                     f"with ?reassign_to=<person id>, or 0 to make them the household's.")
        if owned:
            new_owner = None if reassign_to == 0 else reassign_to
            if new_owner is not None and not people.get(conn, new_owner):
                raise HTTPException(404, "no such person to reassign to")
            conn.execute("UPDATE accounts SET owner_id = %s WHERE owner_id = %s", (new_owner, person_id))
        if not conn.execute("DELETE FROM people WHERE id = %s", (person_id,)).rowcount:
            raise HTTPException(404, "no such person")
        return {"ok": True, "reassigned": owned}


class OwnerIn(BaseModel):
    # null means the household's: everyone sees it.
    owner_id: int | None = None


@router.put("/accounts/{account_id}/owner")
def set_account_owner(account_id: str, body: OwnerIn, request: Request):
    """Whose account this is. Null = the household's, seen by everyone.

    Deliberately unscoped: an admin setting up the household has to be able to
    place an account before the visibility rule starts applying to it.
    """
    with scope.unscoped() as conn:
        if body.owner_id is not None and not people.get(conn, body.owner_id):
            raise HTTPException(404, "no such person")
        n = conn.execute("UPDATE accounts SET owner_id = %s WHERE id = %s",
                         (body.owner_id, account_id)).rowcount
        if not n:
            raise HTTPException(404, "no such account")
        return {"ok": True, "account_id": account_id, "owner_id": body.owner_id}


@router.post("/view-as/{person_id}")
def view_as(person_id: int, request: Request):
    """Switch which person the app is showing, in proxy mode.

    Refused when Tally does the authenticating: there, switching person means
    signing in as them.
    """
    if state["auth"].enabled:
        raise HTTPException(400, "sign in as that person instead")
    with scope.unscoped() as conn:
        if person_id and not people.get(conn, person_id):
            raise HTTPException(404, "no such person")
    from fastapi.responses import JSONResponse
    r = JSONResponse({"ok": True, "person_id": person_id or None})
    if person_id:
        r.set_cookie(auth.COOKIE, state["auth"].issue(person_id).decode(),
                     max_age=auth.SESSION_DAYS * 86400, httponly=True, samesite="lax")
    else:
        r.delete_cookie(auth.COOKIE)
    return r
