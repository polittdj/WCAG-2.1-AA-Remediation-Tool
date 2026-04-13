"""Content edge-case tests.

Each test generates a PDF with pathological content and runs it through
``pipeline.run_pipeline``. The contract under test:

* ``run_pipeline`` must always return a dict (never raise, never leak a
  raw Python traceback into ``result["errors"]``).
* For inputs that are structurally valid PDFs (even if malformed in
  content), the pipeline must produce an output file with the sanctioned
  ``_WGAC_2.1_AA_*`` suffix inside the caller-specified output directory.
* For pathologically large inputs the pipeline must complete in a
  reasonable time without hanging or crashing.

All input PDFs are generated programmatically — no committed fixtures.
"""

from __future__ import annotations

import io
import pathlib

import pikepdf


# ---------------------------------------------------------------------------
# PDF generators
# ---------------------------------------------------------------------------


_APPROVED_SUFFIXES = ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL")


def _font(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/Type1"),
        "/BaseFont": pikepdf.Name("/Helvetica"),
    }))


def _add_page_with_text(
    pdf: pikepdf.Pdf,
    content_ops: bytes,
    page_size: tuple[float, float] = (612, 792),
    rotate: int | None = None,
) -> pikepdf.Object:
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    font = _font(pdf)
    page["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": font}),
    })
    page["/Contents"] = pdf.make_stream(content_ops)
    if rotate is not None:
        page["/Rotate"] = rotate
    return page


def _make_thousand_pages(path: pathlib.Path, n: int = 1000) -> pathlib.Path:
    pdf = pikepdf.new()
    font = _font(pdf)
    for i in range(n):
        pdf.add_blank_page(page_size=(612, 792))
        page = pdf.pages[-1]
        page["/Resources"] = pikepdf.Dictionary({
            "/Font": pikepdf.Dictionary({"/F1": font}),
        })
        ops = f"BT /F1 12 Tf 72 720 Td (Page {i + 1}) Tj ET".encode()
        page["/Contents"] = pdf.make_stream(ops)
    pdf.save(str(path))
    return path


def _make_oversized_page(path: pathlib.Path) -> pathlib.Path:
    # 200 inches * 72 pt/in = 14400 pt
    pdf = pikepdf.new()
    # Dense text: roughly 200 lines down the page.
    lines = []
    for y in range(100, 14300, 72):
        lines.append(f"BT /F1 12 Tf 72 {y} Td (Dense line at y {y}) Tj ET")
    ops = "\n".join(lines).encode()
    _add_page_with_text(pdf, ops, page_size=(14400, 14400))
    pdf.save(str(path))
    return path


def _make_zero_dimension_page(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[-1]
    page["/MediaBox"] = pikepdf.Array([0, 0, 0, 0])
    pdf.save(str(path))
    return path


def _make_negative_mediabox(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(200, 200))
    page = pdf.pages[-1]
    page["/MediaBox"] = pikepdf.Array([-100, -100, 100, 100])
    font = _font(pdf)
    page["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": font}),
    })
    ops = b"BT /F1 12 Tf 0 0 Td (Content in negative box) Tj ET"
    page["/Contents"] = pdf.make_stream(ops)
    pdf.save(str(path))
    return path


def _make_mixed_orientation(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    for label, size in [
        ("Portrait 1", (612, 792)),
        ("Landscape", (792, 612)),
        ("Portrait 2", (612, 792)),
    ]:
        ops = f"BT /F1 12 Tf 72 500 Td ({label}) Tj ET".encode()
        _add_page_with_text(pdf, ops, page_size=size)
    pdf.save(str(path))
    return path


def _make_image_only_pdf(path: pathlib.Path) -> pathlib.Path:
    # A single-page PDF with a rendered raster image and zero text operators.
    # Uses reportlab + PIL (both already hard dependencies).
    from reportlab.lib.pagesizes import LETTER
    from reportlab.lib.utils import ImageReader
    from reportlab.pdfgen import canvas
    from PIL import Image, ImageDraw

    img = Image.new("RGB", (300, 300), color="white")
    draw = ImageDraw.Draw(img)
    # Draw some shapes so the image isn't featureless
    draw.rectangle([20, 20, 280, 280], outline="black", width=2)
    draw.text((100, 140), "IMAGE", fill="black")

    buf = io.BytesIO()
    img.save(buf, format="PNG")
    buf.seek(0)

    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.drawImage(ImageReader(buf), 100, 200, width=400, height=400)
    c.showPage()
    c.save()
    return path


def _make_invisible_text(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    # 3 Tr = render mode 3 (invisible). Text is still extracted by most
    # tools for a11y / accessibility search but is not rendered visually.
    ops = b"BT /F1 12 Tf 3 Tr 72 720 Td (Hidden accessible text) Tj ET"
    _add_page_with_text(pdf, ops)
    pdf.save(str(path))
    return path


def _make_overlapping_text(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    ops_lines = [
        "BT /F1 12 Tf 100 400 Td (First overlapping block) Tj ET",
        "BT /F1 12 Tf 100 400 Td (Second overlapping block) Tj ET",
        "BT /F1 12 Tf 100 400 Td (Third overlapping block) Tj ET",
        "BT /F1 12 Tf 100 400 Td (Fourth overlapping block) Tj ET",
    ]
    ops = "\n".join(ops_lines).encode()
    _add_page_with_text(pdf, ops)
    pdf.save(str(path))
    return path


def _make_rotated_pages(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    for rotation in [0, 90, 180, 270]:
        ops = f"BT /F1 12 Tf 72 720 Td (Rotation {rotation}) Tj ET".encode()
        _add_page_with_text(pdf, ops, rotate=rotation)
    pdf.save(str(path))
    return path


def _make_microscopic_text(path: pathlib.Path) -> pathlib.Path:
    pdf = pikepdf.new()
    # 0.5 pt font size — below any conceivable heading threshold.
    ops = b"BT /F1 0.5 Tf 72 720 Td (This text is microscopic) Tj ET"
    _add_page_with_text(pdf, ops)
    pdf.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


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
    assert out_pdf.exists(), f"output_pdf path does not exist: {out_pdf}"
    out_dir_r = pathlib.Path(out_dir).resolve()
    assert out_pdf.resolve().is_relative_to(out_dir_r), (
        f"output escaped out_dir: {out_pdf.resolve()} not in {out_dir_r}"
    )
    stem = out_pdf.stem
    assert any(stem.endswith(s) for s in _APPROVED_SUFFIXES), (
        f"output filename missing approved suffix: {out_pdf.name!r}"
    )
    return out_pdf


# ---------------------------------------------------------------------------
# 1. Thousand pages — must complete without timeout
# ---------------------------------------------------------------------------


def test_thousand_pages(edge_tmp_dir, run_through_pipeline):
    pdf = _make_thousand_pages(edge_tmp_dir / "thousand.pdf", n=1000)
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    # Sanity check: the output should still contain ~1000 pages.
    with pikepdf.open(str(out_pdf)) as remediated:
        assert len(remediated.pages) == 1000


# ---------------------------------------------------------------------------
# 2. Oversized page dimensions — 200 in x 200 in with dense text
# ---------------------------------------------------------------------------


def test_oversized_page_dimensions(edge_tmp_dir, run_through_pipeline):
    pdf = _make_oversized_page(edge_tmp_dir / "oversized.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 3. Zero-dimension page — MediaBox [0 0 0 0]
# ---------------------------------------------------------------------------


def test_zero_dimension_page(edge_tmp_dir, run_through_pipeline):
    pdf = _make_zero_dimension_page(edge_tmp_dir / "zero_dim.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_graceful(result)  # division-by-zero would fail this


# ---------------------------------------------------------------------------
# 4. Negative MediaBox — [-100 -100 100 100]
# ---------------------------------------------------------------------------


def test_negative_mediabox(edge_tmp_dir, run_through_pipeline):
    pdf = _make_negative_mediabox(edge_tmp_dir / "negative_box.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 5. Mixed orientation — portrait, landscape, portrait
# ---------------------------------------------------------------------------


def test_mixed_orientation(edge_tmp_dir, run_through_pipeline):
    pdf = _make_mixed_orientation(edge_tmp_dir / "mixed.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    # Reading order survives: the output still has 3 pages in the same
    # order, each with its original MediaBox dimensions.
    with pikepdf.open(str(out_pdf)) as remediated:
        assert len(remediated.pages) == 3
        widths = [float(p["/MediaBox"][2]) - float(p["/MediaBox"][0])
                  for p in remediated.pages]
        assert widths == [612.0, 792.0, 612.0], (
            f"page ordering/dimensions changed: {widths}"
        )


# ---------------------------------------------------------------------------
# 6. Image-only page — no text
# ---------------------------------------------------------------------------


def test_image_only_no_text(edge_tmp_dir, run_through_pipeline):
    pdf = _make_image_only_pdf(edge_tmp_dir / "image_only.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    # OCR path activates or graceful degradation — either way, no crash.
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 7. Invisible text — render mode 3
# ---------------------------------------------------------------------------


def test_invisible_text_render_mode_3(edge_tmp_dir, run_through_pipeline):
    pdf = _make_invisible_text(edge_tmp_dir / "invisible_text.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    # Ensure the struct tree doesn't contain duplicate /Span elements
    # pointing at the same content (a sign of double-tagging).
    with pikepdf.open(str(out_pdf)) as remediated:
        sr = remediated.Root.get("/StructTreeRoot")
        if sr is not None:
            # Count total struct elements; shouldn't explode beyond a
            # reasonable upper bound for a 1-page, 1-line document.
            element_count = _count_struct_elements(sr)
            assert element_count < 50, (
                f"struct tree has {element_count} elements for a 1-line "
                f"document — suggests double-tagging of invisible text"
            )


def _count_struct_elements(node, seen=None) -> int:
    if seen is None:
        seen = set()
    obj_id = id(node)
    if obj_id in seen:
        return 0
    seen.add(obj_id)
    count = 1
    try:
        k = node.get("/K") if hasattr(node, "get") else None
    except Exception:
        return count
    if k is None:
        return count
    if isinstance(k, pikepdf.Array):
        for child in k:
            if isinstance(child, pikepdf.Dictionary):
                count += _count_struct_elements(child, seen)
    elif isinstance(k, pikepdf.Dictionary):
        count += _count_struct_elements(k, seen)
    return count


# ---------------------------------------------------------------------------
# 8. Overlapping text blocks
# ---------------------------------------------------------------------------


def test_overlapping_text_blocks(edge_tmp_dir, run_through_pipeline):
    pdf = _make_overlapping_text(edge_tmp_dir / "overlapping.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 9. Rotated pages — 0, 90, 180, 270
# ---------------------------------------------------------------------------


def test_rotated_pages(edge_tmp_dir, run_through_pipeline):
    pdf = _make_rotated_pages(edge_tmp_dir / "rotated.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    # Reading order accounts for rotation: each page's /Rotate value
    # is preserved in the output so screen readers get the correct
    # visual orientation.
    with pikepdf.open(str(out_pdf)) as remediated:
        rotations = [int(p.get("/Rotate", 0)) for p in remediated.pages]
        assert rotations == [0, 90, 180, 270], (
            f"page rotations changed: {rotations}"
        )


# ---------------------------------------------------------------------------
# 10. Microscopic text — 0.5 pt font
# ---------------------------------------------------------------------------


def test_microscopic_text(edge_tmp_dir, run_through_pipeline):
    pdf = _make_microscopic_text(edge_tmp_dir / "tiny.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    # Heading detection must NOT classify 0.5 pt text as a heading.
    # Inspect the struct tree and verify no /H1../H6 element was created.
    with pikepdf.open(str(out_pdf)) as remediated:
        sr = remediated.Root.get("/StructTreeRoot")
        if sr is not None:
            heading_types = _collect_struct_types(sr)
            heading_tags = {"/H1", "/H2", "/H3", "/H4", "/H5", "/H6", "/H"}
            bad = heading_types & heading_tags
            assert not bad, (
                f"heading detection misclassified microscopic text: {bad}"
            )


def _collect_struct_types(node, seen=None) -> set[str]:
    if seen is None:
        seen = set()
    types: set[str] = set()
    obj_id = id(node)
    if obj_id in seen:
        return types
    seen.add(obj_id)
    try:
        s = node.get("/S") if hasattr(node, "get") else None
        if s is not None:
            types.add(str(s))
        k = node.get("/K") if hasattr(node, "get") else None
    except Exception:
        return types
    if k is None:
        return types
    if isinstance(k, pikepdf.Array):
        for child in k:
            if isinstance(child, pikepdf.Dictionary):
                types |= _collect_struct_types(child, seen)
    elif isinstance(k, pikepdf.Dictionary):
        types |= _collect_struct_types(k, seen)
    return types
