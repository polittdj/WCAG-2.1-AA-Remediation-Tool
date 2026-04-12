"""v3 adversarial PDFs — maximum real-world variation.

These PDFs are deliberately designed to trip up the content tagger's
heuristics. They mirror what a real PDF authoring tool produces when it
draws list items with one Tj per glyph (the way some InDesign and MS
Word exports look under the hood).
"""

from __future__ import annotations

import pathlib

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas
import pikepdf
from pikepdf import Array, Dictionary, Name, String

OUT_DIR = pathlib.Path(__file__).parent / "audit_pdfs_v3"


def _strip_metadata(path: pathlib.Path):
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        if "/Lang" in pdf.Root:
            del pdf.Root["/Lang"]
        pdf.save(str(path))


def gen_09v3_fake_lists_every_glyph_separate():
    """Lists where EVERY list prefix is a separate Tj call with wide X-gap.

    This mimics older InDesign/PS exports where each glyph is drawn
    individually. PyMuPDF then puts the bullet and item text on
    SEPARATE lines in get_text('text'), and numbered prefixes like '1.'
    are also on their own line.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "09_fake_lists_no_structure.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Project Requirements Document")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, 9.5 * inch, "Functional Requirements")
    c.setFont("Helvetica", 11)
    bullet_items = [
        "User authentication with OAuth 2.0",
        "Real-time notifications via WebSocket",
        "Role-based access control",
        "Audit log for all admin actions",
        "Export data as CSV or JSON",
    ]
    y = 9 * inch
    for item in bullet_items:
        # Wide 0.5-inch gap — forces PyMuPDF to treat them as
        # separate lines even at the same Y coordinate.
        c.drawString(1.0 * inch, y, "\u2022")
        c.drawString(1.5 * inch, y, item)
        y -= 0.28 * inch

    c.setFont("Helvetica-Bold", 12)
    y -= 0.3 * inch
    c.drawString(1 * inch, y, "Implementation Steps")
    c.setFont("Helvetica", 11)
    y -= 0.3 * inch
    numbered_items = [
        "Set up the development environment",
        "Configure CI/CD pipeline",
        "Implement core database schema",
        "Build authentication module",
        "Develop API endpoints",
    ]
    for i, item in enumerate(numbered_items, 1):
        # Number prefix at 1.0in, item text at 1.5in — wide gap.
        c.drawString(1.0 * inch, y, f"{i}.")
        c.drawString(1.5 * inch, y, item)
        y -= 0.28 * inch
    c.save()
    _strip_metadata(path)


def generate_all():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fn in (gen_09v3_fake_lists_every_glyph_separate,):
        try:
            fn()
            print(f"  OK: {fn.__name__}")
        except Exception as e:
            print(f"  FAIL: {fn.__name__} -- {type(e).__name__}: {e}")


if __name__ == "__main__":
    generate_all()
