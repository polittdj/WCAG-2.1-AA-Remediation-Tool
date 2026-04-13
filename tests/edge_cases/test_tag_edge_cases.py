"""Tag / StructTreeRoot edge-case tests.

Every input PDF is generated programmatically with pikepdf or hand-rolled
raw bytes. Contract under test:

* ``run_pipeline`` always returns a dict, never leaks a raw traceback.
* Deeply nested struct trees, orphaned page references, contradictory
  semantics, duplicate MCIDs, marked content without a struct tree,
  unbalanced BDC/EMC, and circular role maps must not crash, hang, or
  blow the Python recursion limit.
"""

from __future__ import annotations

import pathlib

import pikepdf
from pikepdf import Array, Dictionary, Name


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


def _font(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    }))


def _page_with_contents(pdf: pikepdf.Pdf, content_ops: bytes) -> pikepdf.Object:
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[-1]
    font = _font(pdf)
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(content_ops)
    return page


def _empty_parent_tree(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary({"/Nums": Array([])}))


def _attach_struct_root(pdf: pikepdf.Pdf, k, parent_tree=None) -> None:
    if parent_tree is None:
        parent_tree = _empty_parent_tree(pdf)
    sr = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": k,
        "/ParentTree": parent_tree,
        "/ParentTreeNextKey": 0,
    }))
    pdf.Root["/StructTreeRoot"] = sr
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})


_APPROVED_SUFFIXES = ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL")


def _assert_graceful(result) -> None:
    assert isinstance(result, dict), (
        f"run_pipeline returned {type(result).__name__}, not a dict"
    )
    assert "errors" in result and isinstance(result["errors"], list)
    for err in result["errors"]:
        assert "Traceback (most recent call last)" not in err, (
            f"raw traceback leaked into result['errors']:\n{err[:500]}"
        )


def _assert_output_produced(result, out_dir) -> pathlib.Path:
    _assert_graceful(result)
    out_pdf_s = result.get("output_pdf", "")
    assert out_pdf_s, (
        f"pipeline produced no output PDF; errors: {result.get('errors')}"
    )
    out_pdf = pathlib.Path(out_pdf_s)
    assert out_pdf.exists()
    out_dir_r = pathlib.Path(out_dir).resolve()
    assert out_pdf.resolve().is_relative_to(out_dir_r)
    stem = out_pdf.stem
    assert any(stem.endswith(s) for s in _APPROVED_SUFFIXES), (
        f"output filename missing approved suffix: {out_pdf.name!r}"
    )
    return out_pdf


# ---------------------------------------------------------------------------
# 1. Deeply nested tags — 200 levels
# ---------------------------------------------------------------------------


def test_deeply_nested_tags_200_levels(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    _page_with_contents(pdf, b"BT /F1 12 Tf 72 720 Td (Deep tree) Tj ET")
    # Build a chain of 200 indirect StructElem objects. Each wraps the
    # previous via /K.
    leaf = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
    }))
    chain = leaf
    for _ in range(200):
        chain = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/Div"),
            "/K": chain,
        }))
    _attach_struct_root(pdf, chain)
    path = edge_tmp_dir / "deep_struct.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 2. Orphaned struct elements — struct tree references page that does
#    not exist in the /Pages tree
# ---------------------------------------------------------------------------


def test_orphaned_struct_elements(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    _page_with_contents(pdf, b"BT /F1 12 Tf 72 720 Td (Real page) Tj ET")
    # Make a dangling "page" object that is NOT in pdf.pages
    dangling_page = pdf.make_indirect(Dictionary({
        "/Type": Name("/Page"),
        "/MediaBox": Array([0, 0, 612, 792]),
    }))
    struct = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/P"),
        "/Pg": dangling_page,
    }))
    _attach_struct_root(pdf, Array([struct]))
    path = edge_tmp_dir / "orphan_struct.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 3. Contradictory tag semantics — Table > H1 and H1 > Table
# ---------------------------------------------------------------------------


def test_contradictory_tag_semantics(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    _page_with_contents(pdf, b"BT /F1 12 Tf 72 720 Td (Contradictory) Tj ET")
    # Table containing an H1 child
    table_h1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Table"),
        "/K": Array([
            pdf.make_indirect(Dictionary({
                "/Type": Name("/StructElem"),
                "/S": Name("/H1"),
            })),
        ]),
    }))
    # H1 containing a Table child
    h1_table = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/H1"),
        "/K": Array([
            pdf.make_indirect(Dictionary({
                "/Type": Name("/StructElem"),
                "/S": Name("/Table"),
            })),
        ]),
    }))
    _attach_struct_root(pdf, Array([table_h1, h1_table]))
    path = edge_tmp_dir / "contradictory.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 4. Duplicate MCID — same MCID used twice on one page
# ---------------------------------------------------------------------------


def test_duplicate_mcid(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    ops = (
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf 72 720 Td (First MCID0) Tj ET\n"
        b"EMC\n"
        b"/P <</MCID 0>> BDC\n"
        b"BT /F1 12 Tf 72 700 Td (Duplicate MCID0) Tj ET\n"
        b"EMC\n"
    )
    _page_with_contents(pdf, ops)
    path = edge_tmp_dir / "dup_mcid.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 5. Marked content without StructTreeRoot
# ---------------------------------------------------------------------------


def test_marked_content_without_struct_tree(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    ops = (
        b"/P BDC\n"
        b"BT /F1 12 Tf 72 720 Td (Marked but not tagged) Tj ET\n"
        b"EMC\n"
    )
    _page_with_contents(pdf, ops)
    # Deliberately do NOT attach a StructTreeRoot or MarkInfo.
    path = edge_tmp_dir / "marked_no_tree.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    # Tier 3 (fix_untagged_content + fix_pdfua_meta) should create a
    # StructTreeRoot; at minimum the pipeline must complete gracefully.
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 6. Unbalanced BDC / EMC — more BDC than EMC
# ---------------------------------------------------------------------------


def test_unbalanced_bdc_emc(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # Two BDCs, only one EMC.
    ops = (
        b"/P BDC\n"
        b"BT /F1 12 Tf 72 720 Td (One) Tj ET\n"
        b"/P BDC\n"
        b"BT /F1 12 Tf 72 700 Td (Two, unbalanced) Tj ET\n"
        b"EMC\n"
    )
    _page_with_contents(pdf, ops)
    path = edge_tmp_dir / "unbalanced.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 7. Circular role map — CustomA -> CustomB -> CustomA
# ---------------------------------------------------------------------------


def test_circular_role_map(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    _page_with_contents(pdf, b"BT /F1 12 Tf 72 720 Td (Circular role map) Tj ET")
    role_map = Dictionary({
        "/CustomA": Name("/CustomB"),
        "/CustomB": Name("/CustomA"),
    })
    # A struct element that uses the custom role
    elem = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/CustomA"),
    }))
    sr = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": elem,
        "/ParentTree": _empty_parent_tree(pdf),
        "/ParentTreeNextKey": 0,
        "/RoleMap": role_map,
    }))
    pdf.Root["/StructTreeRoot"] = sr
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
    path = edge_tmp_dir / "circular_rolemap.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)
