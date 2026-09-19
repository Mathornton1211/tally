"""Periodic sync. Sleeps, syncs every healthy Item, repeats.

Holds no state between passes: cursors live in Postgres, so a crash or
restart costs one interval and nothing else.
"""
import logging
import time

from datetime import date, datetime, timedelta

from . import brief, config, db, digest, enrich, funds, monitor, notify, research, rules, sync
from .llm import LLM
from .crypto import TokenBox
from .plaid import Plaid

log = logging.getLogger("tally.worker")


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    s = config.load()
    db.migrate(s.database_url)
    pool = db.pool(s.database_url)
    plaid = Plaid(s.plaid_host, s.plaid_client_id, s.plaid_secret)
    box = TokenBox(s.fernet_key)
    llm = LLM(pool=pool) if s.ai_enabled else None
    notifier = notify.Notifier(pool=pool)
    log.info("worker up, env=%s interval=%ss", s.plaid_env, s.sync_interval_seconds)
    while True:
        started = time.monotonic()
        try:
            results = sync.sync_all(pool, plaid, box)
            log.info("sync pass: %s", results)
            if llm:
                # Names and categories first, so alerts and the digest read clean data.
                log.info("enrich: %s", enrich.run(pool, llm))
            with pool.connection() as conn:
                # Both run with no viewer set, so they see the whole household
                # rather than one person's slice -- a split rule or a sinking
                # fund belongs to the household, not to whoever synced last.
                log.info("split rules: %s", rules.apply_splits(conn))
                log.info("funds filled: %s", funds.auto_fill(conn))
                log.info("alert scan: %s", monitor.scan(conn))
                # The long-running half: same rules, every pass, and what they
                # find accumulates rather than being recomputed and forgotten.
                log.info("research: %s", research.run(conn))
            if notifier.enabled:
                log.info("push: %s", notify.send_new_alerts(pool, notifier))
                now = datetime.now()
                # Once a week, on the first pass after the chosen hour.
                if now.weekday() == s.brief_weekday and now.hour >= s.brief_hour:
                    with pool.connection() as conn:
                        log.info("weekly brief: %s", brief.send_weekly(conn, pool, notifier).get("skipped", "sent"))
            if llm:
                last_month = (date.today().replace(day=1) - timedelta(days=1)).replace(day=1)
                with pool.connection() as conn:
                    # Only months that actually have transactions: a fresh install
                    # would otherwise spend a model call recapping an empty month.
                    has_data = conn.execute(
                        "SELECT 1 FROM transactions WHERE date >= %s AND date < %s LIMIT 1",
                        (last_month, date.today().replace(day=1))).fetchone()
                    if has_data and not conn.execute("SELECT 1 FROM digests WHERE month = %s", (last_month,)).fetchone():
                        log.info("digest %s: %s", last_month, digest.write(conn, llm, last_month)["headline"])
        except Exception:
            log.exception("sync pass crashed")
        time.sleep(max(60, s.sync_interval_seconds - (time.monotonic() - started)))


if __name__ == "__main__":
    main()
