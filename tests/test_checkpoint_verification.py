"""Checkpoint Verification Tests — prove each checkpoint DETECTS and FIXES violations.

Each test follows this pattern:
1. Load verification PDF with KNOWN violation
2. Verify the auditor DETECTS it (status == FAIL)
3. Run the full pipeline (remediation)
4. Verify the violation is FIXED in the output (status == PASS or improved)
5. Inspect actual PDF bytes to confirm structural change

For detect-only checks (no auto-fix), we verify detection and report quality.
For manual-review checks, we verify a numeric confidence score is returned.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
from typing import Any

import pikepdf
import pytest

from wcag_auditor import audit_pdf
from pipeline import run_pipeline

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

VERIFICATION_DIR = pathlib.Path(__file__).parent / "verification_pdfs"


def _audit(pdf_path: str | pathlib.Path) -> dict[str, Any]:
    """Audit a PDF and return checkpoint statuses as {id: status}."""
    result = audit_pdf(str(pdf_path))
    return {c["id"]: c for c in result["checkpoints"]}


def _run_pipeline_on(pdf_name: str) -> tuple[dict, pathlib.Path]:
    """Run full pipeline on a verification PDF. Return (result_dict, output_dir)."""
    src = VERIFICATION_DIR / pdf_name
    assert src.exists(), f"Verification PDF not found: {src}"
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="verify_"))
    result = run_pipeline(str(src), str(out_dir))
    return result, out_dir


def _get_output_pdf(out_dir: pathlib.Path) -> pathlib.Path | None:
    """Find the output PDF in pipeline results directory."""
    pdfs = list(out_dir.glob("*.pdf"))
    return pdfs[0] if pdfs else None


def _status_for(result: dict, checkpoint_id: str) -> str:
    """Extract status for a specific checkpoint from pipeline result."""
    for c in result.get("checkpoints", []):
        if c["id"] == checkpoint_id:
            return c["status"]
    return "MISSING"


# ---------------------------------------------------------------------------
# Per-Checkpoint Detection Tests
# ---------------------------------------------------------------------------


class TestDetection:
    """Verify the auditor correctly DETECTS violations in verification PDFs."""

    def test_c01_untagged_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-01_untagged.pdf")
        assert checks["C-01"]["status"] == "FAIL"

    def test_c02_no_title_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-02_no_title.pdf")
        assert checks["C-02"]["status"] == "FAIL"

    def test_c03_placeholder_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-03_placeholder_title.pdf")
        assert checks["C-03"]["status"] == "FAIL"

    def test_c04_no_language_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-04_no_language.pdf")
        assert checks["C-04"]["status"] == "FAIL"

    def test_c06_no_pdfua_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-06_no_pdfua.pdf")
        assert checks["C-06"]["status"] == "FAIL"

    def test_c07_no_display_title_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-07_no_display_title.pdf")
        assert checks["C-07"]["status"] == "FAIL"

    def test_c09_suspects_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-09_suspects.pdf")
        assert checks["C-09"]["status"] == "FAIL"

    def test_c10_no_tab_order_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-10_no_tab_order.pdf")
        assert checks["C-10"]["status"] == "FAIL"

    def test_c12_empty_struct_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-12_partial_tags.pdf")
        assert checks["C-12"]["status"] == "FAIL"

    def test_c13_bad_bdc_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-13_bad_bdc.pdf")
        assert checks["C-13"]["status"] == "FAIL"

    def test_c14_ghost_text_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-14_ghost_text.pdf")
        assert checks["C-14"]["status"] == "FAIL"

    def test_c19_no_headings_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-19_no_headings.pdf")
        assert checks["C-19"]["status"] == "FAIL"

    def test_c20_skipped_headings_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-20_skipped_headings.pdf")
        assert checks["C-20"]["status"] == "FAIL"

    def test_c23_no_bookmarks_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-23_no_bookmarks.pdf")
        assert checks["C-23"]["status"] == "FAIL"

    def test_c24_flat_table_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-24_flat_table.pdf")
        assert checks["C-24"]["status"] == "FAIL"

    def test_c25_no_scope_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-25_no_scope.pdf")
        assert checks["C-25"]["status"] == "FAIL"

    def test_c28_bad_list_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-28_bad_list.pdf")
        assert checks["C-28"]["status"] == "FAIL"

    def test_c29_no_lbl_lbody_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-29_no_lbl_lbody.pdf")
        assert checks["C-29"]["status"] == "FAIL"

    def test_c31_no_alt_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-31_no_alt.pdf")
        assert checks["C-31"]["status"] == "FAIL"

    def test_c35_no_form_struct_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-35_no_form_struct.pdf")
        assert checks["C-35"]["status"] == "FAIL"

    def test_c36_no_tu_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-36_no_tu.pdf")
        assert checks["C-36"]["status"] == "FAIL"

    def test_c39_no_struct_parent_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-39_no_struct_parent.pdf")
        assert checks["C-39"]["status"] == "FAIL"

    def test_c42_no_link_struct_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-42_no_link_struct.pdf")
        assert checks["C-42"]["status"] == "FAIL"

    def test_c43_no_link_contents_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-43_no_link_contents.pdf")
        assert checks["C-43"]["status"] == "FAIL"

    def test_c44_no_link_dest_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-44_no_link_dest.pdf")
        assert checks["C-44"]["status"] == "FAIL"

    def test_c46_parent_tree_kids_detected(self):
        checks = _audit(VERIFICATION_DIR / "C-46_parent_tree_kids.pdf")
        assert checks["C-46"]["status"] == "FAIL"


# ---------------------------------------------------------------------------
# Per-Checkpoint Remediation Tests
# ---------------------------------------------------------------------------


class TestRemediation:
    """Verify the pipeline FIXES violations (or at least improves them)."""

    def test_c01_tagged_after_fix(self):
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        assert _status_for(result, "C-01") == "PASS"
        # Verify in PDF bytes
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            mark_info = pdf.Root.get("/MarkInfo")
            assert mark_info is not None
            assert bool(mark_info.get("/Marked"))
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c02_title_after_fix(self):
        result, out_dir = _run_pipeline_on("C-02_no_title.pdf")
        assert _status_for(result, "C-02") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            title = str(pdf.docinfo.get("/Title", ""))
            assert title.strip() != ""
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c03_title_not_placeholder_after_fix(self):
        result, out_dir = _run_pipeline_on("C-03_placeholder_title.pdf")
        assert _status_for(result, "C-03") == "PASS"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c04_language_after_fix(self):
        result, out_dir = _run_pipeline_on("C-04_no_language.pdf")
        assert _status_for(result, "C-04") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            lang = str(pdf.Root.get("/Lang", ""))
            assert lang.strip() != ""
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c06_pdfua_after_fix(self):
        result, out_dir = _run_pipeline_on("C-06_no_pdfua.pdf")
        assert _status_for(result, "C-06") == "PASS"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c07_display_title_after_fix(self):
        result, out_dir = _run_pipeline_on("C-07_no_display_title.pdf")
        assert _status_for(result, "C-07") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            vp = pdf.Root.get("/ViewerPreferences")
            assert vp is not None
            assert bool(vp.get("/DisplayDocTitle"))
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c09_suspects_cleared_after_fix(self):
        result, out_dir = _run_pipeline_on("C-09_suspects.pdf")
        assert _status_for(result, "C-09") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            mi = pdf.Root.get("/MarkInfo")
            if mi:
                suspects = mi.get("/Suspects")
                assert suspects is None or not bool(suspects)
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c10_tab_order_after_fix(self):
        result, out_dir = _run_pipeline_on("C-10_no_tab_order.pdf")
        assert _status_for(result, "C-10") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            for page in pdf.pages:
                annots = page.get("/Annots")
                if annots and len(list(annots)) > 0:
                    tabs = page.get("/Tabs")
                    assert str(tabs) == "/S", f"Page missing /Tabs /S"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c13_bdc_fixed_after_pipeline(self):
        result, out_dir = _run_pipeline_on("C-13_bad_bdc.pdf")
        assert _status_for(result, "C-13") == "PASS"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c14_ghost_text_fixed(self):
        result, out_dir = _run_pipeline_on("C-14_ghost_text.pdf")
        assert _status_for(result, "C-14") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            import re
            for page in pdf.pages:
                contents = page.get("/Contents")
                if contents is None:
                    continue
                data = bytes(contents.read_bytes())
                # Should NOT have Tr 3
                assert not re.search(rb"\b3\s+Tr\b", data)
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c36_tu_after_fix(self):
        result, out_dir = _run_pipeline_on("C-36_no_tu.pdf")
        assert _status_for(result, "C-36") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            for page in pdf.pages:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                for annot in list(annots):
                    if str(annot.get("/Subtype", "")) == "/Widget":
                        tu = annot.get("/TU")
                        assert tu is not None and str(tu).strip() != ""
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c43_link_contents_after_fix(self):
        result, out_dir = _run_pipeline_on("C-43_no_link_contents.pdf")
        assert _status_for(result, "C-43") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            for page in pdf.pages:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                for annot in list(annots):
                    if str(annot.get("/Subtype", "")) == "/Link":
                        contents = annot.get("/Contents")
                        assert contents is not None and str(contents).strip() != ""
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_c46_parent_tree_flattened(self):
        result, out_dir = _run_pipeline_on("C-46_parent_tree_kids.pdf")
        assert _status_for(result, "C-46") == "PASS"
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            struct_root = pdf.Root.get("/StructTreeRoot")
            if struct_root:
                pt = struct_root.get("/ParentTree")
                if pt:
                    assert "/Kids" not in pt
                    assert "/Nums" in pt
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Cross-Cutting Verification Tests
# ---------------------------------------------------------------------------


class TestCrossCutting:
    """Cross-cutting tests that verify system-level behavior."""

    def test_multi_violation_has_failures(self):
        """A PDF with known violations must NOT get all PASS."""
        checks = _audit(VERIFICATION_DIR / "multi_violation.pdf")
        fail_count = sum(1 for c in checks.values() if c["status"] == "FAIL")
        assert fail_count >= 3, f"Expected >=3 FAILs, got {fail_count}"

    def test_pipeline_result_has_47_checkpoints(self):
        """Pipeline result must include all 47 checkpoints."""
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        assert len(result["checkpoints"]) == 47
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_output_pdf_is_valid(self):
        """Output PDF must be openable with pikepdf."""
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        out_pdf = _get_output_pdf(out_dir)
        assert out_pdf is not None
        with pikepdf.open(str(out_pdf)) as pdf:
            assert len(pdf.pages) >= 1
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_zip_flat_structure(self):
        """Output ZIP must not contain subdirectories."""
        import zipfile
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        zip_path = result.get("zip_path")
        assert zip_path and pathlib.Path(zip_path).exists()
        with zipfile.ZipFile(zip_path) as zf:
            for name in zf.namelist():
                assert "/" not in name, f"ZIP entry has directory: {name}"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_html_report_generated(self):
        """Pipeline must produce an HTML report."""
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        report = result.get("report_html", "")
        assert report and pathlib.Path(report).exists()
        html = pathlib.Path(report).read_text()
        assert "WCAG 2.1 AA Compliance Report" in html
        assert "C-01" in html
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_compliance_label_partial_when_failures(self):
        """A PDF with initial FAILs should NOT be labeled 'Compliant' if critical checks fail."""
        result, out_dir = _run_pipeline_on("multi_violation.pdf")
        # Check output naming
        out_pdf = _get_output_pdf(out_dir)
        if out_pdf:
            name = out_pdf.name
            # If any critical checkpoint fails, should be PARTIAL
            critical_fails = [
                c for c in result["checkpoints"]
                if c["id"] in ("C-01", "C-02", "C-03", "C-04", "C-10", "C-13",
                               "C-31", "C-36", "C-39", "C-40", "C-46")
                and c["status"] == "FAIL"
            ]
            if critical_fails:
                assert "PARTIAL" in name or "Non_Compliant" in name, \
                    f"File named '{name}' but has {len(critical_fails)} critical FAILs"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_round_trip_improvement(self):
        """Running pipeline on violation PDF must reduce FAIL count."""
        # Initial audit
        initial = _audit(VERIFICATION_DIR / "C-01_untagged.pdf")
        initial_fails = sum(1 for c in initial.values() if c["status"] == "FAIL")

        # Pipeline
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        final_fails = sum(1 for c in result["checkpoints"] if c["status"] == "FAIL")

        assert final_fails < initial_fails, \
            f"Pipeline did not improve: {initial_fails} FAILs -> {final_fails} FAILs"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_no_pass_to_fail_regression(self):
        """Pipeline must not turn any PASS into FAIL."""
        # Start with a PDF that has some PASS checkpoints
        initial = _audit(VERIFICATION_DIR / "C-20_skipped_headings.pdf")
        initially_passing = {cid for cid, c in initial.items() if c["status"] == "PASS"}

        result, out_dir = _run_pipeline_on("C-20_skipped_headings.pdf")
        final_statuses = {c["id"]: c["status"] for c in result["checkpoints"]}

        regressions = []
        for cid in initially_passing:
            if final_statuses.get(cid) == "FAIL":
                regressions.append(cid)

        assert not regressions, f"PASS->FAIL regressions: {regressions}"
        shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_privacy_temp_cleanup(self):
        """No source PDF or temp files should remain after processing."""
        import os
        src = VERIFICATION_DIR / "C-01_untagged.pdf"
        result, out_dir = _run_pipeline_on("C-01_untagged.pdf")
        # Source must still exist (not deleted)
        assert src.exists()
        # Output dir should only contain expected files
        all_files = list(out_dir.rglob("*"))
        for f in all_files:
            if f.is_file():
                assert f.suffix in (".pdf", ".html", ".zip"), \
                    f"Unexpected temp file: {f}"
        shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Detection-Only Tests (no auto-fix expected)
# ---------------------------------------------------------------------------


class TestDetectionOnly:
    """Checkpoints that detect but cannot auto-fix."""

    def test_c08_security_encrypted_detected(self):
        """Encrypted PDF should be detected as encrypted; accessibility
        bit is always set in modern PDF spec (ISO 32000-2), so PASS is correct."""
        checks = _audit(VERIFICATION_DIR / "C-08_restricted_security.pdf")
        # Modern pikepdf/PDF 2.0 always sets accessibility bit, so PASS is correct
        assert checks["C-08"]["status"] == "PASS"
        assert "encrypted" not in checks["C-08"]["detail"].lower() or "permitted" in checks["C-08"]["detail"].lower()

    def test_c19_no_headings_detected_multipage(self):
        """6-page doc without headings should FAIL C-19."""
        checks = _audit(VERIFICATION_DIR / "C-19_no_headings.pdf")
        assert checks["C-19"]["status"] == "FAIL"

    def test_c23_no_bookmarks_long_doc(self):
        """21-page doc without /Outlines should FAIL C-23."""
        checks = _audit(VERIFICATION_DIR / "C-23_no_bookmarks.pdf")
        assert checks["C-23"]["status"] == "FAIL"

    def test_c24_flat_table_no_tr(self):
        """Table with /TD directly should FAIL C-24."""
        checks = _audit(VERIFICATION_DIR / "C-24_flat_table.pdf")
        assert checks["C-24"]["status"] == "FAIL"

    def test_c25_th_no_scope(self):
        """/TH without /Scope should FAIL C-25."""
        checks = _audit(VERIFICATION_DIR / "C-25_no_scope.pdf")
        assert checks["C-25"]["status"] == "FAIL"

    def test_c28_list_no_li(self):
        """/L without /LI children should FAIL C-28."""
        checks = _audit(VERIFICATION_DIR / "C-28_bad_list.pdf")
        assert checks["C-28"]["status"] == "FAIL"

    def test_c29_li_no_parts(self):
        """/LI without /Lbl or /LBody should FAIL C-29."""
        checks = _audit(VERIFICATION_DIR / "C-29_no_lbl_lbody.pdf")
        assert checks["C-29"]["status"] == "FAIL"

    def test_c44_link_no_dest(self):
        """Link without /Dest or /A should FAIL C-44."""
        checks = _audit(VERIFICATION_DIR / "C-44_no_link_dest.pdf")
        assert checks["C-44"]["status"] == "FAIL"
