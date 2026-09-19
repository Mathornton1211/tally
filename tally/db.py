"""Connection pool and a numbered-file migration runner.

Migrations are plain SQL in tally/migrations, applied in filename order, each
in its own transaction, recorded in schema_migrations. Never edit an applied
file: add the next number.

A schema change on a database holding real bank history is the one routine
operation here that can destroy something irreplaceable, and it happens
automatically on every deploy. So a migration that has anything to lose takes a
dump of the database first, and refuses to run if it cannot.
"""
import gzip
import logging
import os
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

log = logging.getLogger("tally.db")

MIGRATIONS = Path(__file__).parent / "migrations"
LOCK = 727001
# Keep a few. These sit beside the nightly dumps and are pruned the same way,
# but they are the ones that matter: each is the last good state before a
# schema change.
KEEP_PRE_MIGRATION = 10


def _dump_dir() -> Path | None:
    d = os.environ.get("TALLY_DUMP_DIR", "").strip()
    return Path(d) if d else None


def _has_data(conn) -> bool:
    """Is there anything here worth protecting? A fresh install has nothing to
    lose and should not be blocked from starting."""
    row = conn.execute(
        """SELECT EXISTS (SELECT 1 FROM information_schema.tables
                          WHERE table_schema = 'public' AND table_name = 'transactions') AS t""").fetchone()
    if not row[0]:
        return False
    return conn.execute("SELECT EXISTS (SELECT 1 FROM transactions LIMIT 1)").fetchone()[0]


def _prune(directory: Path) -> None:
    old = sorted(directory.glob("pre-migration-*.sql.gz"), key=lambda p: p.stat().st_mtime,
                 reverse=True)[KEEP_PRE_MIGRATION:]
    for p in old:
        p.unlink(missing_ok=True)


def pre_migration_dump(database_url: str, pending: list[str]) -> Path:
    """The last good state before a schema change, written before it happens.

    Raises rather than returning on failure. An unattended migration against
    irreplaceable data with no way back is worse than a container that will not
    start and says why.
    """
    directory = _dump_dir()
    if directory is None:
        raise RuntimeError(
            "TALLY_DUMP_DIR is not set, so there is nowhere to put a safety dump before "
            f"applying {', '.join(pending)}. Set it to a writable path (the compose files "
            "mount one), or set TALLY_SKIP_PREMIGRATION_DUMP=1 to accept the risk.")
    if not shutil.which("pg_dump"):
        raise RuntimeError(
            "pg_dump is not installed in this image, so no safety dump can be taken before "
            f"applying {', '.join(pending)}. Set TALLY_SKIP_PREMIGRATION_DUMP=1 to accept the risk.")

    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        raise RuntimeError(f"cannot create {directory} for the safety dump: {e}") from e
    if not os.access(directory, os.W_OK):
        raise RuntimeError(
            f"{directory} is not writable by this process (uid {os.getuid()}), so no safety "
            f"dump can be taken before applying {pending[0]}. The nightly dump container runs "
            f"as root and the app does not, so the directory has to be owned by the app: "
            f"chown {os.getuid()} on the host path mounted at {directory}.")
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H%M%SZ")
    out = directory / f"pre-migration-{stamp}-{pending[0]}.sql.gz"
    proc = subprocess.run(["pg_dump", "--no-owner", "--no-privileges", database_url],
                          capture_output=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(f"pg_dump failed before {pending[0]}: "
                           f"{proc.stderr.decode(errors='replace')[-400:]}")
    with gzip.open(out, "wb") as fh:
        fh.write(proc.stdout)
    _prune(directory)
    log.info("safety dump before %s: %s (%d bytes)", pending[0], out, out.stat().st_size)
    return out


def migrate(database_url: str) -> list[str]:
    applied_now = []
    with psycopg.connect(database_url, autocommit=True) as conn:
        conn.execute("CREATE TABLE IF NOT EXISTS schema_migrations "
                     "(version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())")
        # Two containers starting at once must not both apply 001 -- and must
        # not both take the safety dump either, so it happens inside the lock.
        conn.execute("SELECT pg_advisory_lock(%s)", (LOCK,))
        try:
            done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
            pending = [p for p in sorted(MIGRATIONS.glob("*.sql")) if p.stem not in done]
            if pending and _has_data(conn) and os.environ.get("TALLY_SKIP_PREMIGRATION_DUMP") != "1":
                pre_migration_dump(database_url, [p.stem for p in pending])

            for path in pending:
                with conn.transaction():
                    conn.execute(path.read_text(encoding="utf-8"))
                    conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.stem,))
                applied_now.append(path.stem)
        finally:
            conn.execute("SELECT pg_advisory_unlock(%s)", (LOCK,))
    return applied_now


def check_dump_dir() -> str | None:
    """Is there somewhere to put a rollback point, right now?

    Called at startup so the answer arrives on an ordinary boot rather than in
    the middle of the deploy that first needs it -- which is the one moment a
    refusal is most expensive and least welcome.
    """
    directory = _dump_dir()
    if directory is None:
        return "TALLY_DUMP_DIR is not set"
    if not shutil.which("pg_dump"):
        return "pg_dump is not installed"
    try:
        directory.mkdir(parents=True, exist_ok=True)
    except OSError as e:
        return f"{directory} cannot be created ({e})"
    if not os.access(directory, os.W_OK):
        return f"{directory} is not writable by uid {os.getuid()}"
    return None


def session_timezone() -> str:
    """The household's timezone, as an IANA name.

    It has to be a real name: Postgres silently falls back to UTC on anything
    it does not recognise -- including a plain "-07:00" -- so a fixed offset is
    not a usable fallback, it is a wrong answer that looks like a right one.
    """
    for key in ("TALLY_TIMEZONE", "TZ"):
        value = os.environ.get(key, "").strip()
        if value:
            return value
    # A Linux container without TZ set still knows where it is.
    try:
        name = Path("/etc/timezone").read_text(encoding="utf-8").strip()
        if name:
            return name
    except OSError:
        pass
    try:
        link = os.readlink("/etc/localtime")
        if "zoneinfo/" in link:
            return link.split("zoneinfo/", 1)[1]
    except OSError:
        pass
    return "UTC"


def pool(database_url: str) -> ConnectionPool:
    """Every connection agrees with Python about what day it is.

    Postgres `current_date` is the SERVER's day; `date.today()` is the
    container's. A server in UTC and a household in California disagree for
    seven hours out of every twenty-four, which is long enough for "day 17 of
    30" and "spending over the last 60 days" to quietly mean different months
    and different windows -- and short enough that nobody notices for weeks.
    Setting the session timezone on every connection makes one of them right
    and the other one match it.
    """
    tz = session_timezone()

    def configure(conn):
        # set_config rather than SET TIME ZONE: the latter takes no bind
        # parameter, and building that string by hand is how a config value
        # becomes an injection point.
        #
        # The commit is not optional. psycopg's pool discards any connection
        # its configure callback leaves in a transaction, so without it the
        # pool hands out nothing at all and every request times out.
        conn.execute("SELECT set_config('TimeZone', %s, false)", (tz,))
        conn.commit()

    return ConnectionPool(database_url, min_size=1, max_size=8,
                          kwargs={"row_factory": dict_row}, configure=configure, open=True)
