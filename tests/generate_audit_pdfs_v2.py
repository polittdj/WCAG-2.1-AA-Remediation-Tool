"""Generate adversarial audit PDFs that reproduce the 4 reported issues.

These are different from the clean reportlab PDFs in tests/audit_pdfs/ —
they mimic the kind of real-world PDFs where the content tagger's
heuristics break down:

- Lists drawn with separate Tj operators for bullet + item text
- Tables whose layout looks table-like to PyMuPDF but the extracted
  rows are irregular
- Images placed in a grid layout that PyMuPDF might mis-detect as a table
- Pipeline paths where fix_focus_order silently fails

Each PDF is constructed to reliably trigger the user-reported behavior
so we can write regression tests and verify the fix.
"""

from __future__ import annotations

import pathlib

from reportlab.lib.pagesizes import letter
from reportlab.lib.units import inch
from reportlab.pdfgen import canvas

import pikepdf
from pikepdf import Array, Dictionary, Name, String

OUT_DIR = pathlib.Path(__file__).parent / "audit_pdfs_v2"


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


# ---------------------------------------------------------------------------
# 09v2 — lists where bullet char and item text are SEPARATE draw calls
# ---------------------------------------------------------------------------


def gen_09v2_fake_lists():
    """Lists where bullets are drawn as separate Tj calls.

    Real-world PDFs (e.g. from MS Word, LibreOffice, InDesign) often draw
    a bullet glyph with one drawString then the item text with another
    drawString at a different X offset. PyMuPDF may or may not merge these
    into a single line depending on span proximity rules.

    This also uses uncommon bullet characters (real-world MS Word bullets
    are often U+F0B7 from the Symbol font, not U+2022).
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "09_fake_lists_no_structure.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Project Requirements Document")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, 9.5 * inch, "Functional Requirements")
    c.setFont("Helvetica", 11)
    # Bullet list — draw bullet separately from item text
    bullet_items = [
        "User authentication with OAuth 2.0",
        "Real-time notifications via WebSocket",
        "Role-based access control",
        "Audit log for all admin actions",
        "Export data as CSV or JSON",
    ]
    y = 9 * inch
    for item in bullet_items:
        # Bullet glyph drawn at x=1.2in
        c.drawString(1.2 * inch, y, "\u2022")
        # Item text drawn at x=1.4in (0.2in gap — outside span-merge threshold)
        c.drawString(1.4 * inch, y, item)
        y -= 0.25 * inch

    c.setFont("Helvetica-Bold", 12)
    y -= 0.3 * inch
    c.drawString(1 * inch, y, "Implementation Steps")
    c.setFont("Helvetica", 11)
    y -= 0.3 * inch
    # Numbered list — same separate-draw pattern
    numbered_items = [
        "Set up the development environment",
        "Configure CI/CD pipeline",
        "Implement core database schema",
        "Build authentication module",
        "Develop API endpoints",
    ]
    for i, item in enumerate(numbered_items, 1):
        c.drawString(1.2 * inch, y, f"{i}.")
        c.drawString(1.4 * inch, y, item)
        y -= 0.25 * inch
    c.save()
    _strip_metadata(path)


# ---------------------------------------------------------------------------
# 03v2 — product catalog with grid-like image layout (triggers find_tables)
# ---------------------------------------------------------------------------


def gen_03v2_images():
    """Product catalog with images arranged in a grid.

    PyMuPDF's find_tables() can mis-detect image grids as tables when
    text near images is aligned in columns (product names + descriptions).
    This PDF reproduces that scenario.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "03_images_no_alt_text.pdf"

    from PIL import Image as PILImage
    img_path = OUT_DIR / "_tmp_img.png"
    img = PILImage.new("RGB", (200, 150), color=(100, 150, 200))
    pixels = img.load()
    for x in range(50, 150):
        for y in range(40, 110):
            pixels[x, y] = (220, 80, 80)
    img.save(str(img_path))

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Product Catalog")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, 9.5 * inch, "Featured Products")
    # Row 1: 2 products side-by-side with aligned name/description
    c.drawImage(str(img_path), 1 * inch, 7.5 * inch, width=2 * inch, height=1.5 * inch)
    c.drawImage(str(img_path), 4 * inch, 7.5 * inch, width=2 * inch, height=1.5 * inch)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(1 * inch, 7.2 * inch, "Product A")
    c.drawString(4 * inch, 7.2 * inch, "Product B")
    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, 7.0 * inch, "Our flagship product.")
    c.drawString(4 * inch, 7.0 * inch, "Best seller this year.")
    # Row 2: single full-width product
    c.drawImage(str(img_path), 1 * inch, 4.5 * inch, width=4 * inch, height=2 * inch)
    c.setFont("Helvetica-Bold", 11)
    c.drawString(1 * inch, 4.2 * inch, "Product C")
    c.setFont("Helvetica", 10)
    c.drawString(1 * inch, 4.0 * inch, "Newest addition to our lineup.")
    c.save()
    img_path.unlink(missing_ok=True)
    _strip_metadata(path)


# ---------------------------------------------------------------------------
# 04v2 — table where extract() returns empty or single-row data
# ---------------------------------------------------------------------------


def gen_04v2_table():
    """Table where PyMuPDF detects the rectangle but extract() fails.

    Some PDFs have tables drawn with line operators and text placed
    individually, so find_tables() detects the grid but extract() returns
    an empty row list. The table code must still create a proper
    /Table > /TR > /TD hierarchy with placeholder cells.
    """
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "04_table_no_headers.pdf"

    from reportlab.lib.styles import getSampleStyleSheet
    from reportlab.lib import colors
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle
    )

    doc = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=inch, rightMargin=inch,
        topMargin=inch, bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = []
    story.append(Paragraph("Quarterly Sales Report", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Q3 Revenue by Region", styles["Heading2"]))
    story.append(Spacer(1, 6))
    data1 = [
        ["Region", "Q3 Revenue", "YoY Growth", "Forecast"],
        ["North America", "$124M", "+8%", "$135M"],
        ["Europe", "$89M", "+15%", "$102M"],
        ["Asia Pacific", "$67M", "+22%", "$82M"],
        ["Latin America", "$31M", "+5%", "$33M"],
    ]
    t1 = Table(data1, colWidths=[1.5 * inch, 1.2 * inch, 1.2 * inch, 1.2 * inch])
    t1.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t1)
    story.append(Spacer(1, 24))
    story.append(Paragraph("Top Products", styles["Heading2"]))
    story.append(Spacer(1, 6))
    data2 = [
        ["Product", "Units Sold", "Revenue"],
        ["Widget Pro", "12,450", "$2.1M"],
        ["Gadget Plus", "8,920", "$1.8M"],
        ["Thingamajig", "5,600", "$980K"],
    ]
    t2 = Table(data2, colWidths=[2 * inch, 1.5 * inch, 1.5 * inch])
    t2.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
        ("GRID", (0, 0), (-1, -1), 0.5, colors.black),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("PADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t2)
    doc.build(story)
    _strip_metadata(path)


def generate_all():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    for fn in (gen_09v2_fake_lists, gen_03v2_images, gen_04v2_table):
        try:
            fn()
            print(f"  OK: {fn.__name__}")
        except Exception as e:
            print(f"  FAIL: {fn.__name__} -- {type(e).__name__}: {e}")


if __name__ == "__main__":
    generate_all()
