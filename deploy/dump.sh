#!/bin/sh
# Logical dumps of the Tally database (transactions; Plaid tokens inside are Fernet-sealed).
#
# This exists because the stack's data_class is irreplaceable and the nightly
# rsync cannot honour that on its own. hl-backup copies declared backup_paths
# off a live filesystem, and a live PGDATA copied that way is crash consistent
# at best. It can restore corrupt while looking like a successful backup, which
# is worse than having none. pg_dump output is restorable, so that is what gets
# declared in backup_paths and that is what this writes.
#
# Runs on the same image as the server, so the client can never be older than
# the server and start refusing. That is not a coincidence, it is the reason
# this is its own service rather than a pg_dump inside the app image, where
# Debian's postgresql-client is 15 against a 16 server.
set -u

INTERVAL="${INTERVAL_SECONDS:-86400}"
KEEP="${KEEP:-14}"
OUT=/dumps

log() { echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) $*"; }

dump_once() {
    stamp=$(date -u +%Y-%m-%dT%H%M%SZ)
    tmp="$OUT/.partial-$stamp.sql"
    final="$OUT/tally-$stamp.sql.gz"

    # Two steps rather than `pg_dump | gzip`, because busybox ash has no
    # PIPESTATUS and gzip's exit code would mask a failed dump. A truncated
    # dump that compressed cleanly is exactly the backup you discover is
    # useless at restore time.
    if ! pg_dump --no-owner --no-privileges -f "$tmp" 2>"$OUT/.err"; then
        log "dump FAILED: $(head -1 "$OUT/.err" 2>/dev/null)"
        rm -f "$tmp"
        return 1
    fi

    if ! gzip -c "$tmp" > "$final"; then
        log "compress FAILED for $stamp"
        rm -f "$tmp" "$final"
        return 1
    fi
    rm -f "$tmp"

    # Prove it is complete before trusting it. Size alone catches an empty or
    # header-only dump but not one truncated at 80% by a full disk, and that is
    # the copy you would discover was useless at restore time.
    #
    # pg_dump writes the completion marker only on success, so its presence is
    # the real integrity test. It is NOT the last line: pg_dump 17+ appends a
    # \unrestrict token and a blank line after it, so grep a window rather than
    # tail -1. That detail was found by checking a real dump rather than
    # assuming, and a tail -2 test reported a perfectly good dump as truncated.
    size=$(wc -c < "$final")
    if ! gunzip -c "$final" 2>/dev/null | tail -20 \
         | grep -q "PostgreSQL database dump complete"; then
        log "dump INCOMPLETE: $(basename "$final") ($size bytes) has no"
        log "     completion marker. Treat it as unusable and investigate."
        return 1
    fi
    if [ "$size" -lt 512 ]; then
        log "dump ok but SMALL: $(basename "$final") is only ${size} bytes."
        log "     Complete, so the database is genuinely near-empty."
    else
        log "dump ok: $(basename "$final") ($size bytes)"
    fi

    # Retention. `ls -1t` newest first, so drop everything past KEEP.
    # shellcheck disable=SC2012
    ls -1t "$OUT"/tally-*.sql.gz 2>/dev/null | tail -n "+$((KEEP + 1))" \
        | while IFS= read -r old; do
              log "pruning $(basename "$old")"
              rm -f "$old"
          done
    return 0
}

mkdir -p "$OUT"
log "dump service up: every ${INTERVAL}s, keeping ${KEEP}"

# One immediately, so a fresh deploy is covered rather than unprotected for the
# first 24 hours.
dump_once

while true; do
    sleep "$INTERVAL"
    dump_once
done
