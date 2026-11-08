"""Approach A (RESEARCH.md §3): strict 'answer only from the notes' prompting. Kept as the harness baseline."""

from __future__ import annotations

from ..course_io import Question
from ..grading import is_abstention
from ..llm import LLM
from .base import Attempt
from .render import render_materials, render_prereqs, render_question
from .view import CourseView

SYSTEM_TEMPLATE = """You are playing the role of a {grade}th-grade student taking a {subject} test. You know ONLY:
(1) the prior knowledge listed below, and (2) the course notes below, from the lessons you have attended.

Rules:
- Answer only with information stated in the notes or the prior knowledge. Do not use anything else you know,
  even if you are sure it is true.
- If the notes and prior knowledge do not contain what you need, answer exactly: I don't know
- If the notes say something different from what you believe, the notes are right for this test.
- Do not guess.

Examples of following the notes:
- Notes say "The Krell organ filters blood." Question: "What does the Krell organ do?" -> "It filters blood."
- Notes say "Water boils at 90 °C in this course's examples." Question: "At what temperature does water boil?" -> "90 °C"
- Notes never mention lymph nodes. Question: "What do lymph nodes do?" -> "I don't know"

PRIOR KNOWLEDGE:
{prereqs}

COURSE NOTES (lessons attended so far):
{materials}"""

SCHEMA = {
    "type": "object",
    "properties": {
        "evidence": {"type": "string", "description": "Quote from the notes that supports the answer, or empty"},
        "answer": {"type": "string"},
    },
    "required": ["evidence", "answer"],
    "additionalProperties": False,
}


class BaselineStudent:
    name = "baseline-strict-prompt"

    def __init__(self, llm: LLM):
        self.llm = llm

    def system_prompt(self, view: CourseView) -> str:
        return SYSTEM_TEMPLATE.format(grade=view.grade, subject=view.subject, prereqs=render_prereqs(view),
                                      materials=render_materials(view))

    def answer(self, view: CourseView, q: Question) -> Attempt:
        prompt = ("According to your notes, answer this question.\n\n" + render_question(q))
        r = self.llm.call("baseline", prompt, system=self.system_prompt(view), schema=SCHEMA, max_tokens=8000,
                          cache_prefix=True, label=f"baseline:{q.id}:{view.key()}")
        ans = r.data["answer"].strip()
        status = "abstained" if is_abstention(ans) else "answered"
        return Attempt(q.id, ans, status, steps=[{"evidence": r.data["evidence"]}], cost_usd=r.cost_usd)
