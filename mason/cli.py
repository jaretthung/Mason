"""`mason` command-line entry point."""

from __future__ import annotations

import argparse
import sys

from .config import load_config


def cmd_ping(args) -> int:
    from .llm import LLM

    llm = LLM.from_config()
    for i in range(2):
        r = llm.call("ping", "Reply with exactly the word: pong", max_tokens=2000, label="ping")
        tag = "cached, $0.00" if r.cached else f"${r.cost_usd:.5f}"
        print(f"call {i + 1}: {r.text.strip()!r} · {r.model} · in={r.usage.input_tokens} "
              f"out={r.usage.output_tokens} · {tag}")
    print(llm.ledger.summary())
    return 0


def cmd_spend(args) -> int:
    from .llm import Ledger

    cfg = load_config()
    ledger = Ledger(cfg.per_run_usd, cfg.per_month_usd, cfg.state_dir / "spend.json")
    print(f"This month: ${ledger.month_spend():.2f} of ${cfg.per_month_usd:.2f}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="mason", description="Mason, the AI student.")
    sub = p.add_subparsers(dest="command", required=True)
    sub.add_parser("ping", help="Make one live Claude call (then repeat it from cache) to check setup and costs")
    sub.add_parser("spend", help="Show API spend this month")
    return p


COMMANDS = {"ping": cmd_ping, "spend": cmd_spend}


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return COMMANDS[args.command](args)


if __name__ == "__main__":
    sys.exit(main())
