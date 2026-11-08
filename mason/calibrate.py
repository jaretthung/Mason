"""Check the AI grader against human-labelled answers (PLAN.md M2 / M15)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

from .course_io import load_course
from .grading import grade
from .llm import LLM

AGREEMENT_BAR = 0.85


@dataclass
class CalibrationResult:
    n: int
    agree: int
    disagreements: list[dict]

    @property
    def agreement(self) -> float:
        return self.agree / self.n if self.n else 0.0

    @property
    def passed(self) -> bool:
        return self.agreement >= AGREEMENT_BAR


def run_calibration(llm: LLM, course_dir: str | Path,
                    labels_file: str = "calibration/grader_labels.yaml") -> CalibrationResult:
    lc = load_course(course_dir)
    items = yaml.safe_load((Path(course_dir) / labels_file).read_text())["items"]
    agree, disagreements = 0, []
    for it in items:
        q = lc.question(it["question"])
        g = grade(llm, q, it["answer"])
        if g.correct == it["correct"]:
            agree += 1
        else:
            disagreements.append({"question": q.id, "answer": it["answer"], "human": it["correct"],
                                  "ai": g.correct, "rationale": g.rationale})
    return CalibrationResult(len(items), agree, disagreements)
