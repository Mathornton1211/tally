"""The only door to a model. Local ollama on the home server, nothing else (invariant 2).

Every call is logged to ai_calls with its duration, so "the AI is slow" is a
query, not a feeling. The lab runs one model at a time with a short keep-alive,
so the first call after a quiet spell pays ~30s to load; callers must expect it.
"""
import json
import logging
import os
import re
import time
from collections.abc import Iterator

import httpx

log = logging.getLogger("tally.llm")

DEFAULT_MODEL = "huihui_ai/qwen3-abliterated:30b-a3b"


class LLMUnavailable(Exception):
    pass


class LLM:
    def __init__(self, url: str | None = None, model: str | None = None, pool=None, timeout: float = 240):
        self.url = (url or os.environ.get("OLLAMA_URL") or "http://hl-ollama:11434").rstrip("/")
        self.model = model or os.environ.get("AI_MODEL") or DEFAULT_MODEL
        # Refuse anything that is not a private address or a container name.
        # A typo'd OLLAMA_URL pointing at a hosted API would ship bank data out.
        host = httpx.URL(self.url).host
        if not re.match(r"^(localhost|127\.|10\.|192\.168\.|172\.(1[6-9]|2\d|3[01])\.|hl-[\w-]+$|[\w-]+$)", host):
            raise ValueError(f"OLLAMA_URL host {host!r} is not local; refusing (HANDOFF invariant 2)")
        self.pool = pool
        self._http = httpx.Client(timeout=httpx.Timeout(timeout, connect=5))

    # ---------------------------------------------------------------- health

    def status(self) -> dict:
        try:
            tags = self._http.get(f"{self.url}/api/tags", timeout=5).json()
            loaded = self._http.get(f"{self.url}/api/ps", timeout=5).json()
        except Exception as e:
            return {"reachable": False, "error": str(e), "model": self.model}
        names = [m["name"] for m in tags.get("models", [])]
        return {"reachable": True, "model": self.model, "installed": self.model in names,
                "loaded": any(m["name"] == self.model for m in loaded.get("models", []))}

    # ---------------------------------------------------------------- calls

    def _log(self, task: str, started: float, ok: bool, resp: dict | None = None, error: str | None = None):
        if not self.pool:
            return
        try:
            with self.pool.connection() as conn:
                conn.execute(
                    """INSERT INTO ai_calls (task, model, ms, load_ms, prompt_tokens, eval_tokens, ok, error)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (task, self.model, int((time.monotonic() - started) * 1000),
                     int((resp or {}).get("load_duration", 0) / 1e6) or None,
                     (resp or {}).get("prompt_eval_count"), (resp or {}).get("eval_count"), ok, error))
        except Exception:  # logging must never take down the feature
            log.exception("could not log ai call")

    # num_ctx must match what every other client of hl-ollama uses (the 4096
    # default). A different value forces a full model reload, ~30s, on every
    # switch between Tally and the lab's other agents.
    def _body(self, messages: list[dict], schema: dict | None, temperature: float, stream: bool, num_ctx: int) -> dict:
        body = {"model": self.model, "messages": messages, "stream": stream, "think": False,
                "options": {"temperature": temperature, "num_ctx": num_ctx}}
        if schema:
            body["format"] = schema
        return body

    def json(self, task: str, messages: list[dict], schema: dict, temperature: float = 0,
             num_ctx: int = 4096) -> dict:
        started = time.monotonic()
        try:
            r = self._http.post(f"{self.url}/api/chat", json=self._body(messages, schema, temperature, False, num_ctx))
            r.raise_for_status()
            resp = r.json()
            out = json.loads(resp["message"]["content"])
        except (httpx.HTTPError, KeyError, json.JSONDecodeError) as e:
            self._log(task, started, False, error=repr(e))
            raise LLMUnavailable(str(e)) from e
        self._log(task, started, True, resp)
        return out

    def stream(self, task: str, messages: list[dict], temperature: float = 0.2, num_ctx: int = 4096) -> Iterator[str]:
        started = time.monotonic()
        last: dict = {}
        try:
            with self._http.stream("POST", f"{self.url}/api/chat",
                                   json=self._body(messages, None, temperature, True, num_ctx)) as r:
                r.raise_for_status()
                for line in r.iter_lines():
                    if not line:
                        continue
                    chunk = json.loads(line)
                    if chunk.get("done"):
                        last = chunk
                        break
                    piece = chunk.get("message", {}).get("content", "")
                    if piece:
                        yield piece
        except (httpx.HTTPError, json.JSONDecodeError) as e:
            self._log(task, started, False, error=repr(e))
            raise LLMUnavailable(str(e)) from e
        self._log(task, started, True, last)


# ---------------------------------------------------------------- number guard

_MONEY = re.compile(r"-?\$\s?-?[\d,]+(?:\.\d+)?")
_PCT = re.compile(r"-?[\d,]+(?:\.\d+)?\s?%")


def _numbers_in(value, out: set[str]):
    if isinstance(value, dict):
        for v in value.values():
            _numbers_in(v, out)
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers_in(v, out)
    else:
        try:
            n = float(str(value).replace(",", "").replace("$", "").replace("%", ""))
        except ValueError:
            return
        for x in (n, abs(n)):
            out.add(f"{x:.2f}")
            out.add(f"{round(x):.2f}")
            out.add(f"{x * 100:.2f}")          # 0.17 shown as 17%
            out.add(f"{round(x * 100):.2f}")
            out.add(f"{round(x * 100, 1):.2f}")
            out.add(f"{round(x, 1):.2f}")


def unverified_figures(text: str, *sources) -> list[str]:
    """Dollar and percent figures in model text that trace back to no source value.

    HANDOFF invariant 3: the model phrases numbers, it never produces them. An
    empty list means every figure it wrote exists in the data it was given
    (allowing for its own rounding). Anything returned is shown to the owner as
    unverified rather than silently trusted.
    """
    allowed: set[str] = set()
    for s in sources:
        _numbers_in(s, allowed)
    bad = []
    for m in _MONEY.findall(text) + _PCT.findall(text):
        raw = m.replace("$", "").replace(",", "").replace("%", "").replace(" ", "")
        try:
            v = abs(float(raw))
        except ValueError:
            continue
        candidates = {f"{v:.2f}", f"{round(v):.2f}"}
        if not candidates & allowed:
            bad.append(m.strip())
    return bad
