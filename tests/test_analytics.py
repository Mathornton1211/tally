from datetime import date, timedelta
from decimal import Decimal

from tally import analytics

TODAY = date(2026, 9, 16)


def row(d, amount, name, account="card-1", kind="expense", category="entertainment"):
    return {"date": d, "amount": Decimal(str(amount)), "display_name": name, "merchant_entity_id": None,
            "logo_url": None, "account_id": account, "account_name": account, "category": category,
            "category_label": category, "kind": kind}


def monthly_rows(name, amounts, account="card-1", day=9, **kw):
    out, d = [], date(2025, 10, day)
    for a in amounts:
        out.append(row(d, a, name, account, **kw))
        d = (d.replace(day=28) + timedelta(days=4)).replace(day=day)
    return out


def by_name(streams, name, account=None):
    return [s for s in streams if s.name == name and (account is None or s.account_id == account)]


def test_monthly_subscription_detected_with_next_date():
    streams = analytics.detect_recurring(monthly_rows("Hulu", [18.99] * 11), today=TODAY)
    (s,) = streams
    assert s.cadence == "monthly" and s.active
    assert s.last_date == date(2026, 8, 9)
    assert s.next_date == date(2026, 9, 8)
    assert s.monthly_cost == Decimal("18.99")


def test_price_increase_flagged_only_when_recent():
    recent = monthly_rows("Netflix", [15.49] * 7 + [17.99] * 4)
    (s,) = analytics.detect_recurring(recent, today=TODAY)
    assert s.previous_amount == Decimal("15.49") and s.last_amount == Decimal("17.99")

    old = monthly_rows("Netflix", [15.49] * 2 + [17.99] * 9)
    (s,) = analytics.detect_recurring(old, today=TODAY)
    assert s.previous_amount is None


def test_variable_bill_is_recurring_but_not_a_price_change():
    citypower = monthly_rows("CITY POWER & GAS", [110, 121, 98, 104, 117, 132, 180, 214, 199, 176, 190], category="bills")
    (s,) = analytics.detect_recurring(citypower, today=TODAY)
    assert s.cadence == "monthly" and s.previous_amount is None


def test_weekly_groceries_with_wild_amounts_are_not_a_bill():
    d, rows = date(2026, 3, 7), []
    for amt in [42, 188, 73, 151, 29, 205, 96, 12, 170, 64]:
        rows.append(row(d, amt, "Vons", category="groceries"))
        d += timedelta(days=7)
    assert analytics.detect_recurring(rows, today=TODAY) == []


def test_same_service_on_two_cards_is_two_streams():
    rows = monthly_rows("Spotify", [11.99] * 6, account="freedom") + monthly_rows("Spotify", [11.99] * 6, account="gold")
    streams = analytics.detect_recurring(rows, today=TODAY)
    assert {s.account_id for s in streams} == {"freedom", "gold"}


def test_cancelled_subscription_goes_inactive():
    rows = monthly_rows("Paramount+", [12.99] * 4)  # last charge Jan 2026
    (s,) = analytics.detect_recurring(rows, today=TODAY)
    assert not s.active


def test_double_charge_does_not_break_cadence():
    rows = monthly_rows("Gym", [24.99] * 6)
    rows.append(row(rows[-1]["date"], 24.99, "Gym"))
    (s,) = analytics.detect_recurring(rows, today=date(2026, 4, 1))
    assert s.cadence == "monthly" and s.count == 6


def test_balance_history_walks_back_both_account_types():
    accounts = [{"id": "chk", "type": "depository", "current_balance": Decimal("1000")},
                {"id": "card", "type": "credit", "current_balance": Decimal("300")}]
    today = date.today()
    y = today - timedelta(days=1)
    flows = [
        {"account_id": "chk", "date": today, "amount": Decimal("200")},    # spent 200 today
        {"account_id": "chk", "date": y, "amount": Decimal("-500")},       # paycheck yesterday
        {"account_id": "card", "date": today, "amount": Decimal("50")},    # 50 charged today
    ]
    hist = analytics.estimate_balance_history(accounts, flows, today - timedelta(days=2), today)
    by_day = {h["date"]: h for h in hist}
    assert by_day[today]["assets"] == 1000 and by_day[today]["liabilities"] == 300
    assert by_day[y]["assets"] == 1200 and by_day[y]["liabilities"] == 250
    assert by_day[today - timedelta(days=2)]["assets"] == 700
    assert by_day[today]["net_worth"] == 700


# ---------------------------------------------------------------- habits are not bills

def _habit_rows(name, category, label, amounts, start, account="a"):
    from datetime import timedelta as _td
    return [{"date": start + _td(days=7 * i), "amount": a, "display_name": name,
             "merchant_entity_id": None, "logo_url": None, "account_id": account,
             "account_name": "Card", "category": category, "category_label": label,
             "kind": "expense"}
            for i, a in enumerate(amounts)]


def test_a_regular_coffee_is_not_a_subscription():
    """a coffee shop every Tuesday has a cadence and a stable-ish price, and is
    still not something anybody can cancel. It is also already counted in
    everyday spending, so calling it a bill charges the same money twice."""
    from datetime import date as _d
    rows = _habit_rows("a coffee shop", "dining", "Dining & drinks",
                       [Decimal("7.10"), Decimal("7.45"), Decimal("6.80"), Decimal("7.25")],
                       _d(2026, 6, 2))
    assert analytics.detect_recurring(rows, today=_d(2026, 7, 1)) == []


def test_groceries_on_the_same_day_each_week_are_not_a_bill():
    from datetime import date as _d
    rows = _habit_rows("Costco", "groceries", "Groceries",
                       [Decimal("142.18"), Decimal("118.40"), Decimal("156.02"), Decimal("131.77")],
                       _d(2026, 6, 6))
    assert analytics.detect_recurring(rows, today=_d(2026, 7, 5)) == []


def test_a_fixed_price_charge_in_a_habit_category_still_counts():
    """A meal-kit box is billed, not bought. The distinguishing facts are that
    the amount does not move and it has done so for a while."""
    from datetime import date as _d
    rows = _habit_rows("Hello Fresh", "groceries", "Groceries",
                       [Decimal("69.99")] * 8, _d(2026, 4, 1))
    streams = analytics.detect_recurring(rows, today=_d(2026, 6, 1))
    assert len(streams) == 1 and streams[0].fixed_price is True


def test_two_coincidentally_equal_receipts_are_not_a_subscription():
    """Three visits at 12.71, 12.82, 12.82 put 67% of the history on one price,
    which is a fixed price only if you believe three points."""
    from datetime import date as _d
    rows = _habit_rows("a fast food chain", "dining", "Dining & drinks",
                       [Decimal("12.71"), Decimal("12.82"), Decimal("12.82")], _d(2026, 1, 1))
    assert analytics.detect_recurring(rows, today=_d(2026, 2, 1)) == []


def test_a_utility_that_moves_every_month_is_still_a_bill():
    """Bills are allowed to vary -- the electricity does. The habit rule only
    applies where buying something twice is shopping."""
    from datetime import date as _d
    rows = _habit_rows("City Power", "bills", "Bills & utilities",
                       [Decimal("104.22"), Decimal("131.90"), Decimal("118.55"), Decimal("142.31")],
                       _d(2026, 6, 1))
    streams = analytics.detect_recurring(rows, today=_d(2026, 7, 5))
    assert len(streams) == 1 and streams[0].fixed_price is False
