"""What a student is allowed to see: the CourseView.

Leakage control starts here. A view holds ONLY the lessons attended so far (lessons 1..k, minus any
lessons removed for an ablation), with optional text overrides for planted defects/counterfactuals.
Students receive a view, never the course folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..course_io import Counterfactual, Defect, Lesson, LoadedCourse
from ..ingest import SourceDoc, ingest_file


@dataclass(frozen=True)
class LessonMaterial:
    lesson_id: str
    order: int
    title: str
    slide_only: bool
    files: tuple[tuple[str, str, str], ...]  # (path, kind, text) — readable files only
    unreadable: tuple[tuple[str, str], ...] = ()  # (path, reason) — "not seen by Mason"


@dataclass
class CourseView:
    title: str
    grade: int
    subject: str
    prerequisites: list[str]
    lessons: list[LessonMaterial]  # attended lessons only, in order
    as_of: str
    excluded: tuple[str, ...] = ()
    variant: str = ""  # id of the defect/counterfactual applied, if any
    meta: dict = field(default_factory=dict)

    @property
    def attended_ids(self) -> list[str]:
        return [m.lesson_id for m in self.lessons]

    def key(self) -> str:
        """Identifies the condition (for logs/results)."""
        k = f"as_of={self.as_of}"
        if self.excluded:
            k += f" minus={','.join(self.excluded)}"
        if self.variant:
            k += f" variant={self.variant}"
        return k


def ingest_loader(lc: LoadedCourse, lesson: Lesson, overrides: dict[str, str]) -> list[SourceDoc]:
    """Read every file of a lesson through the ingestion layer (md/txt/vtt/srt/pdf/docx/pptx)."""
    return [ingest_file(lc.root / f.path, f.kind, rel_path=f.path, text_override=overrides.get(f.path))
            for f in lesson.files]


def make_view(lc: LoadedCourse, as_of: str, *, exclude: tuple[str, ...] = (), overrides: dict[str, str] | None = None,
              variant: str = "", loader=ingest_loader) -> CourseView:
    k = lc.course.lesson_order(as_of)
    overrides = overrides or {}
    lessons = []
    for i, lesson in enumerate(lc.course.lessons, start=1):
        if i > k or lesson.id in exclude:  # <-- the gate
            continue
        docs = loader(lc, lesson, overrides)
        readable = tuple((d.path, d.kind, d.text) for d in docs if not d.unreadable)
        unreadable = tuple((d.path, d.error) for d in docs if d.unreadable)
        # "may be covered verbally": every file is a slide deck and none has speaker notes
        slide_only = bool(docs) and all(d.kind == "slides" and not d.has_speaker_notes for d in docs)
        lessons.append(LessonMaterial(lesson.id, i, lesson.title, slide_only, readable, unreadable))
    return CourseView(lc.course.title, lc.course.grade, lc.course.subject, list(lc.prerequisites), lessons,
                      as_of, tuple(exclude), variant)


def defect_overrides(lc: LoadedCourse, d: Defect) -> dict[str, str]:
    text = (lc.root / d.file).read_text()
    assert d.remove in text, f"defect {d.id}: sentence not found"
    return {d.file: text.replace(d.remove, "")}


def counterfactual_overrides(lc: LoadedCourse, c: Counterfactual) -> dict[str, str]:
    text = (lc.root / c.file).read_text()
    assert text.count(c.replace) == 1, f"counterfactual {c.id}: text must occur once"
    return {c.file: text.replace(c.replace, c.with_)}
