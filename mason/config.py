"""Load mason.toml. Defaults live in the repo's mason.toml; a path can be overridden with MASON_CONFIG."""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Price:
    input: float
    output: float
    cache_read: float
    cache_write: float


@dataclass(frozen=True)
class Role:
    model: str
    effort: str


@dataclass
class Config:
    per_run_usd: float
    per_month_usd: float
    cache_dir: Path
    roles: dict[str, Role]
    prices: dict[str, Price]
    state_dir: Path = field(default_factory=lambda: REPO_ROOT / ".mason")

    def role(self, name: str) -> Role:
        if name not in self.roles:
            raise KeyError(f"Unknown LLM role {name!r}; add [roles.{name}] to mason.toml")
        return self.roles[name]

    def price(self, model: str) -> Price:
        if model not in self.prices:
            raise KeyError(f"No price for model {model!r}; add [prices.\"{model}\"] to mason.toml")
        return self.prices[model]


def load_config(path: str | os.PathLike | None = None) -> Config:
    path = Path(path or os.environ.get("MASON_CONFIG") or REPO_ROOT / "mason.toml")
    raw = tomllib.loads(path.read_text())
    base = path.resolve().parent
    cache_dir = Path(raw.get("cache", {}).get("dir", ".mason/cache"))
    if not cache_dir.is_absolute():
        cache_dir = base / cache_dir
    return Config(
        per_run_usd=float(raw["budget"]["per_run_usd"]),
        per_month_usd=float(raw["budget"]["per_month_usd"]),
        cache_dir=cache_dir,
        roles={k: Role(**v) for k, v in raw["roles"].items()},
        prices={k: Price(**v) for k, v in raw["prices"].items()},
        state_dir=base / ".mason",
    )
