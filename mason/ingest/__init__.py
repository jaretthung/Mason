"""Turn uploaded lesson files into located text spans.

Every span carries a locator ("page 3", "slide 5", "00:01:12", "section 2") so notebook quotes and the
teacher report can point back to the exact place in the material. Files that can't be read are returned
with `unreadable=True` and listed in the report under "not seen by Mason" — never a crash.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class Span:
    locator: str
    text: str


@dataclass
class Image:
    locator: str
    ext: str
    data: bytes

    @property
    def sha(self) -> str:
        return hashlib.sha256(self.data).hexdigest()[:16]


@dataclass
class SourceDoc:
    path: str
    kind: str  # notes | slides | reading | transcript
    spans: list[Span] = field(default_factory=list)
    images: list[Image] = field(default_factory=list)
    has_speaker_notes: bool = False
    unreadable: bool = False
    error: str = ""

    @property
    def text(self) -> str:
        """Text for prompts: each span headed by its locator."""
        out = []
        for s in self.spans:
            if not s.text.strip():
                continue
            # markdown sections already start with their heading; others get a locator line
            out.append(s.text if (not s.locator or s.text.lstrip().startswith("#")) else f"[{s.locator}]\n{s.text}")
        return "\n\n".join(out)


def ingest_file(path: str | Path, kind: str, rel_path: str | None = None, text_override: str | None = None
                ) -> SourceDoc:
    path = Path(path)
    rel = rel_path or path.name
    ext = path.suffix.lower()
    try:
        if text_override is not None:
            spans = _text_spans(text_override, ext)
            return SourceDoc(rel, kind, spans)
        if ext in (".md", ".txt", ".markdown"):
            return SourceDoc(rel, kind, _text_spans(path.read_text(encoding="utf-8", errors="replace"), ext))
        if ext in (".vtt", ".srt"):
            return SourceDoc(rel, kind, parse_captions(path.read_text(encoding="utf-8", errors="replace")))
        if ext == ".pdf":
            return _pdf(path, rel, kind)
        if ext == ".docx":
            return _docx(path, rel, kind)
        if ext == ".pptx":
            return _pptx(path, rel, kind)
        return SourceDoc(rel, kind, unreadable=True, error=f"unsupported file type {ext or '(none)'}")
    except Exception as e:  # noqa: BLE001 - any parser failure becomes "not seen by Mason"
        return SourceDoc(rel, kind, unreadable=True, error=f"{type(e).__name__}: {e}")


# --------------------------------------------------------------------------- text / markdown


def _text_spans(text: str, ext: str = ".md") -> list[Span]:
    if ext in (".vtt", ".srt"):
        return parse_captions(text)
    # One span per markdown section so locators stay meaningful.
    spans, title, buf = [], "", []
    for line in text.splitlines():
        m = re.match(r"^(#{1,3})\s+(.*)", line)
        if m and buf:
            spans.append(Span(title, "\n".join(buf).strip()))
            buf = []
        if m:
            title = m.group(2).strip()
        buf.append(line)
    if buf:
        spans.append(Span(title, "\n".join(buf).strip()))
    return [s for s in spans if s.text]


# --------------------------------------------------------------------------- captions

_TS = re.compile(r"(\d{1,2}:)?\d{1,2}:\d{2}[\.,]\d{1,3}\s*-->\s*(\d{1,2}:)?\d{1,2}:\d{2}[\.,]\d{1,3}")


def parse_captions(text: str) -> list[Span]:
    """WebVTT or SRT -> one span per cue, locator = start time. Drops headers, cue numbers, tags."""
    spans: list[Span] = []
    blocks = re.split(r"\n\s*\n", text.replace("\r\n", "\n").strip())
    for b in blocks:
        lines = [ln for ln in b.split("\n") if ln.strip()]
        if not lines or lines[0].strip().upper().startswith(("WEBVTT", "NOTE", "STYLE")):
            continue
        ts_i = next((i for i, ln in enumerate(lines) if _TS.search(ln)), None)
        if ts_i is None:
            continue
        start = lines[ts_i].split("-->")[0].strip().replace(",", ".")
        cue = " ".join(re.sub(r"<[^>]+>", "", ln).strip() for ln in lines[ts_i + 1:])
        if cue:
            spans.append(Span(start.split(".")[0], cue))
    return spans


# --------------------------------------------------------------------------- pdf / docx / pptx


def _pdf(path: Path, rel: str, kind: str) -> SourceDoc:
    from pypdf import PdfReader

    reader = PdfReader(str(path))
    spans = []
    for i, page in enumerate(reader.pages, start=1):
        t = (page.extract_text() or "").strip()
        if t:
            spans.append(Span(f"page {i}", t))
    doc = SourceDoc(rel, kind, spans)
    if not spans:
        doc.unreadable, doc.error = True, "no extractable text (scanned PDF?)"
    return doc


def _docx(path: Path, rel: str, kind: str) -> SourceDoc:
    import docx

    d = docx.Document(str(path))
    spans, title, buf, n = [], "", [], 0

    def flush():
        nonlocal buf
        if buf:
            spans.append(Span(title or f"section {n}", "\n".join(buf).strip()))
            buf = []

    for p in d.paragraphs:
        if p.style is not None and p.style.name.lower().startswith("heading"):
            flush()
            n += 1
            title = p.text.strip()
        if p.text.strip():
            buf.append(p.text.strip())
    flush()
    for ti, table in enumerate(d.tables, start=1):
        rows = [" | ".join(c.text.strip() for c in row.cells) for row in table.rows]
        spans.append(Span(f"table {ti}", "\n".join(rows)))
    return SourceDoc(rel, kind, spans)


def _pptx(path: Path, rel: str, kind: str) -> SourceDoc:
    from pptx import Presentation
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    spans, images, any_notes = [], [], False

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type == MSO_SHAPE_TYPE.GROUP:
                yield from walk(sh.shapes)
            else:
                yield sh

    for i, slide in enumerate(prs.slides, start=1):
        texts = []
        for sh in walk(slide.shapes):
            if sh.has_text_frame and sh.text_frame.text.strip():
                texts.append(sh.text_frame.text.strip())
            if getattr(sh, "has_table", False) and sh.has_table:
                for row in sh.table.rows:
                    texts.append(" | ".join(c.text.strip() for c in row.cells))
            if sh.shape_type == MSO_SHAPE_TYPE.PICTURE:
                img = sh.image
                images.append(Image(f"slide {i}", img.ext, img.blob))
        notes = ""
        if slide.has_notes_slide:
            notes = slide.notes_slide.notes_text_frame.text.strip()
        body = "\n".join(texts)
        if notes:
            any_notes = True
            body += f"\n(Speaker notes) {notes}"
        if body.strip():
            spans.append(Span(f"slide {i}", body.strip()))
    return SourceDoc(rel, kind, spans, images, has_speaker_notes=any_notes)
