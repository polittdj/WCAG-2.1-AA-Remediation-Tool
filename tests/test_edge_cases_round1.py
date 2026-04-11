"""Edge case tests — Round 1 (GAP 6 requirement)."""

from __future__ import annotations
import json
import pathlib
import sys
import zipfile

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline
from app import process_files_core


def test_zip_contains_both_pdf_and_html_per_file(tmp_path):
    """ZIP should contain exactly one PDF and one HTML."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "ZIP Test"
    src = tmp_path / "ziptest.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    assert res["zip_path"]
    with zipfile.ZipFile(res["zip_path"]) as zf:
        names = zf.namelist()
    pdf_files = [n for n in names if n.endswith(".pdf")]
    html_files = [n for n in names if n.endswith(".html")]
    assert len(pdf_files) == 1, f"Expected 1 PDF in ZIP, got {pdf_files}"
    assert len(html_files) == 1, f"Expected 1 HTML in ZIP, got {html_files}"


def test_report_json_checkpoint_count_is_47(tmp_path):
    """Embedded JSON in HTML report must have exactly 47 checkpoints."""
    import re

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "JSON Count"
    src = tmp_path / "json.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    html = pathlib.Path(res["report_html"]).read_text()
    match = re.search(r'<script type="application/json" id="wcag-audit-data">\s*(.*?)\s*</script>', html, re.DOTALL)
    assert match, "JSON block not found"
    data = json.loads(match.group(1))
    assert len(data["checkpoints"]) == 47


def test_batch_of_one_file_still_works(tmp_path):
    """Single file through process_files_core should work."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Single Batch"
    src = tmp_path / "single.pdf"
    pdf.save(str(src))
    rows, combined_zip, errs = process_files_core([str(src)], work_root=tmp_path / "work")
    assert len(rows) == 1
    assert rows[0][1] in ("PASS", "PARTIAL")
    assert combined_zip is not None


def test_empty_batch_produces_error_not_crash(tmp_path):
    """Empty file list should return empty results without crashing."""
    rows, combined_zip, errs = process_files_core([], work_root=tmp_path)
    assert rows == []
    assert combined_zip is None
    assert errs == []


def test_special_chars_in_filename(tmp_path):
    """File with special characters should process without crash."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Special Chars"
    src = tmp_path / "file (1) - copy [final].pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    assert res["result"] in ("PASS", "PARTIAL")
    assert res["output_pdf"]
