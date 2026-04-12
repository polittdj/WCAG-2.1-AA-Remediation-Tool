"""Smoke tests for app.py.

The Gradio UI itself is exercised manually; these tests cover the
process_files_core() entry point that the UI delegates to and a few
small invariants (constants, ZIP packaging, error rows).
"""

from __future__ import annotations

import pathlib
import sys
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Import the app module — this also acts as a smoke check that all
# Gradio + pipeline imports succeed.
import app  # noqa: E402
from app import (  # noqa: E402
    KNOWN_LIMITATIONS_MD,
    PRIVACY_NOTICE_MD,
    RESULT_HEADERS,
    _row_for,
    process_files_core,
)

TEST_SUITE = ROOT / "test_suite"

GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"


def test_constants_match_spec() -> None:
    assert "Privacy Notice" in PRIVACY_NOTICE_MD
    assert "processed locally" in PRIVACY_NOTICE_MD
    assert "external server" in PRIVACY_NOTICE_MD
    assert "Alt text for images requires human review" in KNOWN_LIMITATIONS_MD
    assert "Password-protected PDFs" in KNOWN_LIMITATIONS_MD
    # Headers are derived from pipeline.CRITICAL_CHECKPOINTS
    from pipeline import CRITICAL_CHECKPOINTS

    assert ["Filename", "Result", *CRITICAL_CHECKPOINTS] == RESULT_HEADERS


def test_build_ui_does_not_crash() -> None:
    demo = app.build_ui()
    assert demo is not None


def test_process_files_core_single_pdf(tmp_path: pathlib.Path) -> None:
    rows, combined_zip, errs = process_files_core([str(GOOD)], work_root=tmp_path)
    assert errs == [], errs
    assert len(rows) == 1
    row = rows[0]
    assert row[0] == GOOD.name
    assert row[1] == "PASS"
    # All critical checkpoint columns should be PASS or NOT_APPLICABLE.
    for cell in row[2:]:
        assert cell in ("PASS", "NOT_APPLICABLE"), f"unexpected checkpoint value: {cell}"

    assert combined_zip is not None
    zip_path = pathlib.Path(combined_zip)
    assert zip_path.exists()
    assert zip_path.name.startswith("WCAG_Compliance_Results_")
    assert zip_path.name.endswith(".zip")
    with zipfile.ZipFile(str(zip_path)) as zf:
        names = zf.namelist()
    # Combined ZIP is FLAT — one output PDF + one HTML report per input,
    # no nested zips, no subdirectories.
    assert len(names) == 2, f"expected 2 flat entries, got {names}"
    pdfs_out = [n for n in names if n.lower().endswith(".pdf")]
    html_out = [n for n in names if n.lower().endswith((".html", ".htm"))]
    assert len(pdfs_out) == 1, f"expected 1 PDF entry, got {pdfs_out}"
    assert len(html_out) == 1, f"expected 1 HTML entry, got {html_out}"
    # No nested ZIPs
    for n in names:
        assert not n.lower().endswith(".zip"), f"nested zip in combined: {n}"
        assert "/" not in n, f"directory entry: {n}"


def test_process_files_core_multiple_pdfs(tmp_path: pathlib.Path) -> None:
    rows, combined_zip, errs = process_files_core([str(GOOD), str(TRAVEL)], work_root=tmp_path)
    assert errs == [], errs
    assert len(rows) == 2
    results = {row[0]: row[1] for row in rows}
    assert results[GOOD.name] == "PASS"
    assert results[TRAVEL.name] == "PASS"
    assert combined_zip is not None
    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
    # Combined ZIP is FLAT — 2 PDFs + 2 HTML reports, no nesting.
    assert len(names) == 4, f"expected 4 flat entries, got {names}"
    assert len(set(names)) == 4, f"duplicate arcnames: {names}"
    pdfs_out = [n for n in names if n.lower().endswith(".pdf")]
    html_out = [n for n in names if n.lower().endswith((".html", ".htm"))]
    assert len(pdfs_out) == 2, f"expected 2 PDF entries, got {pdfs_out}"
    assert len(html_out) == 2, f"expected 2 HTML entries, got {html_out}"
    for n in names:
        assert not n.lower().endswith(".zip"), f"nested zip: {n}"
        assert "/" not in n, f"directory entry: {n}"


def test_error_row_format() -> None:
    err_res = {"result": "ERROR", "checkpoints": [], "errors": ["boom"]}
    row = _row_for("foo.pdf", err_res)
    assert row[0] == "foo.pdf"
    assert row[1] == "ERROR"
    # Empty checkpoint cells fall back to "—"
    assert row[2] == "—"


def test_no_files_returns_empty(tmp_path: pathlib.Path) -> None:
    rows, combined_zip, errs = process_files_core([], work_root=tmp_path)
    assert rows == []
    assert combined_zip is None
    assert errs == []
