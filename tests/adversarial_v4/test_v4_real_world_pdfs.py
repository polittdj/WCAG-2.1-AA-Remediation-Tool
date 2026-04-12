"""Category Q — Real-World PDF Hell.

Simulate PDFs that exist in the wild and cause tools to fail.
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
# Q1 — Linearized (web-optimized) PDF
# ═══════════════════════════════════════════════════════════════════════

def test_q1_linearized_pdf(tmp_path):
    src = tmp_path / "linearized.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Linearized Test"
    pdf.save(str(src), linearize=True)
    pdf.close()

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL"), f"Crashed on linearized PDF: {res['errors']}"
    assert len(res["checkpoints"]) == 47


# ═══════════════════════════════════════════════════════════════════════
# Q2 — PDF with incremental updates
# ═══════════════════════════════════════════════════════════════════════

def test_q2_incremental_updates(tmp_path):
    src = tmp_path / "incremental.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Version 1"
    pdf.save(str(src))
    pdf.close()

    # Append an incremental update
    with pikepdf.open(str(src), allow_overwriting_input=True) as pdf2:
        pdf2.add_blank_page()
        pdf2.docinfo["/Title"] = "Version 2"
        pdf2.save(str(src))

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL")
    with pikepdf.open(res["output_pdf"]) as out:
        assert len(out.pages) == 2, f"Expected 2 pages, got {len(out.pages)}"


# ═══════════════════════════════════════════════════════════════════════
# Q4 — PDF with object streams (PDF 1.5+)
# ═══════════════════════════════════════════════════════════════════════

def test_q4_object_streams(tmp_path):
    src = tmp_path / "objstm.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Object Stream Test"
    # Save with object streams enabled
    pdf.save(str(src), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL"), f"Failed on object stream PDF: {res['errors']}"


# ═══════════════════════════════════════════════════════════════════════
# Q5 — PDF with cross-reference streams
# ═══════════════════════════════════════════════════════════════════════

def test_q5_xref_streams(tmp_path):
    src = tmp_path / "xref_stream.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "XRef Stream Test"
    # pikepdf generates xref streams for PDF 1.5+ by default with object streams
    pdf.save(str(src), object_stream_mode=pikepdf.ObjectStreamMode.generate)
    pdf.close()

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL")
    assert len(res["checkpoints"]) == 47


# ═══════════════════════════════════════════════════════════════════════
# Q6 — PDF with Optional Content Groups (layers)
# ═══════════════════════════════════════════════════════════════════════

def test_q6_optional_content_groups(tmp_path):
    src = tmp_path / "layers.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    page = pdf.pages[0]

    # Create OCG (optional content group)
    ocg = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/OCG"),
        "/Name": pikepdf.String("English Layer"),
    }))

    # Add OCG to catalog
    pdf.Root["/OCProperties"] = pikepdf.Dictionary({
        "/OCGs": pikepdf.Array([ocg]),
        "/D": pikepdf.Dictionary({
            "/ON": pikepdf.Array([ocg]),
            "/Order": pikepdf.Array([ocg]),
        }),
    })

    page["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({
            "/F1": pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Font"),
                "/Subtype": pikepdf.Name("/Type1"),
                "/BaseFont": pikepdf.Name("/Helvetica"),
            })),
        }),
        "/Properties": pikepdf.Dictionary({"/OC1": ocg}),
    })

    page["/Contents"] = pdf.make_stream(
        b"/OC /OC1 BDC\nBT\n/F1 12 Tf\n100 700 Td\n(English Text) Tj\nET\nEMC\n"
    )

    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL"), f"Crashed on OCG PDF: {res['errors']}"


# ═══════════════════════════════════════════════════════════════════════
# Q8 — PDF portfolio / collection
# ═══════════════════════════════════════════════════════════════════════

def test_q8_pdf_portfolio(tmp_path):
    """A PDF with embedded file attachments should not crash."""
    src = tmp_path / "portfolio.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Portfolio Cover"

    # Add an embedded file
    embedded_data = b"%PDF-1.4 fake embedded pdf content"
    ef_stream = pdf.make_stream(embedded_data)
    ef_stream["/Type"] = pikepdf.Name("/EmbeddedFile")

    filespec = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Filespec"),
        "/F": pikepdf.String("attached.pdf"),
        "/EF": pikepdf.Dictionary({"/F": ef_stream}),
    }))

    pdf.Root["/Names"] = pikepdf.Dictionary({
        "/EmbeddedFiles": pikepdf.Dictionary({
            "/Names": pikepdf.Array([
                pikepdf.String("attached.pdf"),
                filespec,
            ]),
        }),
    })

    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["result"] in ("PASS", "PARTIAL"), f"Crashed on portfolio PDF: {res['errors']}"
    assert len(res["checkpoints"]) == 47
