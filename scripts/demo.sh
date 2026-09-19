#!/usr/bin/env bash
# A public demo: real code, a real database, Plaid's sandbox for data, and
# nothing a visitor can change.
#
# The point is to answer "what does it actually look like" without asking
# anybody to install anything. Every number on the page comes through the same
# sync path as a real bank -- the only difference is which Plaid environment
# issued the token.
#
#   ./scripts/demo.sh            build, seed and run on :8098
#   ./scripts/demo.sh --tight    seed the hard case instead: no paycheck,
#                                cards near their limit, one payment overdue
set -euo pipefail
cd "$(dirname "$0")/.."

TIGHT=0
[ "${1:-}" = "--tight" ] && TIGHT=1

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

[ -f .env ] || die "No .env yet. Run ./scripts/install.sh first, or copy .env.example."
grep -qE '^PLAID_SECRET_SANDBOX=.+' .env || die "PLAID_SECRET_SANDBOX is needed: the demo runs on Plaid's sandbox."

export COMPOSE_PROJECT_NAME=tally-demo
COMPOSE="docker compose -f docker-compose.yml -f docker-compose.demo.yml"

say "Building"
$COMPOSE build

say "Starting the database"
$COMPOSE up -d db
for _ in $(seq 1 30); do
  $COMPOSE exec -T db pg_isready -U tally >/dev/null 2>&1 && break
  sleep 2
done

# Seed BEFORE turning on demo mode: seeding writes, and demo mode exists to
# stop writes. The app comes up read-only afterwards.
say "Seeding from Plaid sandbox"
$COMPOSE run --rm -e TALLY_DEMO=0 app python scripts/seed_sandbox.py
if [ "$TIGHT" = "1" ]; then
  note "recreating the tight case: no income, cards near the limit, one overdue"
  $COMPOSE run --rm -e TALLY_DEMO=0 app python scripts/demo_tight.py
fi

say "Starting, read-only"
$COMPOSE up -d app

for _ in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${TALLY_DEMO_PORT:-8098}/healthz" >/dev/null 2>&1; then
    echo
    say "Demo running at http://localhost:${TALLY_DEMO_PORT:-8098}"
    note "No sign-in, nothing writable, sandbox data."
    note "Stop it with: COMPOSE_PROJECT_NAME=tally-demo $COMPOSE down -v"
    exit 0
  fi
  sleep 2
done
die "It did not come up. Logs: COMPOSE_PROJECT_NAME=tally-demo $COMPOSE logs app"
