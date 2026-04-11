"""Tests for fix_ghost_text.py."""

from __future__ import annotations
import pathlib, sys
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fix_ghost_text import fix_ghost_text
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


def test_fixes_tr3_invisible_text(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    stream = b"BT 3 Tr /Helvetica 6 Tf 72 700 Td (Ghost text) Tj 0 Tr ET"
    pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
    pdf.pages[0]["/Resources"] = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary(
                {
                    "/Helvetica": pikepdf.Dictionary(
                        {
                            "/Type": pikepdf.Name("/Font"),
                            "/Subtype": pikepdf.Name("/Type1"),
                            "/BaseFont": pikepdf.Name("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_ghost_text(str(inp), str(out))
    assert any("Tr 3" in c for c in res["changes"]) or any("invisible" in c.lower() for c in res["changes"])
    r = audit_pdf(out)
    assert _status(r, "C-14") == "PASS"


def test_noop_normal_text(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    stream = b"BT /Helvetica 12 Tf 72 700 Td (Normal text) Tj ET"
    pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
    pdf.pages[0]["/Resources"] = pikepdf.Dictionary(
        {
            "/Font": pikepdf.Dictionary(
                {
                    "/Helvetica": pikepdf.Dictionary(
                        {
                            "/Type": pikepdf.Name("/Font"),
                            "/Subtype": pikepdf.Name("/Type1"),
                            "/BaseFont": pikepdf.Name("/Helvetica"),
                        }
                    )
                }
            )
        }
    )
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_ghost_text(str(inp), str(out))
    assert not res["changes"]  # No changes needed
