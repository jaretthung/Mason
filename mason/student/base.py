"""Student interface + the two fake students used to test the evaluation harness itself."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Protocol

from ..course_io import Question
from .view import CourseView

Status = Literal["answered", "abstained", "blocked"]


@dataclass
class Attempt:
    question_id: str
    answer: str | None
    status: Status
    steps: list[dict] = field(default_factory=list)  # solver steps with citations / checker verdicts
    cost_usd: float = 0.0
    notes: str = ""


class Student(Protocol):
    name: str

    def answer(self, view: CourseView, q: Question) -> Attempt: ...


def _key_answer(q: Question) -> str:
    return q.answer  # mc: the letter; written: the model answer


class OmniscientStudent:
    """Knows everything, ignores the course. A correct harness must report ~100% leakage for it."""

    name = "fake-omniscient"

    def answer(self, view: CourseView, q: Question) -> Attempt:
        return Attempt(q.id, _key_answer(q), "answered")


class GatedOracleStudent:
    """Answers correctly exactly when the attended lessons fully teach the question; otherwise abstains.
    A correct harness must report 0% leakage and 100% learning for it."""

    name = "fake-gated-oracle"

    def answer(self, view: CourseView, q: Question) -> Attempt:
        attended = set(view.attended_ids)
        taught = bool(q.tags.lessons) and set(q.tags.lessons) <= attended and bool(q.sufficient)
        if taught:
            return Attempt(q.id, _key_answer(q), "answered")
        return Attempt(q.id, "I don't know", "abstained")
