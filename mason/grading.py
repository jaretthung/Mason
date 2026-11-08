"""Grading: exact match for multiple choice, rubric-based AI grading for written answers.

The AI grader judges ONLY against the answer key and rubric — never against what it believes is true —
so counterfactual courses (PLAN.md T5) are graded by the course's own facts.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from .course_io import Question
from .llm import LLM

ABSTAIN_PATTERNS = re.compile(
    r"^\s*(i\s+(do\s*n[o']?t|cannot|can't)\s+know|i\s+don't\s+know|not\s+in\s+(my\s+)?notes|"
    r"unknown|no\s+answer|cannot\s+answer|i\s+can(not|'t)\s+answer)\b",
    re.IGNORECASE,
)


@dataclass
class GradeResult:
    score: float  # 0..1
    correct: bool
    grader: str  # exact | ai | none
    rationale: str = ""
    criteria: list[dict] = field(default_factory=list)
    choice: str | None = None  # mc: the letter we read from the answer


def is_abstention(answer: str | None) -> bool:
    return answer is None or not answer.strip() or bool(ABSTAIN_PATTERNS.match(answer))


# --------------------------------------------------------------------------- multiple choice


def extract_choice(answer: str, choices: dict[str, str]) -> str | None:
    """Read which option a free-text answer picked. Returns None if absent or ambiguous."""
    letters = list(choices)
    a = answer.strip()
    if not a:
        return None
    upper = a.upper()
    # hedged answers ("A or B", "B/C", "A and D") pick no single option
    if re.search(r"\b[A-Z]\s*(?:OR|AND|/|,|&)\s*\(?[A-Z]\)?(?:\b|$)", upper):
        lone = re.findall(r"(?<![A-Z])([A-Z])(?![A-Z])", upper)
        if len({x for x in lone if x in letters}) > 1:
            return None
    # "B", "b", "(B)", "B)", "B.", "B: text", "B - text"
    m = re.match(r"^\(?([A-Z])\)?(?:[\.\):\-\s]|$)", upper)
    if m and m.group(1) in letters:
        return m.group(1)
    # "Answer: B", "The answer is (c)", "final answer: D"
    m = re.search(r"\b(?:ANSWER|CHOICE|OPTION)\s*(?:IS|:)?\s*\(?([A-Z])\)?\b", upper)
    if m and m.group(1) in letters:
        return m.group(1)
    # the text of exactly one choice
    norm = _norm(a)
    hits = [k for k, v in choices.items() if _norm(v) == norm]
    if len(hits) == 1:
        return hits[0]
    contained = [k for k, v in choices.items() if _norm(v) and _norm(v) in norm]
    if len(contained) == 1:
        return contained[0]
    return None


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", s.lower()).strip()


def grade_mc(q: Question, answer: str | None, key: str | None = None) -> GradeResult:
    key = key or q.answer
    if is_abstention(answer):
        return GradeResult(0.0, False, "exact", "abstained")
    choice = extract_choice(answer, q.choices or {})
    ok = choice == key
    return GradeResult(1.0 if ok else 0.0, ok, "exact",
                       f"read choice {choice!r}, key {key!r}" if choice else "no single choice found",
                       choice=choice)


# --------------------------------------------------------------------------- rubric (AI)

GRADER_SYSTEM = """You grade high school students' written answers against a teacher's answer key and rubric.

Rules:
- Judge ONLY against the answer key and rubric provided. If they disagree with what you believe is true,
  the key and rubric win — this course may define things its own way.
- A criterion is met if the answer clearly states the idea, in any wording. Do not require exact words.
- A criterion is NOT met if the idea is missing, wrong, contradicted elsewhere in the answer, or only hinted at.
- Ignore spelling and grammar. Do not reward extra information that the rubric does not ask for, and do not
  penalize correct extra information unless it contradicts a criterion.
- If the student says they don't know, no criterion is met."""

GRADER_SCHEMA = {
    "type": "object",
    "properties": {
        "criteria": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "index": {"type": "integer"},
                    "met": {"type": "boolean"},
                    "reason": {"type": "string"},
                },
                "required": ["index", "met", "reason"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["criteria"],
    "additionalProperties": False,
}


def grader_prompt(q: Question, answer: str, rubric: list[str], key_answer: str) -> str:
    crit = "\n".join(f"{i}. {c}" for i, c in enumerate(rubric, start=1))
    return (
        f"QUESTION:\n{q.stem}\n\nANSWER KEY:\n{key_answer}\n\nRUBRIC (every criterion must be met for full credit):\n"
        f"{crit}\n\nSTUDENT ANSWER:\n{answer}\n\n"
        f"For each rubric criterion (index 1..{len(rubric)}), decide whether the student answer meets it."
    )


def grade_rubric(llm: LLM, q: Question, answer: str | None, *, rubric: list[str] | None = None,
                 key_answer: str | None = None, label: str = "") -> GradeResult:
    rubric = rubric or q.rubric
    key_answer = key_answer or q.answer
    if is_abstention(answer):
        return GradeResult(0.0, False, "none", "abstained",
                           [{"index": i, "met": False, "reason": "abstained"} for i in range(1, len(rubric) + 1)])
    r = llm.call("grader", grader_prompt(q, answer, rubric, key_answer), system=GRADER_SYSTEM,
                 schema=GRADER_SCHEMA, max_tokens=4000, label=label or f"grade:{q.id}")
    by_index = {c["index"]: c for c in r.data["criteria"]}
    criteria = [by_index.get(i, {"index": i, "met": False, "reason": "not assessed"})
                for i in range(1, len(rubric) + 1)]
    met = sum(1 for c in criteria if c["met"])
    score = met / len(rubric)
    return GradeResult(score, met == len(rubric), "ai",
                       "; ".join(f"{c['index']}:{'✓' if c['met'] else '✗'} {c['reason']}" for c in criteria),
                       criteria)


def grade(llm: LLM, q: Question, answer: str | None, *, key_override: str | None = None) -> GradeResult:
    """Grade one answer. key_override: counterfactual key (mc letter, or the new key fact for written answers)."""
    if q.type == "mc":
        return grade_mc(q, answer, key=key_override)
    if key_override:
        return grade_rubric(llm, q, answer, rubric=[f"States that {key_override}"], key_answer=key_override)
    return grade_rubric(llm, q, answer)
