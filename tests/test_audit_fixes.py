"""Integration tests for the 6 critical audit issues.

These tests use realistic audit PDFs with actual paragraphs, tables,
lists, and images to verify that the pipeline:

  ISSUE 1: Creates proper /P, /Table, /L, /Figure tags (not just H1/H2)
  ISSUE 2: Reports FAIL (not N/A) when content exists but isn't tagged
  ISSUE 3: Sets /Tabs=/S on EVERY page (not just pages with annotations)
  ISSUE 4: Picks meaningful titles (not sentences or agenda items)
  ISSUE 5: Uses visible labels for form field tooltips (not /T names)
  ISSUE 6: Detects multiple H1 and skipped heading levels as FAIL
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile

import pikepdf
import pytest

from pipeline import run_pipeline
from wcag_auditor import audit_pdf

AUDIT_DIR = pathlib.Path(__file__).parent / "audit_pdfs"


def _run_pipeline_on(name: str) -> tuple[dict, pathlib.Path, pathlib.Path]:
    """Run pipeline on an audit PDF. Returns (result, out_dir, output_pdf)."""
    src = AUDIT_DIR / name
    assert src.exists(), f"Audit PDF missing: {src}"
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="audit_"))
    result = run_pipeline(str(src), str(out_dir))
    out_pdfs = list(out_dir.glob("*.pdf"))
    assert out_pdfs, f"Pipeline produced no output PDF for {name}"
    return result, out_dir, out_pdfs[0]


def _count_tags(pdf: pikepdf.Pdf) -> dict[str, int]:
    """Count struct elements by tag name."""
    counts: dict[str, int] = {}
    if "/StructTreeRoot" not in pdf.Root:
        return counts
    stack = [pdf.Root["/StructTreeRoot"].get("/K")]
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


def _status_for(result: dict, cid: str) -> str:
    for c in result.get("checkpoints", []):
        if c["id"] == cid:
            return c["status"]
    return "MISSING"


# ---------------------------------------------------------------------------
# ISSUE 1: Tag creation is not just headings
# ---------------------------------------------------------------------------


class TestIssue1TagCreation:
    """Verify the pipeline creates /P, /Table, /L, /Figure — not only headings."""

    def test_untagged_doc_gets_paragraph_tags(self):
        """3-page doc with dozens of paragraphs should get >10 struct elements."""
        result, out_dir, out_pdf = _run_pipeline_on("01_untagged_no_metadata.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            total = sum(counts.values())
            # Before the fix, this was 4 elements (Document + H1 + H2 + H2).
            # After the fix, should be >10 (paragraphs + headings).
            assert total > 10, f"Expected >10 struct elements, got {total}: {counts}"
            # Specifically, /P elements should exist.
            assert counts.get("P", 0) >= 3, f"Expected /P elements: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_table_doc_gets_table_tags(self):
        """Tables must get /Table, /TR, /TH, /TD elements."""
        result, out_dir, out_pdf = _run_pipeline_on("04_table_no_headers.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            assert counts.get("Table", 0) >= 1, f"No /Table: {counts}"
            assert counts.get("TR", 0) >= 2, f"No /TR rows: {counts}"
            # /TH for header row
            assert counts.get("TH", 0) >= 1, f"No /TH: {counts}"
            # /TD for data cells
            assert counts.get("TD", 0) >= 1, f"No /TD: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_image_doc_gets_figure_tags(self):
        """Images must get /Figure elements."""
        result, out_dir, out_pdf = _run_pipeline_on("03_images_no_alt_text.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # Source PDF has 3 image draws (reportlab dedupes to 1 XObject
            # but we count uses via Do operators)
            assert counts.get("Figure", 0) >= 3, f"Expected 3 /Figures: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_list_doc_gets_list_tags(self):
        """Lists must get /L > /LI > /Lbl + /LBody elements."""
        result, out_dir, out_pdf = _run_pipeline_on("09_fake_lists_no_structure.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # 1 bullet list + 1 numbered list = 2 /L
            assert counts.get("L", 0) >= 2, f"Expected >=2 /L: {counts}"
            # 5 + 5 items
            assert counts.get("LI", 0) >= 10, f"Expected >=10 /LI: {counts}"
            assert counts.get("Lbl", 0) >= 10, f"Expected >=10 /Lbl: {counts}"
            assert counts.get("LBody", 0) >= 10, f"Expected >=10 /LBody: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# ISSUE 2: Auditor detects content, not just tags
# ---------------------------------------------------------------------------


class TestIssue2ContentDetection:
    """Verify the auditor reports FAIL (not N/A) when content exists without tags.

    These tests use audit_pdf() directly on the source PDFs (before the
    pipeline runs) to test the auditor's content-detection logic in
    isolation.
    """

    def test_tables_content_detected(self):
        """04_table_no_headers has visible tables — should be FAIL, not N/A."""
        result = audit_pdf(str(AUDIT_DIR / "04_table_no_headers.pdf"))
        checks = {c["id"]: c for c in result["checkpoints"]}
        for cid in ("C-24", "C-25", "C-27"):
            status = checks[cid]["status"]
            assert status != "NOT_APPLICABLE", \
                f"{cid} should not be N/A when tables exist: {status}"
            assert status == "FAIL", f"{cid} expected FAIL, got {status}"

    def test_lists_content_detected(self):
        """09_fake_lists has bullets and numbered lists — should be FAIL, not N/A."""
        result = audit_pdf(str(AUDIT_DIR / "09_fake_lists_no_structure.pdf"))
        checks = {c["id"]: c for c in result["checkpoints"]}
        for cid in ("C-28", "C-29", "C-30"):
            status = checks[cid]["status"]
            assert status != "NOT_APPLICABLE", \
                f"{cid} should not be N/A when lists exist: {status}"
            assert status == "FAIL", f"{cid} expected FAIL, got {status}"

    def test_images_content_detected(self):
        """03_images has actual image XObjects — should be FAIL, not N/A."""
        result = audit_pdf(str(AUDIT_DIR / "03_images_no_alt_text.pdf"))
        checks = {c["id"]: c for c in result["checkpoints"]}
        for cid in ("C-31", "C-33"):
            status = checks[cid]["status"]
            assert status != "NOT_APPLICABLE", \
                f"{cid} should not be N/A when images exist: {status}"
            assert status == "FAIL", f"{cid} expected FAIL, got {status}"


# ---------------------------------------------------------------------------
# ISSUE 3: /Tabs=/S on every page
# ---------------------------------------------------------------------------


class TestIssue3TabOrder:
    """Verify /Tabs=/S is set on every page of every PDF."""

    @pytest.mark.parametrize("name", [
        "01_untagged_no_metadata.pdf",
        "02_form_no_tooltips.pdf",
        "03_images_no_alt_text.pdf",
        "04_table_no_headers.pdf",
        "06_bad_heading_hierarchy.pdf",
        "09_fake_lists_no_structure.pdf",
    ])
    def test_all_pages_have_tabs_s(self, name):
        result, out_dir, out_pdf = _run_pipeline_on(name)
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                for i, page in enumerate(pdf.pages):
                    tabs = page.get("/Tabs")
                    assert str(tabs) == "/S", \
                        f"{name} page {i} missing /Tabs /S (got {tabs!r})"
            assert _status_for(result, "C-10") == "PASS"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# ISSUE 4: Document titles are meaningful
# ---------------------------------------------------------------------------


class TestIssue4Titles:
    """Verify title derivation rejects sentences and agenda items."""

    def test_table_doc_gets_meaningful_title(self):
        """04_table_no_headers — title should be 'Quarterly Sales Report' (the H1)."""
        result, out_dir, out_pdf = _run_pipeline_on("04_table_no_headers.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                title = str(pdf.docinfo.get("/Title", ""))
            assert title, "Title should not be empty"
            # Must not be '(anonymous)'
            assert "anonymous" not in title.lower()
            # Expect "Quarterly Sales Report" or filename-derived
            assert "Quarterly" in title or "Sales" in title or "Table" in title, \
                f"Unexpected title: {title!r}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_title_not_sentence_heuristic(self):
        """The sentence detector should filter body text."""
        from fix_title import _looks_like_sentence
        assert _looks_like_sentence("The partnership agreement was signed in Berlin.") is True
        assert _looks_like_sentence("Quarterly Sales Report") is False
        assert _looks_like_sentence("Employee Information Form") is False

    def test_title_not_agenda_heuristic(self):
        """The agenda detector should filter numbered agenda items."""
        from fix_title import _looks_like_agenda_item
        assert _looks_like_agenda_item("1. Call to Order — Meeting called to order") is True
        assert _looks_like_agenda_item("1. Introduction") is False  # short, no em-dash
        assert _looks_like_agenda_item("Company Annual Report") is False

    def test_anonymous_title_blacklisted(self):
        """'(anonymous)' should never be used as a title."""
        from fix_title import _is_blacklisted
        assert _is_blacklisted("(anonymous)") is True
        assert _is_blacklisted("anonymous") is True


# ---------------------------------------------------------------------------
# ISSUE 5: Form field tooltips use visible labels
# ---------------------------------------------------------------------------


class TestIssue5FormTooltips:
    """Verify form field /TU uses visible nearby text, not /T field names."""

    def test_form_tooltips_use_visible_labels(self):
        """02_form_no_tooltips has visible labels like 'First Name:' next to
        fields named 'field1'/'field2'. /TU should be the visible labels."""
        result, out_dir, out_pdf = _run_pipeline_on("02_form_no_tooltips.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                tooltips: list[str] = []
                for page in pdf.pages:
                    annots = page.get("/Annots")
                    if not annots:
                        continue
                    for annot in list(annots):
                        if str(annot.get("/Subtype", "")) != "/Widget":
                            continue
                        tu = annot.get("/TU")
                        if tu is not None:
                            tooltips.append(str(tu))
            # Expected visible labels on the form
            expected_words = {"First", "Last", "Email", "Department", "Hire", "Manager"}
            joined = " ".join(tooltips)
            found = sum(1 for w in expected_words if w in joined)
            assert found >= 4, \
                f"Expected >=4 visible-label tooltips, got {found}: {tooltips}"
            # Make sure NONE of them are just 'field1', 'field2', etc.
            for tu in tooltips:
                assert not tu.startswith("field"), \
                    f"Tooltip '{tu}' is a raw field name"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# ISSUE 6: Heading hierarchy detection
# ---------------------------------------------------------------------------


class TestIssue6HeadingHierarchy:
    """Verify multiple H1 and skipped levels are detected by C-20."""

    def test_multiple_h1_detected_as_fail(self, tmp_path):
        """A PDF with two H1 elements must fail C-20."""
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
        pdf.Root["/Lang"] = pikepdf.String("en")

        h1a = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H1"),
        }))
        h1b = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H1"),
        }))
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

        path = tmp_path / "two_h1.pdf"
        pdf.save(str(path))

        result = audit_pdf(str(path))
        c20 = next(c for c in result["checkpoints"] if c["id"] == "C-20")
        assert c20["status"] == "FAIL", f"Expected FAIL, got {c20}"
        assert "Multiple H1" in c20["detail"]

    def test_skipped_levels_detected_as_fail(self, tmp_path):
        """H1 followed by H3 (skipped H2) must fail C-20."""
        pdf = pikepdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
        pdf.Root["/Lang"] = pikepdf.String("en")

        h1 = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H1"),
        }))
        h3 = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"), "/S": pikepdf.Name("/H3"),
        }))
        doc = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"),
            "/S": pikepdf.Name("/Document"),
            "/K": pikepdf.Array([h1, h3]),
        }))
        pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()}))
        sr = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructTreeRoot"),
            "/K": pikepdf.Array([doc]),
            "/ParentTree": pt,
        }))
        pdf.Root["/StructTreeRoot"] = sr

        path = tmp_path / "skipped.pdf"
        pdf.save(str(path))

        result = audit_pdf(str(path))
        c20 = next(c for c in result["checkpoints"] if c["id"] == "C-20")
        assert c20["status"] == "FAIL", f"Expected FAIL, got {c20}"
        assert "skipped" in c20["detail"].lower()

    def test_bad_heading_pdf_produces_single_h1(self):
        """06_bad_heading_hierarchy should be fixed to have exactly one H1."""
        result, out_dir, out_pdf = _run_pipeline_on("06_bad_heading_hierarchy.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # Even though the source had two 22pt headings, the fix
            # demotes the second to H2 to ensure a single H1.
            h1_count = counts.get("H1", 0)
            assert h1_count == 1, f"Expected exactly 1 H1, got {h1_count}: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)
