"""Bills worth a phone call, with the numbers and a script.

The facts come from what the owner has actually paid: how long, how much, and whether
the price crept up. The script is templated, not generated, so it never invents
a discount that was never offered.
"""
import re
from datetime import date
from decimal import Decimal

from . import analytics

ZERO = Decimal(0)

# Where asking actually works. Rent and loan payments are not on this list.
NEGOTIABLE = {
    "bills": ("provider", "Internet and phone prices are set by retention offers, not by the rate card. "
                          "Utilities do not negotiate, but they do have hardship and budget-billing programs."),
    "insurance": ("insurer", "Rates drift up quietly; a re-rate or a bundled discount is a normal request."),
    "services": ("provider", "Ask what plan you are on and whether a cheaper one covers what you use."),
    "entertainment": ("subscription", "Cheaper tiers, annual plans and pauses usually exist."),
    "health": ("provider", "Gyms often have a hold option instead of a cancellation."),
}
MIN_MONTHLY = Decimal("8")

# What can actually be stopped. Rent, a car loan and the electricity are all
# recurring charges and all belong in the total -- they are most of it -- but
# "here is how to cancel your rent" is not advice, it is the app failing to
# know what it is looking at. Those get the negotiation route or nothing.
CANCELLABLE = {"entertainment", "services", "health", "shopping"}


def _m(v) -> str:
    v = Decimal(v or 0)
    return f"${v:,.2f}"


# A regulated utility does not do retention offers, but it does have programs a
# household with a drop in income usually qualifies for.
UTILITY = re.compile(r"gas|electric|sdge|power|water|utility|energy", re.I)


def _script(name: str, monthly: Decimal, annual: Decimal, months: int, since: date,
            kind: str, increased_from: Decimal | None) -> str:
    tenure = f"I've been with you since {since:%B %Y}" if months >= 3 else "I'm a fairly new customer"
    rise = (f" My bill went from {_m(increased_from)} to {_m(monthly)}, which I noticed."
            if increased_from else "")
    if kind == "utility":
        return (f"Hi, I'm a customer paying about {_m(monthly)} a month. My income has dropped and I want to "
                f"ask about three things: whether I qualify for your income-based discount program (in "
                f"California that is CARE or FERA), level or budget billing to even out the monthly amount, "
                f"and a payment arrangement for the current balance.")
    if kind == "subscription":
        return (f"Hi, I'm paying {_m(monthly)} a month for {name}, about {_m(annual)} a year.{rise} "
                f"Money is tight right now. Is there a cheaper plan, an annual rate, or a way to pause "
                f"the account instead of cancelling it?")
    if kind == "insurer":
        return (f"Hi, {tenure}. I'm paying {_m(monthly)} a month, about {_m(annual)} a year.{rise} "
                f"I'd like my policy re-rated and to hear about any discounts I'm not getting: "
                f"bundling, low mileage, paid in full, or a higher deductible. What can you do?")
    return (f"Hi, {tenure} and I'm paying {_m(monthly)} a month, about {_m(annual)} a year.{rise} "
            f"Money is tight and I'm comparing providers. What promotional rate can you offer to keep me, "
            f"and is there a cheaper plan that still covers what I use?")


def negotiable(conn, today: date | None = None) -> dict:
    today = today or date.today()
    rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind = 'expense' AND date >= current_date - 400""").fetchall()
    streams = [s for s in analytics.detect_recurring(rows) if s.active and s.category in NEGOTIABLE]

    out = []
    for s in streams:
        monthly = s.monthly_cost
        if monthly < MIN_MONTHLY:
            continue
        months = max(1, round((s.last_date - s.first_date).days / 30.4) + 1)
        paid = conn.execute(
            """SELECT coalesce(sum(spend), 0) AS total, count(*) AS n FROM v_txn
               WHERE display_name = %s AND kind = 'expense'""", (s.name,)).fetchone()
        kind = "utility" if (s.category == "bills" and UTILITY.search(s.name)) else NEGOTIABLE[s.category][0]
        annual = (monthly * 12).quantize(Decimal("0.01"))
        out.append({
            "name": s.name, "logo_url": s.logo_url, "category": s.category, "category_label": s.category_label,
            "account_name": s.account_name, "monthly": monthly, "annual": annual,
            "last_amount": s.last_amount, "cadence": s.cadence,
            "since": s.first_date, "months_paid": months,
            "paid_so_far": Decimal(paid["total"]), "charges": paid["n"],
            "increased_from": s.previous_amount, "price_changed_on": s.price_changed_on,
            "why": NEGOTIABLE[s.category][1],
            "kind": kind,
            "script": _script(s.name, monthly, annual, months, s.first_date, kind, s.previous_amount),
        })
    out.sort(key=lambda b: -b["annual"])
    return {
        "bills": out,
        "total_monthly": sum((b["monthly"] for b in out), ZERO),
        "total_annual": sum((b["annual"] for b in out), ZERO),
        "with_increases": sum(1 for b in out if b["increased_from"]),
    }

# ---------------------------------------------------------------- getting out of one
#
# Lowering and cancelling are different conversations and need different words.
# Asking for a discount is a negotiation you want to win; cancelling is a
# process a company has deliberately made annoying, and the useful thing is
# knowing what they will say before they say it.

# What a retention line reliably offers, in the order they offer it. Knowing the
# sequence is most of the advantage: the first offer is never the last one, and
# the word "cancel" is what unlocks the rest of it.
RETENTION_LADDER = [
    "a discount for 6-12 months, usually 20-50%",
    "a cheaper tier you were never told about",
    "a pause for 1-3 months instead of cancelling",
    "a one-off credit for the months billed at the higher price",
]

CANCEL_TIPS = [
    "Say the word cancel. Discount offers sit behind it, and front-line staff "
    "often cannot see them until you do.",
    "Phone or chat, not email. A written request is easy to not action; a queue "
    "with a retention target is not.",
    "Get it confirmed in writing and keep it. A cancellation that was never "
    "processed looks exactly like one that was, until the next charge.",
    "Check the renewal date first. Cancelling the day after a renewal usually "
    "means paying for a month you will not use.",
    "If they offer a discount and you still want out, take neither on the call. "
    "Ask them to email the offer, and decide when nobody is selling to you.",
]


def cancel_script(name: str, amount, months: int | None = None) -> str:
    """What to say to get out, and what they will say back.

    Written so the offers are expected rather than persuasive. A retention
    discount is a good outcome if you wanted the thing anyway and a trap if you
    did not, and the difference is entirely whether you decided beforehand.
    """
    tenure = f" Paying for about {months} months." if months and months >= 3 else ""
    ladder = "".join(f"  {i}. {step}\n" for i, step in enumerate(RETENTION_LADDER, 1))
    return (
        f"Cancelling {name} ({_m(amount)} a charge).{tenure}\n\n"
        f"Open with:\n"
        f'  "I would like to cancel my subscription, please."\n\n'
        f"Then stop talking. They will offer, in roughly this order:\n"
        f"{ladder}"
        f"\nDecide before the call which of those you would actually take. If the answer is "
        f"none of them:\n"
        f'  "I appreciate that, but I would still like to cancel today. Can you confirm the '
        f'cancellation and the date my access ends?"\n\n'
        f"Before hanging up, get:\n"
        f"  - the cancellation confirmed in writing\n"
        f"  - the date of the final charge\n"
        f"  - a reference number\n"
    )


def cancel_email(name: str, amount, since: date | None = None) -> str:
    """For the ones with no phone line. Short on purpose -- a long email invites
    a reply asking for detail, which restarts the clock."""
    held = f" I have held this subscription since {since:%B %Y}." if since else ""
    return (
        f"Subject: Cancellation request - {name}\n\n"
        f"Hello,\n\n"
        f"Please cancel my subscription, effective at the end of the current billing "
        f"period.{held}\n\n"
        f"Please confirm by reply:\n"
        f"  - that the cancellation has been processed\n"
        f"  - the date of the final charge\n"
        f"  - a reference number for this request\n\n"
        f"I am not looking for an alternative plan or a retention offer.\n\n"
        f"Thank you.\n"
    )


def cancel_card_script(name: str, fee) -> str:
    """Closing a card is not the only way out of its fee, and rarely the best
    one: it shortens your credit history and removes its limit from your total,
    which moves utilisation the wrong way overnight. A product change keeps both."""
    return (
        f"Getting rid of the {_m(fee)} annual fee on {name}.\n\n"
        f"Ask for a product change before you ask to close:\n"
        f'  "I am being charged {_m(fee)} a year and I am not getting that much value from it. '
        f'Can you move me to a no-fee card in the same family, keeping the account open?"\n\n'
        f"Why that order:\n"
        f"  - a product change keeps the account age and the credit limit, so neither your "
        f"history nor your utilisation changes\n"
        f"  - closing it removes that limit from your total, which raises utilisation on "
        f"everything else the same day\n\n"
        f"If they will not move you:\n"
        f'  "Is there a retention offer on this account?" -- a fee waiver or a points credit '
        f"for the year is common.\n\n"
        f"Only if both fail is closing worth considering, and not in the months before "
        f"applying for anything.\n"
    )


def lower_email(name: str, monthly, since: date | None = None, increased_from=None) -> str:
    """The written version of the negotiation script, for providers that only do
    chat or a contact form."""
    tenure = f" I have been a customer since {since:%B %Y}." if since else ""
    rise = (f" My bill has gone from {_m(increased_from)} to {_m(monthly)}."
            if increased_from else "")
    return (
        f"Subject: Reviewing my plan - {name}\n\n"
        f"Hello,\n\n"
        f"I am paying {_m(monthly)} a month.{tenure}{rise}\n\n"
        f"I am reviewing what I spend and comparing options. Before I move, could you tell me:\n"
        f"  - whether there is a promotional or retention rate available on this account\n"
        f"  - whether a cheaper plan would cover what I actually use\n"
        f"  - the total for the next 12 months, including any fees\n\n"
        f"Thank you.\n"
    )


def cancellation_help(conn, today: date | None = None) -> dict:
    """Every recurring charge, with a way out of each one.

    The negotiable ones also get the script for lowering. Everything gets a
    cancellation route, because "is this still worth it" is a question about the
    whole list rather than only about the expensive parts of it.
    """
    today = today or date.today()
    rows = conn.execute(
        """SELECT date, amount, display_name, merchant_entity_id, logo_url, account_id,
                  account_name, category, category_label, kind
           FROM v_txn WHERE NOT pending AND kind = 'expense' AND date >= current_date - 500"""
    ).fetchall()
    streams = [s for s in analytics.detect_recurring(rows) if s.active and s.kind == "expense"]

    out = []
    for s in sorted(streams, key=lambda x: x.monthly_cost, reverse=True):
        annual = s.monthly_cost * 12
        if annual < MIN_MONTHLY:
            continue
        months = max(1, (today - s.first_date).days // 30)
        negotiable = s.category in NEGOTIABLE
        cancellable = s.category in CANCELLABLE
        out.append({
            "name": s.name, "logo_url": s.logo_url, "category": s.category,
            "category_label": s.category_label, "account_name": s.account_name,
            "amount": s.typical_amount, "cadence": s.cadence,
            "monthly": s.monthly_cost, "annual": annual,
            "paid_so_far": s.typical_amount * s.count, "charges": s.count,
            "since": s.first_date, "next_date": s.next_date, "months": months,
            "increased_from": s.previous_amount if s.price_changed_on else None,
            "negotiable": negotiable,
            "cancellable": cancellable,
            "cancel_script": (cancel_script(s.name, s.typical_amount, months)
                              if cancellable else None),
            "cancel_email": (cancel_email(s.name, s.typical_amount, s.first_date)
                             if cancellable else None),
            "lower_email": (lower_email(s.name, s.monthly_cost, s.first_date,
                                        s.previous_amount if s.price_changed_on else None)
                            if negotiable else None),
            # Said plainly rather than leaving a row with no buttons and no
            # explanation for why it is different from the one above it.
            "note": (None if cancellable or negotiable
                     else "Not something Tally can help you get out of -- it is here so the "
                          "total is the real one."),
        })
    return {
        "subscriptions": out,
        "monthly_total": sum((Decimal(x["monthly"]) for x in out), ZERO),
        "annual_total": sum((Decimal(x["annual"]) for x in out), ZERO),
        "paid_so_far_total": sum((Decimal(x["paid_so_far"]) for x in out), ZERO),
        "tips": CANCEL_TIPS,
        "ladder": RETENTION_LADDER,
    }
