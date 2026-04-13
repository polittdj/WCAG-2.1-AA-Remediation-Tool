"""Malformed PDF edge-case tests.

Every input PDF in this module is generated programmatically (with pikepdf
or by hand-rolling raw bytes) so the suite runs in any environment without
committing binary fixtures.

The contract under test for ``pipeline.run_pipeline``:

* Must never raise an unhandled exception — always returns a dict.
* Must never leak a raw Python traceback into ``result["errors"]``; users
  see clean error messages, not stack dumps.
* Must not hang or blow the recursion limit on pathological structures.
* For clearly-bogus inputs (empty file, wrong signature, etc.) must
  reject the file and surface a non-empty ``errors`` list with a
  non-PASS result.
"""

from __future__ import annotations

import io
import pathlib

import pikepdf


# ---------------------------------------------------------------------------
# Raw-byte helpers
# ---------------------------------------------------------------------------


def _valid_pdf_bytes() -> bytes:
    """Return raw bytes of a minimal valid 1-page PDF built with pikepdf."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    buf = io.BytesIO()
    pdf.save(buf)
    return buf.getvalue()


def _build_raw_pdf(object_bodies: list[bytes]) -> bytes:
    """Hand-roll a minimal PDF from a list of object body strings.

    ``object_bodies`` is 1-indexed: entry 0 becomes object ``1 0 obj``,
    entry 1 becomes ``2 0 obj``, etc. The first object is always used
    as /Root in the trailer, so callers typically make object 1 the
    /Catalog.
    """
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    parts: list[bytes] = [header]
    offsets: list[int] = []
    for i, body in enumerate(object_bodies, start=1):
        offsets.append(sum(len(p) for p in parts))
        parts.append(f"{i} 0 obj\n".encode() + body + b"\nendobj\n")
    xref_offset = sum(len(p) for p in parts)
    parts.append(f"xref\n0 {len(object_bodies) + 1}\n".encode())
    parts.append(b"0000000000 65535 f \n")
    for off in offsets:
        parts.append(f"{off:010d} 00000 n \n".encode())
    parts.append(
        (
            f"trailer\n<< /Size {len(object_bodies) + 1} /Root 1 0 R >>\n"
            f"startxref\n{xref_offset}\n%%EOF\n"
        ).encode()
    )
    return b"".join(parts)


# ---------------------------------------------------------------------------
# Assertion helpers
# ---------------------------------------------------------------------------


def _assert_graceful(result) -> None:
    """Pipeline contract: dict back, no raw traceback in errors."""
    assert isinstance(result, dict), (
        f"run_pipeline returned {type(result).__name__}, not a dict"
    )
    assert "result" in result
    assert "errors" in result
    assert isinstance(result["errors"], list)
    for err in result["errors"]:
        assert "Traceback (most recent call last)" not in err, (
            "raw Python traceback leaked into result['errors']:\n"
            + err[:500]
        )


def _assert_rejected_at_intake(result) -> None:
    """Stricter contract: errors populated and never a false PASS."""
    _assert_graceful(result)
    assert result["result"] != "PASS", (
        f"malformed file was graded PASS: {result.get('result')}"
    )
    assert result["errors"], (
        "expected run_pipeline to surface at least one error for a "
        "clearly-bogus input"
    )


# ---------------------------------------------------------------------------
# 1. Truncated stream — chop the last 500 bytes off a valid PDF
# ---------------------------------------------------------------------------


def test_truncated_stream(edge_tmp_dir, make_valid_pdf, run_through_pipeline):
    pdf_path = make_valid_pdf(edge_tmp_dir / "truncated.pdf")
    data = pdf_path.read_bytes()
    assert len(data) > 600, (
        f"baseline PDF too small to meaningfully truncate: {len(data)} bytes"
    )
    pdf_path.write_bytes(data[:-500])
    result = run_through_pipeline(pdf_path, edge_tmp_dir / "out")
    _assert_graceful(result)
    # A heavily truncated PDF should never be graded PASS.
    assert result["result"] != "PASS"


# ---------------------------------------------------------------------------
# 2. Self-referencing /Parent — page dict whose /Parent points to itself
# ---------------------------------------------------------------------------


def test_self_referencing_parent(edge_tmp_dir, run_through_pipeline):
    body1 = b"<< /Type /Catalog /Pages 2 0 R >>"
    body2 = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    # Page object whose /Parent is a self-reference.
    body3 = (
        b"<< /Type /Page /Parent 3 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> >>"
    )
    p = edge_tmp_dir / "self_ref_parent.pdf"
    p.write_bytes(_build_raw_pdf([body1, body2, body3]))
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 3. Damaged xref table — overwrite xref entries with zeros
# ---------------------------------------------------------------------------


def test_damaged_xref_table(edge_tmp_dir, make_valid_pdf, run_through_pipeline):
    pdf_path = make_valid_pdf(edge_tmp_dir / "bad_xref.pdf")
    data = bytearray(pdf_path.read_bytes())
    xref_pos = data.find(b"xref")
    trailer_pos = data.find(b"trailer")
    assert xref_pos != -1 and trailer_pos != -1, "baseline PDF missing xref/trailer"
    # Overwrite the xref entry bytes (preserve newlines so the parser can
    # still find the trailer).
    for i in range(xref_pos + 5, trailer_pos):
        if data[i] != 0x0A:
            data[i] = ord("0")
    pdf_path.write_bytes(bytes(data))
    result = run_through_pipeline(pdf_path, edge_tmp_dir / "out")
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 4. Wrong file signature — JPEG bytes with a .pdf extension
# ---------------------------------------------------------------------------


def test_wrong_file_signature(edge_tmp_dir, run_through_pipeline):
    p = edge_tmp_dir / "actually_jpeg.pdf"
    p.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 64
    )
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_rejected_at_intake(result)


# ---------------------------------------------------------------------------
# 5. Inflated /Pages /Count — Count claims 999999 but there is 1 real page
# ---------------------------------------------------------------------------


def test_inflated_page_count(edge_tmp_dir, make_valid_pdf, run_through_pipeline):
    src = make_valid_pdf(edge_tmp_dir / "src.pdf")
    dst = edge_tmp_dir / "inflated.pdf"
    with pikepdf.open(str(src)) as pdf:
        pdf.Root.Pages.Count = 999999
        pdf.save(str(dst))
    result = run_through_pipeline(dst, edge_tmp_dir / "out")
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 6. Empty file — zero bytes
# ---------------------------------------------------------------------------


def test_empty_file(edge_tmp_dir, run_through_pipeline):
    p = edge_tmp_dir / "empty.pdf"
    p.write_bytes(b"")
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_rejected_at_intake(result)


# ---------------------------------------------------------------------------
# 7. Single null byte
# ---------------------------------------------------------------------------


def test_single_byte_file(edge_tmp_dir, run_through_pipeline):
    p = edge_tmp_dir / "one_byte.pdf"
    p.write_bytes(b"\x00")
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_rejected_at_intake(result)


# ---------------------------------------------------------------------------
# 8. Header only — %PDF-1.7 with no objects, xref, or trailer
# ---------------------------------------------------------------------------


def test_header_only_no_objects(edge_tmp_dir, run_through_pipeline):
    p = edge_tmp_dir / "header_only.pdf"
    p.write_bytes(b"%PDF-1.7\n")
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_rejected_at_intake(result)


# ---------------------------------------------------------------------------
# 9. Deeply nested dictionary — 500 levels of nesting
# ---------------------------------------------------------------------------


def test_deeply_nested_dictionary(edge_tmp_dir, run_through_pipeline):
    depth = 500
    nested = b"42"
    for _ in range(depth):
        nested = b"<< /K " + nested + b" >>"
    body1 = b"<< /Type /Catalog /Pages 2 0 R /Deep " + nested + b" >>"
    body2 = b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>"
    body3 = (
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> >>"
    )
    p = edge_tmp_dir / "deep_dict.pdf"
    p.write_bytes(_build_raw_pdf([body1, body2, body3]))
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_graceful(result)


# ---------------------------------------------------------------------------
# 10. Duplicate object numbers — two different objects share "3 0 obj"
# ---------------------------------------------------------------------------


def test_duplicate_object_numbers(edge_tmp_dir, run_through_pipeline):
    header = b"%PDF-1.7\n%\xe2\xe3\xcf\xd3\n"
    parts: list[bytes] = [header]

    def _add(body: bytes, num: int) -> int:
        off = sum(len(p) for p in parts)
        parts.append(f"{num} 0 obj\n".encode() + body + b"\nendobj\n")
        return off

    o1_off = _add(b"<< /Type /Catalog /Pages 2 0 R >>", 1)
    o2_off = _add(b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>", 2)
    _add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> >>",
        3,
    )
    # Declare object 3 a second time — this is the malformation.
    o3_dup_off = _add(
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] "
        b"/Resources << >> >>",
        3,
    )

    xref_offset = sum(len(p) for p in parts)
    parts.append(b"xref\n0 4\n")
    parts.append(b"0000000000 65535 f \n")
    parts.append(f"{o1_off:010d} 00000 n \n".encode())
    parts.append(f"{o2_off:010d} 00000 n \n".encode())
    parts.append(f"{o3_dup_off:010d} 00000 n \n".encode())
    parts.append(b"trailer\n<< /Size 4 /Root 1 0 R >>\n")
    parts.append(f"startxref\n{xref_offset}\n%%EOF\n".encode())

    p = edge_tmp_dir / "dup_obj_num.pdf"
    p.write_bytes(b"".join(parts))
    result = run_through_pipeline(p, edge_tmp_dir / "out")
    _assert_graceful(result)
