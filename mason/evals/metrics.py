"""Metric math for the evaluation harness (definitions: PLAN.md §4)."""

from __future__ import annotations

import math
from dataclasses import dataclass


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """95% Wilson score interval for k successes out of n."""
    if n == 0:
        return (0.0, 1.0)
    p = k / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return (max(0.0, centre - half), min(1.0, centre + half))


@dataclass
class ItemOutcome:
    question_id: str
    qtype: str
    n_choices: int  # 0 for written questions
    correct: bool


def leak_rate(items: list[ItemOutcome]) -> dict:
    """Share of never-/not-yet-taught questions answered correctly.

    Multiple-choice is chance-corrected: max(0, (acc - c) / (1 - c)), c = mean 1/n_choices, so a student
    who guesses blindly scores ~0 leakage, and one who knows everything scores 1. Written answers count raw.
    """
    mc = [i for i in items if i.qtype == "mc"]
    wr = [i for i in items if i.qtype != "mc"]
    mc_acc = sum(i.correct for i in mc) / len(mc) if mc else 0.0
    c = (sum(1 / i.n_choices for i in mc) / len(mc)) if mc else 0.0
    mc_leak = max(0.0, (mc_acc - c) / (1 - c)) if mc else 0.0
    wr_leak = sum(i.correct for i in wr) / len(wr) if wr else 0.0
    n = len(items)
    combined = (len(mc) * mc_leak + len(wr) * wr_leak) / n if n else 0.0
    k_raw = sum(i.correct for i in items)
    lo, hi = wilson(k_raw, n)
    return {"leak": combined, "n": n, "n_mc": len(mc), "n_written": len(wr), "mc_raw_accuracy": mc_acc,
            "mc_chance": c, "mc_leak": mc_leak, "written_leak": wr_leak, "raw_correct": k_raw,
            "raw_ci95": [lo, hi]}


def accuracy(items: list[ItemOutcome]) -> dict:
    n = len(items)
    k = sum(i.correct for i in items)
    lo, hi = wilson(k, n)
    return {"accuracy": k / n if n else 0.0, "n": n, "correct": k, "ci95": [lo, hi]}
