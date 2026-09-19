#!/usr/bin/env bash
# Prove the backup restores. An untested backup is not a backup.
#
# Takes the newest dump, loads it into a throwaway Postgres container, and
# checks the tables that matter are there and populated. Touches nothing that
# is live: a separate container, a separate volume, removed at the end.
#
#   bash scripts/restore_test.sh [/path/to/dumps]
set -euo pipefail

DUMPS="${1:-/srv/tally-data/tally/dumps}"
NAME="tally-restore-test-$$"
IMAGE="postgres:16-alpine"
PASSWORD="restore-test-only"

latest=$(ls -1t "$DUMPS"/tally-*.sql.gz 2>/dev/null | head -1 || true)
[ -n "$latest" ] || { echo "no dump found in $DUMPS"; exit 1; }
echo "restoring $(basename "$latest") ($(stat -c %s "$latest") bytes)"

cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; }
trap cleanup EXIT

docker run -d --name "$NAME" -e POSTGRES_PASSWORD="$PASSWORD" -e POSTGRES_DB=restore "$IMAGE" >/dev/null
for _ in $(seq 1 30); do
    docker exec "$NAME" pg_isready -U postgres -d restore >/dev/null 2>&1 && break
    sleep 1
done

gunzip -c "$latest" | docker exec -i -e PGPASSWORD="$PASSWORD" "$NAME" \
    psql -q -U postgres -d restore -v ON_ERROR_STOP=1 >/dev/null
echo "loaded without errors"

rows() {
    docker exec -e PGPASSWORD="$PASSWORD" "$NAME" psql -tA -U postgres -d restore \
        -c "SELECT count(*) FROM $1" 2>/dev/null || echo "MISSING"
}

fail=0
# accounts and transactions are the point of the backup; the rest prove the
# schema came across whole.
for table in accounts transactions items categories liabilities receipts goals alerts; do
    n=$(rows "$table")
    printf '  %-24s %s\n' "$table" "$n"
    [ "$n" = "MISSING" ] && fail=1
done

# The encrypted tokens must survive, or every bank has to be re-linked.
enc=$(docker exec -e PGPASSWORD="$PASSWORD" "$NAME" psql -tA -U postgres -d restore \
      -c "SELECT count(*) FROM items WHERE access_token_enc IS NOT NULL" 2>/dev/null || echo 0)
echo "  items with a stored token   $enc"
echo "  (they decrypt only with TALLY_FERNET_KEY, which is NOT in this dump by design)"

txns=$(rows transactions)
items=$(rows items)
if [ "$txns" != "MISSING" ] && [ "$txns" -eq 0 ]; then
    if [ "$items" != "MISSING" ] && [ "$items" -eq 0 ]; then
        # A fresh install with no banks linked yet. The schema restoring is the
        # whole test there is; calling that a failure would train us to ignore it.
        echo "note: no banks connected yet, so there are no transactions to restore"
    else
        echo "WARNING: banks are connected but the dump holds no transactions"
        fail=1
    fi
fi

[ "$fail" -eq 0 ] && echo "RESTORE TEST PASSED" || { echo "RESTORE TEST FAILED"; exit 1; }
