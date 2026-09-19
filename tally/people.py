"""Who is in the household.

Ownership here means one thing only: an account with an owner is that person's
alone. The household role called "owner" administers people and connections --
it does not grant sight of anyone's private accounts. Those are two different
words that unavoidably collide in English, and conflating them in code would
turn a privacy promise into a bug.
"""
import hashlib
import hmac
import re
import secrets

COLORS = ["series-1", "series-2", "positive", "warn", "accent"]
USERNAME = re.compile(r"^[a-z0-9][a-z0-9._-]{1,30}$")


def _hash(password: str, salt: str) -> str:
    return hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt),
                          n=2 ** 14, r=8, p=1, dklen=32).hex()


def make_hash(password: str) -> str:
    """Per-person salt, stored with the hash. Two people who pick the same
    password must not end up with the same row."""
    salt = secrets.token_hex(16)
    return f"scrypt${salt}${_hash(password, salt)}"


def verify(stored: str | None, password: str) -> bool:
    if not stored or not password:
        return False
    try:
        kind, salt, expected = stored.split("$", 2)
    except ValueError:
        return False
    if kind != "scrypt":
        return False
    return hmac.compare_digest(_hash(password, salt), expected)


def normalise_username(name: str) -> str:
    u = re.sub(r"[^a-z0-9._-]", "", name.strip().lower().replace(" ", ""))
    return u[:31]


def listing(conn, full: bool = True) -> list[dict]:
    """Who is here.

    Everyone signed in may see the roster -- you cannot decide to share an
    account with someone the app refuses to name, and hiding housemates from
    each other would be absurd. What is held back from non-owners is the
    administrative detail: when somebody last signed in, whether they have a
    password set, and how many accounts they keep to themselves. Those answer
    "what is my partner doing", which is not a question this app exists to help
    with.
    """
    if not full:
        return conn.execute(
            """SELECT p.id, p.name, p.username, p.role, p.color
               FROM people p ORDER BY p.created_at, p.id""").fetchall()
    return conn.execute(
        """SELECT p.id, p.name, p.username, p.role, p.color, p.last_seen_at, p.created_at,
                  (p.password_hash IS NOT NULL) AS can_sign_in,
                  (SELECT count(*) FROM accounts a WHERE a.owner_id = p.id) AS accounts
           FROM people p ORDER BY p.created_at, p.id""").fetchall()


def is_owner(conn, person_id: int | None) -> bool:
    """True when nobody is signed in too: proxy mode and one-person installs
    have no role to check and full run of the place."""
    if person_id is None:
        return True
    row = conn.execute("SELECT role FROM people WHERE id = %s", (person_id,)).fetchone()
    return bool(row and row["role"] == "owner")


def get(conn, person_id: int) -> dict | None:
    return conn.execute(
        "SELECT id, name, username, role, color FROM people WHERE id = %s", (person_id,)).fetchone()


def by_username(conn, username: str) -> dict | None:
    return conn.execute(
        "SELECT id, name, username, role, color, password_hash FROM people WHERE username = %s",
        (username.strip().lower(),)).fetchone()


def count(conn) -> int:
    return conn.execute("SELECT count(*) AS n FROM people").fetchone()["n"]


def create(conn, name: str, username: str, password: str | None, role: str = "member",
           color: str | None = None) -> dict:
    n = count(conn)
    return conn.execute(
        """INSERT INTO people (name, username, password_hash, role, color)
           VALUES (%s,%s,%s,%s,%s) RETURNING id, name, username, role, color""",
        (name.strip(), username.strip().lower(), make_hash(password) if password else None,
         role, color or COLORS[n % len(COLORS)])).fetchone()


def bootstrap(conn, password: str) -> dict | None:
    """The first person, from TALLY_PASSWORD, on a database with nobody in it.

    This is what keeps a fresh `scripts/install.sh` working and what turns an
    existing single-password install into a one-person household without anyone
    having to do anything. It runs once: after that, people are managed in the
    app and the environment variable stops mattering.
    """
    if count(conn) > 0:
        return None
    person = create(conn, "Me", "me", password, role="owner")
    conn.commit()
    return person


def touch(conn, person_id: int) -> None:
    conn.execute("UPDATE people SET last_seen_at = now() WHERE id = %s", (person_id,))
