"""Brokerage and retirement accounts: what is held, what it cost, what goes in.

Plaid gives holdings and investment transactions for most brokerages and many
401k providers. Everything here is arithmetic on those rows. Tally reports; it
never recommends a trade or an allocation (HANDOFF invariant 1 in spirit: this
app does not move money, and it is not an adviser).
"""
from collections import defaultdict
from datetime import date
from decimal import Decimal

ZERO = Decimal(0)
RETIREMENT = {"401k", "401a", "403B", "403b", "457b", "ira", "roth", "roth 401k", "sep ira",
              "simple ira", "sarsep", "pension", "retirement", "keogh", "tsp"}


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"))


def is_retirement(subtype: str | None) -> bool:
    return (subtype or "").lower() in RETIREMENT


def portfolio(conn) -> dict:
    accounts = conn.execute(
        """SELECT a.id, a.name, a.mask, a.subtype, a.current_balance, COALESCE(inst.name, a.institution_name) AS institution
           FROM v_acct a LEFT JOIN items i ON i.id = a.item_id
           LEFT JOIN institutions inst ON inst.id = i.institution_id
           WHERE NOT a.hidden AND a.type = 'investment'
           ORDER BY a.current_balance DESC NULLS LAST""").fetchall()
    if not accounts:
        return {"accounts": [], "total_value": ZERO, "holdings": [], "allocation": [],
                "contributions_ytd": ZERO, "has_data": False}

    holdings = conn.execute(
        """SELECT h.account_id, a.name AS account_name, a.mask AS account_mask, a.subtype,
                  s.id AS security_id, s.ticker, s.name AS security_name, s.type AS security_type,
                  s.is_cash_equivalent, h.quantity, h.price, h.price_as_of, h.value, h.cost_basis
           FROM holdings h
           JOIN accounts a ON a.id = h.account_id
           JOIN securities s ON s.id = h.security_id
           WHERE NOT a.hidden
           ORDER BY h.value DESC NULLS LAST""").fetchall()

    total_value = sum((_q(h["value"]) for h in holdings), ZERO)
    # Not every provider reports cost basis; gain is only shown for the part
    # that does, and the response says how much of the portfolio that covers.
    with_basis = [h for h in holdings if h["cost_basis"] is not None and h["value"] is not None]
    basis = sum((_q(h["cost_basis"]) for h in with_basis), ZERO)
    basis_value = sum((_q(h["value"]) for h in with_basis), ZERO)

    by_type: dict[str, Decimal] = defaultdict(Decimal)
    for h in holdings:
        key = "cash" if h["is_cash_equivalent"] else (h["security_type"] or "other")
        by_type[key] += _q(h["value"])

    year_start = date.today().replace(month=1, day=1)
    contributions = conn.execute(
        """SELECT it.account_id, a.subtype, coalesce(sum(it.amount), 0) AS amount
           FROM investment_transactions it JOIN accounts a ON a.id = it.account_id
           WHERE it.date >= %s AND (it.subtype ILIKE '%%contribution%%' OR it.type = 'cash')
             AND it.amount > 0
           GROUP BY 1, 2""", (year_start,)).fetchall()
    contrib_by_account = {c["account_id"]: _q(c["amount"]) for c in contributions}

    recent = conn.execute(
        """SELECT it.date, it.name, it.type, it.subtype, it.quantity, it.amount,
                  s.ticker, s.name AS security_name, a.name AS account_name
           FROM investment_transactions it
           LEFT JOIN securities s ON s.id = it.security_id
           JOIN accounts a ON a.id = it.account_id
           ORDER BY it.date DESC, it.id LIMIT 25""").fetchall()

    holdings_by_account: dict[str, list] = defaultdict(list)
    for h in holdings:
        holdings_by_account[h["account_id"]].append(h)

    account_rows = []
    for a in accounts:
        hs = holdings_by_account.get(a["id"], [])
        value = sum((_q(h["value"]) for h in hs), ZERO) or _q(a["current_balance"])
        account_rows.append({
            **a, "value": value, "holdings": len(hs),
            "retirement": is_retirement(a["subtype"]),
            "contributions_ytd": contrib_by_account.get(a["id"], ZERO),
        })

    return {
        "has_data": bool(holdings),
        "accounts": account_rows,
        "total_value": total_value or sum((_q(a["current_balance"]) for a in accounts), ZERO),
        "retirement_value": sum((r["value"] for r in account_rows if r["retirement"]), ZERO),
        "taxable_value": sum((r["value"] for r in account_rows if not r["retirement"]), ZERO),
        "cost_basis": basis,
        "gain": basis_value - basis,
        "gain_percent": float((basis_value - basis) / basis) if basis > 0 else None,
        "basis_coverage": float(basis_value / total_value) if total_value > 0 else None,
        "holdings": [{**h, "value": _q(h["value"]),
                      "gain": (_q(h["value"]) - _q(h["cost_basis"])) if h["cost_basis"] is not None else None,
                      "weight": float(_q(h["value"]) / total_value) if total_value > 0 else None}
                     for h in holdings],
        "allocation": sorted(({"type": k, "value": v,
                               "percent": float(v / total_value) if total_value > 0 else None}
                              for k, v in by_type.items()), key=lambda r: -r["value"]),
        "contributions_ytd": sum(contrib_by_account.values(), ZERO),
        "recent": recent,
    }
