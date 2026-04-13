"""Tests for IRS-03 — ParentTree validation and rebuild.

Covers validate_and_rebuild_parent_tree() in src/utils/structure_validator.

PAC reports "4.1 Compatible" failures when the PDF's ParentTree contains
references to MCIDs that do not appear in the content streams (orphaned
MCIDs).  Our remediation pipeline can introduce orphans when struct elements
are added or modified without updating the content streams.

Tests
-----
test_parent_tree_validation_clean_pdf
    A properly constructed PDF with matching struct-tree and content-stream
    MCIDs must be reported as valid (True, 0) without modification.

test_parent_tree_rebuild_fixes_orphans
    After manually adding orphaned MCID references to the struct tree,
    validate_and_rebuild_parent_tree must detect the mismatch, rebuild
    the ParentTree, and return (False, N).
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from src.utils.structure_validator import (
    validate_and_rebuild_parent_tree,
    validate_structure_tree,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


_BDC_STREAM = (
    b"q\n"
    b"/Span <</MCID 0>> BDC\n"
    b"BT /F1 12 Tf 72 720 Td (Hello) Tj ET\n"
    b"EMC\n"
    b"/Span <</MCID 1>> BDC\n"
    b"BT /F1 12 Tf 72 700 Td (World) Tj ET\n"
    b"EMC\n"
    b"Q\n"
)


def _make_clean_pdf() -> pikepdf.Pdf:
    """Return an in-memory tagged PDF whose ParentTree is fully consistent.

    The PDF has one page with two MCID markers (0 and 1) in its content
    stream and two corresponding Span struct elements in the struct tree.
    The ParentTree maps page 0 → [span0, span1].
    """
    pdf = pikepdf.new()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})

    # Add a blank page first so pdf.pages[0] is a proper pikepdf.Page
    pdf.add_blank_page()
    page = pdf.pages[0]

    # Attach content stream with MCID 0 and MCID 1
    content = pdf.make_stream(_BDC_STREAM)
    page["/Contents"] = content

    # Build struct elements with /Pg pointing to the real page object
    span0 = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Span"),
        "/Pg": page.obj,
        "/K": pikepdf.Integer(0),
    }))
    span1 = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Span"),
        "/Pg": page.obj,
        "/K": pikepdf.Integer(1),
    }))
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([span0, span1]),
    }))

    # ParentTree: page 0 → [span0, span1]  (index = MCID)
    parent_arr = pikepdf.Array([span0, span1])
    parent_tree = pdf.make_indirect(pikepdf.Dictionary({
        "/Nums": pikepdf.Array([pikepdf.Integer(0), parent_arr]),
    }))

    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc]),
        "/ParentTree": parent_tree,
        "/ParentTreeNextKey": pikepdf.Integer(1),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    return pdf


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_parent_tree_validation_clean_pdf():
    """A properly tagged PDF must validate as (True, 0) — no rebuild needed."""
    pdf = _make_clean_pdf()
    is_valid, num_fixes = validate_and_rebuild_parent_tree(pdf)
    assert is_valid is True, (
        f"Clean PDF should not need a ParentTree rebuild, got is_valid={is_valid}"
    )
    assert num_fixes == 0, f"Expected 0 fixes for a clean PDF, got {num_fixes}"


def test_parent_tree_rebuild_fixes_orphans():
    """Orphaned MCID in struct tree triggers rebuild; result must be (False, N>0)."""
    pdf = _make_clean_pdf()

    # Manually inject an orphaned struct element that references MCID 99,
    # which does not appear in the content stream (only 0 and 1 are there).
    page = pdf.pages[0]
    orphan_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Span"),
        "/Pg": page.obj,
        "/K": pikepdf.Integer(99),   # MCID 99 is NOT in the content stream
    }))
    # Append the orphan to the Document element's /K
    sr = pdf.Root["/StructTreeRoot"]
    doc = list(sr["/K"])[0]
    doc_k = doc["/K"]
    doc_k.append(orphan_elem)

    is_valid, num_fixes = validate_and_rebuild_parent_tree(pdf)

    assert is_valid is False, (
        "PDF with orphaned MCID 99 should be detected as invalid"
    )
    assert num_fixes > 0, (
        f"Expected >0 fixes for orphaned MCID, got {num_fixes}"
    )

    # After rebuild the ParentTree must still map the valid MCIDs (0 and 1)
    pt = pdf.Root["/StructTreeRoot"].get("/ParentTree")
    assert pt is not None, "ParentTree must exist after rebuild"
    nums = pt.get("/Nums")
    assert nums is not None, "Rebuilt ParentTree must have /Nums"

    # The rebuilt nums array should have page-0's entry
    nums_list = list(nums)
    assert len(nums_list) >= 2, "Rebuilt /Nums must have at least one key-value pair"
    # First key must be 0 (page 0)
    assert int(nums_list[0]) == 0, f"Expected page key 0, got {nums_list[0]}"
    # Value must be an array with at least 2 entries (MCID 0 and 1)
    page_arr = nums_list[1]
    assert isinstance(page_arr, pikepdf.Array), "ParentTree value must be an Array"
    assert len(page_arr) >= 2, (
        f"Array must cover at least MCID 0 and 1, has {len(page_arr)} entries"
    )
    # Orphaned MCID 99 must NOT be present (array stops at highest valid MCID)
    assert len(page_arr) <= 2, (
        f"Array should not extend to cover orphaned MCID 99 (len={len(page_arr)})"
    )


def test_no_struct_tree_returns_valid():
    """A PDF with no StructTreeRoot must not crash and must return (True, 0)."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    is_valid, num_fixes = validate_and_rebuild_parent_tree(pdf)
    assert is_valid is True
    assert num_fixes == 0


def test_no_parent_tree_returns_valid():
    """StructTreeRoot without ParentTree should return (True, 0) — no crash."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array(),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    is_valid, num_fixes = validate_and_rebuild_parent_tree(pdf)
    assert is_valid is True
    assert num_fixes == 0


def test_rebuild_preserves_valid_mcids(tmp_path):
    """After rebuild, only the content-stream MCIDs are in the ParentTree."""
    pdf = _make_clean_pdf()

    # Inject TWO orphans with MCIDs that don't exist in the content stream
    page = pdf.pages[0]
    for phantom_mcid in (50, 51):
        phantom = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"),
            "/S": pikepdf.Name("/Span"),
            "/Pg": page.obj,
            "/K": pikepdf.Integer(phantom_mcid),
        }))
        sr = pdf.Root["/StructTreeRoot"]
        doc = list(sr["/K"])[0]
        doc["/K"].append(phantom)

    is_valid, num_fixes = validate_and_rebuild_parent_tree(pdf)
    assert is_valid is False
    assert num_fixes == 2  # two orphaned struct-side MCIDs

    # Verify the ParentTree after rebuild does NOT reference MCIDs 50 or 51
    pt = pdf.Root["/StructTreeRoot"]["/ParentTree"]
    nums_list = list(pt["/Nums"])
    page_arr = list(nums_list[1])  # page-0 array
    # Array length should be 2 (covering MCIDs 0 and 1 only)
    assert len(page_arr) == 2, (
        f"Rebuilt array should cover only MCID 0-1, got length {len(page_arr)}"
    )
