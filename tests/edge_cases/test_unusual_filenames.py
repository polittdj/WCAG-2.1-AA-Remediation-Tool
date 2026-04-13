"""Unusual-filename edge-case tests.

Each test writes a simple valid 1-page PDF under an unusual filename and
verifies that ``pipeline.run_pipeline``:

  1. Never crashes (always returns a dict, no raw traceback).
  2. Produces an output PDF whose stem ends with ``_WGAC_2.1_AA_Compliant``
     or ``_WGAC_2.1_AA_PARTIAL``.
  3. Keeps every output file inside the caller-specified output directory.
  4. Escapes the filename when rendering it in the HTML report.

Every input PDF is generated programmatically via the ``make_valid_pdf``
fixture from ``tests/edge_cases/conftest.py``.
"""

from __future__ import annotations

import pathlib


_APPROVED_SUFFIXES = ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL")


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


def _assert_report_escapes(result, *dangerous: str) -> None:
    report_path = result.get("report_html", "")
    assert report_path, "pipeline produced no HTML report"
    report = pathlib.Path(report_path)
    assert report.exists(), f"report path does not exist: {report}"
    html = report.read_text(encoding="utf-8", errors="replace")
    for s in dangerous:
        if s:
            assert s not in html, (
                f"HTML report contains unescaped dangerous string: {s!r}"
            )


# ---------------------------------------------------------------------------
# 1. Path traversal — ../../../etc/passwd.pdf
# ---------------------------------------------------------------------------


def test_path_traversal_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    # Create an innocent file, then pass a traversal-shaped path.
    # pathlib.Path.resolve() should canonicalize the path back to the
    # real file and the output must stay inside ``out``.
    make_valid_pdf(edge_tmp_dir / "innocent.pdf")
    nested = edge_tmp_dir / "a" / "b" / "c"
    nested.mkdir(parents=True)
    traversal = str(nested / ".." / ".." / ".." / "innocent.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(traversal, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 2. Markup in filename — <script>alert(1)</script>.pdf
# ---------------------------------------------------------------------------


def test_markup_in_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    name = "<script>alert(1)</script>.pdf"
    pdf = make_valid_pdf(edge_tmp_dir / name)
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)
    _assert_report_escapes(result, "<script>alert(1)</script>")


# ---------------------------------------------------------------------------
# 3. Tabs in filename
# ---------------------------------------------------------------------------


def test_tab_characters_in_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "file\twith\ttabs.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 4. Accented characters
# ---------------------------------------------------------------------------


def test_accented_characters(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "résumé_très_spécial.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 5. Cyrillic
# ---------------------------------------------------------------------------


def test_cyrillic_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "файл_документ.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 6. CJK
# ---------------------------------------------------------------------------


def test_cjk_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "文件报告.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 7. Extension only — .pdf
# ---------------------------------------------------------------------------


def test_extension_only(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / ".pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 8. Max path length — 255-byte input filename
# ---------------------------------------------------------------------------


def test_max_path_length(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    # 251-char stem + ".pdf" = 255 bytes, the POSIX filename limit.
    # After the ``_WGAC_2.1_AA_Compliant`` suffix is appended the raw name
    # would exceed 255 bytes, so the pipeline must truncate gracefully.
    stem = "a" * 251
    pdf = make_valid_pdf(edge_tmp_dir / f"{stem}.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    out_pdf = _assert_output_produced(result, out)
    assert len(out_pdf.name.encode("utf-8")) <= 255, (
        f"output filename {len(out_pdf.name)} bytes exceeds 255 POSIX limit: "
        f"{out_pdf.name!r}"
    )


# ---------------------------------------------------------------------------
# 9. Null byte in filename
# ---------------------------------------------------------------------------


def test_null_byte_in_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    # Linux filesystems reject embedded null bytes in paths — Python will
    # raise ValueError when asked to construct a Path from such a string.
    # The pipeline must catch that and surface a clean error instead of
    # propagating the exception.
    real = make_valid_pdf(edge_tmp_dir / "real.pdf")
    bogus_path = str(real) + "\x00hidden"
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(bogus_path, out)
    _assert_graceful(result)
    assert result.get("errors"), (
        "expected run_pipeline to surface a clean error for a null-byte filename"
    )


# ---------------------------------------------------------------------------
# 10. Windows reserved name — CON.pdf
# ---------------------------------------------------------------------------


def test_windows_reserved_name(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "CON.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 11. Quotes in filename
# ---------------------------------------------------------------------------


def test_quotes_in_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    name = "file with \"quotes\" and 'apostrophes'.pdf"
    pdf = make_valid_pdf(edge_tmp_dir / name)
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)
    # The raw quoted substring must not appear verbatim in the HTML report
    # (if it did, the filename would break out of its HTML attribute/text).
    report = pathlib.Path(result["report_html"]).read_text(
        encoding="utf-8", errors="replace",
    )
    assert 'file with "quotes" and \'apostrophes\'' not in report, (
        "filename with quotes was not HTML-escaped in the report"
    )


# ---------------------------------------------------------------------------
# 12. URL-encoded filename
# ---------------------------------------------------------------------------


def test_url_encoded_filename(
    edge_tmp_dir, make_valid_pdf, run_through_pipeline,
):
    pdf = make_valid_pdf(edge_tmp_dir / "file%20encoded%2Fname.pdf")
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(pdf, out)
    _assert_output_produced(result, out)
