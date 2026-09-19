#!/usr/bin/env bash
# Tally, from nothing to a working install.
#
# Generates the secrets, asks for the two Plaid keys, builds, migrates, starts.
# Safe to run again: an existing .env is never overwritten, only filled in.
set -euo pipefail

cd "$(dirname "$0")/.."
ENV_FILE=.env

say()  { printf '\033[1m%s\033[0m\n' "$*"; }
note() { printf '  %s\n' "$*"; }
die()  { printf '\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

command -v docker >/dev/null || die "Docker is not installed. https://docs.docker.com/get-docker/"
docker compose version >/dev/null 2>&1 || die "This needs Docker Compose v2 ('docker compose', not 'docker-compose')."
docker info >/dev/null 2>&1 || die "Docker is installed but not running."

# ---------------------------------------------------------------- secrets

random() { LC_ALL=C tr -dc 'A-Za-z0-9' </dev/urandom | head -c "${1:-32}"; }

fernet_key() {
  # The one secret that cannot be any random string: Fernet wants 32 bytes,
  # url-safe base64. Generated with the same library that will read it.
  docker run --rm python:3.12-slim sh -c \
    "pip install --quiet cryptography >/dev/null 2>&1 && python -c \
     'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'"
}

set_var() {  # set_var NAME VALUE -- only if not already present and non-empty
  local name=$1 value=$2
  if grep -qE "^${name}=.+" "$ENV_FILE" 2>/dev/null; then return; fi
  sed -i.bak "/^${name}=/d" "$ENV_FILE" 2>/dev/null || true
  rm -f "$ENV_FILE.bak"
  printf '%s=%s\n' "$name" "$value" >> "$ENV_FILE"
}

get_var() { grep -E "^$1=" "$ENV_FILE" 2>/dev/null | head -1 | cut -d= -f2-; }

touch "$ENV_FILE"
chmod 600 "$ENV_FILE"

say "Generating secrets"
set_var TALLY_DB_PASSWORD "$(random 32)"
if [ -z "$(get_var TALLY_FERNET_KEY)" ]; then
  note "making an encryption key for your bank tokens…"
  set_var TALLY_FERNET_KEY "$(fernet_key)"
fi
set_var NTFY_TOPIC "tally-$(random 16)"
note "done. Back up .env somewhere safe — the Fernet key is in it."

# ---------------------------------------------------------------- password

if [ -z "$(get_var TALLY_PASSWORD)" ]; then
  say "Pick a password for signing in"
  note "Nothing sits in front of Tally, so this is the only thing between the"
  note "browser and every transaction in your accounts. Make it a real one."
  while :; do
    read -rsp "  Password: " pw1 </dev/tty; echo
    read -rsp "  Again:    " pw2 </dev/tty; echo
    [ -n "$pw1" ] && [ "$pw1" = "$pw2" ] && [ ${#pw1} -ge 8 ] && break
    note "Empty, mismatched, or under 8 characters. Try again."
  done
  set_var TALLY_PASSWORD "$pw1"
  unset pw1 pw2
fi
set_var TALLY_AUTH password

# ---------------------------------------------------------------- Plaid

if [ -z "$(get_var PLAID_CLIENT_ID)" ]; then
  say "Plaid keys"
  note "Tally reads your accounts through Plaid. A free Sandbox account gives"
  note "you fake banks to try it with; the free Trial plan connects up to 10"
  note "real ones. Sign up at https://dashboard.plaid.com/signup and copy the"
  note "client_id and the sandbox secret from Developers → Keys."
  read -rp "  client_id: " cid </dev/tty
  read -rp "  sandbox secret: " sec </dev/tty
  [ -n "$cid" ] && [ -n "$sec" ] || die "Both are needed. Run this again when you have them."
  set_var PLAID_CLIENT_ID "$cid"
  set_var PLAID_SECRET_SANDBOX "$sec"
  set_var PLAID_ENV sandbox
fi

set_var TALLY_PORT 8099
set_var TALLY_BIND 127.0.0.1
set_var AI_ENABLED 0
set_var TALLY_BASE_URL "http://localhost:$(get_var TALLY_PORT)"

# ---------------------------------------------------------------- go

mkdir -p data/receipts data/dumps
# The container runs as uid 10001 (see Dockerfile). It writes receipts, and a
# rollback dump before any schema change -- and refuses to migrate if it cannot.
chown -R 10001 data/receipts data/dumps 2>/dev/null ||   note "could not chown data/ to uid 10001; if migrations later refuse to run, that is why"

say "Building (a few minutes the first time)"
docker compose build

say "Starting"
docker compose up -d
# Migrations run on the app's own startup, so readiness is the real signal.
printf '  waiting for it to come up'
for _ in $(seq 1 60); do
  if curl -fsS "http://127.0.0.1:$(get_var TALLY_PORT)/healthz" >/dev/null 2>&1; then
    echo; say "Tally is running at http://localhost:$(get_var TALLY_PORT)"
    note "Sign in with the password you just set, then Accounts → Connect a bank."
    note "In sandbox, any Plaid test bank works with user_good / pass_good."
    echo
    note "AI features (the assistant, auto-categorising, the monthly recap) are"
    note "off. To turn them on, point OLLAMA_URL at an ollama, set AI_MODEL, set"
    note "AI_ENABLED=1 in .env, and run: docker compose up -d"
    exit 0
  fi
  printf '.'; sleep 2
done
echo
die "It did not come up. Logs: docker compose logs app"
