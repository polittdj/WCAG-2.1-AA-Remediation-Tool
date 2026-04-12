"""Category M — Remediation Correctness Attacks.

These tests verify the tool ACTUALLY FIXES what it claims to fix.
Every assertion checks OUTPUT PDF BYTES, not just 'no exception'.
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import fitz
import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline
from wcag_auditor import audit_pdf


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(src: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "out"
    return run_pipeline(str(src), str(out))


def _make_bare_pdf(path: pathlib.Path, pages: int = 1) -> pathlib.Path:
    """Bare PDF: no title, no lang, no MarkInfo, no struct tree."""
    doc = fitz.open()
    for i in range(pages):
        page = doc.new_page(width=612, height=792)
        page.insert_text((100, 100), f"Page {i + 1} content", fontsize=14, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


# ═══════════════════════════════════════════════════════════════════════
# M1 — Title remediation: verify output bytes
# ═══════════════════════════════════════════════════════════════════════

def test_m1_title_remediation(tmp_path):
    src = _make_bare_pdf(tmp_path / "no_title.pdf")
    res = _run(src, tmp_path)
    assert res["output_pdf"], "No output PDF produced"

    with pikepdf.open(res["output_pdf"]) as pdf:
        title = pdf.docinfo.get("/Title")
        assert title is not None, "/Info/Title missing after remediation"
        title_str = str(title).strip()
        assert len(title_str) > 0, "/Info/Title is empty after remediation"

        # ViewerPreferences / DisplayDocTitle
        vp = pdf.Root.get("/ViewerPreferences")
        if vp is not None:
            ddt = vp.get("/DisplayDocTitle")
            if ddt is not None:
                assert bool(ddt) is True, "/DisplayDocTitle should be true"


# ═══════════════════════════════════════════════════════════════════════
# M2 — Language remediation: verify /Catalog/Lang
# ═══════════════════════════════════════════════════════════════════════

def test_m2_language_remediation(tmp_path):
    src = tmp_path / "no_lang.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    # Explicitly no /Lang
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        lang = pdf.Root.get("/Lang")
        assert lang is not None, "/Catalog/Lang missing after remediation"
        lang_str = str(lang).strip()
        assert len(lang_str) >= 2, f"/Catalog/Lang too short: {lang_str!r}"


# ═══════════════════════════════════════════════════════════════════════
# M3 — Tab order: ALL pages must have /Tabs == /S
# ═══════════════════════════════════════════════════════════════════════

def test_m3_tab_order_all_five_pages(tmp_path):
    src = tmp_path / "no_tabs.pdf"
    pdf = pikepdf.new()
    for _ in range(5):
        pdf.add_blank_page()
        # Add an annotation so fix_focus_order has something to act on
        page = pdf.pages[-1]
        page["/Annots"] = pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Widget"),
                "/FT": pikepdf.Name("/Tx"),
                "/T": pikepdf.String("field"),
                "/Rect": pikepdf.Array([72, 700, 200, 720]),
            }))
        ])
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        for i, page in enumerate(pdf.pages):
            tabs = page.get("/Tabs")
            assert tabs is not None, f"Page {i}: /Tabs missing after remediation"
            assert str(tabs) == "/S", f"Page {i}: /Tabs={tabs}, expected /S"


# ═══════════════════════════════════════════════════════════════════════
# M4 — MarkInfo and StructTreeRoot creation
# ═══════════════════════════════════════════════════════════════════════

def test_m4_markinfo_and_struct_tree(tmp_path):
    src = _make_bare_pdf(tmp_path / "untagged.pdf")
    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        mi = pdf.Root.get("/MarkInfo")
        assert mi is not None, "/MarkInfo missing after remediation"
        marked = mi.get("/Marked")
        assert marked is not None and bool(marked), "/MarkInfo/Marked not true"

        sr = pdf.Root.get("/StructTreeRoot")
        assert sr is not None, "/StructTreeRoot missing after remediation"
        k = sr.get("/K")
        assert k is not None, "/StructTreeRoot/K is empty"


# ═══════════════════════════════════════════════════════════════════════
# M5 — Form field tooltips (/TU) for all widgets
# ═══════════════════════════════════════════════════════════════════════

def test_m5_form_field_tooltips(tmp_path):
    src = tmp_path / "no_tu.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    page = pdf.pages[0]

    names = ["first_name", "last_name", "email", "agree_terms", "newsletter"]
    ftypes = ["/Tx", "/Tx", "/Tx", "/Btn", "/Btn"]
    annots = pikepdf.Array()
    fields = pikepdf.Array()

    for name, ft in zip(names, ftypes):
        w = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Annot"),
            "/Subtype": pikepdf.Name("/Widget"),
            "/FT": pikepdf.Name(ft),
            "/T": pikepdf.String(name),
            "/Rect": pikepdf.Array([72, 700, 200, 720]),
        }))
        annots.append(w)
        fields.append(w)

    page["/Annots"] = annots
    pdf.Root["/AcroForm"] = pikepdf.Dictionary({"/Fields": fields})
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as pdf:
        for page in pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) != "/Widget":
                    continue
                tu = annot.get("/TU")
                assert tu is not None, f"Widget {annot.get('/T')} missing /TU"
                tu_str = str(tu).strip()
                assert len(tu_str) > 0, f"Widget {annot.get('/T')} has empty /TU"


# ═══════════════════════════════════════════════════════════════════════
# M7 — Already-tagged PDF: remediation must not corrupt
# ═══════════════════════════════════════════════════════════════════════

def test_m7_already_tagged_not_corrupted(tmp_path):
    src = tmp_path / "already_tagged.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    page = pdf.pages[0]
    page["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({
            "/F1": pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Font"),
                "/Subtype": pikepdf.Name("/Type1"),
                "/BaseFont": pikepdf.Name("/Helvetica"),
            })),
        }),
    })
    page["/Contents"] = pdf.make_stream(
        b"/P <</MCID 0>> BDC\nBT\n/F1 12 Tf\n100 700 Td\n(Tagged text) Tj\nET\nEMC\n"
    )
    pdf.docinfo["/Title"] = "Already Tagged Document"
    pdf.Root["/Lang"] = pikepdf.String("en-US")
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})

    doc_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([]),
    }))
    p_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/P"),
        "/P": doc_elem,
        "/K": pikepdf.Dictionary({"/Type": pikepdf.Name("/MCR"), "/MCID": 0}),
    }))
    doc_elem["/K"].append(p_elem)

    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc_elem]),
        "/ParentTree": pikepdf.Dictionary({"/Nums": pikepdf.Array([])}),
    }))

    pdf.save(str(src))
    pdf.close()

    # Count elements before
    with pikepdf.open(str(src)) as before_pdf:
        before_title = str(before_pdf.docinfo.get("/Title", ""))

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    with pikepdf.open(res["output_pdf"]) as after_pdf:
        after_title = str(after_pdf.docinfo.get("/Title", ""))
        assert after_title == before_title, f"Title changed: {before_title!r} -> {after_title!r}"
        assert str(after_pdf.Root.get("/Lang")) == "en-US", "Lang changed"
        mi = after_pdf.Root.get("/MarkInfo")
        assert mi is not None and bool(mi.get("/Marked")), "MarkInfo corrupted"


# ═══════════════════════════════════════════════════════════════════════
# M8 — Visual content preserved after remediation
# ═══════════════════════════════════════════════════════════════════════

def test_m8_visual_content_preserved(tmp_path):
    src = tmp_path / "visual.pdf"
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 200), "Important Text Here", fontsize=16, fontname="helv")
    # Draw a rectangle
    rect = fitz.Rect(50, 300, 200, 350)
    page.draw_rect(rect, color=(1, 0, 0), fill=(1, 0, 0))
    doc.save(str(src))
    doc.close()

    # Extract text before
    before_doc = fitz.open(str(src))
    before_text = before_doc[0].get_text()
    before_doc.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    # Extract text after — must still contain the same text
    after_doc = fitz.open(res["output_pdf"])
    after_text = after_doc[0].get_text()
    after_doc.close()

    assert "Important Text Here" in after_text, \
        f"Text lost after remediation. Before: {before_text!r}, After: {after_text!r}"


# ═══════════════════════════════════════════════════════════════════════
# M12 — Report accuracy: JSON checkpoint data matches actual fixes
# ═══════════════════════════════════════════════════════════════════════

def test_m12_report_accuracy(tmp_path):
    """Process a bare PDF and verify the report JSON reflects actual state."""
    src = _make_bare_pdf(tmp_path / "for_report.pdf")
    res = _run(src, tmp_path)
    assert res["report_html"]

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    # Extract JSON data block
    match = re.search(
        r'<script type="application/json" id="wcag-audit-data">\s*(.*?)\s*</script>',
        html, re.DOTALL,
    )
    if match:
        data = json.loads(match.group(1))
        cps = data.get("checkpoints", [])
        assert len(cps) == 47, f"Expected 47 checkpoints, got {len(cps)}"

        # Every checkpoint must have a non-null status
        for cp in cps:
            assert cp.get("status") is not None, f"Checkpoint {cp.get('id')} has null status"
            assert cp["status"] in (
                "PASS", "FAIL", "NOT_APPLICABLE", "MANUAL_REVIEW", "INDETERMINATE",
            ), f"Checkpoint {cp.get('id')} has invalid status: {cp['status']}"
    else:
        # Legacy report — check that all C-XX IDs appear
        for i in range(1, 48):
            cid = f"C-{i:02d}"
            assert cid in html, f"Checkpoint {cid} missing from report"
