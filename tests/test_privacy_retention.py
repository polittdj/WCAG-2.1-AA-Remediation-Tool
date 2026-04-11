"""Tests for data privacy and retention — Section 8 requirement.

Verifies that no uploaded files persist after pipeline processing.
"""

from __future__ import annotations
import os
import pathlib
import sys
import tempfile

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline


def _make_pdf(tmp_path: pathlib.Path, name: str = "input.pdf") -> pathlib.Path:
    p = tmp_path / name
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Privacy Test"
    pdf.save(str(p))
    return p


def test_source_file_not_deleted(tmp_path: pathlib.Path) -> None:
    """Pipeline must NOT delete the original input file."""
    src = _make_pdf(tmp_path, "source.pdf")
    out = tmp_path / "output"
    run_pipeline(str(src), str(out))
    assert src.exists(), "Pipeline deleted the original source file"


def test_temp_files_cleaned_up(tmp_path: pathlib.Path) -> None:
    """Pipeline temp directory should be cleaned up after processing."""
    src = _make_pdf(tmp_path)
    out = tmp_path / "output"
    # Count wcag_pipe_ dirs before
    before = set(pathlib.Path(tempfile.gettempdir()).glob("wcag_pipe_*"))
    run_pipeline(str(src), str(out))
    after = set(pathlib.Path(tempfile.gettempdir()).glob("wcag_pipe_*"))
    new_dirs = after - before
    assert len(new_dirs) == 0, f"Pipeline left temp dirs: {new_dirs}"


def test_output_dir_contains_only_expected_files(tmp_path: pathlib.Path) -> None:
    """Output directory should only contain the expected output files."""
    src = _make_pdf(tmp_path)
    out = tmp_path / "output"
    res = run_pipeline(str(src), str(out))
    if res["result"] in ("PASS", "PARTIAL"):
        files = list(out.iterdir())
        extensions = {f.suffix for f in files}
        # Only .pdf, .html, .zip expected
        assert extensions.issubset({".pdf", ".html", ".zip"}), f"Unexpected file types in output: {extensions}"


def test_no_content_in_error_messages(tmp_path: pathlib.Path) -> None:
    """Error messages should not contain file content."""
    src = _make_pdf(tmp_path)
    out = tmp_path / "output"
    res = run_pipeline(str(src), str(out))
    for err in res.get("errors", []):
        # Error messages should not contain PDF binary data
        assert b"%PDF" not in err.encode("utf-8", errors="replace"), "Error message contains PDF binary data"
