"""Regenerate the ingestion fixtures. Needs reportlab (not a Mason dependency); outputs are committed.

    python3 tests/fixtures/make_fixtures.py
"""

import io
from pathlib import Path

HERE = Path(__file__).resolve().parent


def pdf():
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas

    c = canvas.Canvas(str(HERE / "two_pages.pdf"), pagesize=letter)
    c.drawString(72, 700, "Page one: Osmosis is the diffusion of water.")
    c.showPage()
    c.drawString(72, 700, "Page two: Active transport requires ATP.")
    c.showPage()
    c.save()
    c = canvas.Canvas(str(HERE / "blank.pdf"), pagesize=letter)
    c.showPage()
    c.save()


def docx():
    import docx as d

    doc = d.Document()
    doc.add_heading("Ribosomes", level=1)
    doc.add_paragraph("Ribosomes make proteins.")
    doc.add_heading("Lysosomes", level=1)
    doc.add_paragraph("Lysosomes contain digestive enzymes.")
    t = doc.add_table(rows=2, cols=2)
    t.cell(0, 0).text, t.cell(0, 1).text = "Organelle", "Job"
    t.cell(1, 0).text, t.cell(1, 1).text = "Golgi", "Packages proteins"
    doc.save(HERE / "organelles.docx")


def pptx():
    from PIL import Image
    from pptx import Presentation
    from pptx.util import Inches

    prs = Presentation()
    s1 = prs.slides.add_slide(prs.slide_layouts[1])
    s1.shapes.title.text = "Enzymes"
    s1.placeholders[1].text = "Lower activation energy"
    s1.notes_slide.notes_text_frame.text = "Explain that the enzyme is not used up."
    s2 = prs.slides.add_slide(prs.slide_layouts[5])
    s2.shapes.title.text = "Diagram of a cell"
    buf = io.BytesIO()
    Image.new("RGB", (40, 30), (0, 128, 0)).save(buf, "PNG")
    buf.seek(0)
    s2.shapes.add_picture(buf, Inches(1), Inches(2))
    prs.save(HERE / "enzymes.pptx")

    prs = Presentation()
    s = prs.slides.add_slide(prs.slide_layouts[1])
    s.shapes.title.text = "No notes here"
    s.placeholders[1].text = "Just bullets"
    prs.save(HERE / "no_notes.pptx")


if __name__ == "__main__":
    pdf()
    docx()
    pptx()
    (HERE / "corrupt.pptx").write_bytes(b"this is not a zip file")
    (HERE / "captions.srt").write_text(
        "1\n00:00:01,000 --> 00:00:04,000\nOxygen is the final electron acceptor.\n\n"
        "2\n00:00:04,500 --> 00:00:08,000\n<i>It forms water.</i>\n")
    print("fixtures written to", HERE)
