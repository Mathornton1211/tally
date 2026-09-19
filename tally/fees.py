"""Fees: find every one, then say how to stop it, in the owner's own numbers.

HANDOFF section 6. Detection is deterministic: Plaid's BANK_FEES categories
first, then the bank's own wording. The playbook text is templated from facts
pulled out of the database, so every number in it is real. Nothing here asks a
model anything; phrasing can be softened by one later without changing a fact.
"""
import re
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal

FEE_TYPES = {
    "overdraft":    {"label": "Overdraft",               "avoidable": True},
    "nsf":          {"label": "Insufficient funds",      "avoidable": True},
    "maintenance":  {"label": "Monthly account fee",     "avoidable": True},
    "atm":          {"label": "ATM fee",                 "avoidable": True},
    "foreign":      {"label": "Foreign transaction fee", "avoidable": True},
    "late":         {"label": "Late payment",            "avoidable": True},
    "interest":     {"label": "Card interest",           "avoidable": True},
    "cash_advance": {"label": "Cash advance",            "avoidable": True},
    "paper":        {"label": "Paper statement",         "avoidable": True},
    "annual":       {"label": "Annual card fee",         "avoidable": None},   # worth it or not
    "wire":         {"label": "Wire transfer",           "avoidable": False},
    "other":        {"label": "Other bank fee",          "avoidable": None},
}

_DETAILED = {
    "BANK_FEES_OVERDRAFT_FEES": "overdraft",
    "BANK_FEES_INSUFFICIENT_FUNDS": "nsf",
    "BANK_FEES_ATM_FEES": "atm",
    "BANK_FEES_FOREIGN_TRANSACTION_FEES": "foreign",
    "BANK_FEES_LATE_FEES": "late",
    "BANK_FEES_INTEREST_CHARGE": "interest",
    "BANK_FEES_CASH_ADVANCE": "cash_advance",
}

_WORDS = [
    (re.compile(r"ANNUAL (MEMBERSHIP )?FEE", re.I), "annual"),
    (re.compile(r"PAPER STATEMENT", re.I), "paper"),
    (re.compile(r"MONTHLY (SERVICE|MAINTENANCE)|SERVICE CHARGE|MAINTENANCE FEE", re.I), "maintenance"),
    (re.compile(r"OVERDRAFT|OD FEE", re.I), "overdraft"),
    (re.compile(r"\bNSF\b|INSUFFICIENT|RETURNED ITEM", re.I), "nsf"),
    (re.compile(r"\bATM\b.*FEE|NON-NETWORK", re.I), "atm"),
    (re.compile(r"FOREIGN (TRANS|TXN|CURRENCY)", re.I), "foreign"),
    (re.compile(r"LATE (PAYMENT )?FEE", re.I), "late"),
    (re.compile(r"INTEREST CHARGE|PURCHASE INTEREST", re.I), "interest"),
    (re.compile(r"CASH ADVANCE", re.I), "cash_advance"),
    (re.compile(r"\bWIRE\b.*FEE", re.I), "wire"),
]
_ANY_FEE = re.compile(r"\bFEE\b|INTEREST CHARGE", re.I)

_FOREIGN_TAIL = re.compile(r"\s(MX|MEX|CAN|GBR|FRA|DEU|ESP|ITA|JPN)$|\s[A-Z]{2}\s(MX|CA|GB)$", re.I)


def classify(row: dict) -> str | None:
    """Fee type for a transaction, or None if it is not a fee."""
    if Decimal(row["amount"]) <= 0:
        return None
    name = row.get("bank_text") or row["name"] or ""
    in_fees = row.get("pfc_primary") == "BANK_FEES" or row.get("category") == "fees"
    if in_fees:
        for rx, kind in _WORDS:  # the bank's own words beat a generic Plaid bucket
            if rx.search(name):
                return kind
        return _DETAILED.get(row.get("pfc_detailed") or "", "other")
    # Outside BANK_FEES only trust an explicit fee word, never a merchant called "Fee Fi Pizza".
    if _ANY_FEE.search(name) and row.get("kind") == "expense":
        for rx, kind in _WORDS:
            if rx.search(name):
                return kind
    return None


def is_foreign(name: str) -> bool:
    return bool(_FOREIGN_TAIL.search(name or ""))


def _money(v) -> str:
    return f"${Decimal(v):,.2f}"


# ---------------------------------------------------------------- report

def report(conn, start: date, end: date) -> dict:
    rows = conn.execute(
        """SELECT id, date, amount, name, bank_text, display_name, pfc_primary, pfc_detailed, category, kind,
                  account_id, account_name, account_mask, account_type, institution
           FROM v_txn WHERE date BETWEEN %s AND %s AND amount > 0
             AND (category = 'fees' OR pfc_primary = 'BANK_FEES' OR bank_text ~* '\\mFEE\\M|INTEREST CHARGE')
           ORDER BY date DESC""", (start, end)).fetchall()

    fees = []
    for r in rows:
        kind = classify(r)
        if kind:
            fees.append({**r, "fee_type": kind, "fee_label": FEE_TYPES[kind]["label"],
                         "avoidable": FEE_TYPES[kind]["avoidable"]})

    by_type: dict[str, list[dict]] = defaultdict(list)
    for f in fees:
        by_type[f["fee_type"]].append(f)

    settings = {r["account_id"]: r for r in conn.execute("SELECT * FROM account_settings").fetchall()}
    accounts = {r["id"]: r for r in conn.execute(
        """SELECT a.id, a.name, a.mask, a.type, a.subtype, a.current_balance, COALESCE(inst.name, a.institution_name) AS institution
           FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
           LEFT JOIN institutions inst ON inst.id = i.institution_id WHERE NOT a.hidden""").fetchall()}

    builders = {
        "overdraft": _overdraft, "nsf": _overdraft, "maintenance": _maintenance, "atm": _atm,
        "foreign": _foreign, "late": _late, "interest": _interest, "annual": _annual,
        "paper": _paper, "cash_advance": _cash_advance,
    }
    plays = []
    for kind, items in by_type.items():
        total = sum(Decimal(i["amount"]) for i in items)
        play = {
            "type": kind, "label": FEE_TYPES[kind]["label"], "avoidable": FEE_TYPES[kind]["avoidable"],
            "total": total, "count": len(items), "last_date": items[0]["date"],
            "accounts": sorted({f"{i['account_name']} ··{i['account_mask']}" for i in items}),
            "facts": [], "steps": [], "script": None, "needs": [],
        }
        builder = builders.get(kind)
        if builder:
            builder(conn, play, items, accounts, settings)
        plays.append(play)
    plays.sort(key=lambda p: p["total"], reverse=True)

    total = sum(Decimal(f["amount"]) for f in fees)
    avoidable = sum(Decimal(f["amount"]) for f in fees if f["avoidable"])
    months = defaultdict(Decimal)
    for f in fees:
        months[f["date"].replace(day=1)] += Decimal(f["amount"])
    return {
        "start": start, "end": end, "total": total, "avoidable": avoidable, "count": len(fees),
        "by_month": [{"month": m, "amount": a} for m, a in sorted(months.items())],
        "playbook": plays, "fees": fees,
    }


# ---------------------------------------------------------------- playbook builders

def _fee_noun(label: str) -> str:
    noun = label.lower()
    return noun if noun.endswith("fee") else f"{noun} fee"


def _courtesy_script(item: dict, first_seen: date | None, label: str) -> str:
    tenure = f"I've banked with you since {first_seen:%B %Y}, and this" if first_seen else "This"
    return (f"Hi, I'm calling about a {_money(item['amount'])} {_fee_noun(label)} charged on "
            f"{item['date']:%B} {item['date'].day} to my {item['account_name']} ending in {item['account_mask']}. "
            f"{tenure} was a one-time timing issue that I've already fixed. "
            f"Could you reverse it as a courtesy?")


def _first_seen(conn, account_id: str) -> date | None:
    r = conn.execute("SELECT min(date) AS d FROM transactions WHERE account_id = %s", (account_id,)).fetchone()
    return r["d"] if r else None


def _overdraft(conn, play, items, accounts, settings):
    worst = []
    for fee in items[:3]:
        day_rows = conn.execute(
            """SELECT display_name, amount FROM v_txn
               WHERE account_id = %s AND date BETWEEN %s AND %s AND amount > 0 AND id <> %s
                 AND category <> 'fees' ORDER BY amount DESC LIMIT 3""",
            (fee["account_id"], fee["date"] - timedelta(days=1), fee["date"], fee["id"])).fetchall()
        if day_rows:
            what = ", ".join(f"{r['display_name']} {_money(r['amount'])}" for r in day_rows)
            worst.append(f"{fee['date']:%b} {fee['date'].day}: {what} cleared when the balance was too low.")
        else:
            worst.append(f"{fee['date']:%b} {fee['date'].day}: nothing large cleared that day, so the balance "
                         f"was already running close to zero going in.")
    play["facts"] += worst

    acct_id = items[0]["account_id"]
    acct = accounts.get(acct_id)
    acct_name = acct["name"] if acct else "checking"
    # Everyday outflows only. Rent is predictable and gets its own line; folding
    # it into a percentile turns the advice into "keep rent in checking forever".
    cushion = conn.execute(
        """SELECT percentile_cont(0.9) WITHIN GROUP (ORDER BY out) AS p90 FROM (
             SELECT date, sum(amount) AS out FROM v_txn
             WHERE account_id = %s AND amount > 0 AND kind = 'expense' AND category NOT IN ('rent', 'loans')
               AND date >= current_date - 180
             GROUP BY date) d""", (acct_id,)).fetchone()["p90"]
    big = conn.execute(
        """SELECT display_name, max(amount) AS amount, mode() WITHIN GROUP (ORDER BY extract(day FROM date)) AS dom
           FROM v_txn WHERE account_id = %s AND category IN ('rent', 'loans') AND date >= current_date - 100
           GROUP BY display_name ORDER BY 2 DESC LIMIT 1""", (acct_id,)).fetchone()
    buffer = max(Decimal(100), round(Decimal(cushion or 150) * 2, -1))
    savings = [a for a in accounts.values() if a["type"] == "depository" and a["subtype"] == "savings"
               and Decimal(a["current_balance"] or 0) > 500]
    play["steps"].append(f"Keep a {_money(buffer)} floor in {acct_name}. That is twice your heavier everyday "
                         f"spending days, excluding rent and loan payments.")
    if big:
        play["steps"].append(f"Your largest scheduled payment is {big['display_name']} at {_money(big['amount'])} "
                             f"around day {int(big['dom'])} of the month. Check the balance two days before it.")
    if savings:
        s = max(savings, key=lambda a: Decimal(a["current_balance"] or 0))
        play["steps"].append(
            f"Turn on overdraft protection linked to {s['name']} ··{s['mask']} "
            f"({_money(s['current_balance'])}). A transfer usually costs nothing; an overdraft is {_money(items[0]['amount'])}.")
    play["steps"].append("Ask the bank to decline card purchases instead of covering them (opt out of overdraft coverage).")
    play["script"] = _courtesy_script(items[0], _first_seen(conn, items[0]["account_id"]), play["label"])


def _maintenance(conn, play, items, accounts, settings):
    acct_id = items[0]["account_id"]
    acct = accounts.get(acct_id)
    s = settings.get(acct_id) or {}
    months = len({i["date"].replace(day=1) for i in items})
    play["facts"].append(f"Charged in {months} month{'s' if months != 1 else ''} on {acct['name'] if acct else 'this account'}.")
    if s.get("min_balance_waiver"):
        play["steps"].append(f"The fee is waived above {_money(s['min_balance_waiver'])}. "
                             f"Today's balance is {_money(acct['current_balance'])}.")
    else:
        play["needs"].append({"account_id": acct_id, "field": "min_balance_waiver",
                              "ask": "What balance waives this account's monthly fee?"})
    fee_free = {r["account_id"] for r in conn.execute(
        """SELECT a.id AS account_id FROM v_acct a
           WHERE a.subtype = 'checking' AND NOT a.hidden AND NOT EXISTS (
             SELECT 1 FROM v_txn v WHERE v.account_id = a.id AND v.category = 'fees'
               AND v.date >= current_date - 365)""").fetchall()}
    free = [a for a in accounts.values() if a["id"] in fee_free and a["id"] != acct_id]
    if free:
        names = " or ".join(f"{a['name']} ··{a['mask']}" for a in free[:2])
        play["steps"].append(f"You already have checking with no fees this year: {names}. "
                             f"Moving direct deposit and bills there ends this fee for good.")
    play["steps"].append("Many credit unions waive it with one direct deposit a month. Ask which rule applies.")
    first = _first_seen(conn, acct_id)
    play["script"] = (f"Hi, I've been charged a {_money(items[0]['amount'])} monthly fee on my "
                      f"{items[0]['account_name']} ending in {items[0]['account_mask']} "
                      f"{len(items)} time{'s' if len(items) != 1 else ''} recently"
                      f"{f', and I have banked with you since {first:%B %Y}' if first else ''}. "
                      f"What exactly do I need to do to have it waived, and can you refund the last one?")


def _atm(conn, play, items, accounts, settings):
    # The withdrawal that caused each fee: same account, same day, not itself a
    # fee. Pairing works even when Plaid has renamed the line to the store name.
    places: dict[str, int] = defaultdict(int)
    cash_out = Decimal(0)
    for fee in items:
        w = conn.execute(
            """SELECT display_name, amount FROM v_txn WHERE account_id = %s AND date = %s AND id <> %s
                 AND category <> 'fees' AND amount > 0
               ORDER BY (bank_text ~* 'ATM|WITHDRAW|CASH') DESC, (amount %% 20 = 0) DESC, amount DESC LIMIT 1""",
            (fee["account_id"], fee["date"], fee["id"])).fetchone()
        if w:
            places[w["display_name"]] += 1
            cash_out += Decimal(w["amount"])
    if places:
        top = max(places, key=places.get)
        play["facts"].append(f"{sum(places.values())} out-of-network withdrawals totaling {_money(cash_out)}, "
                             f"most at {top} ({places[top]}).")
    grocer = conn.execute(
        """SELECT display_name, count(*) AS n FROM v_txn
           WHERE category = 'groceries' AND date >= current_date - 90
           GROUP BY display_name ORDER BY n DESC LIMIT 1""").fetchone()
    if grocer:
        play["steps"].append(f"Get cash back at checkout at {grocer['display_name']}, where you shopped "
                             f"{grocer['n']} times in the last 90 days. It is free.")
    play["steps"].append("If your credit union is on the CO-OP network, its ATM locator lists thousands of fee-free machines. Check it before withdrawing.")
    per_year = Decimal(items[0]["amount"]) * Decimal(len(items)) * Decimal(365) / Decimal(max(30, (play["last_date"] - items[-1]["date"]).days or 30))
    play["facts"].append(f"At this pace that is about {_money(round(per_year, 0))} a year in ATM fees alone, before any operator surcharge.")


def _foreign(conn, play, items, accounts, settings):
    trips = defaultdict(list)
    for i in items:
        trips[(i["account_id"], i["date"].isocalendar()[:2])].append(i)
    for (acct_id, _), fees in list(trips.items())[:3]:
        spent = conn.execute(
            """SELECT coalesce(sum(amount), 0) AS s, min(date) AS d FROM v_txn
               WHERE account_id = %s AND date BETWEEN %s AND %s AND category <> 'fees' AND amount > 0""",
            (acct_id, min(f["date"] for f in fees) - timedelta(days=1), max(f["date"] for f in fees) + timedelta(days=1))).fetchone()
        acct = accounts[acct_id]
        play["facts"].append(f"{_money(spent['s'])} spent abroad on {acct['name']} ··{acct['mask']} "
                             f"cost {_money(sum(Decimal(f['amount']) for f in fees))} extra.")
    charged = {i["account_id"] for i in items}
    marked_free = [accounts[a] for a, s in settings.items() if a in accounts and s.get("foreign_fee_pct") is not None
                   and Decimal(s["foreign_fee_pct"]) == 0]
    for a in marked_free:
        if a["id"] in charged:
            play["facts"].append(f"{a['name']} ··{a['mask']} is marked as having no foreign transaction fee, but it "
                                 f"charged one. Check the card terms, or dispute the fee if the card really has none.")
    no_ftf = [a for a in marked_free if a["id"] not in charged]
    if no_ftf:
        play["steps"].append("Use " + " or ".join(f"{a['name']} ··{a['mask']}" for a in no_ftf)
                             + " outside the US. You told Tally it has no foreign transaction fee.")
    else:
        play["needs"].append({"field": "foreign_fee_pct", "ask": "Which of your cards charge no foreign transaction fee?"})
        play["steps"].append("Pick one card with no foreign transaction fee and keep it for trips. Many travel and "
                             "no-annual-fee cards have none; mark it in Accounts so Tally can remind you.")
    play["steps"].append("If a card terminal abroad offers to charge you in dollars, say no and pay in pesos. "
                         "That conversion is usually worse than the fee.")


def _late(conn, play, items, accounts, settings):
    for i in items[:3]:
        play["facts"].append(f"{i['date']:%b} {i['date'].day}: {_money(i['amount'])} on {i['account_name']} ··{i['account_mask']}.")
    play["steps"].append("Set autopay for at least the minimum payment on every card. It turns a missed "
                         "due date into a non-event, and you can still pay more by hand.")
    play["steps"].append("A late payment 30+ days past due can hit your credit report. If this was the first "
                         "one, call today: first late fees are reversed more often than not.")
    play["script"] = _courtesy_script(items[0], _first_seen(conn, items[0]["account_id"]), play["label"])


def _interest(conn, play, items, accounts, settings):
    per_card = defaultdict(Decimal)
    for i in items:
        per_card[i["account_id"]] += Decimal(i["amount"])
    for acct_id, amt in sorted(per_card.items(), key=lambda kv: kv[1], reverse=True):
        a = accounts[acct_id]
        apr = (settings.get(acct_id) or {}).get("apr")
        apr_txt = f" at {Decimal(apr):.2f}% APR" if apr else ""
        play["facts"].append(f"{_money(amt)} of interest on {a['name']} ··{a['mask']}{apr_txt}, "
                             f"balance now {_money(a['current_balance'])}.")
        if not apr:
            play["needs"].append({"account_id": acct_id, "field": "apr", "ask": f"What APR does {a['name']} charge?"})
    play["steps"].append("Pay the full statement balance, not the current balance and not the minimum. "
                         "Paying the statement balance by the due date means zero interest on new purchases.")
    cash = sum(Decimal(a["current_balance"] or 0) for a in accounts.values()
               if a["type"] == "depository" and a["subtype"] == "savings")
    owed = sum(Decimal(accounts[a]["current_balance"] or 0) for a in per_card)
    if cash > owed and owed > 0:
        play["steps"].append(f"You have {_money(cash)} in savings and {_money(owed)} on these cards. "
                             f"Savings earns a few percent; card debt costs twenty-something. Paying it off is the best return available.")


def _annual(conn, play, items, accounts, settings):
    for i in items:
        a = accounts[i["account_id"]]
        renew = i["date"].replace(year=i["date"].year + 1)
        spent = conn.execute(
            "SELECT coalesce(sum(spend), 0) AS s FROM v_txn WHERE account_id = %s AND date >= current_date - 365",
            (i["account_id"],)).fetchone()["s"]
        rate = (settings.get(i["account_id"]) or {}).get("reward_rate")
        play["facts"].append(f"{_money(i['amount'])} on {a['name']} ··{a['mask']}, renews around {renew:%B %Y}. "
                             f"{_money(spent)} spent on it in the last year.")
        if rate:
            earned = Decimal(spent) * Decimal(rate) / 100
            verdict = "earns its fee" if earned >= Decimal(i["amount"]) else "does not earn its fee back in rewards alone"
            play["steps"].append(f"At {Decimal(rate):.1f}% back that is about {_money(earned)} in rewards, so the card {verdict}. "
                                 f"Count any credits you actually use before deciding.")
        else:
            play["needs"].append({"account_id": i["account_id"], "field": "reward_rate",
                                  "ask": f"About what percent back does {a['name']} earn?"})
        play["steps"].append(f"Around {renew - timedelta(days=45):%B %Y}, call and ask for a retention offer or a "
                             f"downgrade to the no-fee version. Downgrading keeps the account age; closing loses it.")


def _paper(conn, play, items, accounts, settings):
    a = accounts[items[0]["account_id"]]
    play["steps"].append(f"Switch {a['name']} ··{a['mask']} to e-statements in the bank's app.")
    if Decimal(a["current_balance"] or 0) < 100:
        play["steps"].append(f"This account holds {_money(a['current_balance'])}. If you do not use it, "
                             f"closing it removes the fee and one more login to watch.")


def _cash_advance(conn, play, items, accounts, settings):
    play["steps"].append("Cash advances start charging interest the same day, usually at a higher APR than purchases. "
                         "Use a debit card at an in-network ATM instead.")
