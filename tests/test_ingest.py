from pathlib import Path

import pytest

from mason.course_io import load_course
from mason.ingest import ingest_file, parse_captions
from mason.student.view import make_view

FX = Path(__file__).resolve().parent / "fixtures"
SAMPLE = Path(__file__).resolve().parent.parent / "courses" / "sample-bio"


def test_pdf_pages():
    d = ingest_file(FX / "two_pages.pdf", "reading")
    assert not d.unreadable
    assert [s.locator for s in d.spans] == ["page 1", "page 2"]
    assert "Osmosis is the diffusion of water" in d.spans[0].text
    assert "[page 2]" in d.text


def test_scanned_or_blank_pdf_is_unreadable():
    d = ingest_file(FX / "blank.pdf", "reading")
    assert d.unreadable and "no extractable text" in d.error


def test_docx_sections_and_tables():
    d = ingest_file(FX / "organelles.docx", "notes")
    locs = [s.locator for s in d.spans]
    assert locs == ["Ribosomes", "Lysosomes", "table 1"]
    assert "digestive enzymes" in d.spans[1].text
    assert "Golgi | Packages proteins" in d.spans[2].text


def test_pptx_slides_notes_images():
    d = ingest_file(FX / "enzymes.pptx", "slides")
    assert [s.locator for s in d.spans] == ["slide 1", "slide 2"]
    assert "Lower activation energy" in d.spans[0].text
    assert "(Speaker notes) Explain that the enzyme is not used up." in d.spans[0].text
    assert d.has_speaker_notes
    assert len(d.images) == 1 and d.images[0].locator == "slide 2" and d.images[0].ext == "png"


def test_pptx_without_notes():
    d = ingest_file(FX / "no_notes.pptx", "slides")
    assert not d.has_speaker_notes and "Just bullets" in d.text


def test_corrupt_file_is_reported_not_crash():
    d = ingest_file(FX / "corrupt.pptx", "slides")
    assert d.unreadable and d.error


def test_unsupported_type():
    d = ingest_file(FX / "make_fixtures.py", "notes")
    assert d.unreadable and "unsupported" in d.error


def test_srt_and_vtt_captions():
    d = ingest_file(FX / "captions.srt", "transcript")
    assert [s.locator for s in d.spans] == ["00:00:01", "00:00:04"]
    assert d.spans[1].text == "It forms water."
    v = ingest_file(SAMPLE / "L5" / "video_transcript.vtt", "transcript")
    assert len(v.spans) == 8 and "final electron acceptor" in v.text
    assert "-->" not in v.text and "WEBVTT" not in v.text


def test_vtt_with_cue_ids_and_hours():
    spans = parse_captions("WEBVTT\n\nintro\n01:02:03.000 --> 01:02:05.000\nHello <b>class</b>\n")
    assert spans[0].locator == "01:02:03" and spans[0].text == "Hello class"


def test_markdown_sections_keep_text():
    d = ingest_file(SAMPLE / "L3" / "notes.md", "notes")
    assert any(s.locator == "Osmosis" for s in d.spans)
    assert "sodium-potassium pump" in d.text


def test_text_override_used_for_variants():
    d = ingest_file(SAMPLE / "L1" / "notes.md", "notes", text_override="# Changed\nNew text.")
    assert "New text." in d.text and "Hooke" not in d.text


def test_view_flags_slide_only_lesson_and_lists_unreadable(tmp_path):
    lc = load_course(SAMPLE)
    v = make_view(lc, "L6")
    flags = {m.lesson_id: m.slide_only for m in v.lessons}
    assert flags["L4"] is True and flags["L5"] is False
    # a lesson whose only file is unreadable shows up as "not seen"
    import shutil
    dst = tmp_path / "c"
    shutil.copytree(SAMPLE, dst)
    (dst / "L2" / "notes.md").unlink()
    (dst / "L2" / "notes.pptx").write_bytes(b"garbage")
    (dst / "course.yaml").write_text((dst / "course.yaml").read_text().replace("L2/notes.md", "L2/notes.pptx"))
    v2 = make_view(load_course(dst), "L3")
    l2 = next(m for m in v2.lessons if m.lesson_id == "L2")
    assert l2.files == () and l2.unreadable and l2.unreadable[0][0] == "L2/notes.pptx"
