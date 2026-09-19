"""Turning "if I took a job paying $120k" into numbers the planner can use.

The whole module exists because of one gap between how people say things and
how money works: **a salary is gross and a budget is net**. Someone who says
"$120k" has about $7,200 a month to spend, not $10,000. Planning a payoff date
on the $10,000 is not a small error -- it is roughly a third of the money, and
every date it produces is a date that will not happen.

So a stated salary is converted, the conversion is returned alongside the
answer rather than hidden inside it, and a person who knows their actual
take-home can state that instead and skip the estimate entirely.

It is an estimate and it is labelled as one everywhere it surfaces. Tally is
not a payroll calculator.
"""
from decimal import ROUND_HALF_UP, Decimal

ZERO = Decimal(0)


def _q(v) -> Decimal:
    return Decimal(v or 0).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# 2025 figures, single filer, standard deduction, no 401k and no pre-tax
# benefits. Kept as one table with the year on it so it is obvious when it goes
# stale, rather than scattered through the arithmetic.
TAX_YEAR = 2025
STANDARD_DEDUCTION = Decimal("15000")
FEDERAL_BRACKETS = [
    (Decimal("11925"), Decimal("0.10")),
    (Decimal("48475"), Decimal("0.12")),
    (Decimal("103350"), Decimal("0.22")),
    (Decimal("197300"), Decimal("0.24")),
    (Decimal("250525"), Decimal("0.32")),
    (Decimal("626350"), Decimal("0.35")),
    (None, Decimal("0.37")),
]
SOCIAL_SECURITY_RATE = Decimal("0.062")
SOCIAL_SECURITY_WAGE_BASE = Decimal("176100")
MEDICARE_RATE = Decimal("0.0145")

# A flat stand-in for state income tax. A real bracket table per state is a
# different project; this is one number a person can correct, and a state with
# no income tax is 0.
DEFAULT_STATE_RATE = Decimal("5.0")


def _federal(taxable: Decimal) -> Decimal:
    owed, last = ZERO, ZERO
    for ceiling, rate in FEDERAL_BRACKETS:
        top = taxable if ceiling is None else min(taxable, ceiling)
        if top > last:
            owed += (top - last) * rate
        if ceiling is None or taxable <= ceiling:
            break
        last = ceiling
    return owed


def take_home(gross_annual, state_rate: Decimal | None = None) -> dict:
    """Estimated monthly take-home from a gross annual salary.

    Every component is returned, not just the total, so the estimate can be
    argued with. Somebody who thinks the state rate is wrong can see exactly
    what it cost them.
    """
    gross = _q(gross_annual)
    state_rate = Decimal(DEFAULT_STATE_RATE if state_rate is None else state_rate)

    taxable = max(gross - STANDARD_DEDUCTION, ZERO)
    federal = _federal(taxable)
    social = min(gross, SOCIAL_SECURITY_WAGE_BASE) * SOCIAL_SECURITY_RATE
    medicare = gross * MEDICARE_RATE
    state = taxable * state_rate / 100
    net = gross - federal - social - medicare - state

    return {
        "gross_annual": gross,
        "gross_monthly": _q(gross / 12),
        "net_annual": _q(net),
        "net_monthly": _q(net / 12),
        "federal": _q(federal),
        "social_security": _q(social),
        "medicare": _q(medicare),
        "state": _q(state),
        "state_rate": state_rate,
        "effective_rate": _q((gross - net) / gross * 100) if gross else ZERO,
        "tax_year": TAX_YEAR,
        "estimate": True,
        "assumes": (f"single filer, standard deduction, {state_rate}% state tax, "
                    "no 401k or pre-tax benefits"),
    }
