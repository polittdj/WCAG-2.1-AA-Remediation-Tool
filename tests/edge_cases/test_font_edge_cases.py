"""Font / encoding edge-case tests.

The tool does not introspect font internals directly — text extraction
is delegated to PyMuPDF (fitz), and heading detection is driven by
font-size metadata only (fix_headings.py uses size >= 14 pt). These
tests verify that pathological font setups do not crash the pipeline
and do not misclassify text as headings.

Every input PDF is generated programmatically.
"""

from __future__ import annotations

import pathlib

import pikepdf
from pikepdf import Array, Dictionary, Name, String


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


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


def _page_with_font_resources(
    pdf: pikepdf.Pdf,
    font_resources: pikepdf.Object,
    content_ops: bytes,
    page_size: tuple[float, float] = (612, 792),
) -> pikepdf.Object:
    """Add a page that references a pre-built /Font resources dict."""
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    page["/Resources"] = Dictionary({"/Font": font_resources})
    page["/Contents"] = pdf.make_stream(content_ops)
    return page


def _helvetica_font(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    }))


def _collect_struct_types(pdf: pikepdf.Pdf) -> set[str]:
    """Return the set of all /S tag names in the remediated struct tree."""
    types: set[str] = set()
    try:
        sr = pdf.Root.get("/StructTreeRoot")
    except Exception:
        return types
    if sr is None:
        return types
    stack = [sr]
    seen: set[int] = set()
    while stack:
        node = stack.pop()
        try:
            obj_id = id(node)
        except Exception:
            continue
        if obj_id in seen:
            continue
        seen.add(obj_id)
        try:
            s = node.get("/S") if hasattr(node, "get") else None
            if s is not None:
                types.add(str(s))
            k = node.get("/K") if hasattr(node, "get") else None
        except Exception:
            continue
        if k is None:
            continue
        if isinstance(k, pikepdf.Array):
            for child in k:
                if isinstance(child, pikepdf.Dictionary):
                    stack.append(child)
        elif isinstance(k, pikepdf.Dictionary):
            stack.append(k)
    return types


# ---------------------------------------------------------------------------
# 1. Type3 user-defined font — bitmap glyphs, no /ToUnicode
# ---------------------------------------------------------------------------


def test_type3_user_defined_font(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # Build a minimal Type 3 font dict: /CharProcs with one trivial glyph.
    glyph_stream = pdf.make_indirect(pikepdf.Stream(
        pdf,
        b"0 0 10 10 d1",  # declare glyph bbox (no actual drawing)
    ))
    char_procs = pdf.make_indirect(Dictionary({
        "/A": glyph_stream,
    }))
    encoding = pdf.make_indirect(Dictionary({
        "/Type": Name("/Encoding"),
        "/Differences": Array([65, Name("/A")]),
    }))
    type3_font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type3"),
        "/Name": Name("/T3"),
        "/FontBBox": Array([0, 0, 10, 10]),
        "/FontMatrix": Array([0.1, 0, 0, 0.1, 0, 0]),
        "/FirstChar": 65,
        "/LastChar": 65,
        "/Widths": Array([10]),
        "/Encoding": encoding,
        "/CharProcs": char_procs,
        # deliberately NO /ToUnicode
    }))
    # Two fonts: the Type 3 custom font plus a standard Helvetica for
    # readable body text so the pipeline's heading detector can run.
    resources = Dictionary({
        "/T3": type3_font,
        "/F1": _helvetica_font(pdf),
    })
    # Use the Type 3 font for the first string, then Helvetica for body.
    ops = (
        b"BT /T3 12 Tf 100 700 Td <41> Tj ET\n"
        b"BT /F1 12 Tf 100 680 Td (Body text with standard font) Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "type3_font.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 2. CIDFont without /ToUnicode
# ---------------------------------------------------------------------------


def test_cid_font_without_tounicode(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    cid_system_info = pdf.make_indirect(Dictionary({
        "/Registry": String("Adobe"),
        "/Ordering": String("Identity"),
        "/Supplement": 0,
    }))
    descendant = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/CIDFontType2"),
        "/BaseFont": Name("/ArialMT"),
        "/CIDSystemInfo": cid_system_info,
        "/W": Array([]),
        "/DW": 1000,
        "/CIDToGIDMap": Name("/Identity"),
    }))
    type0_font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type0"),
        "/BaseFont": Name("/ArialMT"),
        "/Encoding": Name("/Identity-H"),
        "/DescendantFonts": Array([descendant]),
        # deliberately NO /ToUnicode CMap
    }))
    resources = Dictionary({
        "/C1": type0_font,
        "/F1": _helvetica_font(pdf),
    })
    # Hex string with a CID pair; Helvetica body for readable fallback.
    ops = (
        b"BT /C1 12 Tf 100 700 Td <00410042> Tj ET\n"
        b"BT /F1 12 Tf 100 680 Td (CIDFont with no ToUnicode) Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "cidfont_no_tounicode.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 3. Mixed encodings across pages
# ---------------------------------------------------------------------------


def test_mixed_encodings_across_pages(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    winansi_font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
        "/Encoding": Name("/WinAnsiEncoding"),
    }))
    macroman_font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
        "/Encoding": Name("/MacRomanEncoding"),
    }))
    diff_encoding = pdf.make_indirect(Dictionary({
        "/Type": Name("/Encoding"),
        "/BaseEncoding": Name("/WinAnsiEncoding"),
        "/Differences": Array([128, Name("/Euro"), Name("/bullet")]),
    }))
    custom_font = pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
        "/Encoding": diff_encoding,
    }))
    _page_with_font_resources(
        pdf,
        Dictionary({"/F1": winansi_font}),
        b"BT /F1 12 Tf 100 700 Td (Page one WinAnsi) Tj ET",
    )
    _page_with_font_resources(
        pdf,
        Dictionary({"/F1": macroman_font}),
        b"BT /F1 12 Tf 100 700 Td (Page two MacRoman) Tj ET",
    )
    _page_with_font_resources(
        pdf,
        Dictionary({"/F1": custom_font}),
        b"BT /F1 12 Tf 100 700 Td (Page three custom differences) Tj ET",
    )
    path = edge_tmp_dir / "mixed_encodings.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 4. Right-to-left text (Arabic or Hebrew code points)
# ---------------------------------------------------------------------------


def test_right_to_left_text(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    font = _helvetica_font(pdf)
    resources = Dictionary({"/F1": font})
    # Put UTF-8 bytes of Arabic text inside a PDF string literal. The
    # glyph rendering will be garbage (Helvetica has no Arabic glyphs)
    # but the content stream parser has to handle the bytes without
    # crashing, and the page must remain a valid struct-tree parent.
    arabic_bytes = "مرحبا بالعالم".encode("utf-8")
    # Escape parentheses/backslashes just in case:
    arabic_escaped = (
        arabic_bytes
        .replace(b"\\", b"\\\\")
        .replace(b"(", b"\\(")
        .replace(b")", b"\\)")
    )
    ops = (
        b"BT /F1 12 Tf 100 700 Td ("
        + arabic_escaped
        + b") Tj ET\n"
        b"BT /F1 12 Tf 100 680 Td (Fallback English line) Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "rtl_text.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 5. Bidirectional text — alternating English and Arabic on same line
# ---------------------------------------------------------------------------


def test_bidirectional_text(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    font = _helvetica_font(pdf)
    resources = Dictionary({"/F1": font})
    arabic_bytes = "مرحبا".encode("utf-8").replace(b"(", b"\\(").replace(b")", b"\\)")
    ops = (
        b"BT /F1 12 Tf 100 700 Td (Hello ) Tj ("
        + arabic_bytes
        + b") Tj ( world) Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "bidi_text.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 6. Math notation (subscripts and superscripts)
# ---------------------------------------------------------------------------


def test_math_notation(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    font = _helvetica_font(pdf)
    resources = Dictionary({"/F1": font})
    # 12 pt baseline body, 8 pt subscript/superscript below heading threshold.
    ops = (
        b"BT /F1 12 Tf 100 700 Td (Body text E) Tj ET\n"
        b"BT /F1 8 Tf 155 705 Td (2) Tj ET\n"   # superscript
        b"BT /F1 12 Tf 100 680 Td (H) Tj ET\n"
        b"BT /F1 8 Tf 112 675 Td (2) Tj ET\n"   # subscript
        b"BT /F1 12 Tf 120 680 Td (O) Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "math_notation.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # Heading detector threshold is >= 14 pt — neither the 12 pt body nor
    # the 8 pt sub/superscripts should be classified as headings.
    with pikepdf.open(str(out_pdf)) as remediated:
        types = _collect_struct_types(remediated)
        heading_tags = {"/H1", "/H2", "/H3", "/H4", "/H5", "/H6"}
        bad = types & heading_tags
        assert not bad, (
            f"heading detector misclassified small text as headings: {bad}"
        )


# ---------------------------------------------------------------------------
# 7. Ligatures and special glyphs
# ---------------------------------------------------------------------------


def test_ligatures_and_special_glyphs(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    font = _helvetica_font(pdf)
    resources = Dictionary({"/F1": font})
    # fi U+FB01, fl U+FB02, ff U+FB00, ffi U+FB03, em dash U+2014,
    # ellipsis U+2026, trademark U+2122.
    special = "office fluff — … ™"
    special_bytes = special.encode("utf-8").replace(b"(", b"\\(").replace(b")", b"\\)")
    ops = (
        b"BT /F1 12 Tf 100 700 Td ("
        + special_bytes
        + b") Tj ET"
    )
    _page_with_font_resources(pdf, resources, ops)
    path = edge_tmp_dir / "ligatures.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)
