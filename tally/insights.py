"""Consolidation and money-left-on-the-table. HANDOFF section 7.

Every recommendation carries an annual dollar figure computed here and the
assumptions behind it. Where a number depends on something Plaid does not
provide (an APR, an APY), it is either estimated from real interest lines,
labeled as an estimate, or the insight asks for the missing fact instead.
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

from . import analytics, fees

ZERO = Decimal(0)


def _m(v) -> str:
    return f"${Decimal(v):,.0f}" if abs(Decimal(v)) >= 100 else f"${Decimal(v):,.2f}"


def _acct(a) -> str:
    return f"{a['name']} ··{a['mask']}" if a.get("mask") else a["name"]


def estimate_rates(accounts: list[dict], interest_rows: list[dict]) -> dict[str, dict]:
    """Effective yearly rate from the last 90 days of interest lines vs balance.

    Savings: interest earned / balance. Cards: interest charged / balance.
    Rough by design (balances move within the month), so always shown as ~.
    """
    by_acct: dict[str, Decimal] = defaultdict(Decimal)
    for r in interest_rows:
        by_acct[r["account_id"]] += abs(Decimal(r["amount"]))
    out = {}
    for a in accounts:
        bal = abs(Decimal(a["current_balance"] or 0))
        paid = by_acct.get(a["id"], ZERO)
        if bal > 0 and paid > 0:
            out[a["id"]] = {"rate": (paid * 4 / bal * 100).quantize(Decimal("0.01")), "basis_90d": paid}
    return out


def compute(conn, today: date | None = None) -> dict:
    today = today or date.today()
    accounts = conn.execute(
        """SELECT a.id, a.name, a.mask, a.type, a.subtype, a.current_balance, a.credit_limit,
                  COALESCE(inst.name, a.institution_name) AS institution, s.apy, s.apr, s.annual_fee, s.reward_rate
           FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
           LEFT JOIN institutions inst ON inst.id = i.institution_id
           LEFT JOIN account_settings s ON s.account_id = a.id
           WHERE NOT a.hidden""").fetchall()
    by_id = {a["id"]: a for a in accounts}
    activity = {r["account_id"]: r for r in conn.execute(
        """SELECT account_id, max(date) FILTER (WHERE category NOT IN ('interest','fees')) AS last_real,
                  count(*) FILTER (WHERE date >= current_date - 90 AND category NOT IN ('interest','fees')) AS n90,
                  coalesce(sum(amount) FILTER (WHERE category = 'fees' AND date >= current_date - 365), 0) AS fees_12m,
                  coalesce(sum(amount) FILTER (WHERE amount > 0 AND kind <> 'income' AND date >= current_date - 90), 0) / 3 AS out_monthly
           FROM v_txn GROUP BY account_id""").fetchall()}
    interest_rows = conn.execute(
        """SELECT account_id, amount, category, pfc_detailed FROM v_txn
           WHERE date >= current_date - 90 AND (category = 'interest' OR pfc_detailed = 'BANK_FEES_INTEREST_CHARGE'
                 OR name ~* 'INTEREST CHARGE')""").fetchall()
    earned = estimate_rates([a for a in accounts if a["type"] == "depository"],
                            [r for r in interest_rows if r["category"] == "interest"])
    charged = estimate_rates([a for a in accounts if a["type"] in ("credit", "loan")],
                             [r for r in interest_rows if r["category"] != "interest"])

    recs: list[dict] = []

    # --- Cash earning less than it could.
    cash = [a for a in accounts if a["type"] == "depository" and Decimal(a["current_balance"] or 0) > 0]

    def apy_of(a):
        if a["apy"] is not None:
            return Decimal(a["apy"]), "you entered"
        if a["id"] in earned:
            return earned[a["id"]]["rate"], "estimated from interest paid"
        return None, None

    rated = [(a, *apy_of(a)) for a in cash]
    known = [(a, r, src) for a, r, src in rated if r is not None]
    if known:
        best, best_rate, best_src = max(known, key=lambda x: x[1])
        for a, rate, src in rated:
            if a["id"] == best["id"]:
                continue
            bal = Decimal(a["current_balance"] or 0)
            if a["subtype"] == "checking":
                buffer = max(Decimal(1000), Decimal(activity.get(a["id"], {}).get("out_monthly") or 0) * Decimal("1.5"))
                movable = bal - buffer
                why = f"keeping {_m(buffer)} in checking for about six weeks of bills"
            else:
                movable = bal
                why = "the whole balance"
            this_rate = rate if rate is not None else ZERO
            gain = (movable * (best_rate - this_rate) / 100).quantize(Decimal("0.01"))
            if movable >= 500 and gain >= 20:
                recs.append({
                    "kind": "cash_drag", "priority": "high" if gain >= 150 else "medium",
                    "title": f"Move {_m(movable)} from {_acct(a)} to {_acct(best)}",
                    "impact": gain,
                    "detail": f"{_acct(best)} earns ~{best_rate:.2f}% ({best_src}); {_acct(a)} earns "
                              f"{'~' + format(this_rate, '.2f') + '%' if rate is not None else 'nothing Tally can see'}. "
                              f"Figured on {why}.",
                    "accounts": [a["id"], best["id"]],
                    "assumptions": ["Rates can change", "Uses today's balances"],
                })

    # --- Card interest.
    cards = [a for a in accounts if a["type"] in ("credit", "loan") and Decimal(a["current_balance"] or 0) > 0]
    interest_12m = {r["account_id"]: Decimal(r["s"]) for r in conn.execute(
        """SELECT account_id, sum(amount) AS s FROM v_txn
           WHERE date >= current_date - 365 AND amount > 0
             AND (pfc_detailed = 'BANK_FEES_INTEREST_CHARGE' OR name ~* 'INTEREST CHARGE')
           GROUP BY account_id""").fetchall()}
    for a in cards:
        paid = interest_12m.get(a["id"], ZERO)
        if paid >= 25:
            apr = Decimal(a["apr"]) if a["apr"] is not None else charged.get(a["id"], {}).get("rate")
            recs.append({
                "kind": "card_interest", "priority": "high",
                "title": f"Stop paying interest on {_acct(a)}",
                "impact": paid,
                "detail": f"{_m(paid)} of interest in the last 12 months on a {_m(a['current_balance'])} balance"
                          f"{f' (~{apr:.1f}% effective)' if apr else ''}. Paying the statement balance in full each month "
                          f"brings this to zero.",
                "accounts": [a["id"]], "assumptions": ["Same spending pattern next year"],
            })

    # --- Debt order when there is more than one balance.
    if len(cards) >= 2:
        def rate(a):
            if a["apr"] is not None:
                return Decimal(a["apr"]), "entered"
            if a["id"] in charged:
                return charged[a["id"]]["rate"], "estimated"
            return None, None
        ranked = sorted(cards, key=lambda a: (rate(a)[0] is None, -(rate(a)[0] or 0)))
        order = []
        for a in ranked:
            r, src = rate(a)
            order.append(f"{_acct(a)} {_m(a['current_balance'])}" + (f" at ~{r:.1f}% ({src})" if r else " (rate unknown)"))
        recs.append({
            "kind": "debt_order", "priority": "medium",
            "title": "Pay extra toward the highest-rate balance first",
            "impact": ZERO,
            "detail": "Minimums on everything, every spare dollar to the top of this list: " + "; ".join(order) + ".",
            "accounts": [a["id"] for a in ranked],
            "assumptions": ["Unknown rates sort last; add APRs in Accounts to fix the order"],
        })

    # --- Idle accounts.
    for a in accounts:
        act = activity.get(a["id"])
        n90 = act["n90"] if act else 0
        bal = Decimal(a["current_balance"] or 0)
        # A savings account that just sits there earning interest is doing its job.
        parked_savings = a["type"] == "depository" and a["id"] in earned and bal >= 500
        if n90 == 0 and a["type"] in ("depository", "credit") and not parked_savings:
            fee_cost = Decimal(act["fees_12m"]) if act else ZERO
            annual = Decimal(a["annual_fee"] or 0)
            impact = fee_cost + annual
            if a["type"] == "credit":
                detail = (f"No purchases in 90 days. {'It costs ' + _m(annual) + ' a year. ' if annual else ''}"
                          f"Closing a no-fee card can lower your credit score by shrinking available credit and "
                          f"account age. Often better: keep it, put one small subscription on it, set autopay.")
            else:
                detail = (f"No activity in 90 days, balance {_m(bal)}"
                          f"{', and it charged ' + _m(fee_cost) + ' in fees this year' if fee_cost else ''}. "
                          f"Move the balance and close it: one less login to watch for fraud.")
            recs.append({
                "kind": "idle_account", "priority": "medium" if impact else "low",
                "title": f"{_acct(a)} is sitting idle", "impact": impact, "detail": detail,
                "accounts": [a["id"]], "assumptions": [],
            })

    # --- Subscriptions.
    stream_rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind IN ('expense','income') AND date >= current_date - 400""").fetchall()
    streams = [s for s in analytics.detect_recurring(stream_rows) if s.active and s.kind == "expense"]
    by_name: dict[str, list] = defaultdict(list)
    for s in streams:
        by_name[s.name.lower()].append(s)
    for name, ss in by_name.items():
        if len({s.account_id for s in ss}) > 1:
            keep = ss[0]
            waste = sum(s.monthly_cost for s in ss[1:]) * 12
            recs.append({
                "kind": "duplicate_subscription", "priority": "high",
                "title": f"{keep.name} is billed on {len(ss)} cards",
                "impact": waste,
                "detail": "Charged on " + " and ".join(s.account_name for s in ss)
                          + f". Unless two people use separate plans, cancel one and save {_m(waste)} a year.",
                "accounts": [s.account_id for s in ss], "assumptions": ["Both plans are for the same person"],
            })
    for s in streams:
        if s.previous_amount is not None:
            extra = (s.last_amount - s.previous_amount) * 12
            recs.append({
                "kind": "price_increase", "priority": "low",
                "title": f"{s.name} went from {_m(s.previous_amount)} to {_m(s.last_amount)}",
                "impact": extra,
                "detail": f"{_m(extra)} more a year than before. Worth checking for a cheaper plan, "
                          f"an annual option, or whether you still use it.",
                "accounts": [s.account_id], "assumptions": [],
            })
    subs_total = sum(s.monthly_cost for s in streams if s.category in ("entertainment", "services", "health"))

    # --- Avoidable fees roll-up (details live on the Fees page).
    # Card interest already has its own insight above; counting it here too
    # would double the headline number.
    fee_rep = fees.report(conn, today.replace(year=today.year - 1), today)
    plays = [p for p in fee_rep["playbook"] if p["avoidable"] and p["type"] != "interest"]
    avoidable = sum((p["total"] for p in plays), ZERO)
    if avoidable > 0:
        top = max(plays, key=lambda p: p["total"])
        n = sum(p["count"] for p in plays)
        recs.append({
            "kind": "fees", "priority": "high" if avoidable >= 100 else "medium",
            "title": f"{_m(avoidable)} in avoidable bank fees this year",
            "impact": avoidable,
            "detail": f"{n} fees in 12 months, not counting card interest. Biggest: {top['label'].lower()} at "
                      f"{_m(top['total'])}. The Fees page has a fix for each one.",
            "accounts": [], "assumptions": [], "link": "/fees",
        })

    # --- Too many checking accounts.
    checking = [a for a in accounts if a["type"] == "depository" and a["subtype"] == "checking"]
    if len(checking) >= 3:
        recs.append({
            "kind": "consolidate_checking", "priority": "low",
            "title": f"{len(checking)} checking accounts", "impact": ZERO,
            "detail": "Most people need one for bills and maybe one for spending. "
                      + ", ".join(_acct(a) for a in checking) + ".",
            "accounts": [a["id"] for a in checking], "assumptions": [],
        })

    order = {"high": 0, "medium": 1, "low": 2}
    recs.sort(key=lambda r: (-r["impact"], order[r["priority"]]))
    return {
        "total_impact": sum(r["impact"] for r in recs),
        "subscriptions_monthly": subs_total,
        "recommendations": recs,
        "rates": {
            "savings": {k: v["rate"] for k, v in earned.items()},
            "debt": {k: v["rate"] for k, v in charged.items()},
        },
        "accounts": [{**a, "estimated_apy": earned.get(a["id"], {}).get("rate"),
                      "estimated_apr": charged.get(a["id"], {}).get("rate")} for a in accounts],
    }
