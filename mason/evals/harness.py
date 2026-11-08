"""The evaluation harness: does the student's success depend on the course material?

Tests (PLAN.md §4):
  T1 leakage   — questions not yet taught (or never taught) at a probe point; should be failed/abstained.
  T2 learning  — taught questions whose material is sufficient, after the whole course; should be correct.
  T3 ablation  — remove one lesson; its questions should drop toward the leak floor.
(T4-T6 arrive in M7.)
"""

from __future__ import annotations

import datetime as _dt
import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable

from ..course_io import LoadedCourse, Question
from ..grading import GradeResult, grade
from ..llm import LLM
from ..student.base import Attempt, Student
from ..student.view import CourseView, make_view
from .metrics import ItemOutcome, accuracy, leak_rate

LEAK_BAR = 0.05
LEARN_BAR = 0.80
ABLATION_GAP_BAR = 0.60

Grader = Callable[[Question, str | None, str | None], GradeResult]


def llm_grader(llm: LLM) -> Grader:
    return lambda q, answer, key=None: grade(llm, q, answer, key_override=key)


def exact_key_grader(q: Question, answer: str | None, key: str | None = None) -> GradeResult:
    """Offline grader for harness self-tests: written answers must equal the answer key verbatim."""
    from ..grading import grade_mc
    if q.type == "mc":
        return grade_mc(q, answer, key=key)
    ok = answer is not None and answer.strip() == (key or q.answer).strip()
    return GradeResult(1.0 if ok else 0.0, ok, "exact-key")


@dataclass
class ItemResult:
    question_id: str
    qtype: str
    condition: str
    status: str
    answer: str | None
    correct: bool
    score: float
    rationale: str = ""
    cost_usd: float = 0.0
    steps: list = field(default_factory=list)


def n_choices(q: Question) -> int:
    return len(q.choices) if q.type == "mc" and q.choices else 0


def min_lesson_order(lc: LoadedCourse, q: Question) -> int | None:
    if not q.tags.lessons:
        return None
    return min(lc.course.lesson_order(x) for x in q.tags.lessons)


def is_untaught_at(lc: LoadedCourse, q: Question, as_of: str) -> bool:
    """A leakage probe at this point: never taught, or first taught after `as_of`."""
    if q.probe == "beyond":
        return True
    m = min_lesson_order(lc, q)
    return m is not None and m > lc.course.lesson_order(as_of)


class Harness:
    def __init__(self, lc: LoadedCourse, student: Student, grader: Grader, *, workers: int = 4,
                 loader=None, progress: Callable[[str], None] | None = None):
        self.lc = lc
        self.student = student
        self.grader = grader
        self.workers = workers
        self.loader = loader
        self.progress = progress or (lambda s: None)
        self._cache: dict[tuple[str, str], ItemResult] = {}

    # ------------------------------------------------------------------ running

    def view(self, as_of: str, exclude: tuple[str, ...] = (), overrides=None, variant: str = "") -> CourseView:
        kw = {"loader": self.loader} if self.loader else {}
        return make_view(self.lc, as_of, exclude=exclude, overrides=overrides, variant=variant, **kw)

    def run(self, view: CourseView, questions: list[Question], key_overrides: dict[str, str] | None = None
            ) -> list[ItemResult]:
        key_overrides = key_overrides or {}
        todo = [q for q in questions if (view.key(), q.id) not in self._cache]

        def one(q: Question) -> ItemResult:
            att: Attempt = self.student.answer(view, q)
            g = self.grader(q, att.answer, key_overrides.get(q.id))
            return ItemResult(q.id, q.type, view.key(), att.status, att.answer, g.correct, g.score,
                              g.rationale, att.cost_usd, att.steps)

        if todo:
            self.progress(f"{view.key()}: {len(todo)} questions")
            with ThreadPoolExecutor(max_workers=self.workers) as ex:
                for r in ex.map(one, todo):
                    self._cache[(view.key(), r.question_id)] = r
        return [self._cache[(view.key(), q.id)] for q in questions]

    @staticmethod
    def outcomes(results: list[ItemResult], qs: dict[str, Question]) -> list[ItemOutcome]:
        return [ItemOutcome(r.question_id, r.qtype, n_choices(qs[r.question_id]), r.correct) for r in results]

    # ------------------------------------------------------------------ tests

    def t1_leakage(self, probe_points: list[str] | None = None) -> dict:
        lc = self.lc
        if probe_points is None:
            lessons = lc.course.lessons
            probe_points = [lessons[len(lessons) // 2 - 1].id, lessons[-1].id]
        qs = {q.id: q for q in lc.exam.questions}
        per_point, all_results = {}, []
        for k in probe_points:
            probes = [q for q in lc.exam.questions if is_untaught_at(lc, q, k)]
            res = self.run(self.view(k), probes)
            all_results += res
            per_point[k] = leak_rate(self.outcomes(res, qs))
        overall = leak_rate(self.outcomes(all_results, qs))
        leaked = [r.question_id + "@" + r.condition for r in all_results if r.correct]
        return {"test": "T1", "metric": "leak", "value": overall["leak"], "bar": f"<= {LEAK_BAR:.0%}",
                "passed": overall["leak"] <= LEAK_BAR, "detail": overall, "per_probe_point": per_point,
                "leaked_items": leaked,
                "abstain_rate": sum(r.status != "answered" for r in all_results) / max(1, len(all_results))}

    def t2_learning(self) -> dict:
        lc = self.lc
        last = lc.course.lessons[-1].id
        qs = {q.id: q for q in lc.exam.questions}
        covered = [q for q in lc.exam.questions if q.tags.lessons and q.sufficient]
        res = self.run(self.view(last), covered)
        acc = accuracy(self.outcomes(res, qs))
        missed = [{"question": r.question_id, "status": r.status, "answer": r.answer, "why": r.rationale}
                  for r in res if not r.correct]
        return {"test": "T2", "metric": "learning", "value": acc["accuracy"], "bar": f">= {LEARN_BAR:.0%}",
                "passed": acc["accuracy"] >= LEARN_BAR, "detail": acc, "missed": missed}

    def t3_ablation(self, lessons: list[str] | None = None) -> dict:
        lc = self.lc
        last = lc.course.lessons[-1].id
        lessons = lessons or [lsn.id for lsn in lc.course.lessons]
        qs = {q.id: q for q in lc.exam.questions}
        per_lesson = {}
        for lid in lessons:
            dep = [q for q in lc.exam.questions if lid in q.tags.lessons and q.sufficient]
            if not dep:
                continue
            with_l = accuracy(self.outcomes(self.run(self.view(last), dep), qs))["accuracy"]
            without = self.run(self.view(last, exclude=(lid,)), dep)
            without_acc = accuracy(self.outcomes(without, qs))["accuracy"]
            per_lesson[lid] = {"n": len(dep), "with": with_l, "without": without_acc, "gap": with_l - without_acc,
                               "still_correct_without": [r.question_id for r in without if r.correct]}
        gaps = [v["gap"] for v in per_lesson.values()]
        mean_gap = sum(gaps) / len(gaps) if gaps else 0.0
        return {"test": "T3", "metric": "dependence_gap", "value": mean_gap, "bar": f">= {ABLATION_GAP_BAR:.0%}",
                "passed": mean_gap >= ABLATION_GAP_BAR, "per_lesson": per_lesson}


def evaluate(lc: LoadedCourse, student: Student, grader: Grader, *, tests=("T1", "T2", "T3"),
             ablate: list[str] | None = None, workers: int = 4, progress=None, loader=None) -> dict:
    h = Harness(lc, student, grader, workers=workers, progress=progress, loader=loader)
    results = []
    if "T2" in tests:
        results.append(h.t2_learning())
    if "T1" in tests:
        results.append(h.t1_leakage())
    if "T3" in tests:
        results.append(h.t3_ablation(ablate))
    core = [r for r in results if r["test"] in ("T1", "T2")]
    return {
        "course": lc.course.title,
        "student": getattr(student, "name", type(student).__name__),
        "timestamp": _dt.datetime.now().isoformat(timespec="seconds"),
        "pass_bar": {"leak": LEAK_BAR, "learning": LEARN_BAR},
        "passed": bool(core) and all(r["passed"] for r in core),
        "results": results,
        "items": [asdict(r) for r in h._cache.values()],
    }


def save_report(report: dict, out_dir: str | Path = "evals/out") -> Path:
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = report["timestamp"].replace(":", "").replace("-", "")
    p = out / f"{stamp}-{report['student']}.json"
    p.write_text(json.dumps(report, indent=2, default=str))
    return p


def summarize(report: dict) -> str:
    lines = [f"Course: {report['course']}  ·  Student: {report['student']}"]
    for r in report["results"]:
        mark = "PASS" if r["passed"] else "FAIL"
        lines.append(f"  {r['test']} {r['metric']:<15} {r['value']:6.1%}  (bar {r['bar']})  {mark}")
        if r["test"] == "T1":
            d = r["detail"]
            lines.append(f"       n={d['n']} (mc {d['n_mc']}, written {d['n_written']}), raw correct "
                         f"{d['raw_correct']}, 95% CI of raw [{d['raw_ci95'][0]:.0%}, {d['raw_ci95'][1]:.0%}], "
                         f"abstained {r['abstain_rate']:.0%}")
        if r["test"] == "T2":
            lines.append(f"       {r['detail']['correct']}/{r['detail']['n']} correct; missed: "
                         + ", ".join(m["question"] for m in r["missed"][:12]))
        if r["test"] == "T3":
            for lid, v in r["per_lesson"].items():
                lines.append(f"       remove {lid}: {v['with']:.0%} -> {v['without']:.0%} (gap {v['gap']:+.0%})")
    lines.append(f"OVERALL (T1 leak AND T2 learning): {'PASS' if report['passed'] else 'FAIL'}")
    return "\n".join(lines)
