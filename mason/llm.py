"""The single gateway for every Claude call Mason makes.

Responsibilities:
- pick model + effort for a *role* (from mason.toml),
- answer identical requests from a disk cache (reproducible runs, $0 re-runs),
- account tokens and USD cost,
- enforce hard budget caps (per run and per calendar month) *before* a call is made,
- return parsed JSON when a schema is given (structured outputs).

Tests use `FakeBackend` so nothing here needs the network.
"""

from __future__ import annotations

import datetime as _dt
import hashlib
import json
import os
import threading
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable, Protocol

from .config import Config, Price, load_config

DEFAULT_MAX_TOKENS = 16000


class LLMError(RuntimeError):
    """The model returned something unusable (refusal, truncation, invalid JSON)."""


class BudgetExceeded(RuntimeError):
    """A hard spending cap would be crossed."""


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def cost(self, price: Price) -> float:
        return (
            self.input_tokens * price.input
            + self.output_tokens * price.output
            + self.cache_read_tokens * price.cache_read
            + self.cache_write_tokens * price.cache_write
        ) / 1_000_000


@dataclass
class RawResponse:
    """What a backend returns: the final text plus usage."""

    text: str
    model: str
    usage: Usage
    stop_reason: str = "end_turn"


@dataclass
class LLMResponse:
    text: str
    data: Any  # parsed JSON when a schema was given, else None
    model: str
    usage: Usage
    cost_usd: float
    cached: bool
    role: str = ""
    label: str = ""


class Backend(Protocol):
    def create(self, request: dict) -> RawResponse: ...


# --------------------------------------------------------------------------- backends


class AnthropicBackend:
    """Calls the real Claude API via the official SDK."""

    def __init__(self, client=None):
        import anthropic  # imported lazily so offline tests never need credentials

        self._anthropic = anthropic
        # Use MASON_ANTHROPIC_BASE_URL (not the generic ANTHROPIC_BASE_URL, which a host tool such as
        # Claude Code may set for itself) so Mason's spend always goes to the founder's own API account.
        base_url = os.environ.get("MASON_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
        self.client = client or anthropic.Anthropic(base_url=base_url)

    def create(self, request: dict) -> RawResponse:
        params = dict(request)
        # Long requests: stream to avoid HTTP timeouts, then take the final message.
        with self.client.messages.stream(**params) as stream:
            msg = stream.get_final_message()
        if msg.stop_reason == "refusal":
            raise LLMError(f"Model refused: {getattr(msg, 'stop_details', None)}")
        if msg.stop_reason == "max_tokens":
            raise LLMError("Response truncated at max_tokens; raise max_tokens for this call")
        text = "".join(b.text for b in msg.content if b.type == "text")
        u = msg.usage
        usage = Usage(
            input_tokens=u.input_tokens or 0,
            output_tokens=u.output_tokens or 0,
            cache_read_tokens=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write_tokens=getattr(u, "cache_creation_input_tokens", 0) or 0,
        )
        return RawResponse(text=text, model=msg.model, usage=usage, stop_reason=msg.stop_reason)


class FakeBackend:
    """Offline backend for tests. `responder(request) -> str` produces the model's text.

    Usage is estimated from character counts so cost/budget logic is exercised too.
    """

    def __init__(self, responder: Callable[[dict], str]):
        self.responder = responder
        self.calls: list[dict] = []

    def create(self, request: dict) -> RawResponse:
        self.calls.append(request)
        text = self.responder(request)
        in_chars = len(json.dumps(request.get("system", ""))) + len(json.dumps(request["messages"]))
        return RawResponse(
            text=text,
            model=request["model"],
            usage=Usage(input_tokens=max(1, in_chars // 4), output_tokens=max(1, len(text) // 4)),
        )


# --------------------------------------------------------------------------- ledger


class Ledger:
    """Tracks spend for the current run and for the calendar month (persisted)."""

    def __init__(self, per_run_usd: float, per_month_usd: float, state_file: Path | None):
        self.per_run_usd = per_run_usd
        self.per_month_usd = per_month_usd
        self.state_file = state_file
        self.run_spend = 0.0
        self.calls = 0
        self.cached_calls = 0
        self._lock = threading.Lock()

    @staticmethod
    def _month() -> str:
        return _dt.date.today().strftime("%Y-%m")

    def _load(self) -> dict:
        if self.state_file and self.state_file.exists():
            return json.loads(self.state_file.read_text())
        return {}

    def month_spend(self) -> float:
        return float(self._load().get(self._month(), 0.0))

    def check(self) -> None:
        """Refuse to start a call once a cap is reached. One call can overshoot by at most its own cost."""
        if self.run_spend >= self.per_run_usd:
            raise BudgetExceeded(
                f"Run budget reached: ${self.run_spend:.2f} of ${self.per_run_usd:.2f} (mason.toml [budget])"
            )
        if self.month_spend() >= self.per_month_usd:
            raise BudgetExceeded(
                f"Monthly budget reached: ${self.month_spend():.2f} of ${self.per_month_usd:.2f} (mason.toml [budget])"
            )

    def record(self, cost: float, cached: bool) -> None:
        with self._lock:
            self.calls += 1
            if cached:
                self.cached_calls += 1
                return
            self.run_spend += cost
            if self.state_file:
                data = self._load()
                data[self._month()] = round(float(data.get(self._month(), 0.0)) + cost, 6)
                self.state_file.parent.mkdir(parents=True, exist_ok=True)
                self.state_file.write_text(json.dumps(data, indent=2, sort_keys=True))

    def summary(self) -> str:
        return (
            f"{self.calls} calls ({self.cached_calls} cached) · run cost ${self.run_spend:.4f} · "
            f"month ${self.month_spend():.2f} of ${self.per_month_usd:.2f}"
        )


# --------------------------------------------------------------------------- gateway


@dataclass
class LLM:
    config: Config
    backend: Backend
    ledger: Ledger
    use_cache: bool = True
    log: list[LLMResponse] = field(default_factory=list)

    @classmethod
    def from_config(cls, config: Config | None = None, backend: Backend | None = None, **kw) -> "LLM":
        config = config or load_config()
        ledger = Ledger(config.per_run_usd, config.per_month_usd, config.state_dir / "spend.json")
        return cls(config=config, backend=backend or AnthropicBackend(), ledger=ledger, **kw)

    @classmethod
    def fake(cls, responder: Callable[[dict], str], config: Config | None = None, tmp_dir: Path | None = None,
             per_run_usd: float | None = None) -> "LLM":
        """Offline LLM for tests. No disk cache; spend tracked in memory (or under tmp_dir)."""
        config = config or load_config()
        state = (tmp_dir / "spend.json") if tmp_dir else None
        ledger = Ledger(per_run_usd if per_run_usd is not None else config.per_run_usd, config.per_month_usd, state)
        return cls(config=config, backend=FakeBackend(responder), ledger=ledger, use_cache=False)

    # -- public API -----------------------------------------------------------------

    def call(
        self,
        role: str,
        prompt: str | list[dict],
        *,
        system: str | list[dict] | None = None,
        schema: dict | None = None,
        max_tokens: int = DEFAULT_MAX_TOKENS,
        cache_prefix: bool = False,
        label: str = "",
    ) -> LLMResponse:
        """One stateless request. `prompt` is user text or a list of content blocks (text/image)."""
        request = self.build_request(role, prompt, system=system, schema=schema,
                                     max_tokens=max_tokens, cache_prefix=cache_prefix)
        return self.send(role, request, schema=schema, label=label)

    def build_request(self, role: str, prompt: str | list[dict], *, system: str | list[dict] | None = None,
                      schema: dict | None = None, max_tokens: int = DEFAULT_MAX_TOKENS,
                      cache_prefix: bool = False) -> dict:
        r = self.config.role(role)
        content = prompt if isinstance(prompt, list) else [{"type": "text", "text": prompt}]
        request: dict[str, Any] = {
            "model": r.model,
            "max_tokens": max_tokens,
            "messages": [{"role": "user", "content": content}],
            "output_config": {"effort": r.effort},
        }
        if system:
            if cache_prefix:
                # Cache the (large, stable) system prompt — e.g. the course notes — across many questions.
                blocks = [{"type": "text", "text": system}] if isinstance(system, str) else [dict(b) for b in system]
                blocks[-1] = {**blocks[-1], "cache_control": {"type": "ephemeral"}}
                request["system"] = blocks
            else:
                request["system"] = system
        if schema is not None:
            request["output_config"]["format"] = {"type": "json_schema", "schema": schema}
        return request

    def send(self, role: str, request: dict, *, schema: dict | None = None, label: str = "") -> LLMResponse:
        key = request_key(request)
        if self.use_cache:
            hit = self._cache_get(key)
            if hit is not None:
                resp = LLMResponse(text=hit["text"], data=_parse(hit["text"], schema), model=hit["model"],
                                   usage=Usage(**hit["usage"]), cost_usd=0.0, cached=True, role=role, label=label)
                self.ledger.record(0.0, cached=True)
                self.log.append(resp)
                return resp

        self.ledger.check()
        raw = self.backend.create(request)
        if raw.stop_reason == "refusal":
            raise LLMError("Model refused the request")
        data = _parse(raw.text, schema)
        cost = raw.usage.cost(self.config.price(request["model"]))
        self.ledger.record(cost, cached=False)
        if self.use_cache:
            self._cache_put(key, {"text": raw.text, "model": raw.model, "usage": asdict(raw.usage)})
        resp = LLMResponse(text=raw.text, data=data, model=raw.model, usage=raw.usage, cost_usd=cost,
                           cached=False, role=role, label=label)
        self.log.append(resp)
        return resp

    # -- cache ----------------------------------------------------------------------

    def _cache_path(self, key: str) -> Path:
        return self.config.cache_dir / key[:2] / f"{key}.json"

    def _cache_get(self, key: str) -> dict | None:
        p = self._cache_path(key)
        return json.loads(p.read_text()) if p.exists() else None

    def _cache_put(self, key: str, value: dict) -> None:
        p = self._cache_path(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(value))


def request_key(request: dict) -> str:
    return hashlib.sha256(json.dumps(request, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def _parse(text: str, schema: dict | None) -> Any:
    if schema is None:
        return None
    try:
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise LLMError(f"Expected JSON matching schema, got: {text[:200]!r}") from e
