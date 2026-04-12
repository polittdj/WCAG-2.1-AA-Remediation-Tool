"""Category O — Silent Data Corruption Detectors.

The WORST kind of bug: tool says 'PASS' but output is wrong.
Every test checks ACTUAL BYTES of the output PDF.
"""

from __future__ import annotations

import pathlib
import sys

import fitz
import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline


def _run(src: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "out"
    return run_pipeline(str(src), str(out))


# ═══════════════════════════════════════════════════════════════════════
# O4 — Content stream integrity: balanced BDC/EMC
# ═══════════════════════════════════════════════════════════════════════

def test_o4_balanced_bdc_emc_after_remediation(tmp_path):
    """After remediation, every page must have balanced BDC/EMC."""
    src = tmp_path / "untagged.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Untagged paragraph one", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Untagged paragraph two", fontsize=12, fontname="helv")
    doc.save(str(src))
    doc.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        for i, page in enumerate(pdf.pages):
            c = page.get("/Contents")
            if c is None:
                continue
            if isinstance(c, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in c)
            else:
                data = bytes(c.read_bytes())
            bdc_count = data.count(b"BDC")
            emc_count = data.count(b"EMC")
            assert bdc_count == emc_count, (
                f"Page {i}: BDC={bdc_count} != EMC={emc_count} — unbalanced operators"
            )

    # Also verify the page still renders
    out_doc = fitz.open(res["output_pdf"])
    for i in range(out_doc.page_count):
        pix = out_doc[i].get_pixmap(dpi=72)
        assert pix.width > 0 and pix.height > 0, f"Page {i} renders empty"
    out_doc.close()


# ═══════════════════════════════════════════════════════════════════════
# O5 — Font resources survive remediation
# ═══════════════════════════════════════════════════════════════════════

def test_o5_fonts_survive(tmp_path):
    src = tmp_path / "multifonts.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Helvetica text", fontsize=12, fontname="helv")
    page.insert_text((72, 130), "Times text", fontsize=12, fontname="tiro")
    page.insert_text((72, 160), "Courier text", fontsize=12, fontname="cour")
    doc.save(str(src))
    doc.close()

    # Extract text before
    before_doc = fitz.open(str(src))
    before_text = before_doc[0].get_text()
    before_doc.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    after_doc = fitz.open(res["output_pdf"])
    after_text = after_doc[0].get_text()
    after_doc.close()

    assert "Helvetica text" in after_text, "Helvetica text lost"
    assert "Times text" in after_text, "Times text lost"
    assert "Courier text" in after_text, "Courier text lost"


# ═══════════════════════════════════════════════════════════════════════
# O7 — Page count preserved
# ═══════════════════════════════════════════════════════════════════════

def test_o7_page_count_preserved(tmp_path):
    src = tmp_path / "seven_pages.pdf"
    doc = fitz.open()
    for i in range(7):
        page = doc.new_page(width=612, height=792)
        page.insert_text((72, 100), f"Page {i + 1} of 7", fontsize=14, fontname="helv")
    doc.save(str(src))
    doc.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        assert len(pdf.pages) == 7, f"Expected 7 pages, got {len(pdf.pages)}"


# ═══════════════════════════════════════════════════════════════════════
# O8 — No metadata cross-contamination between files
# ═══════════════════════════════════════════════════════════════════════

def test_o8_no_metadata_leak(tmp_path):
    # File A
    src_a = tmp_path / "alice.pdf"
    pdf_a = pikepdf.new()
    pdf_a.add_blank_page()
    pdf_a.docinfo["/Author"] = "Alice Smith"
    pdf_a.docinfo["/Title"] = "Alice Report"
    pdf_a.save(str(src_a))
    pdf_a.close()

    # File B
    src_b = tmp_path / "bob.pdf"
    pdf_b = pikepdf.new()
    pdf_b.add_blank_page()
    pdf_b.docinfo["/Author"] = "Bob Jones"
    pdf_b.docinfo["/Title"] = "Bob Report"
    pdf_b.save(str(src_b))
    pdf_b.close()

    # Process A then B
    res_a = _run(src_a, tmp_path / "out_a")
    res_b = _run(src_b, tmp_path / "out_b")

    assert res_a["output_pdf"] and res_b["output_pdf"]

    with pikepdf.open(res_a["output_pdf"]) as pa:
        author_a = str(pa.docinfo.get("/Author", ""))
        assert "Bob" not in author_a, f"File A leaked Bob's metadata: {author_a}"

    with pikepdf.open(res_b["output_pdf"]) as pb:
        author_b = str(pb.docinfo.get("/Author", ""))
        assert "Alice" not in author_b, f"File B leaked Alice's metadata: {author_b}"


# ═══════════════════════════════════════════════════════════════════════
# O9 — Hyperlink destinations survive remediation
# ═══════════════════════════════════════════════════════════════════════

def test_o9_hyperlinks_survive(tmp_path):
    src = tmp_path / "links.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.add_blank_page()
    pdf.add_blank_page()

    page0 = pdf.pages[0]
    page0["/Annots"] = pikepdf.Array([
        # External link
        pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Annot"),
            "/Subtype": pikepdf.Name("/Link"),
            "/Rect": pikepdf.Array([72, 700, 300, 720]),
            "/A": pikepdf.Dictionary({
                "/S": pikepdf.Name("/URI"),
                "/URI": pikepdf.String("https://example.com"),
            }),
        })),
    ])

    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as out_pdf:
        found_external = False
        for page in out_pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) != "/Link":
                    continue
                action = annot.get("/A")
                if action and str(action.get("/URI", "")) == "https://example.com":
                    found_external = True
        assert found_external, "External link to example.com lost after remediation"


# ═══════════════════════════════════════════════════════════════════════
# O10 — AcroForm field values preserved
# ═══════════════════════════════════════════════════════════════════════

def test_o10_field_values_preserved(tmp_path):
    src = tmp_path / "filled_form.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    page = pdf.pages[0]

    text_field = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Annot"),
        "/Subtype": pikepdf.Name("/Widget"),
        "/FT": pikepdf.Name("/Tx"),
        "/T": pikepdf.String("name_field"),
        "/V": pikepdf.String("John Doe"),
        "/Rect": pikepdf.Array([72, 700, 300, 720]),
    }))
    checkbox = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Annot"),
        "/Subtype": pikepdf.Name("/Widget"),
        "/FT": pikepdf.Name("/Btn"),
        "/T": pikepdf.String("agree"),
        "/V": pikepdf.Name("/Yes"),
        "/Rect": pikepdf.Array([72, 660, 90, 678]),
    }))

    page["/Annots"] = pikepdf.Array([text_field, checkbox])
    pdf.Root["/AcroForm"] = pikepdf.Dictionary({
        "/Fields": pikepdf.Array([text_field, checkbox]),
    })

    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as out_pdf:
        found_text = False
        found_check = False
        for page in out_pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) != "/Widget":
                    continue
                t = str(annot.get("/T", ""))
                if t == "name_field":
                    v = str(annot.get("/V", ""))
                    assert v == "John Doe", f"Text field value changed: {v!r}"
                    found_text = True
                elif t == "agree":
                    v = str(annot.get("/V", ""))
                    assert v == "/Yes", f"Checkbox value changed: {v!r}"
                    ft = str(annot.get("/FT", ""))
                    assert ft == "/Btn", f"Field type changed: {ft!r}"
                    found_check = True
        assert found_text, "Text field 'name_field' not found in output"
        assert found_check, "Checkbox 'agree' not found in output"


# ═══════════════════════════════════════════════════════════════════════
# O6 — Image count preserved
# ═══════════════════════════════════════════════════════════════════════

def test_o6_image_count_preserved(tmp_path):
    """Images must survive remediation. Uses distinct sizes to prevent
    deduplication, and verifies at least as many unique XObject images
    exist in the output as in the input."""
    src = tmp_path / "images.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    # Create 4 images with DISTINCT sizes so they cannot be deduplicated
    sizes = [(20, 20), (30, 30), (40, 40), (50, 50)]
    for i, (w, h) in enumerate(sizes):
        pix = fitz.Pixmap(fitz.csRGB, fitz.IRect(0, 0, w, h), 1)
        pix.clear_with(50 * (i + 1))  # distinct fill values
        img_rect = fitz.Rect(72 + i * 80, 400, 72 + i * 80 + w, 400 + h)
        page.insert_image(img_rect, pixmap=pix)
    doc.save(str(src))
    doc.close()

    # Count unique images before
    before_doc = fitz.open(str(src))
    before_images = len(before_doc[0].get_images())
    before_doc.close()
    assert before_images >= 1, f"Precondition: expected >= 1 image, got {before_images}"

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    after_doc = fitz.open(res["output_pdf"])
    after_images = len(after_doc[0].get_images())
    after_doc.close()
    # Remediation must not drop ALL images; at least the input count
    # should survive (pipeline copies the PDF, doesn't strip images)
    assert after_images >= before_images, \
        f"Images lost: before={before_images}, after={after_images}"
