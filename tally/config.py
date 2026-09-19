"""Everything read from the environment, in one place, validated at startup.

A missing required value raises with its name rather than failing later with a
Plaid 400 or a psycopg connection error that points somewhere else.
"""
import os
from dataclasses import dataclass

PLAID_HOSTS = {
    "sandbox": "https://sandbox.plaid.com",
    "production": "https://production.plaid.com",
}


def _need(name: str) -> str:
    value = os.environ.get(name, "").strip()
    if not value:
        raise RuntimeError(f"{name} is not set")
    return value


@dataclass(frozen=True)
class Settings:
    database_url: str
    plaid_env: str
    plaid_client_id: str
    plaid_secret: str
    fernet_key: str
    redirect_uri: str | None
    timezone: str
    demo: bool
    auth_mode: str
    auth_password: str | None
    sync_interval_seconds: int
    ai_enabled: bool
    brief_weekday: int
    brief_hour: int

    @property
    def plaid_host(self) -> str:
        return PLAID_HOSTS[self.plaid_env]


def load() -> Settings:
    env = os.environ.get("PLAID_ENV", "sandbox").strip()
    if env not in PLAID_HOSTS:
        raise RuntimeError(f"PLAID_ENV must be one of {sorted(PLAID_HOSTS)}, got {env!r}")
    # One secret per environment, selected by PLAID_ENV, so flipping the env
    # can never send a sandbox secret to production or the reverse.
    secret = _need(f"PLAID_SECRET_{env.upper()}")
    auth_mode = os.environ.get("TALLY_AUTH", "proxy").strip()
    if auth_mode not in ("proxy", "password"):
        raise RuntimeError(f"TALLY_AUTH must be 'proxy' or 'password', got {auth_mode!r}")
    return Settings(
        database_url=_need("TALLY_DATABASE_URL"),
        plaid_env=env,
        plaid_client_id=_need("PLAID_CLIENT_ID"),
        plaid_secret=secret,
        fernet_key=_need("TALLY_FERNET_KEY"),
        # Only OAuth institutions need it. Unset is fine for sandbox and for
        # non-OAuth banks; Plaid rejects a link token whose URI is not on the
        # dashboard allowlist, so an empty value is safer than a wrong one.
        redirect_uri=os.environ.get("PLAID_REDIRECT_URI", "").strip() or None,
        # proxy: something in front (Authentik) has already authenticated the
        # request. password: Tally asks for one itself. Default is proxy so the
        # homelab deploy is unchanged; the standalone compose sets password.
        # One definition of "today", for Python and for Postgres.
        timezone=os.environ.get("TALLY_TIMEZONE", "").strip() or os.environ.get("TZ", "").strip() or "UTC",
        # A public demo has to be readable by strangers and unchangeable by
        # them. Anything that writes is refused, and the Plaid credentials are
        # never real in this mode.
        demo=os.environ.get("TALLY_DEMO", "") == "1",
        auth_mode=auth_mode,
        auth_password=os.environ.get("TALLY_PASSWORD", "").strip() or None,
        sync_interval_seconds=int(os.environ.get("SYNC_INTERVAL_SECONDS", "21600")),
        # Model URL and name are read by tally.llm (OLLAMA_URL, AI_MODEL).
        ai_enabled=os.environ.get("AI_ENABLED", "1") != "0",
        # Push settings (NTFY_URL, NTFY_TOPIC, TALLY_BASE_URL) are read by
        # tally.notify. 0 = Monday, local time on the host.
        brief_weekday=int(os.environ.get("BRIEF_WEEKDAY", "0")),
        brief_hour=int(os.environ.get("BRIEF_HOUR", "8")),
    )
