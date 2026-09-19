"""What is left to do before this install is actually useful.

The gap this closes: connect a bank and you land on a dashboard that is
technically correct and means nothing. Every number is there and none of them
is a decision. Somebody who installed a finance app on a Sunday afternoon gives
it about two minutes.

So this is a checklist, and the rule for what goes on it is narrow: a step
earns its place only if skipping it leaves a page visibly empty or a number
quietly wrong. "Set a budget" qualifies -- the Budget page is blank without it.
"Add a receipt" does not.

Each step knows whether it is done, why it matters in one line, and -- where
Tally can already work it out -- what the answer probably is. A checklist that
only nags is a worse version of an empty page.
"""
from datetime import date, timedelta
from decimal import Decimal

from . import budgets, goals

ZERO = Decimal(0)
# Below this there is not enough history for a suggestion to be worth making.
ENOUGH_HISTORY_DAYS = 45


def _scalar(conn, sql: str, params=()) -> int:
    row = conn.execute(sql, params).fetchone()
    return list(row.values())[0] if row else 0


def state(conn) -> dict:
    """Everything the welcome screen needs, in one read."""
    items = _scalar(conn, "SELECT count(*) AS n FROM items")
    accounts = _scalar(conn, "SELECT count(*) AS n FROM v_acct WHERE NOT hidden")
    txns = _scalar(conn, "SELECT count(*) AS n FROM v_txn")
    first = conn.execute("SELECT min(date) AS d, max(date) AS x FROM v_txn").fetchone()
    span = ((first["x"] - first["d"]).days if first["d"] and first["x"] else 0)

    budgeted = _scalar(conn, "SELECT count(*) AS n FROM budgets WHERE tally_can_see(owner_id)")
    goal_count = _scalar(conn,
                         "SELECT count(*) AS n FROM goals WHERE NOT archived AND tally_can_see(owner_id)")
    funds = _scalar(conn, "SELECT count(*) AS n FROM funds WHERE tally_can_see(owner_id)")
    people = _scalar(conn, "SELECT count(*) AS n FROM people")
    alerts = _scalar(conn, "SELECT count(*) AS n FROM alerts")

    steps = []

    steps.append({
        "key": "connect",
        "title": "Connect a bank",
        "why": "Everything else reads from this. Nothing leaves your machine except the call to Plaid.",
        "done": items > 0,
        "detail": (f"{items} connected, {accounts} accounts, {txns:,} transactions"
                   if items else "Tally has nothing to read yet."),
        "action": "/accounts",
        "action_label": "Connect",
        "blocking": True,
    })

    # A budget before there is anything to budget against is a guess, so this
    # step only appears once there is enough history to suggest real numbers.
    ready_for_budgets = span >= ENOUGH_HISTORY_DAYS
    suggestion = None
    if ready_for_budgets and not budgeted:
        picks = budgets.suggest(conn)
        if picks:
            suggestion = {
                "categories": len(picks),
                "total": sum((p["amount"] for p in picks), ZERO),
                "top": [{"label": p["label"], "amount": p["amount"]} for p in picks[:4]],
            }
    steps.append({
        "key": "budget",
        "title": "Set the month's budgets",
        "why": "The Budget page is blank until something is set, and the pace warnings have nothing to warn about.",
        "done": budgeted > 0,
        "detail": (f"{budgeted} categories budgeted" if budgeted
                   else f"Tally can fill these in from the last three months"
                        if suggestion else "Needs a few weeks of history first."),
        "action": "/budget",
        "action_label": "Set them up",
        "ready": ready_for_budgets,
        "suggestion": suggestion,
    })

    goal_ideas = goals.suggestions(conn) if items else []
    steps.append({
        "key": "goal",
        "title": "Pick something to aim at",
        "why": "Net worth is a chart until it has a destination. A goal turns it into a question with an answer.",
        "done": goal_count > 0,
        "detail": (f"{goal_count} goals" if goal_count
                   else goal_ideas[0]["why"] if goal_ideas else "Connect a bank first."),
        "action": "/goals",
        "action_label": "Add a goal",
        "ready": items > 0,
        "suggestion": {"ideas": [{"name": g["name"], "why": g["why"]} for g in goal_ideas[:2]]}
                      if goal_ideas else None,
    })

    # The first scan is what turns "we found some fees" from a claim into a list.
    steps.append({
        "key": "review",
        "title": "Look at what Tally found",
        "why": "Fees you can get back, subscriptions that went up, and anything that looks wrong on a card.",
        "done": alerts > 0,
        "detail": (f"{alerts} things flagged so far" if alerts
                   else "Runs automatically after each sync."),
        "action": "/alerts",
        "action_label": "See the list",
        "ready": txns > 0,
    })

    steps.append({
        "key": "household",
        "title": "Add anyone else",
        "why": "Each person gets their own login. An account with an owner is visible to them alone.",
        "done": people > 1,
        "detail": (f"{people} people" if people > 1 else "Optional. Skip it if it is just you."),
        "action": "/household",
        "action_label": "Add someone",
        "optional": True,
    })

    steps.append({
        "key": "fund",
        "title": "Start saving for something",
        "why": "One pot per thing, with gift cards and store credit counted where they actually work.",
        "done": funds > 0,
        "detail": f"{funds} on the list" if funds else "Optional.",
        "action": "/funds",
        "action_label": "Add one",
        "optional": True,
    })

    required = [s for s in steps if not s.get("optional")]
    done = [s for s in required if s["done"]]
    return {
        "steps": steps,
        "done": len(done),
        "total": len(required),
        "complete": len(done) == len(required),
        # Only worth interrupting somebody for while the basics are missing.
        "show_welcome": not steps[0]["done"] or len(done) < 2,
        "history_days": span,
        "counts": {"items": items, "accounts": accounts, "transactions": txns,
                   "budgets": budgeted, "goals": goal_count, "funds": funds,
                   "people": people, "alerts": alerts},
    }


def first_month(conn, today: date | None = None) -> dict:
    """One honest paragraph about what Tally can already see, for the welcome
    screen to show instead of a progress bar with nothing behind it."""
    today = today or date.today()
    since = today - timedelta(days=90)
    row = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS spent, coalesce(sum(income), 0) AS earned,
                  count(*) AS n
           FROM v_txn WHERE date >= %s""", (since,)).fetchone()
    top = conn.execute(
        """SELECT category_label AS label, coalesce(sum(spend), 0) AS amount
           FROM v_txn WHERE kind = 'expense' AND date >= %s
           GROUP BY 1 ORDER BY 2 DESC LIMIT 3""", (since,)).fetchall()
    fees = conn.execute(
        """SELECT coalesce(sum(spend), 0) AS amount, count(*) AS n
           FROM v_txn WHERE category = 'fees' AND date >= %s""", (since,)).fetchone()
    return {
        "since": since, "transactions": row["n"],
        "spent": row["spent"], "earned": row["earned"],
        "top_categories": top,
        "fees": {"amount": fees["amount"], "count": fees["n"]},
    }
