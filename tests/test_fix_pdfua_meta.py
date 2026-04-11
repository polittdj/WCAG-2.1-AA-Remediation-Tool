"""Tests for fix_pdfua_meta.py — PDF/UA metadata, ViewerPreferences, Suspects."""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_pdfua_meta import fix_pdfua_meta  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402


def _save(pdf: pikepdf.Pdf, tmp_path: pathlib.Path, name: str = "test.pdf") -> pathlib.Path:
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _status(report: dict, checkpoint_id: str) -> str:
    for c in report["checkpoints"]:
        if c["id"] == checkpoint_id:
            return c["status"]
    return "MISSING"


def test_adds_pdfua_identifier(tmp_path: pathlib.Path) -> None:
    """fix_pdfua_meta should add pdfuaid:part=1 to XMP metadata."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path, "no_xmp.pdf")
    out = tmp_path / "out.pdf"
    res = fix_pdfua_meta(str(inp), str(out))
    assert out.exists()
    assert any("pdfuaid" in c.lower() for c in res["changes"])
    # Verify via audit
    r = audit_pdf(out)
    assert _status(r, "C-06") == "PASS"


def test_preserves_existing_xmp(tmp_path: pathlib.Path) -> None:
    """If XMP already has pdfuaid, don't duplicate."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    xmp = (
        b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
        b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
        b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
        b'<rdf:Description rdf:about=""'
        b' xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">'
        b"<pdfuaid:part>1</pdfuaid:part>"
        b"</rdf:Description>"
        b"</rdf:RDF>"
        b"</x:xmpmeta>"
        b'<?xpacket end="w"?>'
    )
    meta = pdf.make_stream(xmp)
    meta["/Type"] = pikepdf.Name("/Metadata")
    meta["/Subtype"] = pikepdf.Name("/XML")
    pdf.Root["/Metadata"] = meta
    inp = _save(pdf, tmp_path, "has_xmp.pdf")
    out = tmp_path / "out.pdf"
    res = fix_pdfua_meta(str(inp), str(out))
    # Should not add duplicate
    assert not any("Injected" in c for c in res["changes"])


def test_sets_display_doc_title(tmp_path: pathlib.Path) -> None:
    """fix_pdfua_meta should set DisplayDocTitle=true."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    fix_pdfua_meta(str(inp), str(out))
    r = audit_pdf(out)
    assert _status(r, "C-07") == "PASS"


def test_clears_suspects(tmp_path: pathlib.Path) -> None:
    """fix_pdfua_meta should remove /Suspects=true."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True, "/Suspects": True})
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_pdfua_meta(str(inp), str(out))
    assert any("Suspects" in c for c in res["changes"])
    r = audit_pdf(out)
    assert _status(r, "C-09") == "PASS"


def test_idempotent(tmp_path: pathlib.Path) -> None:
    """Running fix_pdfua_meta twice should be safe."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    mid = tmp_path / "mid.pdf"
    out = tmp_path / "out.pdf"
    fix_pdfua_meta(str(inp), str(mid))
    fix_pdfua_meta(str(mid), str(out))
    r = audit_pdf(out)
    assert _status(r, "C-06") == "PASS"
    assert _status(r, "C-07") == "PASS"
    assert _status(r, "C-09") == "PASS"
