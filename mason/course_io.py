"""Course folder format: load and validate.

A course folder contains:
  course.yaml        title, grade, subject, ordered lessons (each with files), exam + prereq file names
  concepts.yaml      gold concept list (id, name, lesson) — sample/eval courses; real courses get them from tagging
  prereqs.yaml       approved prior knowledge ("what students already know")
  exam.yaml          questions with keys, rubrics and tags
  variants/defects.yaml, variants/counterfactuals.yaml   (eval courses only, PLAN.md T4/T5)
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, field_validator, model_validator

FileKind = Literal["notes", "slides", "reading", "transcript"]
QType = Literal["mc", "short", "diagram", "essay"]
Probe = Literal["beyond", "gap"]


class LessonFile(BaseModel):
    path: str
    kind: FileKind


class Lesson(BaseModel):
    id: str
    title: str
    files: list[LessonFile]

    @property
    def slide_only(self) -> bool:
        return all(f.kind == "slides" for f in self.files)


class Course(BaseModel):
    title: str
    grade: int
    subject: str
    lessons: list[Lesson]
    exam_file: str = "exam.yaml"
    prerequisites_file: str = "prereqs.yaml"
    concepts_file: str | None = "concepts.yaml"

    def lesson_order(self, lesson_id: str) -> int:
        """1-based position of a lesson."""
        for i, lesson in enumerate(self.lessons, start=1):
            if lesson.id == lesson_id:
                return i
        raise KeyError(lesson_id)


class Concept(BaseModel):
    id: str
    name: str
    lesson: str


class Tags(BaseModel):
    concepts: list[str] = Field(default_factory=list)
    lessons: list[str] = Field(default_factory=list)  # empty = never taught in this course


class Question(BaseModel):
    id: str
    type: QType
    stem: str
    choices: dict[str, str] | None = None  # letter -> text (mc only)
    answer: str
    rubric: list[str] = Field(default_factory=list)  # key points a correct answer must contain
    image: str | None = None
    tags: Tags = Field(default_factory=Tags)
    sufficient: bool | None = None  # eval courses: does the material fully explain it?
    probe: Probe | None = None  # beyond = never taught; gap = taught but insufficiently

    @model_validator(mode="after")
    def _check(self):
        if self.type == "mc":
            if not self.choices or len(self.choices) < 2:
                raise ValueError(f"{self.id}: mc question needs >= 2 choices")
            if self.answer not in self.choices:
                raise ValueError(f"{self.id}: answer {self.answer!r} not among choices {list(self.choices)}")
        if self.type in ("short", "essay") and not self.rubric:
            raise ValueError(f"{self.id}: {self.type} question needs a rubric")
        if self.type == "diagram" and not self.image:
            raise ValueError(f"{self.id}: diagram question needs an image")
        if self.probe == "beyond" and self.tags.lessons:
            raise ValueError(f"{self.id}: 'beyond' probes must not be tagged with a lesson")
        return self

    @property
    def lesson_ids(self) -> list[str]:
        return self.tags.lessons


class Exam(BaseModel):
    id: str
    title: str
    after_lesson: str
    questions: list[Question]

    @field_validator("questions")
    @classmethod
    def _unique(cls, qs):
        ids = [q.id for q in qs]
        dupes = {i for i in ids if ids.count(i) > 1}
        if dupes:
            raise ValueError(f"duplicate question ids: {sorted(dupes)}")
        return qs


class Defect(BaseModel):
    """T4: delete a key sentence from a lesson; listed questions should then fail."""

    id: str
    lesson: str
    file: str
    remove: str
    affects: list[str]


class Counterfactual(BaseModel):
    """T5: change a fact in a lesson; Mason should follow the course, not the world."""

    id: str
    lesson: str
    file: str
    replace: str
    with_: str = Field(alias="with")
    question: str
    expected: str  # mc: the new correct letter; short: the new key fact
    note: str = ""


class LoadedCourse(BaseModel):
    root: Path
    course: Course
    exam: Exam
    prerequisites: list[str]
    concepts: list[Concept] = Field(default_factory=list)
    defects: list[Defect] = Field(default_factory=list)
    counterfactuals: list[Counterfactual] = Field(default_factory=list)

    def lesson_text(self, lesson_id: str, overrides: dict[str, str] | None = None) -> dict[str, str]:
        """Raw text of each file in a lesson ({relative path: text}). Text formats only (md/txt/vtt)."""
        lesson = next(lsn for lsn in self.course.lessons if lsn.id == lesson_id)
        out = {}
        for f in lesson.files:
            if overrides and f.path in overrides:
                out[f.path] = overrides[f.path]
            else:
                out[f.path] = (self.root / f.path).read_text()
        return out

    def question(self, qid: str) -> Question:
        return next(q for q in self.exam.questions if q.id == qid)


def _yaml(path: Path):
    return yaml.safe_load(path.read_text())


def load_course(root: str | Path) -> LoadedCourse:
    root = Path(root)
    course = Course(**_yaml(root / "course.yaml"))
    exam = Exam(**_yaml(root / course.exam_file))
    prereqs = _yaml(root / course.prerequisites_file)["prerequisites"]
    concepts = []
    if course.concepts_file and (root / course.concepts_file).exists():
        concepts = [Concept(**c) for c in _yaml(root / course.concepts_file)["concepts"]]
    defects, cfs = [], []
    if (root / "variants" / "defects.yaml").exists():
        defects = [Defect(**d) for d in _yaml(root / "variants" / "defects.yaml")["defects"]]
    if (root / "variants" / "counterfactuals.yaml").exists():
        cfs = [Counterfactual(**c) for c in _yaml(root / "variants" / "counterfactuals.yaml")["counterfactuals"]]
    return LoadedCourse(root=root, course=course, exam=exam, prerequisites=prereqs, concepts=concepts,
                        defects=defects, counterfactuals=cfs)


def validate_course(root: str | Path) -> tuple[LoadedCourse, list[str]]:
    """Load a course and run cross-file consistency checks. Returns (course, problems)."""
    lc = load_course(root)
    problems: list[str] = []
    lesson_ids = [lsn.id for lsn in lc.course.lessons]
    concept_ids = {c.id for c in lc.concepts}

    if len(set(lesson_ids)) != len(lesson_ids):
        problems.append("duplicate lesson ids")
    for lsn in lc.course.lessons:
        for f in lsn.files:
            if not (lc.root / f.path).exists():
                problems.append(f"{lsn.id}: missing file {f.path}")
    if lc.exam.after_lesson not in lesson_ids:
        problems.append(f"exam.after_lesson {lc.exam.after_lesson!r} is not a lesson")
    for c in lc.concepts:
        if c.lesson not in lesson_ids:
            problems.append(f"concept {c.id}: unknown lesson {c.lesson}")
    for q in lc.exam.questions:
        for lid in q.tags.lessons:
            if lid not in lesson_ids:
                problems.append(f"{q.id}: unknown lesson tag {lid}")
        if concept_ids:
            for cid in q.tags.concepts:
                if cid not in concept_ids:
                    problems.append(f"{q.id}: unknown concept {cid}")
        if q.image and not (lc.root / q.image).exists():
            problems.append(f"{q.id}: missing image {q.image}")
    qids = {q.id for q in lc.exam.questions}
    for d in lc.defects:
        text = (lc.root / d.file).read_text() if (lc.root / d.file).exists() else ""
        if d.remove not in text:
            problems.append(f"defect {d.id}: sentence to remove not found verbatim in {d.file}")
        for qid in d.affects:
            if qid not in qids:
                problems.append(f"defect {d.id}: unknown question {qid}")
    for c in lc.counterfactuals:
        text = (lc.root / c.file).read_text() if (lc.root / c.file).exists() else ""
        if text.count(c.replace) != 1:
            problems.append(f"counterfactual {c.id}: text to replace must occur exactly once in {c.file} "
                            f"(found {text.count(c.replace)})")
        if c.question not in qids:
            problems.append(f"counterfactual {c.id}: unknown question {c.question}")
        else:
            q = lc.question(c.question)
            if q.type == "mc" and c.expected not in (q.choices or {}):
                problems.append(f"counterfactual {c.id}: expected {c.expected!r} is not a choice of {q.id}")
    return lc, problems


def course_stats(lc: LoadedCourse, probe_points: list[str] | None = None) -> dict:
    """Counts used by the M1 check. probe_points = lessons after which T1 is run (default: middle + last)."""
    qs = lc.exam.questions
    order = {lsn.id: i for i, lsn in enumerate(lc.course.lessons, start=1)}
    if probe_points is None:
        probe_points = [lc.course.lessons[len(order) // 2 - 1].id, lc.course.lessons[-1].id]
    probes = 0
    for k in probe_points:
        kk = order[k]
        for q in qs:
            if q.probe == "beyond" or (q.tags.lessons and min(order[x] for x in q.tags.lessons) > kk):
                probes += 1
    by_lesson: dict[str, int] = {}
    for q in qs:
        key = ",".join(q.tags.lessons) or "(never taught)"
        by_lesson[key] = by_lesson.get(key, 0) + 1
    by_type: dict[str, int] = {}
    for q in qs:
        by_type[q.type] = by_type.get(q.type, 0) + 1
    return {
        "lessons": len(lc.course.lessons),
        "slide_only_lessons": [lsn.id for lsn in lc.course.lessons if lsn.slide_only],
        "questions": len(qs),
        "by_type": by_type,
        "by_lesson": by_lesson,
        "covered_sufficient": sum(1 for q in qs if q.tags.lessons and q.sufficient),
        "gap_questions": sum(1 for q in qs if q.probe == "gap"),
        "beyond_probes": sum(1 for q in qs if q.probe == "beyond"),
        "probe_points": probe_points,
        "leakage_probe_instances": probes,
        "missing_gold_tags": [q.id for q in qs if q.probe != "beyond" and not q.tags.lessons],
        "missing_sufficient": [q.id for q in qs if q.sufficient is None],
        "defects": len(lc.defects),
        "counterfactuals": len(lc.counterfactuals),
        "concepts": len(lc.concepts),
    }
