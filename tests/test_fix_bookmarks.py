"""Tests for fix_bookmarks.py."""

from __future__ import annotations
import pathlib, sys
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fix_bookmarks import fix_bookmarks
from wcag_auditor import audit_pdf


def _save(pdf, tmp_path, name="test.pdf"):
    p = tmp_path / name
    pdf.save(str(p))
    return p


def test_skips_short_documents(tmp_path):
    pdf = pikepdf.new()
    for _ in range(5):
        pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_bookmarks(str(inp), str(out))
    assert "optional" in res["changes"][0].lower()


def test_adds_bookmarks_for_long_doc(tmp_path):
    pdf = pikepdf.new()
    for _ in range(25):
        pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_bookmarks(str(inp), str(out))
    assert any("bookmark" in c.lower() for c in res["changes"])
    # Verify bookmarks exist
    with pikepdf.open(str(out)) as pdf2:
        outlines = pdf2.Root.get("/Outlines")
        assert outlines is not None


def test_preserves_existing_bookmarks(tmp_path):
    pdf = pikepdf.new()
    for _ in range(25):
        pdf.add_blank_page()
    # Add existing bookmark
    item = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Title": pikepdf.String("Existing"),
                "/Dest": pikepdf.Array([pdf.pages[0].obj, pikepdf.Name("/Fit")]),
            }
        )
    )
    outline = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Outlines"),
                "/First": item,
                "/Last": item,
                "/Count": 1,
            }
        )
    )
    item["/Parent"] = outline
    pdf.Root["/Outlines"] = outline
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_bookmarks(str(inp), str(out))
    assert "already has bookmarks" in res["changes"][0]
