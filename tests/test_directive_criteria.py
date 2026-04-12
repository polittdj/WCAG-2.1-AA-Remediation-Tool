"""Strict completion-criteria tests matching the directive acceptance checklist.

Every assertion in this file maps directly to a checkbox in the
"COMPLETION CRITERIA" section of the audit directive. These tests
fail hard if any of the 6+1 critical fixes regresses.

Each test processes a real audit PDF through the full pipeline,
opens the resulting output with pikepdf, and inspects actual
PDF structure — not just the HTML report, which was the thing
that was lying in the original audit.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import zipfile
from typing import Any

import pikepdf
import pytest

from app import process_files_core
from pipeline import run_pipeline

AUDIT_DIR = pathlib.Path(__file__).parent / "audit_pdfs"


def _run(name: str) -> tuple[dict, pathlib.Path, pathlib.Path]:
    src = AUDIT_DIR / name
    assert src.exists(), f"Missing audit PDF: {src}"
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="criteria_"))
    result = run_pipeline(str(src), str(out_dir))
    out_pdfs = list(out_dir.glob("*.pdf"))
    assert out_pdfs, f"Pipeline produced no output for {name}"
    return result, out_dir, out_pdfs[0]


def _count_tags(pdf: pikepdf.Pdf) -> dict[str, int]:
    counts: dict[str, int] = {}
    if "/StructTreeRoot" not in pdf.Root:
        return counts
    stack: list[Any] = [pdf.Root["/StructTreeRoot"].get("/K")]
    seen: set[tuple[int, int]] = set()
    while stack:
        n = stack.pop()
        if n is None:
            continue
        if isinstance(n, pikepdf.Array):
            for x in n:
                stack.append(x)
            continue
        if not isinstance(n, pikepdf.Dictionary):
            continue
        og = getattr(n, "objgen", None)
        if og is not None:
            if og in seen:
                continue
            seen.add(og)
        s = n.get("/S")
        if s is not None:
            tag = str(s).lstrip("/")
            counts[tag] = counts.get(tag, 0) + 1
        k = n.get("/K")
        if k is not None:
            stack.append(k)
    return counts


# ---------------------------------------------------------------------------
# CHECKBOX 1: 01_untagged output has >= 15 structure elements
# ---------------------------------------------------------------------------


def test_checkbox_01_untagged_has_15_plus_structs():
    """01_untagged_no_metadata.pdf must produce >= 15 struct elements."""
    result, out_dir, out_pdf = _run("01_untagged_no_metadata.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            counts = _count_tags(pdf)
        total = sum(counts.values())
        assert total >= 15, f"Expected >=15 struct elements, got {total}: {counts}"
        # Must include /P tags (body paragraphs) — not just headings
        assert counts.get("P", 0) >= 3, f"No /P tags: {counts}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 2: 04_tables output has /Table /TR /TH /TD tags
# ---------------------------------------------------------------------------


def test_checkbox_04_tables_has_table_tags():
    """04_table_no_headers.pdf must produce /Table, /TR, /TH, /TD."""
    result, out_dir, out_pdf = _run("04_table_no_headers.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            counts = _count_tags(pdf)
        required = ("Table", "TR", "TH", "TD")
        for tag in required:
            assert counts.get(tag, 0) >= 1, f"Missing /{tag}: {counts}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 3: 09_lists output has /L /LI /Lbl /LBody tags
# ---------------------------------------------------------------------------


def test_checkbox_09_lists_has_list_tags():
    """09_fake_lists_no_structure.pdf must produce /L, /LI, /Lbl, /LBody."""
    result, out_dir, out_pdf = _run("09_fake_lists_no_structure.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            counts = _count_tags(pdf)
        for tag in ("L", "LI", "Lbl", "LBody"):
            assert counts.get(tag, 0) >= 1, f"Missing /{tag}: {counts}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 4: 03_images output has /Figure tags with /Alt
# ---------------------------------------------------------------------------


def test_checkbox_03_images_has_figure_with_alt():
    """03_images_no_alt_text.pdf must produce /Figure tags with /Alt."""
    result, out_dir, out_pdf = _run("03_images_no_alt_text.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            # Walk struct tree and inspect each /Figure element's /Alt
            fig_count = 0
            fig_with_alt = 0
            stack: list[Any] = [pdf.Root["/StructTreeRoot"].get("/K")]
            seen: set[tuple[int, int]] = set()
            while stack:
                n = stack.pop()
                if n is None:
                    continue
                if isinstance(n, pikepdf.Array):
                    for x in n:
                        stack.append(x)
                    continue
                if not isinstance(n, pikepdf.Dictionary):
                    continue
                og = getattr(n, "objgen", None)
                if og is not None:
                    if og in seen:
                        continue
                    seen.add(og)
                s = n.get("/S")
                if s is not None and str(s).lstrip("/") == "Figure":
                    fig_count += 1
                    alt = n.get("/Alt")
                    if alt is not None and str(alt).strip():
                        fig_with_alt += 1
                k = n.get("/K")
                if k is not None:
                    stack.append(k)
        assert fig_count >= 1, f"No /Figure elements found"
        assert fig_with_alt == fig_count, \
            f"Only {fig_with_alt}/{fig_count} /Figure elements have /Alt"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 5: ALL pages in ALL output PDFs have /Tabs = /S
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("audit_pdf_name", [
    "01_untagged_no_metadata.pdf",
    "02_form_no_tooltips.pdf",
    "03_images_no_alt_text.pdf",
    "04_table_no_headers.pdf",
    "05_bad_contrast.pdf",
    "06_bad_heading_hierarchy.pdf",
    "08_lang.pdf",
    "09_fake_lists_no_structure.pdf",
    "10_security.pdf",
])
def test_checkbox_all_pages_have_tabs_s(audit_pdf_name):
    """Every page of every output PDF must have /Tabs /S (PDF/UA-1)."""
    result, out_dir, out_pdf = _run(audit_pdf_name)
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            for i, page in enumerate(pdf.pages):
                tabs = page.get("/Tabs")
                assert tabs is not None, f"{audit_pdf_name} page {i} has no /Tabs"
                assert str(tabs) == "/S", \
                    f"{audit_pdf_name} page {i} has /Tabs={tabs}, expected /S"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 6: 04_tables title is NOT "(anonymous)"
# ---------------------------------------------------------------------------


def test_checkbox_04_tables_title_not_anonymous():
    """04_table_no_headers output title must not be '(anonymous)'."""
    result, out_dir, out_pdf = _run("04_table_no_headers.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            title = str(pdf.docinfo.get("/Title", "")).strip()
        assert title, f"Title is empty"
        assert "anonymous" not in title.lower(), f"Title contains 'anonymous': {title!r}"
        # Expect the largest-text heading "Quarterly Sales Report"
        assert "Quarterly" in title or "Sales" in title, \
            f"Unexpected title: {title!r}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 7: 02_forms /TU contains descriptive text (not "field1")
# ---------------------------------------------------------------------------


def test_checkbox_02_forms_tu_descriptive():
    """02_form_no_tooltips output /TU must contain descriptive visible labels."""
    result, out_dir, out_pdf = _run("02_form_no_tooltips.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            tu_values: list[str] = []
            for page in pdf.pages:
                annots = page.get("/Annots")
                if not annots:
                    continue
                for annot in list(annots):
                    if str(annot.get("/Subtype", "")) != "/Widget":
                        continue
                    tu = annot.get("/TU")
                    if tu is not None:
                        tu_values.append(str(tu))
        assert tu_values, "No widgets with /TU found"
        descriptive_words = {"First", "Last", "Email", "Department", "Hire", "Manager", "Name"}
        matches = sum(1 for v in tu_values if any(w in v for w in descriptive_words))
        assert matches >= 3, \
            f"Only {matches} /TU values contain descriptive words: {tu_values}"
        # None should be raw 'field1' etc.
        for v in tu_values:
            assert not v.startswith("field"), f"/TU is raw field name: {v}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# CHECKBOX 8: 06_headings multi-H1 detection + output has single H1
# ---------------------------------------------------------------------------


def test_checkbox_06_headings_single_h1_after_remediation():
    """06_bad_heading_hierarchy output must have exactly one H1 (tool fixed)."""
    result, out_dir, out_pdf = _run("06_bad_heading_hierarchy.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            counts = _count_tags(pdf)
        h1 = counts.get("H1", 0)
        assert h1 == 1, f"Expected exactly 1 H1, got {h1}: {counts}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


def test_checkbox_06_multi_h1_detected_as_fail(tmp_path):
    """A PDF with two H1s in its struct tree must fail C-20."""
    from wcag_auditor import audit_pdf

    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    pdf.Root["/Lang"] = pikepdf.String("en")

    h1a = pdf.make_indirect(pikepdf.Dictionary({"/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H1")}))
    h1b = pdf.make_indirect(pikepdf.Dictionary({"/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H1")}))
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([h1a, h1b]),
    }))
    pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()}))
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc]),
        "/ParentTree": pt,
    }))
    pdf.Root["/StructTreeRoot"] = sr
    path = tmp_path / "multi_h1.pdf"
    pdf.save(str(path))

    result = audit_pdf(str(path))
    c20 = next(c for c in result["checkpoints"] if c["id"] == "C-20")
    assert c20["status"] == "FAIL", f"Expected C-20 FAIL, got {c20}"
    assert "Multiple H1" in c20["detail"]


# ---------------------------------------------------------------------------
# CHECKBOX 9: No checkpoint reports N/A when that content type exists
# ---------------------------------------------------------------------------


def test_checkbox_09_no_na_on_applicable_content_tables():
    """04_tables must not report N/A on table checks (content has tables)."""
    from wcag_auditor import audit_pdf
    result = audit_pdf(str(AUDIT_DIR / "04_table_no_headers.pdf"))
    checks = {c["id"]: c for c in result["checkpoints"]}
    for cid in ("C-24", "C-25", "C-26", "C-27"):
        status = checks[cid]["status"]
        assert status != "NOT_APPLICABLE", \
            f"{cid} is N/A but tables exist: {checks[cid]}"
        assert status == "FAIL", f"{cid} should be FAIL (no tags yet): {status}"


def test_checkbox_09_no_na_on_applicable_content_lists():
    """09_lists must not report N/A on list checks (content has lists)."""
    from wcag_auditor import audit_pdf
    result = audit_pdf(str(AUDIT_DIR / "09_fake_lists_no_structure.pdf"))
    checks = {c["id"]: c for c in result["checkpoints"]}
    for cid in ("C-28", "C-29", "C-30"):
        status = checks[cid]["status"]
        assert status != "NOT_APPLICABLE", \
            f"{cid} is N/A but lists exist: {checks[cid]}"
        assert status == "FAIL", f"{cid} should be FAIL: {status}"


def test_checkbox_09_no_na_on_applicable_content_images():
    """03_images must not report N/A on image checks (content has images)."""
    from wcag_auditor import audit_pdf
    result = audit_pdf(str(AUDIT_DIR / "03_images_no_alt_text.pdf"))
    checks = {c["id"]: c for c in result["checkpoints"]}
    for cid in ("C-31", "C-32", "C-33"):
        status = checks[cid]["status"]
        assert status != "NOT_APPLICABLE", \
            f"{cid} is N/A but images exist: {checks[cid]}"


# ---------------------------------------------------------------------------
# CHECKBOX 10: ZIP output is flat
# ---------------------------------------------------------------------------


def test_checkbox_zip_output_is_flat(tmp_path):
    """Combined ZIP must be flat — no nested .zip, no subdirectories."""
    pdfs = []
    for name in ["a.pdf", "b.pdf", "c.pdf"]:
        p = tmp_path / name
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(str(p))
        pdfs.append(str(p))

    rows, combined_zip, errs = process_files_core(pdfs)
    assert combined_zip, f"No combined ZIP: {errs}"
    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
        assert names, "ZIP is empty"
        for name in names:
            assert not name.lower().endswith(".zip"), f"Nested ZIP: {name}"
            assert "/" not in name, f"Subdirectory: {name}"
            assert name.lower().endswith((".pdf", ".html", ".htm")), \
                f"Unexpected file type: {name}"


# ---------------------------------------------------------------------------
# CHECKBOX 11: titles rejected for sentences and agenda items
# ---------------------------------------------------------------------------


def test_checkbox_title_rejects_sentence_first_block():
    """08_lang has a body sentence as first text — title must not use it."""
    result, out_dir, out_pdf = _run("08_lang.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            title = str(pdf.docinfo.get("/Title", "")).strip()
        assert title, "Title is empty"
        # The sentence starts with "The partnership agreement was signed..."
        assert "partnership agreement was signed" not in title.lower(), \
            f"Title is a body sentence: {title!r}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)


def test_checkbox_title_rejects_agenda_item_first_block():
    """10_security has '1. Call to Order...' as first text — title must reject it."""
    result, out_dir, out_pdf = _run("10_security.pdf")
    try:
        with pikepdf.open(str(out_pdf)) as pdf:
            title = str(pdf.docinfo.get("/Title", "")).strip()
        assert title, "Title is empty"
        assert "Call to Order" not in title, \
            f"Title is an agenda item: {title!r}"
        assert not title.startswith("1."), \
            f"Title starts with numbered-list prefix: {title!r}"
    finally:
        shutil.rmtree(str(out_dir), ignore_errors=True)
