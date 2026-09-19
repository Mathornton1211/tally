"""Push notifications through the lab's own ntfy. Nothing leaves the network.

An alert nobody sees is worth nothing, which is the whole reason this exists:
a payment past due or a balance that will not cover tomorrow's bill has to
reach a phone, not wait for someone to open a dashboard.

ntfy here has no authentication, so the topic name is the only secret. It is
generated per install and kept in the stack's .env, never printed.
"""
import logging
import os
import re

import httpx

log = logging.getLogger("tally.notify")

# Severity -> ntfy priority. 'high' buzzes through Do Not Disturb on most
# phones; everything else stays quiet.
PRIORITY = {"high": 4, "medium": 3, "low": 2}
TAGS = {
    "payment_overdue": "rotating_light", "payment_shortfall": "warning", "runway_short": "hourglass_flowing_sand",
    "card_testing": "credit_card", "duplicate_charge": "heavy_dollar_sign", "amount_outlier": "chart_with_upwards_trend",
    "utilization_high": "chart", "reversible_fee": "moneybag", "price_increase": "arrow_upper_right",
    "foreign_activity": "airplane", "new_merchant_large": "shopping_cart", "velocity": "zap",
    "brief": "calendar", "test": "wave",
}


class Notifier:
    def __init__(self, url: str | None = None, topic: str | None = None, base_link: str | None = None, pool=None):
        self.url = (url or os.environ.get("NTFY_URL") or "").rstrip("/")
        self.topic = topic or os.environ.get("NTFY_TOPIC") or ""
        self.base_link = (base_link or os.environ.get("TALLY_BASE_URL") or "").rstrip("/")
        self.pool = pool
        self._http = httpx.Client(timeout=10)

    @property
    def enabled(self) -> bool:
        return bool(self.url and self.topic)

    def status(self) -> dict:
        if not self.enabled:
            return {"enabled": False, "reason": "NTFY_URL or NTFY_TOPIC not set"}
        try:
            r = self._http.get(f"{self.url}/v1/health", timeout=5)
            # The topic is shown in full: the UI behind Authentik is exactly
            # where it belongs, and the owner needs it to subscribe on his phone.
            return {"enabled": True, "reachable": r.status_code == 200,
                    "topic": self.topic, "url": self.url,
                    "subscribe_url": f"{self.url}/{self.topic}"}
        except Exception as e:
            return {"enabled": True, "reachable": False, "error": str(e), "url": self.url}

    def send(self, title: str, body: str, *, kind: str = "alert", priority: int = 3,
             tag: str | None = None, path: str | None = None, alert_id: int | None = None) -> bool:
        if not self.enabled:
            return False
        headers = {
            # ntfy reads these as UTF-8 only when they are plain ASCII; strip the
            # rest rather than send mojibake to a phone.
            "Title": _ascii(title),
            "Priority": str(priority),
            "Tags": tag or "money_with_wings",
        }
        if self.base_link and path:
            headers["Click"] = f"{self.base_link}{path}"
        ok, err = True, None
        try:
            r = self._http.post(f"{self.url}/{self.topic}", data=_ascii(body).encode(), headers=headers)
            r.raise_for_status()
        except Exception as e:
            ok, err = False, str(e)
            log.warning("ntfy send failed: %s", e)
        self._log(kind, title, body, priority, alert_id, ok, err)
        return ok

    def _log(self, kind, title, body, priority, alert_id, ok, err):
        if not self.pool:
            return
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """INSERT INTO notifications (kind, title, body, priority, alert_id, ok, error)
                       VALUES (%s,%s,%s,%s,%s,%s,%s)""",
                    (kind, title, body, priority, alert_id, ok, err))
        except Exception:
            log.exception("could not log notification")


def _ascii(s: str) -> str:
    return re.sub(r"[^\x20-\x7e\n]", "", s or "")


MAX_PER_PASS = 6


def send_new_alerts(pool, notifier: Notifier, min_severity: str = "medium") -> dict:
    """Send alerts that have not been sent before. Never repeats one.

    Quiet by design: at most a handful per pass, and the least urgent are held
    for the weekly brief rather than buzzing a phone at 3am.
    """
    if not notifier.enabled:
        return {"skipped": "notifications not configured"}
    order = {"low": 0, "medium": 1, "high": 2}
    floor = order.get(min_severity, 1)
    with pool.connection() as conn:
        rows = conn.execute(
            """SELECT id, rule, severity, title, detail FROM alerts
               WHERE status = 'open' AND notified_at IS NULL
               ORDER BY CASE severity WHEN 'high' THEN 0 WHEN 'medium' THEN 1 ELSE 2 END, occurred_on DESC
               LIMIT 40""").fetchall()
    sent = held = 0
    for r in rows:
        if order.get(r["severity"], 0) < floor or sent >= MAX_PER_PASS:
            held += 1
            continue
        ok = notifier.send(r["title"], r["detail"], kind="alert", priority=PRIORITY.get(r["severity"], 3),
                           tag=TAGS.get(r["rule"]), path="/alerts", alert_id=r["id"])
        if ok:
            sent += 1
            with pool.connection() as conn:
                conn.execute("UPDATE alerts SET notified_at = now() WHERE id = %s", (r["id"],))
    return {"sent": sent, "held": held}
