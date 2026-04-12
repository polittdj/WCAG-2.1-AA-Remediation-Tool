"""Generate audit PDFs with realistic content to verify the 6 critical issues.

These are richer than the checkpoint-level verification PDFs — they contain
actual paragraphs, tables, lists, and images to expose the "everything is N/A"
problem where the auditor doesn't detect CONTENT, only TAGS.

Run:  python tests/generate_audit_pdfs.py
"""

from __future__ import annotations

import pathlib

from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.lib import colors
from reportlab.pdfgen import canvas
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    PageBreak,
    Image as RLImage,
)

import pikepdf
from pikepdf import Array, Dictionary, Name, String

OUT_DIR = pathlib.Path(__file__).parent / "audit_pdfs"


# ---------------------------------------------------------------------------
# 01 - Untagged PDF with real paragraphs (3 pages, ~15 paragraphs)
# ---------------------------------------------------------------------------

def gen_01_untagged_no_metadata():
    """3-page PDF with dozens of paragraphs. No tags, no metadata."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "01_untagged_no_metadata.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=inch, rightMargin=inch,
        topMargin=inch, bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = []

    # Page 1
    story.append(Paragraph("Company Annual Report 2025", styles["Title"]))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Executive Summary", styles["Heading1"]))
    story.append(Paragraph(
        "This annual report summarizes the financial and operational performance "
        "of our company over the 2025 fiscal year. Revenue grew 12% year-over-year "
        "and operating income increased 18%.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph(
        "The board of directors is pleased to present these results to shareholders. "
        "Full details follow in the subsequent sections of this report.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Market Overview", styles["Heading2"]))
    story.append(Paragraph(
        "The global market environment in 2025 was characterized by economic "
        "recovery following the downturn of the prior year. Our core markets "
        "demonstrated solid growth, particularly in Asia and Europe.",
        styles["Normal"],
    ))
    story.append(Paragraph(
        "Competition from new entrants remained a concern throughout the year. "
        "However, our product differentiation strategy proved effective.",
        styles["Normal"],
    ))
    story.append(PageBreak())

    # Page 2
    story.append(Paragraph("Financial Results", styles["Heading1"]))
    story.append(Paragraph(
        "Total revenue for fiscal year 2025 was $847 million, representing "
        "growth of 12% over the prior year. Operating expenses grew modestly "
        "at 4%, resulting in significant operating leverage.",
        styles["Normal"],
    ))
    story.append(Paragraph(
        "Gross margin expanded to 42.3% from 39.8% in the prior year, reflecting "
        "improved pricing discipline and supply chain efficiency.",
        styles["Normal"],
    ))
    story.append(Spacer(1, 12))
    story.append(Paragraph("Regional Performance", styles["Heading2"]))
    story.append(Paragraph(
        "North America remained our largest market, contributing 48% of total "
        "revenue. European operations delivered record results, growing 15% on "
        "a constant currency basis.",
        styles["Normal"],
    ))
    story.append(Paragraph(
        "Asian markets, particularly Japan and Southeast Asia, continued their "
        "expansion with 22% revenue growth for the region.",
        styles["Normal"],
    ))
    story.append(PageBreak())

    # Page 3
    story.append(Paragraph("Strategic Initiatives", styles["Heading1"]))
    story.append(Paragraph(
        "During 2025, we launched three major strategic initiatives focused on "
        "digital transformation, sustainability, and operational excellence.",
        styles["Normal"],
    ))
    story.append(Paragraph(
        "Our digital transformation program achieved significant milestones, "
        "including the launch of our new customer portal and the completion "
        "of our ERP system upgrade.",
        styles["Normal"],
    ))
    story.append(Paragraph("Outlook for 2026", styles["Heading2"]))
    story.append(Paragraph(
        "Looking ahead to 2026, we expect continued growth driven by favorable "
        "market conditions and the benefits from our strategic investments.",
        styles["Normal"],
    ))
    story.append(Paragraph(
        "We remain committed to delivering long-term value to all our stakeholders "
        "through disciplined execution and prudent capital allocation.",
        styles["Normal"],
    ))

    doc.build(story)
    # Strip metadata to make it "no metadata"
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        # Clear all docinfo
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        # Remove /Lang, /MarkInfo, etc
        if "/Lang" in pdf.Root:
            del pdf.Root["/Lang"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        pdf.save(str(path))


# ---------------------------------------------------------------------------
# 02 - Form with no tooltips (uses field1, field2, etc.)
# ---------------------------------------------------------------------------

def gen_02_form_no_tooltips():
    """Form PDF with visible labels and adjacent widgets, no /TU."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "02_form_no_tooltips.pdf"

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Employee Information Form")
    c.setFont("Helvetica", 12)
    # Labels next to fields
    labels_y = [9, 8.3, 7.6, 6.9, 6.2, 5.5]
    label_texts = ["First Name:", "Last Name:", "Email Address:",
                   "Department:", "Hire Date:", "Manager:"]
    for y, text in zip(labels_y, label_texts):
        c.drawString(1 * inch, y * inch, text)
    c.save()

    # Now add widgets via pikepdf
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        page = pdf.pages[0]
        page_obj = page.obj
        annots = []
        for i, (y, label) in enumerate(zip(labels_y, label_texts)):
            # Field to the right of label, ~100pt wide
            x1 = 2.5 * inch
            y1 = y * inch - 2
            x2 = x1 + 200
            y2 = y1 + 16
            widget = pdf.make_indirect(Dictionary({
                "/Type": Name("/Annot"),
                "/Subtype": Name("/Widget"),
                "/Rect": Array([x1, y1, x2, y2]),
                "/T": String(f"field{i+1}"),
                "/FT": Name("/Tx"),
                "/P": page_obj,
            }))
            annots.append(widget)
        page["/Annots"] = Array(annots)
        # Add AcroForm so it's recognized as a form
        if "/AcroForm" not in pdf.Root:
            pdf.Root["/AcroForm"] = Dictionary({
                "/Fields": Array(annots),
                "/NeedAppearances": True,
            })
        pdf.save(str(path))


# ---------------------------------------------------------------------------
# 03 - PDF with images but no alt text
# ---------------------------------------------------------------------------

def gen_03_images_no_alt_text():
    """PDF with actual image XObjects but no /Figure tags or /Alt."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "03_images_no_alt_text.pdf"

    # Create a simple PNG image data using PIL
    from PIL import Image as PILImage
    import io

    img_path = OUT_DIR / "_temp_img.png"
    img = PILImage.new("RGB", (200, 150), color=(100, 150, 200))
    # Add some visible pixels so it's not just a solid block
    pixels = img.load()
    for x in range(50, 150):
        for y in range(40, 110):
            pixels[x, y] = (220, 80, 80)
    img.save(str(img_path))

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Product Catalog")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, 9.5 * inch, "Featured Products")
    # Draw the image twice
    c.drawImage(str(img_path), 1 * inch, 7.5 * inch, width=2 * inch, height=1.5 * inch)
    c.drawImage(str(img_path), 4 * inch, 7.5 * inch, width=2 * inch, height=1.5 * inch)
    c.drawString(1 * inch, 7 * inch, "Product A: Our flagship product.")
    c.drawString(4 * inch, 7 * inch, "Product B: Best seller this year.")
    # Another image
    c.drawImage(str(img_path), 1 * inch, 4.5 * inch, width=4 * inch, height=2 * inch)
    c.drawString(1 * inch, 4 * inch, "Product C: Newest addition to our lineup.")
    c.save()
    img_path.unlink(missing_ok=True)

    # Strip any metadata and struct tree
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


# ---------------------------------------------------------------------------
# 04 - Table PDF without /Table tags
# ---------------------------------------------------------------------------

def gen_04_table_no_headers():
    """PDF with 2 visible data tables but no /Table struct elements."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "04_table_no_headers.pdf"

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

    # Table 1 - Sales by region
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

    # Table 2 - Top products
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

    # Strip metadata and structure
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


# ---------------------------------------------------------------------------
# 06 - Broken heading hierarchy
# ---------------------------------------------------------------------------

def gen_06_bad_heading_hierarchy():
    """PDF that looks like broken headings: H1 -> H3 -> H5, multiple H1s."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "06_bad_heading_hierarchy.pdf"

    c = canvas.Canvas(str(path), pagesize=letter)
    # Two "H1" size (22pt)
    c.setFont("Helvetica-Bold", 22)
    c.drawString(1 * inch, 10 * inch, "Heading A")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, 9.5 * inch, "Body text under heading A follows here.")
    # "H3" size (14pt) - skipped H2
    c.setFont("Helvetica-Bold", 14)
    c.drawString(1 * inch, 9 * inch, "Subsection 1.1.1 (skipped H2)")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, 8.5 * inch, "Body text here.")
    # "H5" size (11pt bold) - skipped H4
    c.setFont("Helvetica-Bold", 11)
    c.drawString(1 * inch, 8 * inch, "Tiny Heading (skipped H4)")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, 7.5 * inch, "More body.")
    # Second "H1" - violation
    c.setFont("Helvetica-Bold", 22)
    c.drawString(1 * inch, 7 * inch, "Second Main Heading")
    c.setFont("Helvetica", 11)
    c.drawString(1 * inch, 6.5 * inch, "Second body.")
    c.save()

    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


# ---------------------------------------------------------------------------
# 09 - List PDF without /L tags
# ---------------------------------------------------------------------------

def gen_09_fake_lists_no_structure():
    """PDF with visible bullet and numbered lists but no /L tags."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "09_fake_lists_no_structure.pdf"

    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 16)
    c.drawString(1 * inch, 10 * inch, "Project Requirements Document")
    c.setFont("Helvetica-Bold", 12)
    c.drawString(1 * inch, 9.5 * inch, "Functional Requirements")
    c.setFont("Helvetica", 11)
    # Bullet list
    bullet_items = [
        "User authentication with OAuth 2.0",
        "Real-time notifications via WebSocket",
        "Role-based access control",
        "Audit log for all admin actions",
        "Export data as CSV or JSON",
    ]
    y = 9 * inch
    for item in bullet_items:
        c.drawString(1.2 * inch, y, f"\u2022 {item}")
        y -= 0.25 * inch

    c.setFont("Helvetica-Bold", 12)
    y -= 0.3 * inch
    c.drawString(1 * inch, y, "Implementation Steps")
    c.setFont("Helvetica", 11)
    y -= 0.3 * inch
    # Numbered list
    numbered_items = [
        "Set up the development environment",
        "Configure CI/CD pipeline",
        "Implement core database schema",
        "Build authentication module",
        "Develop API endpoints",
    ]
    for i, item in enumerate(numbered_items, 1):
        c.drawString(1.2 * inch, y, f"{i}. {item}")
        y -= 0.25 * inch

    c.save()

    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


def gen_05_bad_contrast():
    """PDF with three text elements at different contrast ratios."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "05_bad_contrast.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1 * inch, 10 * inch, "Contrast Test Document")
    c.setFont("Helvetica", 12)
    # Very low contrast (light gray on white, ~1.47:1 FAIL)
    c.setFillColorRGB(0.8, 0.8, 0.8)
    c.drawString(1 * inch, 9 * inch, "This text has very poor contrast on white.")
    # Mid-low contrast (gray, ~2.85:1 FAIL)
    c.setFillColorRGB(0.6, 0.6, 0.6)
    c.drawString(1 * inch, 8.5 * inch, "This text has insufficient contrast.")
    # Good contrast (dark gray, ~12.6:1 PASS)
    c.setFillColorRGB(0.2, 0.2, 0.2)
    c.drawString(1 * inch, 8 * inch, "This text has excellent contrast and passes WCAG AA.")
    c.save()
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


def gen_07_restricted_security():
    """PDF encrypted with restricted permissions."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "07_restricted_security.pdf"
    c = canvas.Canvas(str(path), pagesize=letter)
    c.setFont("Helvetica-Bold", 18)
    c.drawString(1 * inch, 10 * inch, "Restricted Security Document")
    c.setFont("Helvetica", 12)
    c.drawString(1 * inch, 9.5 * inch, "This document has restricted security settings.")
    c.drawString(1 * inch, 9.2 * inch, "It should be detected as encrypted.")
    c.save()
    # Re-save with encryption
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        pdf.docinfo["/Title"] = String("Secured Document")
        pdf.save(
            str(path),
            encryption=pikepdf.Encryption(
                owner="owner123",
                user="",
                allow=pikepdf.Permissions(
                    extract=False,
                    modify_annotation=False,
                    modify_assembly=False,
                    modify_form=False,
                    modify_other=False,
                    print_lowres=True,
                    print_highres=True,
                    accessibility=False,
                ),
            ),
        )


def gen_08_lang():
    """PDF with multi-language content where first text is a sentence
    (verifying the title heuristic rejects body sentences)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "08_lang.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=inch, rightMargin=inch,
        topMargin=inch, bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("The partnership agreement was signed in Berlin on March 15.", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("International Partnership Report", styles["Title"]),
        Spacer(1, 12),
        Paragraph("This report describes the outcomes of the Berlin partnership.", styles["Normal"]),
        Paragraph("Beide Parteien haben zugestimmt.", styles["Normal"]),
        Paragraph("Les deux parties ont accepte.", styles["Normal"]),
    ]
    doc.build(story)
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


def gen_10_security():
    """PDF where the first text block is a numbered agenda item
    (verifying title heuristic rejects agenda items)."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    path = OUT_DIR / "10_security.pdf"
    doc = SimpleDocTemplate(
        str(path), pagesize=letter,
        leftMargin=inch, rightMargin=inch,
        topMargin=inch, bottomMargin=inch,
    )
    styles = getSampleStyleSheet()
    story = [
        Paragraph("1. Call to Order \u2014 Meeting called to order at 9:00 AM by the Chairperson.", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Security Committee Meeting Minutes", styles["Title"]),
        Spacer(1, 12),
        Paragraph("2. Roll Call \u2014 All members present.", styles["Normal"]),
        Paragraph("3. Approval of Minutes \u2014 Prior meeting minutes approved.", styles["Normal"]),
    ]
    doc.build(story)
    with pikepdf.open(str(path), allow_overwriting_input=True) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if "/StructTreeRoot" in pdf.Root:
            del pdf.Root["/StructTreeRoot"]
        if "/MarkInfo" in pdf.Root:
            del pdf.Root["/MarkInfo"]
        pdf.save(str(path))


def generate_all():
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    generators = [
        gen_01_untagged_no_metadata,
        gen_02_form_no_tooltips,
        gen_03_images_no_alt_text,
        gen_04_table_no_headers,
        gen_05_bad_contrast,
        gen_06_bad_heading_hierarchy,
        gen_07_restricted_security,
        gen_08_lang,
        gen_09_fake_lists_no_structure,
        gen_10_security,
    ]
    for fn in generators:
        try:
            fn()
            print(f"  OK: {fn.__name__}")
        except Exception as e:
            print(f"  FAIL: {fn.__name__} -- {type(e).__name__}: {e}")
    print(f"\nGenerated audit PDFs in {OUT_DIR}")


if __name__ == "__main__":
    generate_all()
