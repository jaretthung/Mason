"""Render a CourseView as plain text for prompts."""

from __future__ import annotations

from ..course_io import Question
from .view import CourseView


def render_materials(view: CourseView) -> str:
    if not view.lessons:
        return "(No lessons attended yet.)"
    parts = []
    for m in view.lessons:
        parts.append(f"===== LESSON {m.order}: {m.title} =====")
        for path, kind, text in m.files:
            parts.append(f"--- {kind}: {path} ---\n{text.strip()}")
    return "\n\n".join(parts)


def render_prereqs(view: CourseView) -> str:
    return "\n".join(f"- {p}" for p in view.prerequisites)


def render_question(q: Question) -> str:
    s = f"QUESTION {q.id}:\n{q.stem}"
    if q.type == "mc" and q.choices:
        s += "\n" + "\n".join(f"{k}. {v}" for k, v in q.choices.items())
        s += "\n\nAnswer with the letter of one choice, or exactly \"I don't know\"."
    else:
        s += "\n\nAnswer in 1-4 sentences, or exactly \"I don't know\"."
    return s
