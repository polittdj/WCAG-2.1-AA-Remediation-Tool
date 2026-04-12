"""Tests for the combined-ZIP output structure.

After a batch is processed, the user downloads ONE zip file. When
they unzip it, the remediated PDFs and HTML reports must be right
there — no nested zips, no confusing subdirectories.
"""

from __future__ import annotations

import pathlib
import tempfile
import zipfile

import pikepdf
import pytest

from app import process_files_core


def _make_pdfs(tmp_path: pathlib.Path, names: list[str]) -> list[str]:
    paths = []
    for name in names:
        p = tmp_path / name
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = name
        pdf.save(str(p))
        paths.append(str(p))
    return paths


def test_zip_output_is_flat(tmp_path: pathlib.Path) -> None:
    """Process 3 PDFs and assert the combined ZIP is flat.

    - No entry has a .zip extension (no nested zips).
    - No entry contains a path separator (no subdirectories).
    - All entries are .pdf or .html files.
    """
    pdfs = _make_pdfs(tmp_path, ["alpha.pdf", "beta.pdf", "gamma.pdf"])
    rows, combined_zip, errs = process_files_core(pdfs)

    assert combined_zip is not None, f"No combined zip produced. errs={errs}"
    assert pathlib.Path(combined_zip).exists()

    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
        assert names, "ZIP is empty"
        for name in names:
            # Rule 1: no nested zips
            assert not name.lower().endswith(".zip"), \
                f"Nested ZIP entry: {name}"
            # Rule 2: no subdirectories
            assert "/" not in name and "\\" not in name, \
                f"Entry has directory separator: {name}"
            # Rule 3: only PDF or HTML (optional summary permitted)
            lower = name.lower()
            assert lower.endswith((".pdf", ".html", ".htm")), \
                f"Unexpected file type in ZIP: {name}"


def test_zip_contains_one_pdf_and_one_html_per_input(tmp_path: pathlib.Path) -> None:
    """Each input PDF produces exactly one output PDF + one HTML report."""
    pdfs = _make_pdfs(tmp_path, ["one.pdf", "two.pdf"])
    rows, combined_zip, errs = process_files_core(pdfs)
    assert combined_zip is not None

    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
        pdfs_out = [n for n in names if n.lower().endswith(".pdf")]
        html_out = [n for n in names if n.lower().endswith((".html", ".htm"))]
        assert len(pdfs_out) == 2, f"Expected 2 output PDFs, got {pdfs_out}"
        assert len(html_out) == 2, f"Expected 2 output HTML reports, got {html_out}"


def test_zip_handles_duplicate_input_stems(tmp_path: pathlib.Path) -> None:
    """Two inputs with the same basename shouldn't overwrite each other.

    The combined ZIP must disambiguate with (1), (2), etc. so both
    outputs are preserved.
    """
    # Create two files with the same stem in different subdirs
    subdir_a = tmp_path / "a"
    subdir_b = tmp_path / "b"
    subdir_a.mkdir()
    subdir_b.mkdir()
    paths = []
    for sub in (subdir_a, subdir_b):
        p = sub / "report.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.save(str(p))
        paths.append(str(p))

    rows, combined_zip, errs = process_files_core(paths)
    assert combined_zip is not None

    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
        pdfs_out = sorted(n for n in names if n.lower().endswith(".pdf"))
        # Either two distinct names or disambiguated with (1) suffix
        assert len(pdfs_out) == 2, f"Expected 2 PDFs, got {pdfs_out}"
        # They must not be identical
        assert pdfs_out[0] != pdfs_out[1]


def test_zip_single_file_is_flat(tmp_path: pathlib.Path) -> None:
    """A single-file batch should also produce a flat ZIP."""
    pdfs = _make_pdfs(tmp_path, ["solo.pdf"])
    rows, combined_zip, errs = process_files_core(pdfs)
    assert combined_zip is not None

    with zipfile.ZipFile(combined_zip) as zf:
        names = zf.namelist()
        for name in names:
            assert not name.endswith(".zip")
            assert "/" not in name
        # Should have one PDF + one HTML
        assert any(n.endswith(".pdf") for n in names)
        assert any(n.endswith(".html") or n.endswith(".htm") for n in names)
