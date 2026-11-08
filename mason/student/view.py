"""What a student is allowed to see: the CourseView.

Leakage control starts here. A view holds ONLY the lessons attended so far (lessons 1..k, minus any
lessons removed for an ablation), with optional text overrides for planted defects/counterfactuals.
Students receive a view, never the course folder.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ..course_io import Counterfactual, Defect, Lesson, LoadedCourse


@dataclass(frozen=True)
class LessonMaterial:
    lesson_id: str
    order: int
    title: str
    slide_only: bool
    files: tuple[tuple[str, str, str], ...]  # (path, kind, text)


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


def text_loader(lc: LoadedCourse, lesson: Lesson, overrides: dict[str, str]) -> list[tuple[str, str, str]]:
    """Default loader: read text files directly (md/txt/vtt). Replaced by ingestion for pdf/pptx/docx (M4)."""
    out = []
    for f in lesson.files:
        text = overrides.get(f.path)
        if text is None:
            text = (lc.root / f.path).read_text()
        out.append((f.path, f.kind, text))
    return out


def make_view(lc: LoadedCourse, as_of: str, *, exclude: tuple[str, ...] = (), overrides: dict[str, str] | None = None,
              variant: str = "", loader=text_loader) -> CourseView:
    k = lc.course.lesson_order(as_of)
    overrides = overrides or {}
    lessons = []
    for i, lesson in enumerate(lc.course.lessons, start=1):
        if i > k or lesson.id in exclude:  # <-- the gate
            continue
        lessons.append(LessonMaterial(lesson.id, i, lesson.title, lesson.slide_only,
                                      tuple(loader(lc, lesson, overrides))))
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
