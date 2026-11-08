"""Approach B (RESEARCH.md §3, recommended): notebook + cite-every-step + independent checker.

1. Notebook = verbatim passages from attended lessons only (built from the gated CourseView).
2. Solver: one fresh, stateless call per question. Every step cites notebook entries (L3.07), prerequisites
   (P2) or earlier steps (S1). It may answer "I don't know" and say what the notes are missing.
3. Deterministic pre-check: citations to ids Mason doesn't have are struck without asking any model.
4. Checker: a separate call that sees each step next to ONLY the text it cites (never the answer key) and
   strikes unsupported steps. Any struck step, or an answer that doesn't follow, blocks the answer.
"""

from __future__ import annotations

import re
import threading

from ..course_io import LoadedCourse, Question
from ..grading import is_abstention
from ..llm import LLM
from ..notebook import Entry, build_entries, render_entries
from .base import Attempt
from .render import render_question
from .view import CourseView

SOLVER_SYSTEM = """You are Mason, a {grade}th-grade student taking a {subject} test. Everything you know about
this subject is in your NOTEBOOK (passages copied from the lessons you attended) and the PRIOR KNOWLEDGE list.
You have no other knowledge of the subject.

How to answer:
- Work in short numbered steps. Each step makes ONE claim and cites where it comes from:
  notebook entry ids (e.g. "L3.07"), prior-knowledge ids (e.g. "P2"), or earlier steps (e.g. "S1").
- A claim citing notebook/prior knowledge must be directly stated by the cited text (a paraphrase is fine).
- A claim citing earlier steps must follow from them by simple reasoning or arithmetic.
- Do not use anything that is not in the cited text, even if you are sure it is true. If the notebook says
  something different from what you believe, the notebook is right.
- Only include steps you need for the answer. For multiple choice, support your choice; you do not need to
  rule out every other option.
- If the notebook and prior knowledge do not contain what you need, set answer to exactly "I don't know" and
  use "missing" to say what information the notes would need to contain.

PRIOR KNOWLEDGE:
{prereqs}

NOTEBOOK (lessons attended so far):
{notebook}"""

SOLVER_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"claim": {"type": "string"}, "cites": {"type": "array", "items": {"type": "string"}}},
                "required": ["claim", "cites"],
                "additionalProperties": False,
            },
        },
        "answer": {"type": "string"},
        "missing": {"type": "string"},
    },
    "required": ["steps", "answer", "missing"],
    "additionalProperties": False,
}

CHECKER_SYSTEM = """You audit a student's reasoning. The student may use ONLY the cited text. You do not know the
correct answer and must not judge whether the answer is true in the real world — only whether each step is
supported by the text it cites.

For each step:
- "supported": the cited text states the claim (paraphrase is fine), or, for steps citing earlier steps, the claim
  follows from those steps by simple logic or arithmetic.
- "unsupported": the claim adds any fact, definition, mechanism, number or explanation that is not in the cited
  text — even if it is true — or cites text that does not say it.
Then decide whether the final answer follows from the supported steps alone (for multiple choice: whether the
supported steps pick out that option)."""

CHECKER_SCHEMA = {
    "type": "object",
    "properties": {
        "steps": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "verdict": {"type": "string", "enum": ["supported", "unsupported"]},
                    "reason": {"type": "string"},
                },
                "required": ["index", "verdict", "reason"],
                "additionalProperties": False,
            },
        },
        "answer_follows": {"type": "boolean"},
        "reason": {"type": "string"},
    },
    "required": ["steps", "answer_follows", "reason"],
    "additionalProperties": False,
}

_STEP_REF = re.compile(r"^S(\d+)$", re.IGNORECASE)


class NotebookStudent:
    name = "mason-notebook"

    def __init__(self, llm: LLM, lc: LoadedCourse | None = None):
        self.llm = llm
        self._entries: dict[str, list[Entry]] = {}
        self._lock = threading.Lock()

    # -- materials -------------------------------------------------------------------

    def entries(self, view: CourseView) -> list[Entry]:
        with self._lock:
            if view.key() not in self._entries:
                self._entries[view.key()] = build_entries(view)  # built from the gated view only
            return self._entries[view.key()]

    @staticmethod
    def prereq_ids(view: CourseView) -> dict[str, str]:
        return {f"P{i}": p for i, p in enumerate(view.prerequisites, start=1)}

    def system_prompt(self, view: CourseView) -> str:
        pre = "\n".join(f"[{k}] {v}" for k, v in self.prereq_ids(view).items())
        nb = render_entries(self.entries(view)) or "(empty — no lessons attended yet)"
        return SOLVER_SYSTEM.format(grade=view.grade, subject=view.subject, prereqs=pre, notebook=nb)

    # -- answering -------------------------------------------------------------------

    def answer(self, view: CourseView, q: Question) -> Attempt:
        sol = self.llm.call("solver", render_question(q), system=self.system_prompt(view), schema=SOLVER_SCHEMA,
                            max_tokens=8000, cache_prefix=True, label=f"solve:{q.id}:{view.key()}")
        cost = sol.cost_usd
        steps = [{"claim": s["claim"], "cites": list(s["cites"])} for s in sol.data["steps"]]
        answer = sol.data["answer"].strip()
        missing = sol.data.get("missing", "").strip()

        if is_abstention(answer):
            return Attempt(q.id, "I don't know", "abstained", steps, cost, notes=missing)

        # Deterministic pre-check: every citation must be something Mason actually has.
        sources = {e.id: e.text for e in self.entries(view)} | self.prereq_ids(view)
        for i, s in enumerate(steps, start=1):
            bad = [c for c in s["cites"] if c not in sources and not _valid_step_ref(c, i)]
            if not s["cites"]:
                s.update(verdict="unsupported", reason="no citation")
            elif bad:
                s.update(verdict="unsupported", reason=f"cites material Mason does not have: {', '.join(bad)}")
        if not steps:
            return Attempt(q.id, None, "blocked", steps, cost, notes="answer given with no supporting steps")

        chk = self.llm.call("checker", self._checker_prompt(q, steps, answer, sources), system=CHECKER_SYSTEM,
                            schema=CHECKER_SCHEMA, max_tokens=6000, label=f"check:{q.id}:{view.key()}")
        cost += chk.cost_usd
        verdicts = {v["index"]: v for v in chk.data["steps"]}
        for i, s in enumerate(steps, start=1):
            if s.get("verdict") == "unsupported":
                continue  # already struck deterministically
            v = verdicts.get(i)
            s["verdict"] = v["verdict"] if v else "unsupported"
            s["reason"] = v["reason"] if v else "not assessed by checker"

        struck = [i for i, s in enumerate(steps, start=1) if s["verdict"] == "unsupported"]
        if struck or not chk.data["answer_follows"]:
            why = (f"struck step(s) {', '.join(f'S{i}' for i in struck)}" if struck else "") + \
                  ("" if chk.data["answer_follows"] else f"; answer does not follow: {chk.data['reason']}")
            return Attempt(q.id, None, "blocked", steps, cost, notes=why.strip("; ") + (
                f" | would-be answer: {answer}"))
        return Attempt(q.id, answer, "answered", steps, cost, notes=missing)

    @staticmethod
    def _checker_prompt(q: Question, steps: list[dict], answer: str, sources: dict[str, str]) -> str:
        lines = [render_question(q).rsplit("\n\n", 1)[0], "", "STUDENT'S STEPS (each with the text it cites):"]
        for i, s in enumerate(steps, start=1):
            lines.append(f"\nS{i}. {s['claim']}")
            for c in s["cites"]:
                if c in sources:
                    lines.append(f"    cited [{c}]: {sources[c]}")
                elif _valid_step_ref(c, i):
                    lines.append(f"    cited [{c.upper()}] (earlier step)")
                else:
                    lines.append(f"    cited [{c}]: (NOT AVAILABLE — this citation does not exist)")
        lines += ["", f"FINAL ANSWER: {answer}", "",
                  f"Judge steps S1..S{len(steps)} (use index 1..{len(steps)}) and whether the answer follows."]
        return "\n".join(lines)


def _valid_step_ref(c: str, i: int) -> bool:
    m = _STEP_REF.match(c.strip())
    return bool(m) and 1 <= int(m.group(1)) < i
