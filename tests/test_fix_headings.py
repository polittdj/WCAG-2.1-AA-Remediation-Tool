"""Tests for fix_headings.py."""

from __future__ import annotations
import pathlib, sys
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fix_headings import fix_headings
from wcag_auditor import audit_pdf


def _save(pdf, tmp_path, name="test.pdf"):
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _status(r, cid):
    for c in r["checkpoints"]:
        if c["id"] == cid:
            return c["status"]
    return "MISSING"


def test_preserves_existing_headings(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    h1 = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/H1"),
            }
        )
    )
    doc = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
                "/K": pikepdf.Array([h1]),
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
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_headings(str(inp), str(out))
    assert "already has heading tags" in res["changes"][0]


def test_noop_no_struct_tree(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_headings(str(inp), str(out))
    assert out.exists()


def test_idempotent(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    mid = tmp_path / "mid.pdf"
    out = tmp_path / "out.pdf"
    fix_headings(str(inp), str(mid))
    fix_headings(str(mid), str(out))
    assert out.exists()
