"""The safety dump around schema changes.

A migration runs automatically on every deploy, against the only irreplaceable
thing in the app. These tests are about the two ways that can go wrong: no
rollback point, and a rollback point nobody checked existed.
"""
import gzip
import os
import shutil

import psycopg
import pytest

from tally import db

# The two tests that take a real dump need the real binary. It is installed in
# the image (see Dockerfile) but not necessarily on a dev machine, and the
# behaviour that matters -- refusing to migrate without one -- is tested either
# way.
needs_pg_dump = pytest.mark.skipif(shutil.which("pg_dump") is None,
                                   reason="pg_dump not on PATH; it is in the container image")


@pytest.fixture
def seeded(db_url):
    """A database that has something to lose."""
    with psycopg.connect(db_url, autocommit=True) as c:
        c.execute("INSERT INTO institutions (id, name) VALUES ('i','Bank') ON CONFLICT DO NOTHING")
        c.execute("""INSERT INTO items (id, plaid_item_id, institution_id, access_token_enc)
                     VALUES (1,'it','i','x') ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO accounts (id, item_id, source, name, type, subtype, current_balance)
                     VALUES ('a',1,'plaid','Checking','depository','checking',100)
                     ON CONFLICT DO NOTHING""")
        c.execute("""INSERT INTO transactions (id, account_id, amount, date, name,
                                               pfc_primary, pfc_detailed, raw)
                     VALUES ('t1','a',12.34,current_date,'SHOP','GENERAL_MERCHANDISE',
                             'GENERAL_MERCHANDISE_OTHER','{}') ON CONFLICT DO NOTHING""")
    return db_url


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    monkeypatch.delenv("TALLY_DUMP_DIR", raising=False)
    monkeypatch.delenv("TALLY_SKIP_PREMIGRATION_DUMP", raising=False)


def _pretend_pending(monkeypatch, tmp_path):
    """One extra migration file that has not been applied yet."""
    extra = tmp_path / "migrations"
    extra.mkdir()
    for real in sorted((db.MIGRATIONS).glob("*.sql")):
        (extra / real.name).write_text(real.read_text(encoding="utf-8"), encoding="utf-8")
    (extra / "999_later.sql").write_text("CREATE TABLE later_on (id int);", encoding="utf-8")
    monkeypatch.setattr(db, "MIGRATIONS", extra)


@needs_pg_dump
def test_a_schema_change_on_real_data_writes_a_rollback_point_first(seeded, tmp_path, monkeypatch):
    dumps = tmp_path / "dumps"
    monkeypatch.setenv("TALLY_DUMP_DIR", str(dumps))
    _pretend_pending(monkeypatch, tmp_path)

    assert db.migrate(seeded) == ["999_later"]

    made = list(dumps.glob("pre-migration-*.sql.gz"))
    assert len(made) == 1 and "999_later" in made[0].name
    body = gzip.open(made[0], "rt", encoding="utf-8", errors="replace").read()
    # The point of it: the data is actually in there, from before the change.
    assert "COPY public.transactions" in body and "SHOP" in body
    # And it is the state BEFORE, so it does not know about the new table.
    assert "later_on" not in body


def test_it_refuses_to_migrate_real_data_with_nowhere_to_put_the_dump(seeded, tmp_path, monkeypatch):
    """An unattended migration against irreplaceable data with no way back is
    worse than a container that will not start and says why."""
    _pretend_pending(monkeypatch, tmp_path)
    with pytest.raises(RuntimeError, match="TALLY_DUMP_DIR"):
        db.migrate(seeded)
    with psycopg.connect(seeded, autocommit=True) as c:
        assert not c.execute(
            "SELECT to_regclass('public.later_on') IS NOT NULL").fetchone()[0]


def test_a_fresh_install_is_not_blocked(db_url, tmp_path, monkeypatch):
    """Nothing to lose, nothing to protect. Refusing here would mean nobody
    could install the app without configuring a backup directory first."""
    _pretend_pending(monkeypatch, tmp_path)
    assert db.migrate(db_url) == ["999_later"]


def test_the_risk_can_be_accepted_on_purpose(seeded, tmp_path, monkeypatch):
    _pretend_pending(monkeypatch, tmp_path)
    monkeypatch.setenv("TALLY_SKIP_PREMIGRATION_DUMP", "1")
    assert db.migrate(seeded) == ["999_later"]


def test_nothing_pending_means_no_dump_and_no_noise(seeded, tmp_path, monkeypatch):
    """Every restart calls migrate(). Dumping on each one would fill the disk
    and bury the dumps that matter."""
    dumps = tmp_path / "dumps"
    monkeypatch.setenv("TALLY_DUMP_DIR", str(dumps))
    assert db.migrate(seeded) == []
    assert not dumps.exists() or list(dumps.glob("*.sql.gz")) == []


@needs_pg_dump
def test_old_rollback_points_are_pruned(seeded, tmp_path, monkeypatch):
    dumps = tmp_path / "dumps"
    dumps.mkdir()
    for i in range(14):
        f = dumps / f"pre-migration-2026-01-{i + 1:02d}T000000Z-00{i}_x.sql.gz"
        f.write_bytes(b"x")
        os.utime(f, (1_700_000_000 + i, 1_700_000_000 + i))
    monkeypatch.setenv("TALLY_DUMP_DIR", str(dumps))
    _pretend_pending(monkeypatch, tmp_path)

    db.migrate(seeded)
    kept = list(dumps.glob("pre-migration-*.sql.gz"))
    assert len(kept) == db.KEEP_PRE_MIGRATION
    # The newest survive, including the one just written.
    assert any("999_later" in k.name for k in kept)
