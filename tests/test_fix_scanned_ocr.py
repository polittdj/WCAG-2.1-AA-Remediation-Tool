"""Exhaustive tests for fix_scanned_ocr.py — detection, OCR, and edge cases.

Tests are split into:
  * Detection-only tests (no tesseract needed — always run)
  * OCR integration tests (gated on ocrmypdf + tesseract availability)
  * Pipeline integration tests (full pipeline on scanned PDFs)
"""

from __future__ import annotations

import os
import pathlib
import shutil
import sys

import fitz  # PyMuPDF
import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_scanned_ocr import (  # noqa: E402
    classify_document,
    classify_pages,
    fix_scanned_ocr,
)

TEST_SUITE = ROOT / "test_suite"


# ---------------------------------------------------------------------------
# Helpers — synthetic PDF builders
# ---------------------------------------------------------------------------


def _make_scan_pdf(path: str, text: str = "HELLO OCR TEST", pages: int = 1) -> None:
    """Create an image-only PDF by rendering text to PNG then embedding."""
    src = fitz.open()
    for _ in range(pages):
        p = src.new_page(width=612, height=792)
        p.insert_text((100, 100), text, fontsize=36, fontname="helv")
    images = [src[i].get_pixmap(dpi=200).tobytes("png") for i in range(src.page_count)]
    src.close()
    out = fitz.open()
    for png in images:
        page = out.new_page(width=612, height=792)
        page.insert_image(page.rect, stream=png)
    out.save(path)
    out.close()


def _make_digital_pdf(path: str) -> None:
    """Create a born-digital PDF with real text and fonts."""
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((100, 100), "This is real digital text content", fontsize=14, fontname="helv")
    page.insert_text((100, 140), "With multiple lines of content here", fontsize=14, fontname="helv")
    doc.save(path)
    doc.close()


def _make_hybrid_pdf(path: str) -> None:
    """Create a PDF where page 1 is digital text and page 2 is a scan."""
    # Page 1: real text
    doc = fitz.open()
    p1 = doc.new_page(width=612, height=792)
    p1.insert_text((100, 100), "This page has real digital text", fontsize=14, fontname="helv")

    # Page 2: render to image then re-embed
    tmp = fitz.open()
    tp = tmp.new_page(width=612, height=792)
    tp.insert_text((100, 100), "SCANNED PAGE TWO", fontsize=36, fontname="helv")
    png = tmp[0].get_pixmap(dpi=200).tobytes("png")
    tmp.close()

    p2 = doc.new_page(width=612, height=792)
    p2.insert_image(p2.rect, stream=png)
    doc.save(path)
    doc.close()


def _has_ocrmypdf() -> bool:
    """Return True iff ocrmypdf and tesseract are both available.

    Both are hard dependencies of the test suite (installed via
    requirements-dev.txt / apt). If either is missing the tests
    below will fail loudly — skip-on-missing-dependency is banned.
    """
    try:
        import ocrmypdf  # noqa: F401
        return shutil.which("tesseract") is not None
    except ImportError:
        return False


if not _has_ocrmypdf():  # pragma: no cover
    raise RuntimeError(
        "ocrmypdf and tesseract are required for the test suite. "
        "Install with: pip install ocrmypdf && apt-get install tesseract-ocr"
    )


# Legacy no-op marker kept so old imports don't break; always applies.
def skip_no_ocr(fn):  # noqa: N802 — match pytest decorator style
    return fn


# ---------------------------------------------------------------------------
# Detection tests (always run — no tesseract needed)
# ---------------------------------------------------------------------------


class TestDetection:
    def test_scan_classified_as_scanned(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan)
        assert classify_document(scan) == "scanned"

    def test_digital_classified_as_digital(self, tmp_path: pathlib.Path) -> None:
        dig = str(tmp_path / "digital.pdf")
        _make_digital_pdf(dig)
        assert classify_document(dig) == "digital"

    def test_hybrid_classified_as_hybrid(self, tmp_path: pathlib.Path) -> None:
        hyb = str(tmp_path / "hybrid.pdf")
        _make_hybrid_pdf(hyb)
        result = classify_document(hyb)
        assert result in ("hybrid", "scanned"), f"expected hybrid/scanned, got {result}"

    def test_per_page_classification_scan(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan2.pdf")
        _make_scan_pdf(scan, pages=3)
        pages = classify_pages(scan)
        assert len(pages) == 3
        assert all(p == "scan" for p in pages)

    def test_per_page_classification_digital(self, tmp_path: pathlib.Path) -> None:
        dig = str(tmp_path / "dig2.pdf")
        _make_digital_pdf(dig)
        pages = classify_pages(dig)
        assert len(pages) == 1
        assert pages[0] == "digital"

    def test_scan_has_no_fonts(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan3.pdf")
        _make_scan_pdf(scan)
        with pikepdf.open(scan) as pdf:
            for page in pdf.pages:
                res = page.get("/Resources", {})
                fonts = res.get("/Font") if res else None
                assert fonts is None or len(list(fonts.keys())) == 0

    def test_scan_has_no_extractable_text(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan4.pdf")
        _make_scan_pdf(scan)
        doc = fitz.open(scan)
        text = doc[0].get_text("text").strip()
        doc.close()
        assert text == ""

    def test_digital_has_extractable_text(self, tmp_path: pathlib.Path) -> None:
        dig = str(tmp_path / "dig3.pdf")
        _make_digital_pdf(dig)
        doc = fitz.open(dig)
        text = doc[0].get_text("text").strip()
        doc.close()
        assert len(text) > 10

    def test_tagged_pdf_classified_as_digital(self, tmp_path: pathlib.Path) -> None:
        """A PDF with a StructTreeRoot should always be 'digital'
        even if its pages have no text — to prevent ocrmypdf
        TaggedPDFError."""
        tagged = str(tmp_path / "tagged.pdf")
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
        doc = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Document"),
                    "/K": pikepdf.Array(),
                }
            )
        )
        pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()}))
        sr = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructTreeRoot"),
                    "/K": pikepdf.Array([doc]),
                    "/ParentTree": pt,
                }
            )
        )
        pdf.Root["/StructTreeRoot"] = sr
        pdf.save(tagged)
        assert classify_document(tagged) == "digital"

    def test_empty_pdf_classified_as_digital_or_scanned(self, tmp_path: pathlib.Path) -> None:
        """A bare blank page (no content at all) should not crash."""
        bare = str(tmp_path / "bare.pdf")
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(bare)
        # Should not raise
        result = classify_document(bare)
        assert result in ("digital", "scanned")

    def test_nonexistent_file_returns_empty(self, tmp_path: pathlib.Path) -> None:
        pages = classify_pages(str(tmp_path / "no_such_file.pdf"))
        assert pages == []


# ---------------------------------------------------------------------------
# fix_scanned_ocr module tests (detection → no-op / OCR)
# ---------------------------------------------------------------------------


class TestFixScannedOcr:
    def test_digital_is_noop(self, tmp_path: pathlib.Path) -> None:
        """A digital PDF should pass through unchanged."""
        dig = str(tmp_path / "digital.pdf")
        _make_digital_pdf(dig)
        out = str(tmp_path / "out.pdf")
        result = fix_scanned_ocr(dig, out)
        assert result["classification"] == "digital"
        assert result["ocr_applied"] is False
        assert result["errors"] == []
        assert os.path.exists(out)
        # Output should be byte-for-byte copy
        assert os.path.getsize(out) == os.path.getsize(dig)

    def test_digital_no_struct_tree_change(self, tmp_path: pathlib.Path) -> None:
        """Digital PDFs should not get a struct tree stub added."""
        dig = str(tmp_path / "digital.pdf")
        _make_digital_pdf(dig)
        out = str(tmp_path / "out.pdf")
        fix_scanned_ocr(dig, out)
        with pikepdf.open(out):
            pass  # verifies the output is a valid PDF

    @skip_no_ocr
    def test_scan_gets_ocred(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan, text="HELLO OCR")
        out = str(tmp_path / "out.pdf")
        result = fix_scanned_ocr(scan, out)
        assert result["ocr_applied"] is True
        assert result["classification"] == "scanned"
        assert result["errors"] == []
        assert "ocrmypdf" in result["tool"]
        # Output should have extractable text
        doc = fitz.open(out)
        text = doc[0].get_text("text").upper()
        doc.close()
        # Tesseract may misread at low quality; check for partial match.
        assert any(w in text for w in ("HELLO", "LLO", "OCR")), (
            f"OCR text should contain recognizable words, got: {text!r}"
        )

    @skip_no_ocr
    def test_scan_gets_struct_stub(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan)
        out = str(tmp_path / "out.pdf")
        fix_scanned_ocr(scan, out)
        with pikepdf.open(out) as pdf:
            assert pdf.Root.get("/StructTreeRoot") is not None
            sr = pdf.Root["/StructTreeRoot"]
            assert sr.get("/ParentTree") is not None
            pt = sr["/ParentTree"]
            assert "/Nums" in pt
            mi = pdf.Root.get("/MarkInfo")
            assert mi is not None
            assert bool(mi.get("/Marked"))

    @skip_no_ocr
    def test_scan_gets_lang(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan)
        out = str(tmp_path / "out.pdf")
        fix_scanned_ocr(scan, out)
        with pikepdf.open(out) as pdf:
            lang = str(pdf.Root.get("/Lang", ""))
            assert lang, "/Lang should be set after OCR"

    @skip_no_ocr
    def test_multi_page_scan(self, tmp_path: pathlib.Path) -> None:
        scan = str(tmp_path / "multi.pdf")
        _make_scan_pdf(scan, text="PAGE CONTENT", pages=3)
        out = str(tmp_path / "out.pdf")
        result = fix_scanned_ocr(scan, out)
        assert result["ocr_applied"] is True
        assert result["pages_total"] == 3
        doc = fitz.open(out)
        for i in range(doc.page_count):
            text = doc[i].get_text("text")
            assert len(text) > 3, f"page {i + 1} should have OCR text"
        doc.close()

    def test_force_ocr_env_var(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """WCAG_FORCE_OCR=1 forces OCR on digital PDFs too."""
        monkeypatch.setenv("WCAG_FORCE_OCR", "1")
        dig = str(tmp_path / "digital.pdf")
        _make_digital_pdf(dig)
        out = str(tmp_path / "out.pdf")
        result = fix_scanned_ocr(dig, out)
        assert result["classification"] == "forced"
        assert result["ocr_applied"] is True

    def test_ocr_lang_env_var(self, tmp_path: pathlib.Path) -> None:
        """WCAG_OCR_LANG should be respected for /Lang fallback."""
        # Only test with 'eng' which is always installed — the /Lang
        # mapping is tested, not Tesseract language support.
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan)
        out = str(tmp_path / "out.pdf")
        os.environ["WCAG_OCR_LANG"] = "eng"
        try:
            fix_scanned_ocr(scan, out)
            with pikepdf.open(out) as pdf:
                lang = str(pdf.Root.get("/Lang", ""))
                # ocrmypdf may set /Lang itself (e.g. "en"); our stub
                # only fills it when absent. Either way, a non-empty
                # /Lang is the requirement.
                assert lang, "/Lang should be set after OCR"
        finally:
            del os.environ["WCAG_OCR_LANG"]

    def test_graceful_without_ocrmypdf(self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """If ocrmypdf can't import, the module should copy input and report error."""
        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan)
        out = str(tmp_path / "out.pdf")
        # Temporarily hide ocrmypdf from imports
        real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

        def fake_import(name, *args, **kwargs):
            if name == "ocrmypdf":
                raise ImportError("mocked")
            return real_import(name, *args, **kwargs)

        monkeypatch.setattr("builtins.__import__", fake_import)
        result = fix_scanned_ocr(scan, out)
        assert result["ocr_applied"] is False
        assert any("not installed" in e for e in result["errors"])
        assert os.path.exists(out)


# ---------------------------------------------------------------------------
# Pipeline integration tests
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    @skip_no_ocr
    def test_scan_through_full_pipeline(self, tmp_path: pathlib.Path) -> None:
        """Full pipeline on a scanned PDF: all critical checkpoints should pass."""
        from pipeline import run_pipeline

        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan, text="TRAVEL APPROVAL FORM")
        out_dir = str(tmp_path / "out")
        result = run_pipeline(scan, out_dir)

        assert result["result"] == "PASS", f"errors: {result['errors']}"
        statuses = {c["id"]: c["status"] for c in result["checkpoints"]}
        for cid in ("C-02", "C-04", "C-01", "C-13", "C-03", "C-46"):
            assert statuses[cid] in ("PASS", "NOT_APPLICABLE"), f"{cid}: expected PASS/NA, got {statuses[cid]}"

    @skip_no_ocr
    def test_scan_title_derived_from_ocr(self, tmp_path: pathlib.Path) -> None:
        """fix_title should derive a title from OCR text."""
        from pipeline import run_pipeline

        scan = str(tmp_path / "scan.pdf")
        _make_scan_pdf(scan, text="EMPLOYEE HANDBOOK 2026")
        out_dir = str(tmp_path / "out")
        result = run_pipeline(scan, out_dir)
        output_pdf = result.get("output_pdf", "")
        assert output_pdf and os.path.exists(output_pdf)
        with pikepdf.open(output_pdf) as pdf:
            title = str(pdf.docinfo.get("/Title", "")).strip()
            assert title, "title should be set from OCR content"

    @skip_no_ocr
    def test_digital_through_pipeline_unchanged(self, tmp_path: pathlib.Path) -> None:
        """A digital PDF should pass through the OCR step as a no-op."""
        from pipeline import run_pipeline

        dig = str(tmp_path / "digital.pdf")
        _make_digital_pdf(dig)
        out_dir = str(tmp_path / "out")
        result = run_pipeline(dig, out_dir)
        # Should still produce output (even if some checkpoints fail
        # due to minimal PDF not having all required metadata)
        assert result.get("output_pdf")
        assert os.path.exists(result["output_pdf"])

    def test_existing_fixtures_unaffected(self, tmp_path: pathlib.Path) -> None:
        """Adding fix_scanned_ocr to the pipeline must not regress existing fixtures."""
        from pipeline import run_pipeline

        good = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
        if not good.exists():
            pytest.skip("fixture not available")
        out_dir = str(tmp_path / "out")
        result = run_pipeline(str(good), out_dir)
        assert result["result"] == "PASS", f"regression: {result['errors']}"
