"""Edge case tests — Round 2 (GAP 6 requirement)."""

from __future__ import annotations
import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline
from wcag_auditor import audit_pdf


def test_multi_page_pdf_processes(tmp_path):
    """10-page document should process without issues."""
    pdf = pikepdf.new()
    for _ in range(10):
        pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Multi-Page Test"
    src = tmp_path / "multipage.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    assert res["result"] in ("PASS", "PARTIAL")
    assert len(res["checkpoints"]) == 47


def test_unicode_title_preserved(tmp_path):
    """Unicode characters in title should be preserved."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Formulaire de voyage — Édition spéciale"
    src = tmp_path / "unicode.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    assert res["result"] in ("PASS", "PARTIAL")
    # Title should be preserved
    with pikepdf.open(res["output_pdf"]) as pdf2:
        title = str(pdf2.docinfo.get("/Title", ""))
        assert "Formulaire" in title or "voyage" in title


def test_deeply_nested_struct_tree(tmp_path):
    """Document with deeply nested struct tree should not crash."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})

    # Build 20-level deep nesting
    innermost = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Span"),
            }
        )
    )
    current = innermost
    for i in range(20):
        wrapper = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Sect"),
                    "/K": pikepdf.Array([current]),
                }
            )
        )
        current = wrapper

    doc = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
                "/K": pikepdf.Array([current]),
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

    src = tmp_path / "deep.pdf"
    pdf.save(str(src))
    r = audit_pdf(src)
    assert len(r["checkpoints"]) == 47


def test_pdf_with_many_widgets(tmp_path):
    """Document with 50 form fields should process."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/AcroForm"] = pikepdf.Dictionary({"/Fields": pikepdf.Array()})
    annots = pikepdf.Array()
    fields = pdf.Root["/AcroForm"]["/Fields"]
    for i in range(50):
        w = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Annot"),
                    "/Subtype": pikepdf.Name("/Widget"),
                    "/Rect": pikepdf.Array([72, 700 - i * 10, 300, 710 - i * 10]),
                    "/FT": pikepdf.Name("/Tx"),
                    "/T": pikepdf.String(f"field_{i}"),
                }
            )
        )
        fields.append(w)
        annots.append(w)
    pdf.pages[0]["/Annots"] = annots
    src = tmp_path / "many_widgets.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    assert res["result"] in ("PASS", "PARTIAL")


def test_pipeline_output_is_valid_pdf(tmp_path):
    """Output PDF from pipeline should be openable by both pikepdf and fitz."""
    import fitz

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Valid Output"
    src = tmp_path / "valid.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    output = res["output_pdf"]
    assert output
    # pikepdf
    with pikepdf.open(output) as pk:
        assert len(pk.pages) >= 1
    # fitz
    doc = fitz.open(output)
    assert doc.page_count >= 1
    doc.close()
