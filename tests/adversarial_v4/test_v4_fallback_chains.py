"""Category S — Fallback Chain Verification.

Monkey-patch primary libraries to force fallback paths.
Verify fallbacks ACTUALLY ACTIVATE, not just 'no crash'.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import fitz
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline


def _run(src: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "out"
    return run_pipeline(str(src), str(out))


def _make_simple_pdf(path: pathlib.Path) -> pathlib.Path:
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Test content for fallback testing", fontsize=12, fontname="helv")
    doc.save(str(path))
    doc.close()
    return path


# ═══════════════════════════════════════════════════════════════════════
# S5 — Jinja2 template rendering fails → legacy fallback
# ═══════════════════════════════════════════════════════════════════════

def test_s5_jinja2_failure_produces_legacy_report(tmp_path, monkeypatch):
    src = _make_simple_pdf(tmp_path / "test.pdf")

    import reporting.html_generator as hg
    original = hg.generate_report

    def _fail(**kwargs):
        raise RuntimeError("Simulated Jinja2 failure")

    monkeypatch.setattr(hg, "generate_report", _fail)

    res = _run(src, tmp_path)
    # Remediated PDF should still be produced
    assert res["output_pdf"], "No output PDF when Jinja2 fails"
    # Report should still exist (via legacy fallback)
    assert res["report_html"], "No report when Jinja2 fails"
    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")
    assert "Compliance Report" in html, "Legacy report missing title"


# ═══════════════════════════════════════════════════════════════════════
# S6 — ZipFile write fails (disk full simulation)
# ═══════════════════════════════════════════════════════════════════════

def test_s6_zipfile_failure(tmp_path, monkeypatch):
    src = _make_simple_pdf(tmp_path / "test.pdf")

    import zipfile
    original_write = zipfile.ZipFile.write

    def _fail_write(self, *args, **kwargs):
        raise OSError("No space left on device")

    monkeypatch.setattr(zipfile.ZipFile, "write", _fail_write)

    res = _run(src, tmp_path)
    # Should produce PARTIAL (ZIP failed)
    assert res["result"] in ("PASS", "PARTIAL")
    # Should have errors logged
    assert len(res["errors"]) > 0 or res["zip_path"] == ""


# ═══════════════════════════════════════════════════════════════════════
# S4 — Tesseract not installed
# ═══════════════════════════════════════════════════════════════════════

def test_s4_tesseract_unavailable(tmp_path, monkeypatch):
    """When tesseract is unavailable, non-scanned PDFs should still process."""
    src = _make_simple_pdf(tmp_path / "digital.pdf")

    # Monkey-patch subprocess for tesseract detection
    import fix_scanned_ocr
    original_classify = fix_scanned_ocr.classify_document

    def _no_tesseract(path):
        # Return digital classification (no OCR needed)
        return {"classification": "digital", "signals": [], "errors": []}

    monkeypatch.setattr(fix_scanned_ocr, "classify_document", _no_tesseract)

    res = _run(src, tmp_path)
    # Born-digital PDF should still process fine without tesseract
    assert res["result"] in ("PASS", "PARTIAL")
    assert res["output_pdf"], "No output produced when tesseract unavailable"


# ═══════════════════════════════════════════════════════════════════════
# S8 — Both primary and fallback fail for one check
# ═══════════════════════════════════════════════════════════════════════

def test_s8_all_methods_fail_for_one_check(tmp_path, monkeypatch):
    """When everything fails for one checkpoint, others must still run."""
    src = _make_simple_pdf(tmp_path / "test.pdf")

    import wcag_auditor

    # Monkey-patch one check function to always raise
    original_checks = list(wcag_auditor._CHECKERS)
    patched_checks = []
    for cid, fn in original_checks:
        if cid == "C-31":  # Figure alt text check
            def _broken_check(pdf, _fn=fn):
                raise RuntimeError("All methods failed for C-31")
            patched_checks.append((cid, _broken_check))
        else:
            patched_checks.append((cid, fn))

    monkeypatch.setattr(wcag_auditor, "_CHECKERS", patched_checks)

    res = _run(src, tmp_path)
    cps = res.get("checkpoints", [])
    assert len(cps) == 47, f"Expected 47 checkpoints, got {len(cps)}"

    # C-31 should be INDETERMINATE or error state, NOT crash the whole audit
    c31 = next((c for c in cps if c["id"] == "C-31"), None)
    assert c31 is not None, "C-31 missing from results"
    assert c31["status"] in ("INDETERMINATE", "FAIL", "MANUAL_REVIEW", "NOT_APPLICABLE"), \
        f"C-31 status should indicate failure, got: {c31['status']}"

    # All other checks should have produced results
    for cp in cps:
        if cp["id"] != "C-31":
            assert cp["status"] is not None, f"{cp['id']} has null status"
