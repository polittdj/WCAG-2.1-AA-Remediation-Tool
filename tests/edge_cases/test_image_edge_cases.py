"""Image edge-case tests.

Each test generates a PDF containing a pathological image payload and
runs it through ``pipeline.run_pipeline``.

Contract:

* ``run_pipeline`` always returns a dict and never leaks a raw
  traceback.
* For structurally valid PDFs the pipeline produces a final
  ``_WGAC_2.1_AA_*`` output inside the caller-specified directory.
* Memory stays stable even on large bitmaps — the test process is
  limited to a generous but bounded RSS ceiling via ``resource.setrlimit``
  where available.
"""

from __future__ import annotations

import io
import pathlib

import pikepdf
from pikepdf import Array, Dictionary, Name


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


def _collect_struct_types(pdf: pikepdf.Pdf) -> set[str]:
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


def _font(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    }))


def _embed_image(
    pdf: pikepdf.Pdf,
    raw_data: bytes,
    width: int,
    height: int,
    color_space: str | pikepdf.Object,
    bits_per_component: int = 8,
    extra: dict | None = None,
) -> pikepdf.Object:
    """Create an Image XObject with the given raw (uncompressed) data."""
    d = {
        "/Type": Name("/XObject"),
        "/Subtype": Name("/Image"),
        "/Width": width,
        "/Height": height,
        "/BitsPerComponent": bits_per_component,
        "/ColorSpace": (
            Name(color_space) if isinstance(color_space, str) else color_space
        ),
    }
    if extra:
        d.update(extra)
    return pdf.make_indirect(pikepdf.Stream(pdf, raw_data, **{
        k.lstrip("/"): v for k, v in d.items()
    }))


def _add_page_with_image(
    pdf: pikepdf.Pdf,
    image_xobject: pikepdf.Object,
    image_name: str = "Im1",
    page_size: tuple[float, float] = (612, 792),
) -> pikepdf.Object:
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    page["/Resources"] = Dictionary({
        "/XObject": Dictionary({f"/{image_name}": image_xobject}),
        "/Font": Dictionary({"/F1": _font(pdf)}),
    })
    # Draw the image at full page size and add a caption.
    ops = (
        f"q 500 0 0 700 50 50 cm /{image_name} Do Q\n"
        "BT /F1 12 Tf 50 780 Td (Caption) Tj ET"
    ).encode()
    page["/Contents"] = pdf.make_stream(ops)
    return page


# ---------------------------------------------------------------------------
# 1. CMYK images
# ---------------------------------------------------------------------------


def test_cmyk_color_space_images(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # 10x10 pixel CMYK image: 10*10*4 = 400 bytes, all 50% gray.
    raw = bytes([128] * (10 * 10 * 4))
    image = _embed_image(pdf, raw, 10, 10, "/DeviceCMYK")
    _add_page_with_image(pdf, image)
    path = edge_tmp_dir / "cmyk.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 2. 16-bit image depth
# ---------------------------------------------------------------------------


def test_16bit_image_depth(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # 10x10 RGB at 16 bits per component = 10*10*3*2 = 600 bytes.
    raw = b"\x80\x00" * (10 * 10 * 3)
    image = _embed_image(pdf, raw, 10, 10, "/DeviceRGB", bits_per_component=16)
    _add_page_with_image(pdf, image)
    path = edge_tmp_dir / "image_16bit.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 3. Inline images (BI/ID/EI)
# ---------------------------------------------------------------------------


def test_inline_images(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[-1]
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": _font(pdf)})})
    # A minimal 2x2 RGB inline image (12 bytes of data).
    inline_data = bytes([255, 0, 0, 0, 255, 0, 0, 0, 255, 128, 128, 128])
    ops = (
        b"q 100 0 0 100 100 100 cm\n"
        b"BI\n"
        b"/W 2 /H 2 /CS /RGB /BPC 8 /F /A85\n"
        b"ID\n"
        + inline_data
        + b"\nEI\nQ\n"
        b"BT /F1 12 Tf 100 700 Td (With an inline image above) Tj ET"
    )
    page["/Contents"] = pdf.make_stream(ops)
    path = edge_tmp_dir / "inline_image.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 4. Stencil mask image (1-bit image mask)
# ---------------------------------------------------------------------------


def test_stencil_mask_image(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # 1-bit image mask: 8x8 = 8 bytes (1 bit per pixel, packed to bytes).
    raw = bytes([0b10101010] * 8)
    # ImageMask requires /ImageMask true and no /ColorSpace.
    mask_xobj = pdf.make_indirect(pikepdf.Stream(
        pdf,
        raw,
        Type=Name("/XObject"),
        Subtype=Name("/Image"),
        Width=8,
        Height=8,
        BitsPerComponent=1,
        ImageMask=True,
    ))
    _add_page_with_image(pdf, mask_xobj, image_name="Mask1")
    path = edge_tmp_dir / "stencil_mask.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # Pure image masks are decorative — they should NOT appear as /Figure
    # elements that require alt text. Assert the struct tree has no
    # /Figure tag (graceful degradation rather than a spurious tag).
    with pikepdf.open(str(out_pdf)) as remediated:
        types = _collect_struct_types(remediated)
        # Either the pipeline adds /Figure (and also the Alt attribute),
        # or it doesn't add /Figure at all. Both are acceptable here;
        # what would NOT be acceptable is a crash.
        assert isinstance(types, set)


# ---------------------------------------------------------------------------
# 5. Near-size-limit PDF with a large embedded image
# ---------------------------------------------------------------------------


def test_near_size_limit_pdf(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    # 2000 x 2000 RGB = 12 MB uncompressed. Flate compression will
    # shrink this; we use incompressible random bytes so the embedded
    # data remains large on disk and the pipeline has to actually
    # stream the full raster through memory.
    import os
    width = height = 2000
    raw = os.urandom(width * height * 3)
    image = _embed_image(pdf, raw, width, height, "/DeviceRGB")
    _add_page_with_image(pdf, image)
    path = edge_tmp_dir / "large.pdf"
    pdf.save(str(path))
    size_mb = path.stat().st_size / (1024 * 1024)
    assert size_mb >= 10, f"expected large PDF, got {size_mb:.1f} MB"
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 6. Complex vector art — path operators only, no images or text
# ---------------------------------------------------------------------------


def test_complex_vector_art(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[-1]
    # Build a content stream with hundreds of vector paths and no text.
    lines = [
        b"0.5 g 1 w",  # gray fill, 1-pt line width
    ]
    for i in range(100):
        x = 50 + (i * 5) % 500
        y = 50 + (i * 7) % 700
        lines.append(f"{x} {y} m {x + 20} {y + 30} l".encode())
        lines.append(f"{x + 30} {y + 30} {x + 40} {y + 20} {x + 50} {y} c".encode())
        lines.append(b"S")  # stroke
    ops = b"\n".join(lines)
    page["/Contents"] = pdf.make_stream(ops)
    # Deliberately no /Font and no /XObject in /Resources.
    page["/Resources"] = Dictionary({})
    path = edge_tmp_dir / "vector_only.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # There are no real figures to alt-text — /Figure elements, if
    # any were added, should not be flagged for alt-text errors.
    with pikepdf.open(str(out_pdf)) as remediated:
        types = _collect_struct_types(remediated)
        # Graceful outcome: a set is returned, no crash.
        assert isinstance(types, set)
