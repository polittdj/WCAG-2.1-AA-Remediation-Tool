"""Tests for fix_annotations.py."""

from __future__ import annotations
import pathlib, sys
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fix_annotations import fix_annotations


def _save(pdf, tmp_path, name="test.pdf"):
    p = tmp_path / name
    pdf.save(str(p))
    return p


def test_sets_contents_on_text_annot(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    annot = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Text"),
                "/Rect": pikepdf.Array([72, 700, 100, 720]),
            }
        )
    )
    pdf.pages[0]["/Annots"] = pikepdf.Array([annot])
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_annotations(str(inp), str(out))
    assert any("Contents" in c for c in res["changes"])


def test_skips_widget_and_link(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    w = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Widget"),
                "/Rect": pikepdf.Array([72, 700, 100, 720]),
            }
        )
    )
    l = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Link"),
                "/Rect": pikepdf.Array([72, 680, 100, 700]),
            }
        )
    )
    pdf.pages[0]["/Annots"] = pikepdf.Array([w, l])
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_annotations(str(inp), str(out))
    assert not res["changes"]


def test_noop_no_annotations(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_annotations(str(inp), str(out))
    assert not res["changes"]
