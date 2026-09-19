# Tally

**Most money apps assume you have some.** They open on a pie chart, ask you to
set a budget, and quietly assume the paycheck lands on the 15th and covers
everything. That is a fine assumption right up until it isn't — and the month
it stops being true is the month you need the app most.

Tally is built the other way round. It starts from *does the money last until
the next money*, and it keeps working when the answer becomes yes.

It runs on your own machine, connects to real banks through Plaid, and does its
AI work against a model you host. Nothing about your money reaches anyone
else's server. It is read-only by design: Tally can see your accounts, and it
can never move a cent.

```bash
git clone https://github.com/you/tally && cd tally
./scripts/install.sh
```

Docker, five minutes, and it comes up on <http://localhost:8099>.

Want to look before installing? `./scripts/demo.sh` runs the whole thing on
Plaid's sandbox — real code, real database, nothing writable. Add `--tight` to
see the version that matters: no paycheck, cards near their limit, one payment
already overdue.

---

## What it does differently

**It tells you what you can actually spend.** Not the balance — the balance is
a lie the moment rent is due. Tally subtracts the bills that have not landed
yet, so "$135 left" means $135 and not $135-minus-$120-of-subscriptions.

**It stops crying wolf.** Rent went out on the 1st and is not going out again,
so it is not extrapolated across the month. The first version of the budget
projection said $2,150 of rent was "heading for $3,794" and raised nine alerts
out of fourteen categories. Nine became two, and both were real.

**It counts the money that is not cash.** Gift cards, store credit, rebates,
trade-ins — real money, locked to one merchant. A $599 printer with a $150
Amazon card needs $369 more, but $449 *at the till*, because the gift card does
not work at the hardware shop. Two numbers, both shown.

**It answers questions instead of making you build filters.** "How much did I
spend at Costco last year" works, and it shows you what it understood so a
wrong reading is visible rather than a silently wrong total. The numbers are
computed in SQL over the matched rows, so they can never be a model's
arithmetic.

**It answers questions about a life you do not have yet.** "If I take a job at
$120k and rent goes to $1,600, how long until the cards are gone?" is answered
from your real balances, APRs and the last 90 days of your own spending — and
from an estimate of what $120k actually *pays*, which is about $7,300 a month,
not $10,000. Planning on the gross number is not optimism, it is a date that
cannot happen. If the month does not balance, you get the shortfall instead of
a comfortable date.

**It keeps working while nobody is looking.** After every sync the same rules
run again and what they find accumulates. Not "Netflix went up $3" — *"Netflix
has gone up three times since 2024, $84 a year more than when you signed up."*
Only a thing with a memory can say the second one. Every figure is arithmetic
on what the bank reported, and each finding says how sure it is.

**It knows what they will say when you call.** Cancelling a subscription is a
process companies have made deliberately annoying. Tally ships the retention
ladder — discount, cheaper tier, pause, credit — in the order it gets offered,
so you decide before the call instead of during it. Card fees lead with a
product change rather than closing the account, because closing it raises
utilisation on everything else the same day.

**Private money stays private.** Each person in the household gets their own
login. An account with an owner is visible to that person alone — including not
to whoever administers the server. A privacy setting with an admin backdoor is
not one.

---

## Everything else it does

**More than one person.** Each person in the household gets their own login. An
account is either the household's or one person's — and an account with an owner
is visible to that person alone, including not to whoever administers the server.
Shared money stays shared; private money stays private. Budgets, funds and goals
can be either.

**The month you are in.** Budgets per category that are judged while the month
is still running, not after it. Tally separates what you have spent from what is
already committed — the subscriptions and bills that recur and have not landed
yet — because money that is spoken for is not money you can spend. The recurring
part is deliberately not extrapolated: rent went out on the 1st and is not going
out again, and an app that projects it four times spends the month crying wolf.

**What is actually coming.** A payment calendar built from Plaid's liabilities
data: due dates, minimums, APRs. Cash runway that answers "does the money last
until the next money". A payoff planner that rolls freed-up minimums forward and
tells you the truth when the numbers do not work.

**The stuff that quietly costs you.** Every fee found and classified, each with
the specific move that avoids it next time. Subscriptions you forgot, and the
ones whose price went up. Duplicate charges, card-testing patterns, amounts well
outside a merchant's normal range.

**Saving up for one thing.** A fund per purchase, with gift cards, store credit,
rebates and trade-ins counted as the real money they are — and kept separate from
cash, because a Home Depot card does not buy groceries.

**Rules that do the boring part.** Rename a merchant to something readable,
recategorise it, tag it, or split the same charge the same way every time.
Renaming, categorising and tagging apply to your whole history the instant you
save the rule, and un-apply the instant you delete it.

**A destination, not just a chart.** Goals for net worth, being debt free, or an
emergency fund measured in months of spending rather than a number that goes
stale. The pace is measured from how your net worth has actually moved, so a bad
month makes the projection less optimistic on its own.

**Funds that fill themselves.** Set a fund to take a fixed amount out of every
paycheck, a percentage of whatever lands, or a fixed sum each month. The preview
runs it against your real past income before you commit to it.

**One link for the accountant.** A read-only page covering one date range, that
expires, that you can revoke, and that tells you when it was last opened. Not a
login, and nothing outside its range.

**More than one currency.** Accounts in different currencies are converted to
your home currency at rates you enter, dated so history is not rewritten when a
rate changes. Anything you have not given a rate for is flagged rather than
silently counted 1:1.

**Asked in English.** A local model that can answer questions about your own
transactions, clean up merchant names, categorise what Plaid gets wrong, and
write a monthly recap. It runs on your ollama, or not at all.

**One queue instead of a chore.** Everything waiting on a human decision —
uncategorised charges, merchants nobody has confirmed before, a possible
duplicate, a rule worth making — collected in one place and worked through in a
few keystrokes. Confirming a merchant teaches it, so the same thing does not
come back next month.

**Your history is yours, past Plaid's window.** Plaid serves roughly 24 months
and its sync can ask for a transaction to be deleted. Tally archives every
removal before acting on one, obeys the recent ones — a reversal last week
genuinely did not happen — and refuses to delete anything older than 90 days on
a single line of JSON, flagging it instead. A wrongly-kept transaction is a
discrepancy somebody can see and fix; a wrongly-deleted one is gone.

Also: receipts with OCR that match themselves to transactions, investments and
401k holdings, manual accounts for the bank Plaid does not support, split
transactions, CSV and tax-pack export, and an installable phone app.

---

## Setting it up

### Plaid

Tally talks to banks through [Plaid](https://plaid.com). Sign up, and from
**Developers → Keys** copy the `client_id` and the **sandbox** secret.

- **Sandbox** is free and unlimited, with fake banks. Sign in to any of them
  with `user_good` / `pass_good`. Start here.
- **Production** on the free Trial plan connects up to **10 real banks**. No
  card required. Ask Plaid for production access in the dashboard.
- Beyond that, Plaid bills per connected item per month. This is the one part of
  running Tally that can cost money, and it is worth knowing before you invite
  anyone else to use your instance.

Some banks (Chase, Capital One, Amex, Bank of America) require OAuth, which
requires HTTPS. That means a real hostname and a certificate — see below — plus
adding that exact URL to the Plaid dashboard allowlist as `PLAID_REDIRECT_URI`.
Banks that do not use OAuth work fine over plain HTTP on localhost.

### Local AI (optional)

Point `OLLAMA_URL` at an [ollama](https://ollama.com), set `AI_MODEL`, set
`AI_ENABLED=1`, and `docker compose up -d`. Any instruction-following model in
the 7B-and-up range does the job.

Tally refuses to talk to a non-local model host. Bank transactions are not going
to a cloud API, and that is enforced in code rather than left to config.

With AI off, every page still works. You lose the assistant, automatic merchant
clean-up, and the monthly recap.

### Phone alerts (optional)

Set `NTFY_URL` and `NTFY_TOPIC` to use [ntfy](https://ntfy.sh) — the public
server or your own. You get a push when a payment is close and the balance will
not cover it, when a card is maxed, when a gift card is about to expire, and a
Monday morning brief. Subscribe to the topic in the ntfy app; the topic name is
shown on the Accounts page.

---

## Putting it on the network

By default Tally binds to `127.0.0.1` — this machine only. That is the right
default for something holding a complete picture of your finances.

To reach it from elsewhere, pick one:

- **Tailscale (easiest, and what I would do).** Leave the bind on loopback and
  use `tailscale serve`. You get HTTPS and a real hostname, and it is reachable
  from your phone without being on the internet.
- **A reverse proxy you already run.** Caddy, Traefik, nginx. Terminate TLS
  there. If it authenticates too (Authentik, oauth2-proxy), set
  `TALLY_AUTH=proxy` and Tally will stop asking for its own password.
- **`TALLY_BIND=0.0.0.0`.** Plain HTTP on your LAN. The password still applies,
  but the traffic is not encrypted and the session cookie crosses the network in
  the clear. Fine for a trusted wired network, not for anything else.

Do not put it on the open internet without TLS and something in front of it.

---

## Backups

Transactions can be re-synced from Plaid. These cannot:

| What | Where | Why it matters |
|---|---|---|
| `TALLY_FERNET_KEY` | `.env` | Without it, every bank connection has to be made again |
| Receipt images | `./data/receipts` | They exist nowhere else once the paper is gone |
| Manual accounts, splits, funds, budgets, notes | Postgres | Typed in by hand; not in any bank feed |

Dump the database with:

```bash
docker compose exec -T db pg_dump -U tally tally | gzip > tally-$(date +%F).sql.gz
```

`scripts/restore_test.sh` restores a dump into a scratch database and checks it
actually comes back. A backup you have never restored is a hypothesis.

---

## Running it without Docker

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements.txt
(cd web && npm ci && npm run build)
export $(grep -v '^#' .env | xargs)      # or set them however you like
uvicorn tally.api:app --port 8000
```

Migrations run at startup. `python -m tally.worker` is the background sync.

Tests need a scratch Postgres — they drop and recreate the `public` schema, so
point them at a database you do not care about:

```bash
TALLY_TEST_DATABASE_URL=postgresql://tally:tallydev@127.0.0.1:5544/tally pytest
```

---

## How it is put together

```
tally/            FastAPI app, one module per concern
  plaid.py        the only thing that talks to Plaid. Read-only calls only
  sync.py         /transactions/sync with cursors; rows and cursor commit together
  analytics.py    balance history, recurring-charge detection
  plan.py         runway, debts, payoff simulation, what-if
  budgets.py      monthly targets, rollover, pace and projection
  goals.py        net worth / debt-free / emergency-fund goals and trajectory
  research.py     findings that accumulate between syncs, with confidence
  trends.py       years, year-over-year clamped to the same span, annual review
  setup.py        what is left to do before this install is useful
  rules.py        rename, recategorise, tag and split automatically
  money.py        home currency and dated exchange rates
  people.py       the household; scope.py carries who is asking
  share.py        read-only links for an accountant
  search.py       a sentence -> filters -> a total computed in SQL
  funds.py        saving for one purchase, with gift cards and store credit
  fees.py         fee classification and the playbook for avoiding each one
  monitor.py      fraud and anomaly rules -> alerts
  llm.py          local model access, structured output, refuses remote hosts
  auth.py         the front door, for installs without one in front
  migrations/     numbered SQL, applied at startup, never edited after shipping
web/              React + Vite, TanStack Query, ECharts, Tailwind
deploy/           the homelab stack (Traefik + Authentik). Not the standalone one
```

Some things that are true throughout, and worth knowing before changing
anything:

- **Plaid's sign convention is resolved once**, in the `v_txn` view. Positive
  `spend` is money out, positive `income` is money in. Nothing downstream
  re-interprets a sign.
- **Card payments and transfers are neither spending nor income.** Counting a
  card payment as spending double-counts every purchase on that card.
- **Access tokens are encrypted at rest** with a key that lives only in the
  environment, so a database dump on its own cannot pull anyone's transactions.
- **Migrations are append-only.** Once a numbered file has shipped it is never
  edited; the next change is a new number.
- **Privacy is one predicate, in two views.** `tally_can_see(owner_id)` in
  `v_txn` and `v_acct` is the entire enforcement surface. Read accounts through
  `v_acct`, never the `accounts` table, or a private balance leaks even while
  its transactions are correctly hidden — which is exactly the bug that shipped
  and had to be fixed.
- **Totals are computed in SQL, never by a model.** The assistant and search can
  choose *what* to add up; they never produce the number.

`HANDOFF.md` is the long version: the reasoning behind each round of work, the
bugs that were hit, and what they taught.

---

## Is it maintained

Fair question to ask of anything you are about to give bank access to.

- **Version** — shown on the Settings page and at `/healthz`, so "what is this
  box running" has an answer.
- **Tests** — 317 of them, run on every push against a real Postgres. The suite
  includes the bugs that actually shipped, each one pinned by the test that
  would have caught it.
- **CI** — `.github/workflows/ci.yml`: Python tests, web typecheck, lint,
  build, and a check that the image contains what migrations need.
- **Migrations** — append-only, and a schema change on a database with data in
  it takes a rollback dump first and refuses to run if it cannot.

`HANDOFF.md` is the long version: every round of work, the reasoning, and the
bugs — including the ones that were embarrassing. It is kept honest because it
is what makes the next change safe.

---

## Licence

MIT.
