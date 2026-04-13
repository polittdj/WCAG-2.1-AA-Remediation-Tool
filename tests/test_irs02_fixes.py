"""Tests for IRS-02 fixes — C-20 heading, C-25 TH scope, C-13 RoleMap.

Fix 1 (C-20): demote extra H1s → tested extensively in test_fix_headings.py
Fix 2 (C-25): add /Scope to TH elements lacking it
Fix 3 (C-13): replace non-standard BDC tags / RoleMap entries with standard equivalents
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_content_streams import fix_content_streams, _clean_role_map
from fix_content_tagger import _fix_existing_th_scope


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tagged_pdf() -> pikepdf.Pdf:
    """Return a minimal in-memory tagged PDF with a StructTreeRoot."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})
    sr_k = pikepdf.Array()
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": sr_k,
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    return pdf, sr_k


def _add_elem(pdf: pikepdf.Pdf, tag: str, parent_k: pikepdf.Array,
              attrs: dict | None = None) -> pikepdf.Dictionary:
    d: dict = {
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name(f"/{tag}"),
    }
    if attrs:
        d.update(attrs)
    elem = pdf.make_indirect(pikepdf.Dictionary(d))
    parent_k.append(elem)
    return elem


def _get_scope(th_elem: pikepdf.Dictionary) -> str | None:
    """Return the /Scope value from a TH element's /A attribute dict, or None."""
    a = th_elem.get("/A")
    if a is None:
        return None
    if isinstance(a, pikepdf.Dictionary):
        s = a.get("/Scope")
        return str(s).lstrip("/") if s is not None else None
    if isinstance(a, pikepdf.Array):
        for attr in a:
            if isinstance(attr, pikepdf.Dictionary):
                s = attr.get("/Scope")
                if s is not None:
                    return str(s).lstrip("/")
    return None


# ---------------------------------------------------------------------------
# IRS-02 Fix 2 — C-25: TH elements must have a Scope attribute
# ---------------------------------------------------------------------------


def test_th_gets_scope():
    """TH struct elements lacking /Scope must receive /Scope = /Column."""
    pdf, sr_k = _make_tagged_pdf()

    # Build: StructTreeRoot > Document > Table > TR > TH (no Scope)
    doc = _add_elem(pdf, "Document", sr_k)
    doc_k = pikepdf.Array()
    doc["/K"] = doc_k

    table = _add_elem(pdf, "Table", doc_k)
    table_k = pikepdf.Array()
    table["/K"] = table_k

    tr = _add_elem(pdf, "TR", table_k)
    tr_k = pikepdf.Array()
    tr["/K"] = tr_k

    th1 = _add_elem(pdf, "TH", tr_k)
    th2 = _add_elem(pdf, "TH", tr_k)
    _add_elem(pdf, "TD", tr_k)  # TD should not be touched

    # Pre-condition: no /Scope on any TH
    assert _get_scope(th1) is None, "TH1 should not have /Scope before fix"
    assert _get_scope(th2) is None, "TH2 should not have /Scope before fix"

    count = _fix_existing_th_scope(pdf)

    assert count == 2, f"Expected 2 TH elements fixed, got {count}"
    assert _get_scope(th1) == "Column", f"TH1 scope: {_get_scope(th1)}"
    assert _get_scope(th2) == "Column", f"TH2 scope: {_get_scope(th2)}"


def test_th_with_existing_scope_unchanged():
    """TH elements that already carry /Scope must not be modified."""
    pdf, sr_k = _make_tagged_pdf()

    doc = _add_elem(pdf, "Document", sr_k)
    doc_k = pikepdf.Array()
    doc["/K"] = doc_k

    table = _add_elem(pdf, "Table", doc_k)
    table_k = pikepdf.Array()
    table["/K"] = table_k

    th_with_scope = _add_elem(
        pdf, "TH", table_k,
        attrs={"/A": pikepdf.Dictionary({
            "/O": pikepdf.Name("/Table"),
            "/Scope": pikepdf.Name("/Row"),
        })},
    )
    th_no_scope = _add_elem(pdf, "TH", table_k)

    count = _fix_existing_th_scope(pdf)

    # Only the TH that lacked /Scope should be fixed
    assert count == 1, f"Expected 1 fix, got {count}"
    # The pre-existing /Row scope must be preserved
    assert _get_scope(th_with_scope) == "Row", "Existing /Row scope must be preserved"
    assert _get_scope(th_no_scope) == "Column", "Missing scope must be set to /Column"


def test_no_table_no_th_scope_fix():
    """A document with no TH elements should return 0 fixes."""
    pdf, sr_k = _make_tagged_pdf()

    doc = _add_elem(pdf, "Document", sr_k)
    doc_k = pikepdf.Array()
    doc["/K"] = doc_k
    _add_elem(pdf, "P", doc_k)

    count = _fix_existing_th_scope(pdf)
    assert count == 0


# ---------------------------------------------------------------------------
# IRS-02 Fix 3 — C-13: non-standard BDC tags and RoleMap entries
# ---------------------------------------------------------------------------


def test_content_tag_gets_rolemap(tmp_path):
    """A PDF whose /RoleMap has a /Content entry gets it remapped to /Span.

    C-13 requires that any non-standard structure type used in a PDF is
    either absent (replaced in the content stream) or mapped to a standard
    type via /RoleMap.  fix_content_streams replaces /Content BDC in
    content streams AND updates the /RoleMap entry from /Content → /Span.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})

    # Set up a /RoleMap that maps /Content to /Content (self-referential —
    # common in Acrobat-produced PDFs; not a standard PDF/UA type).
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array(),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
        "/RoleMap": pikepdf.Dictionary({
            "/Content": pikepdf.Name("/Content"),   # non-standard self-reference
            "/Textbody": pikepdf.Name("/Textbody"), # another common non-standard
        }),
    }))
    pdf.Root["/StructTreeRoot"] = sr

    src = tmp_path / "in.pdf"
    pdf.save(str(src))
    pdf.close()

    out = tmp_path / "out.pdf"
    result = fix_content_streams(str(src), str(out))

    assert not result["errors"], f"Unexpected errors: {result['errors']}"

    with pikepdf.open(str(out)) as fixed:
        role_map = fixed.Root["/StructTreeRoot"]["/RoleMap"]
        content_mapping = str(role_map.get("/Content", "MISSING")).lstrip("/")
        textbody_mapping = str(role_map.get("/Textbody", "MISSING")).lstrip("/")

    assert content_mapping == "Span", (
        f"/Content in RoleMap should map to /Span after fix, got /{content_mapping}"
    )
    assert textbody_mapping == "P", (
        f"/Textbody in RoleMap should map to /P after fix, got /{textbody_mapping}"
    )


def test_normal_tag_gets_rolemap(tmp_path):
    """/Normal in /RoleMap (Word export) must be remapped to /P (IRS-02)."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})

    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array(),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
        "/RoleMap": pikepdf.Dictionary({
            "/Normal": pikepdf.Name("/Normal"),  # Word export non-standard tag
        }),
    }))
    pdf.Root["/StructTreeRoot"] = sr

    src = tmp_path / "in.pdf"
    pdf.save(str(src))
    pdf.close()

    out = tmp_path / "out.pdf"
    fix_content_streams(str(src), str(out))

    with pikepdf.open(str(out)) as fixed:
        role_map = fixed.Root["/StructTreeRoot"]["/RoleMap"]
        normal_mapping = str(role_map.get("/Normal", "MISSING")).lstrip("/")

    assert normal_mapping == "P", (
        f"/Normal in RoleMap should map to /P after fix, got /{normal_mapping}"
    )


def test_clean_role_map_direct():
    """`_clean_role_map` replaces known non-standard keys, leaves standard keys."""
    pdf = pikepdf.new()
    pdf.add_blank_page()

    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array(),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
        "/RoleMap": pikepdf.Dictionary({
            "/Content": pikepdf.Name("/Content"),
            "/Textbody": pikepdf.Name("/Textbody"),
            "/Normal": pikepdf.Name("/Normal"),
            "/P": pikepdf.Name("/P"),         # already standard — must be left alone
            "/Span": pikepdf.Name("/Span"),   # already standard — must be left alone
        }),
    }))
    pdf.Root["/StructTreeRoot"] = sr

    modified = _clean_role_map(pdf)

    role_map = pdf.Root["/StructTreeRoot"]["/RoleMap"]
    assert str(role_map["/Content"]).lstrip("/") == "Span"
    assert str(role_map["/Textbody"]).lstrip("/") == "P"
    assert str(role_map["/Normal"]).lstrip("/") == "P"
    # Standard entries must be untouched
    assert str(role_map["/P"]).lstrip("/") == "P"
    assert str(role_map["/Span"]).lstrip("/") == "Span"
    assert modified == 3, f"Expected 3 modifications, got {modified}"
