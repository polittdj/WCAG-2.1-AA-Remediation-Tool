"""Regression tests for the 4 issues reported in Round 2 of the audit.

Each test maps 1:1 to a reported issue:

1. 09_fake_lists: bullets and numbered prefixes drawn as separate Tj
   operators (widely-separated X) should still produce /L, /LI, /Lbl,
   /LBody tags. Also verifies /Tabs=/S on every page.
2. 04_table_no_headers: tables must have full /Table > /TR > /TH + /TD
   hierarchy. Spurious single-row tables from mis-detection must be
   rejected.
3. 03_images_no_alt_text: images must get /Figure tags unconditionally,
   even when table detection runs first.
4. Flat ZIP output: 3+ files batched produce a flat ZIP with no
   nested .zip entries and no subdirectories.
"""

from __future__ import annotations

import pathlib
import shutil
import tempfile
import zipfile
from typing import Any

import pikepdf
import pytest

from app import process_files_core
from pipeline import run_pipeline

AUDIT_V2 = pathlib.Path(__file__).parent / "audit_pdfs_v2"
AUDIT_V3 = pathlib.Path(__file__).parent / "audit_pdfs_v3"


@pytest.fixture(scope="module", autouse=True)
def _generate_adversarial_pdfs():
    """Generate v2 and v3 adversarial audit PDFs before tests run."""
    try:
        from tests.generate_audit_pdfs_v2 import generate_all as gen_v2
        gen_v2()
    except Exception as e:
        pytest.skip(f"v2 generator unavailable: {e}")
    try:
        from tests.generate_audit_pdfs_v3 import generate_all as gen_v3
        gen_v3()
    except Exception as e:
        pytest.skip(f"v3 generator unavailable: {e}")


def _count_tags(pdf: pikepdf.Pdf) -> dict[str, int]:
    counts: dict[str, int] = {}
    if "/StructTreeRoot" not in pdf.Root:
        return counts
    stack: list[Any] = [pdf.Root["/StructTreeRoot"].get("/K")]
    seen: set[tuple[int, int]] = set()
    while stack:
        n = stack.pop()
        if n is None:
            continue
        if isinstance(n, pikepdf.Array):
            for x in n:
                stack.append(x)
            continue
        if not isinstance(n, pikepdf.Dictionary):
            continue
        og = getattr(n, "objgen", None)
        if og is not None:
            if og in seen:
                continue
            seen.add(og)
        s = n.get("/S")
        if s is not None:
            tag = str(s).lstrip("/")
            counts[tag] = counts.get(tag, 0) + 1
        k = n.get("/K")
        if k is not None:
            stack.append(k)
    return counts


def _run(src: pathlib.Path):
    assert src.exists(), f"Missing: {src}"
    out_dir = pathlib.Path(tempfile.mkdtemp(prefix="round2_"))
    result = run_pipeline(str(src), str(out_dir))
    out_pdfs = list(out_dir.glob("*.pdf"))
    assert out_pdfs, f"No output PDF for {src.name}"
    return result, out_dir, out_pdfs[0]


# ---------------------------------------------------------------------------
# Issue 1: list tag detection + /Tabs on 09_fake_lists
# ---------------------------------------------------------------------------


class TestIssue1Lists:
    """Bullets and numbered prefixes drawn as separate Tj operators must
    still produce /L, /LI, /Lbl, /LBody tags."""

    def test_v2_bullets_and_numbered_both_detected(self):
        """v2: bullets on separate lines, numbered "1. text" on one line."""
        result, out_dir, out_pdf = _run(AUDIT_V2 / "09_fake_lists_no_structure.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # Both bullet list AND numbered list must be detected → 2 /L
            assert counts.get("L", 0) >= 2, f"Expected >=2 /L, got {counts}"
            assert counts.get("LI", 0) >= 10, f"Expected >=10 /LI, got {counts}"
            assert counts.get("Lbl", 0) >= 10, f"Expected >=10 /Lbl, got {counts}"
            assert counts.get("LBody", 0) >= 10, f"Expected >=10 /LBody, got {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_v3_every_glyph_separate_detected(self):
        """v3: both bullets AND numbered prefixes on separate lines.

        This is the worst case — every list-item prefix glyph is drawn
        in its own Tj at a widely-separated X. PyMuPDF's get_text('text')
        puts every prefix on its own line, separated from the body.
        The lookahead in _add_lists must still pair them correctly.
        """
        result, out_dir, out_pdf = _run(AUDIT_V3 / "09_fake_lists_no_structure.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            assert counts.get("L", 0) >= 2, f"Expected >=2 /L, got {counts}"
            assert counts.get("LI", 0) >= 10, f"Expected >=10 /LI, got {counts}"
            assert counts.get("Lbl", 0) >= 10, f"Expected >=10 /Lbl, got {counts}"
            assert counts.get("LBody", 0) >= 10, f"Expected >=10 /LBody, got {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_v2_tabs_s_on_every_page(self):
        """09_fake_lists must have /Tabs=/S on every page (user reported MISSING)."""
        result, out_dir, out_pdf = _run(AUDIT_V2 / "09_fake_lists_no_structure.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                for i, page in enumerate(pdf.pages):
                    tabs = page.get("/Tabs")
                    assert tabs is not None and str(tabs) == "/S", \
                        f"page {i}: /Tabs={tabs}, expected /S"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_v3_tabs_s_on_every_page(self):
        result, out_dir, out_pdf = _run(AUDIT_V3 / "09_fake_lists_no_structure.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                for i, page in enumerate(pdf.pages):
                    tabs = page.get("/Tabs")
                    assert tabs is not None and str(tabs) == "/S", \
                        f"page {i}: /Tabs={tabs}, expected /S"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Issue 2: full /Table > /TR > /TH + /TD hierarchy on 04_table_no_headers
# ---------------------------------------------------------------------------


class TestIssue2TableHierarchy:
    """Tables must get full /Table > /TR > /TH (first row) > /TD hierarchy."""

    def test_04_tables_has_full_hierarchy(self):
        result, out_dir, out_pdf = _run(AUDIT_V2 / "04_table_no_headers.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # Expect at least 1 /Table AND at least 2 /TR AND some TH/TD
            assert counts.get("Table", 0) >= 1, f"Missing /Table: {counts}"
            assert counts.get("TR", 0) >= 2, f"Too few /TR: {counts}"
            # TH only on header rows
            assert counts.get("TH", 0) >= 2, f"Missing /TH header cells: {counts}"
            # TD on data rows
            assert counts.get("TD", 0) >= 2, f"Missing /TD data cells: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)

    def test_tables_never_create_orphan_th(self):
        """Spurious single-row tables from image-heavy pages must be
        rejected (no orphan /TH without /Table + /TR)."""
        result, out_dir, out_pdf = _run(AUDIT_V2 / "03_images_no_alt_text.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
            # An image PDF should have NO /TH and NO /TR — the
            # hardened _add_tables rejects tables with <2 rows or <2 cols.
            assert counts.get("TH", 0) == 0, \
                f"Spurious /TH on image PDF: {counts}"
            assert counts.get("TR", 0) == 0, \
                f"Spurious /TR on image PDF: {counts}"
            assert counts.get("Table", 0) == 0, \
                f"Spurious /Table on image PDF: {counts}"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Issue 3: /Figure unconditional on 03_images_no_alt_text
# ---------------------------------------------------------------------------


class TestIssue3Figures:
    """Images must ALWAYS get /Figure tags, regardless of what table
    detection does."""

    def test_03_images_has_3_figures(self):
        result, out_dir, out_pdf = _run(AUDIT_V2 / "03_images_no_alt_text.pdf")
        try:
            with pikepdf.open(str(out_pdf)) as pdf:
                counts = _count_tags(pdf)
                # Also check every /Figure has /Alt
                fig_no_alt = 0
                fig_total = 0
                stack: list[Any] = [pdf.Root["/StructTreeRoot"].get("/K")]
                seen: set[tuple[int, int]] = set()
                while stack:
                    n = stack.pop()
                    if n is None:
                        continue
                    if isinstance(n, pikepdf.Array):
                        for x in n:
                            stack.append(x)
                        continue
                    if not isinstance(n, pikepdf.Dictionary):
                        continue
                    og = getattr(n, "objgen", None)
                    if og is not None:
                        if og in seen:
                            continue
                        seen.add(og)
                    s = n.get("/S")
                    if s is not None and str(s).lstrip("/") == "Figure":
                        fig_total += 1
                        alt = n.get("/Alt")
                        if not alt or not str(alt).strip():
                            fig_no_alt += 1
                    k = n.get("/K")
                    if k is not None:
                        stack.append(k)
            assert counts.get("Figure", 0) >= 3, \
                f"Expected >=3 /Figure tags, got {counts}"
            assert fig_no_alt == 0, \
                f"{fig_no_alt}/{fig_total} Figures missing /Alt"
        finally:
            shutil.rmtree(str(out_dir), ignore_errors=True)


# ---------------------------------------------------------------------------
# Issue 4: flat ZIP output
# ---------------------------------------------------------------------------


class TestIssue4FlatZip:
    """Processing 3+ files must produce a flat ZIP (no nested .zip)."""

    def test_three_files_flat_zip(self, tmp_path):
        pdfs = []
        for name in ["one.pdf", "two.pdf", "three.pdf"]:
            p = tmp_path / name
            pdf = pikepdf.new()
            pdf.add_blank_page()
            pdf.save(str(p))
            pdfs.append(str(p))

        rows, combined_zip, errs = process_files_core(pdfs)
        assert combined_zip, f"No combined zip: {errs}"
        with zipfile.ZipFile(combined_zip) as zf:
            names = zf.namelist()
            assert names, "ZIP is empty"
            for n in names:
                assert not n.lower().endswith(".zip"), \
                    f"Nested ZIP entry: {n}"
                assert "/" not in n and "\\" not in n, \
                    f"Subdirectory entry: {n}"
                assert n.lower().endswith((".pdf", ".html", ".htm")), \
                    f"Unexpected file type: {n}"
            # 3 PDFs + 3 HTML reports = 6 entries
            pdfs_out = [n for n in names if n.lower().endswith(".pdf")]
            html_out = [n for n in names if n.lower().endswith((".html", ".htm"))]
            assert len(pdfs_out) == 3, f"Expected 3 output PDFs, got {pdfs_out}"
            assert len(html_out) == 3, f"Expected 3 output HTMLs, got {html_out}"

    def test_five_files_flat_zip(self, tmp_path):
        """Batch of 5 — double-check no surprises at larger batch sizes."""
        pdfs = []
        for i in range(5):
            p = tmp_path / f"file_{i}.pdf"
            pdf = pikepdf.new()
            pdf.add_blank_page()
            pdf.save(str(p))
            pdfs.append(str(p))

        rows, combined_zip, errs = process_files_core(pdfs)
        assert combined_zip
        with zipfile.ZipFile(combined_zip) as zf:
            names = zf.namelist()
            for n in names:
                assert not n.lower().endswith(".zip")
                assert "/" not in n
            assert len(names) == 10, f"Expected 10 flat entries, got {names}"
