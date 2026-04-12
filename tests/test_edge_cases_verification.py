"""Edge case tests for checkpoint verification hardening.

Tests adversarial and unusual PDF structures to ensure the pipeline
handles them gracefully without crashing or producing corrupt output.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile

import pikepdf
import pytest
from pikepdf import Array, Dictionary, Name, String, Pdf

from wcag_auditor import audit_pdf
from pipeline import run_pipeline

# Check if the pipeline's OCR step works. The pyo3 panic from the
# cryptography module can crash the entire process, so we test cautiously
# using a subprocess to avoid polluting the test process.
import subprocess, sys

def _check_pipeline_ocr():
    """Check if the pipeline can run without crashing from OCR import."""
    try:
        result = subprocess.run(
            [sys.executable, "-c", "import ocrmypdf"],
            capture_output=True, timeout=5
        )
        return result.returncode == 0
    except Exception:
        return False


HAS_PIPELINE_OCR = _check_pipeline_ocr()

needs_ocrmypdf = pytest.mark.skipif(
    not HAS_PIPELINE_OCR,
    reason="ocrmypdf unavailable (cryptography module issue in this environment)"
)


def _run(pdf_path: str) -> tuple[dict, pathlib.Path]:
    out = pathlib.Path(tempfile.mkdtemp(prefix="edge_"))
    result = run_pipeline(pdf_path, str(out))
    return result, out


# ---------------------------------------------------------------------------
# Edge Case 1: Zero-page PDF
# ---------------------------------------------------------------------------


class TestZeroPagePdf:
    """A PDF with zero pages should not crash the pipeline."""

    def test_zero_pages_no_crash(self, tmp_path):
        pdf = Pdf.new()
        # Don't add any pages
        path = tmp_path / "zero_pages.pdf"
        pdf.save(str(path))
        result, out = _run(str(path))
        # Should not crash; result may be ERROR or PARTIAL
        assert result["result"] in ("PARTIAL", "ERROR", "PASS")
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 2: Large number of form fields
# ---------------------------------------------------------------------------


class TestManyWidgets:
    """PDF with 50+ form fields should complete without timeout."""

    @needs_ocrmypdf
    def test_50_widgets(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        annots = []
        for i in range(50):
            w = pdf.make_indirect(Dictionary({
                "/Type": Name("/Annot"),
                "/Subtype": Name("/Widget"),
                "/Rect": Array([50, 700 - i * 12, 200, 712 - i * 12]),
                "/T": String(f"field_{i:03d}"),
                "/FT": Name("/Tx"),
            }))
            annots.append(w)
        page["/Annots"] = Array(annots)
        path = tmp_path / "many_widgets.pdf"
        pdf.save(str(path))
        result, out = _run(str(path))
        # All widgets should get /TU
        for c in result["checkpoints"]:
            if c["id"] == "C-36":
                assert c["status"] == "PASS", f"C-36 should PASS with 50 widgets: {c['detail']}"
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 3: Deeply nested struct tree (50 levels)
# ---------------------------------------------------------------------------


class TestDeeplyNested:
    """Pipeline should handle deeply nested structures without stack overflow."""

    def test_deep_nesting(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
        pdf.Root["/Lang"] = String("en-US")
        pdf.docinfo["/Title"] = String("Deep Nested Doc")

        # Create 50-level deep structure
        leaf = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/P"),
        }))
        current = leaf
        for i in range(49):
            parent = pdf.make_indirect(Dictionary({
                "/Type": Name("/StructElem"),
                "/S": Name("/Div"),
                "/K": Array([current]),
            }))
            current = parent

        parent_tree = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
        struct_root = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructTreeRoot"),
            "/K": Array([current]),
            "/ParentTree": parent_tree,
        }))
        pdf.Root["/StructTreeRoot"] = struct_root

        path = tmp_path / "deep_nested.pdf"
        pdf.save(str(path))

        # Should not crash
        result = audit_pdf(str(path))
        statuses = {c["id"]: c["status"] for c in result["checkpoints"]}
        assert statuses["C-01"] == "PASS"
        assert statuses["C-12"] == "PASS"


# ---------------------------------------------------------------------------
# Edge Case 4: PDF with only images (no text — OCR path)
# ---------------------------------------------------------------------------


class TestImageOnlyPdf:
    """PDF with an image XObject but no text operators."""

    @needs_ocrmypdf
    def test_image_only_no_crash(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        # Add a tiny 1x1 image
        img_data = b"\x89PNG\r\n\x1a\n" + b"\x00" * 50  # fake data
        # Actually just use raw content with image draw operator
        page["/Resources"] = Dictionary({
            "/Font": Dictionary({"/F1": pdf.make_indirect(Dictionary({
                "/Type": Name("/Font"), "/Subtype": Name("/Type1"),
                "/BaseFont": Name("/Helvetica"),
            }))}),
        })
        # No text content at all
        content = pdf.make_stream(b"q 100 0 0 100 72 600 cm /Im1 Do Q")
        page["/Contents"] = content

        path = tmp_path / "image_only.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        assert result["result"] in ("PASS", "PARTIAL")
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 5: All text same font size (heading detection edge case)
# ---------------------------------------------------------------------------


class TestUniformFontSize:
    """When all text is same size, heading detection should still work."""

    def test_uniform_text(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        page["/Resources"] = Dictionary({
            "/Font": Dictionary({"/F1": pdf.make_indirect(Dictionary({
                "/Type": Name("/Font"), "/Subtype": Name("/Type1"),
                "/BaseFont": Name("/Helvetica"),
            }))}),
        })
        # All 12pt text
        content = b"BT /F1 12 Tf 72 700 Td (Same size heading) Tj ET\n"
        content += b"BT /F1 12 Tf 72 680 Td (Same size body text) Tj ET\n"
        content += b"BT /F1 12 Tf 72 660 Td (More body text here) Tj ET\n"
        stream = pdf.make_stream(content)
        page["/Contents"] = stream

        path = tmp_path / "uniform_font.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        # Should complete without crash
        assert result["result"] in ("PASS", "PARTIAL")
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 6: Circular reference in struct tree
# ---------------------------------------------------------------------------


class TestCircularReference:
    """Pipeline should not infinite loop on circular struct tree."""

    def test_circular_struct(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
        pdf.Root["/Lang"] = String("en-US")
        pdf.docinfo["/Title"] = String("Circular Doc")

        # Create two nodes that reference each other
        node_a = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/Div"),
        }))
        node_b = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/P"),
            "/K": Array([node_a]),
        }))
        # Create circular reference
        node_a["/K"] = Array([node_b])

        parent_tree = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
        struct_root = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructTreeRoot"),
            "/K": Array([node_a]),
            "/ParentTree": parent_tree,
        }))
        pdf.Root["/StructTreeRoot"] = struct_root

        path = tmp_path / "circular.pdf"
        pdf.save(str(path))

        # Should not infinite loop (auditor has cycle detection)
        result = audit_pdf(str(path))
        assert len(result["checkpoints"]) == 47


# ---------------------------------------------------------------------------
# Edge Case 7: Empty content streams
# ---------------------------------------------------------------------------


class TestEmptyContentStream:
    """Pages with empty or missing content streams."""

    @needs_ocrmypdf
    def test_empty_content(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        # Page with empty content
        page = pdf.pages[0]
        stream = pdf.make_stream(b"")
        page["/Contents"] = stream

        path = tmp_path / "empty_content.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        assert result["result"] in ("PASS", "PARTIAL")
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 8: Very long text in single paragraph
# ---------------------------------------------------------------------------


class TestLongText:
    """PDF with a very long text string (5000+ chars)."""

    def test_long_paragraph(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[0]
        page["/Resources"] = Dictionary({
            "/Font": Dictionary({"/F1": pdf.make_indirect(Dictionary({
                "/Type": Name("/Font"), "/Subtype": Name("/Type1"),
                "/BaseFont": Name("/Helvetica"),
            }))}),
        })
        long_text = "A" * 5000
        content = f"BT /F1 10 Tf 72 700 Td ({long_text}) Tj ET".encode()
        stream = pdf.make_stream(content)
        page["/Contents"] = stream

        path = tmp_path / "long_text.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        assert result["result"] in ("PASS", "PARTIAL")
        assert len(result["checkpoints"]) == 47
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 9: Multiple pages with different orientations
# ---------------------------------------------------------------------------


class TestMixedOrientation:
    """Portrait + landscape pages in same document."""

    @needs_ocrmypdf
    def test_mixed_pages(self, tmp_path):
        pdf = Pdf.new()
        # Portrait page
        pdf.add_blank_page(page_size=(612, 792))
        # Landscape page
        pdf.add_blank_page(page_size=(792, 612))
        # Square page
        pdf.add_blank_page(page_size=(500, 500))

        path = tmp_path / "mixed_orient.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        assert result["result"] in ("PASS", "PARTIAL")
        shutil.rmtree(str(out), ignore_errors=True)


# ---------------------------------------------------------------------------
# Edge Case 10: Special characters in PDF metadata
# ---------------------------------------------------------------------------


class TestSpecialCharsMetadata:
    """PDF with special chars in title and metadata."""

    def test_unicode_title(self, tmp_path):
        pdf = Pdf.new()
        pdf.add_blank_page(page_size=(612, 792))
        pdf.docinfo["/Title"] = String("Rapport d'activite 2026 — Resultats & Perspectives")
        pdf.docinfo["/Author"] = String("Jean-Pierre Dupont")
        pdf.Root["/Lang"] = String("fr-FR")
        pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})

        parent_tree = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
        struct_root = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructTreeRoot"),
            "/K": Array([]),
            "/ParentTree": parent_tree,
        }))
        pdf.Root["/StructTreeRoot"] = struct_root

        path = tmp_path / "special_chars.pdf"
        pdf.save(str(path))

        result, out = _run(str(path))
        # Title should be preserved (not clobbered)
        for c in result["checkpoints"]:
            if c["id"] == "C-03":
                assert c["status"] == "PASS"
        shutil.rmtree(str(out), ignore_errors=True)
