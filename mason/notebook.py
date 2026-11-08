"""Mason's notebook: what it 'wrote down' while attending lessons.

Design (refines PLAN.md M5; see commit message):
- ENTRIES are verbatim passages of the lesson material — paragraphs, bullets, caption groups — each with an
  ID, lesson and locator. They are cut deterministically, so every entry is an exact quote by construction
  and no outside knowledge can enter the notebook. (`verify_entries` still re-checks this.)
- The CONCEPT INDEX is the only AI-written part: for each lesson, which concepts it covers, which entries
  cover them, and whether each is *explained* or only *mentioned*. Labels cannot leak facts into answers;
  the solver reasons only from entry text.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .llm import LLM
from .student.view import CourseView, LessonMaterial

MAX_WORDS = 90


@dataclass
class Entry:
    id: str  # e.g. "L3.07"
    lesson_id: str
    lesson_order: int
    source_path: str
    locator: str  # section / slide / page / timestamp
    text: str  # verbatim material


@dataclass
class IndexedConcept:
    name: str
    lesson_id: str
    entry_ids: list[str]
    depth: str  # explained | mentioned_only
    note: str = ""


@dataclass
class Notebook:
    entries: list[Entry] = field(default_factory=list)
    concepts: list[IndexedConcept] = field(default_factory=list)

    def by_id(self) -> dict[str, Entry]:
        return {e.id: e for e in self.entries}

    def for_lessons(self, lesson_ids) -> "Notebook":
        keep = set(lesson_ids)
        return Notebook([e for e in self.entries if e.lesson_id in keep],
                        [c for c in self.concepts if c.lesson_id in keep])

    def to_json(self) -> str:
        return json.dumps({"entries": [asdict(e) for e in self.entries],
                           "concepts": [asdict(c) for c in self.concepts]}, indent=1)

    @classmethod
    def from_json(cls, s: str) -> "Notebook":
        d = json.loads(s)
        return cls([Entry(**e) for e in d["entries"]], [IndexedConcept(**c) for c in d["concepts"]])


# --------------------------------------------------------------------------- cutting entries

_LOCATOR_LINE = re.compile(r"^\[(?P<loc>[^\]]+)\]$")
_HEADING = re.compile(r"^#{1,6}\s+(?P<t>.+)$")
_BULLET = re.compile(r"^\s*(?:[-*•]|\d+[\.\)])\s+")


def _split_long(text: str) -> list[str]:
    words = text.split()
    if len(words) <= MAX_WORDS:
        return [text]
    sentences = re.split(r"(?<=[.!?])\s+(?=[A-Z(])", text)
    chunks, cur = [], ""
    for s in sentences:
        if cur and len((cur + " " + s).split()) > MAX_WORDS:
            chunks.append(cur)
            cur = s
        else:
            cur = (cur + " " + s).strip()
    if cur:
        chunks.append(cur)
    return chunks


def cut_passages(text: str) -> list[tuple[str, str]]:
    """Split rendered file text into (locator, passage) units. Passages are verbatim substrings of `text`."""
    out: list[tuple[str, str]] = []
    locator = ""
    for block in re.split(r"\n\s*\n", text):
        lines = [ln for ln in block.split("\n") if ln.strip()]
        if not lines:
            continue
        m = _LOCATOR_LINE.match(lines[0].strip())
        if m:
            locator = m.group("loc")
            lines = lines[1:]
        h = _HEADING.match(lines[0]) if lines else None
        if h:
            locator = h.group("t").strip()
            lines = lines[1:]
        if not lines:
            continue
        if all(_BULLET.match(ln) for ln in lines) or (len(lines) > 1 and sum(bool(_BULLET.match(ln)) for ln in lines) >= len(lines) - 1):
            # a list: one entry per bullet (a non-bullet lead-in line becomes its own entry)
            for ln in lines:
                out.append((locator, ln.strip()))
        else:
            for chunk in _split_long(" ".join(ln.strip() for ln in lines)):
                out.append((locator, chunk))
    return out


def build_entries(view: CourseView) -> list[Entry]:
    entries: list[Entry] = []
    for m in view.lessons:
        n = 0
        for path, kind, text in m.files:
            if kind == "transcript":
                passages = _group_captions(text)
            else:
                passages = cut_passages(text)
            for loc, passage in passages:
                n += 1
                entries.append(Entry(f"{m.lesson_id}.{n:02d}", m.lesson_id, m.order, path, loc, passage))
    return entries


def _group_captions(text: str, per_entry: int = 2) -> list[tuple[str, str]]:
    """Captions arrive as [timestamp]\\ncue blocks; group consecutive cues so entries read as sentences."""
    cues = cut_passages(text)
    out = []
    for i in range(0, len(cues), per_entry):
        group = cues[i:i + per_entry]
        out.append((group[0][0], "\n".join(c[1] for c in group)))
    return out


def verify_entries(entries: list[Entry], view: CourseView) -> list[str]:
    """Every entry's words must appear, in order, in its source file text (whitespace-normalized)."""
    norm = lambda s: re.sub(r"\s+", " ", s).strip()  # noqa: E731
    sources = {(m.lesson_id, p): norm(t) for m in view.lessons for p, _, t in m.files}
    problems = []
    for e in entries:
        src = sources.get((e.lesson_id, e.source_path))
        if src is None:
            problems.append(f"{e.id}: source {e.source_path} not in lesson {e.lesson_id}")
            continue
        parts = [norm(x) for x in e.text.split("\n")]
        if not all(p in src for p in parts):
            problems.append(f"{e.id}: text not found verbatim in {e.source_path}")
    return problems


# --------------------------------------------------------------------------- concept index (AI)

INDEX_SYSTEM = """You are indexing a student's notes from one lesson. You will see numbered passages copied from
the lesson. List the concepts this lesson covers and which passages cover each one.

Rules:
- Use ONLY what the passages say. Never add facts, definitions or explanations of your own.
- depth = "explained" if the passages explain the concept well enough that a student could answer questions
  about it from the passages alone; "mentioned_only" if a term is named or listed but not explained
  (for example a bullet that only names a model or a term).
- In "note", for mentioned_only concepts, say briefly what is missing (e.g. "named on a slide, never defined").
- Concept names should be short (2-8 words), in the lesson's own terms."""

INDEX_SCHEMA = {
    "type": "object",
    "properties": {
        "concepts": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "name": {"type": "string"},
                    "entry_ids": {"type": "array", "items": {"type": "string"}},
                    "depth": {"type": "string", "enum": ["explained", "mentioned_only"]},
                    "note": {"type": "string"},
                },
                "required": ["name", "entry_ids", "depth", "note"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["concepts"],
    "additionalProperties": False,
}


def render_entries(entries: list[Entry]) -> str:
    return "\n".join(f"[{e.id}] ({e.locator}) {e.text}" if e.locator else f"[{e.id}] {e.text}" for e in entries)


def index_lesson(llm: LLM, lesson: LessonMaterial, entries: list[Entry]) -> list[IndexedConcept]:
    if not entries:
        return []
    prompt = (f"LESSON {lesson.order}: {lesson.title}\n"
              f"{'(This lesson is a slide deck with no speaker notes.)' if lesson.slide_only else ''}\n\n"
              f"PASSAGES:\n{render_entries(entries)}")
    r = llm.call("notebook", prompt, system=INDEX_SYSTEM, schema=INDEX_SCHEMA, max_tokens=16000,
                 label=f"index:{lesson.lesson_id}")
    valid = {e.id for e in entries}
    out = []
    for c in r.data["concepts"]:
        ids = [i for i in c["entry_ids"] if i in valid]  # drop hallucinated ids
        if ids:
            out.append(IndexedConcept(c["name"], lesson.lesson_id, ids, c["depth"], c.get("note", "")))
    return out


def build_notebook(view: CourseView, llm: LLM | None = None) -> Notebook:
    """Entries for every attended lesson; concept index too if an LLM is given."""
    entries = build_entries(view)
    problems = verify_entries(entries, view)
    if problems:  # by construction this should never happen; refuse rather than store unverified notes
        raise ValueError("Unverified notebook entries: " + "; ".join(problems[:5]))
    concepts: list[IndexedConcept] = []
    if llm is not None:
        for m in view.lessons:
            concepts += index_lesson(llm, m, [e for e in entries if e.lesson_id == m.lesson_id])
    return Notebook(entries, concepts)


def save_notebook(nb: Notebook, path: str | Path) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(nb.to_json())
