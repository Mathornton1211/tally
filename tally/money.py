"""Home currency and the rates everything converts at.

Rates are entered by the household, not fetched. Tally does not phone out, and
a self-hosted finance app that silently depended on a third-party rate endpoint
would trade away the one property it is built on.

A rate is dated and applies from that date forward, so history stays honest: a
rate typed in today does not retroactively change what last year's holiday cost.
"""
from datetime import date
from decimal import ROUND_HALF_UP, Decimal

# The ones Plaid actually reports, plus the majors. Not a closed list -- any
# three-letter code can be added -- just what the picker offers first.
COMMON = [
    ("USD", "US dollar", "$"), ("EUR", "Euro", "€"), ("GBP", "Pound sterling", "£"),
    ("CAD", "Canadian dollar", "$"), ("AUD", "Australian dollar", "$"),
    ("JPY", "Japanese yen", "¥"), ("CHF", "Swiss franc", "Fr"), ("SEK", "Swedish krona", "kr"),
    ("NOK", "Norwegian krone", "kr"), ("DKK", "Danish krone", "kr"), ("NZD", "New Zealand dollar", "$"),
    ("MXN", "Mexican peso", "$"), ("INR", "Indian rupee", "₹"), ("SGD", "Singapore dollar", "$"),
    ("HKD", "Hong Kong dollar", "$"), ("PLN", "Polish złoty", "zł"), ("BRL", "Brazilian real", "R$"),
    ("ZAR", "South African rand", "R"),
]
SYMBOLS = {code: symbol for code, _, symbol in COMMON}


def home(conn) -> str:
    row = conn.execute("SELECT value FROM settings WHERE key = 'home_currency'").fetchone()
    return row["value"] if row else "USD"


def set_home(conn, currency: str) -> str:
    currency = currency.strip().upper()
    conn.execute(
        """INSERT INTO settings (key, value) VALUES ('home_currency', %s)
           ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value""", (currency,))
    return currency


def in_use(conn) -> list[str]:
    """Currencies that actually appear in the data, so the settings page can ask
    for exactly the rates that are missing rather than all of them."""
    rows = conn.execute(
        """SELECT DISTINCT currency FROM (
               SELECT COALESCE(iso_currency, tally_home_currency()) AS currency FROM v_acct
               UNION
               SELECT COALESCE(iso_currency, tally_home_currency()) FROM transactions
           ) x WHERE currency IS NOT NULL ORDER BY 1""").fetchall()
    return [r["currency"] for r in rows]


def rates(conn) -> list[dict]:
    return conn.execute(
        """SELECT DISTINCT ON (currency) currency, as_of, rate, source
           FROM fx_rates ORDER BY currency, as_of DESC""").fetchall()


def set_rate(conn, currency: str, rate: Decimal, as_of: date | None = None, source: str = "manual"):
    conn.execute(
        """INSERT INTO fx_rates (currency, as_of, rate, source) VALUES (%s,%s,%s,%s)
           ON CONFLICT (currency, as_of) DO UPDATE SET rate = EXCLUDED.rate, source = EXCLUDED.source""",
        (currency.strip().upper(), as_of or date.today(), rate, source))


def status(conn) -> dict:
    """What the settings page needs: the home currency, what is in use, and
    which of those have no rate — because those are silently counting as 1:1,
    which is the failure mode worth naming out loud."""
    h = home(conn)
    used = in_use(conn)
    have = {r["currency"] for r in rates(conn)}
    missing = [c for c in used if c != h and c not in have]
    return {
        "home": h, "symbol": SYMBOLS.get(h, ""), "in_use": used,
        "rates": rates(conn), "missing": missing,
        "common": [{"code": c, "name": n, "symbol": s} for c, n, s in COMMON],
        "multi": len([c for c in used if c != h]) > 0,
    }


def convert(amount: Decimal, rate: Decimal) -> Decimal:
    return (Decimal(amount) * Decimal(rate)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
