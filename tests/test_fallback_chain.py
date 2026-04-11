"""Tests for library fallback chains — Section 8 requirement.

Verifies that PDF operations handle errors gracefully.
"""

from __future__ import annotations
import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wcag_auditor import audit_pdf
from pipeline import run_pipeline


def test_corrupt_pdf_returns_indeterminate(tmp_path: pathlib.Path) -> None:
    """Corrupt files should return INDETERMINATE, not crash."""
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"NOT A REAL PDF FILE AT ALL")
    r = audit_pdf(bad)
    for c in r["checkpoints"]:
        assert c["status"] == "INDETERMINATE"


def test_truncated_pdf_handled(tmp_path: pathlib.Path) -> None:
    """Truncated PDF should be handled gracefully."""
    truncated = tmp_path / "truncated.pdf"
    truncated.write_bytes(b"%PDF-1.4\n1 0 obj\n<<\n/Type /Catalog\n")
    r = audit_pdf(truncated)
    for c in r["checkpoints"]:
        assert c["status"] == "INDETERMINATE"


def test_zero_byte_file(tmp_path: pathlib.Path) -> None:
    """Zero-byte file should not crash."""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    r = audit_pdf(empty)
    for c in r["checkpoints"]:
        assert c["status"] == "INDETERMINATE"


def test_nonexistent_file(tmp_path: pathlib.Path) -> None:
    """Nonexistent file should not crash."""
    r = audit_pdf(tmp_path / "does_not_exist.pdf")
    for c in r["checkpoints"]:
        assert c["status"] == "INDETERMINATE"


def test_pipeline_corrupt_returns_partial(tmp_path: pathlib.Path) -> None:
    """Pipeline should return PARTIAL for corrupt files, not crash."""
    bad = tmp_path / "bad.pdf"
    bad.write_bytes(b"GARBAGE DATA")
    res = run_pipeline(str(bad), str(tmp_path / "out"))
    assert res["result"] == "PARTIAL"
    assert len(res["errors"]) > 0


def test_pipeline_encrypted_returns_partial(tmp_path: pathlib.Path) -> None:
    """Pipeline should handle encrypted PDFs gracefully."""
    enc = tmp_path / "encrypted.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(str(enc), encryption=pikepdf.Encryption(owner="o", user="u", R=4))
    res = run_pipeline(str(enc), str(tmp_path / "out"))
    assert res["result"] == "PARTIAL"
    assert any("password" in e.lower() for e in res["errors"])


def test_pikepdf_and_fitz_both_open_valid_pdf(tmp_path: pathlib.Path) -> None:
    """Both libraries should open the same valid PDF."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Fallback Test"
    p = tmp_path / "valid.pdf"
    pdf.save(str(p))

    # pikepdf
    with pikepdf.open(str(p)) as pk:
        assert len(pk.pages) == 1

    # fitz
    import fitz

    doc = fitz.open(str(p))
    assert doc.page_count == 1
    doc.close()


def test_auditor_never_crashes_on_any_test_pdf(tmp_path: pathlib.Path) -> None:
    """Auditor should never raise an exception on any input."""
    test_suite = ROOT / "test_suite"
    for pdf_file in sorted(test_suite.glob("*.pdf")):
        r = audit_pdf(pdf_file)
        assert "checkpoints" in r, f"Auditor crashed on {pdf_file.name}"
        assert len(r["checkpoints"]) == 47, f"Wrong checkpoint count on {pdf_file.name}"
