"""Acceptance tests for fix_focus_order.py."""

from __future__ import annotations

import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_focus_order import fix_focus_order  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"
GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
# The "Compliant" Travel Form fixture already has /Tabs /S — we need
# the raw file to exercise the upgrade path.
TRAVEL_RAW = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [
    GOOD,
    TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf",
    TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf",
    TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf",
    TRAVEL,
]


def _statuses(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def test_raw_travel_form_tabs_upgraded_to_s(tmp_path: pathlib.Path) -> None:
    """Raw Travel Form ships with /Tabs /W; the fix must upgrade both pages to /S."""
    if not TRAVEL_RAW.exists():
        import pytest

        pytest.skip(f"raw fixture not present: {TRAVEL_RAW.name}")
    out = tmp_path / "out.pdf"
    # Precondition: at least one page has something other than /S.
    with pikepdf.open(str(TRAVEL_RAW)) as pdf:
        tabs_before = [str(page.get("/Tabs", "")) for page in pdf.pages]
    assert any(t != "/S" for t in tabs_before), f"precondition failed: {tabs_before}"

    res = fix_focus_order(str(TRAVEL_RAW), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["pages_modified"] > 0

    with pikepdf.open(str(out)) as pdf:
        for i, page in enumerate(pdf.pages):
            # Every page with /Annots must end up with /Tabs /S.
            if page.get("/Annots"):
                assert str(page.get("/Tabs")) == "/S", f"page {i} tabs={page.get('/Tabs')}"


def test_idempotent(tmp_path: pathlib.Path) -> None:
    """Running the fix twice is a no-op on the second pass."""
    first = tmp_path / "first.pdf"
    second = tmp_path / "second.pdf"
    fix_focus_order(str(TRAVEL), str(first))
    res2 = fix_focus_order(str(first), str(second))
    assert res2["errors"] == []
    # No page should need modification the second time.
    assert res2["pages_modified"] == 0


def test_page_without_annots_left_alone(tmp_path: pathlib.Path) -> None:
    """A blank page has no annotations; /Tabs should stay unset."""
    bare = tmp_path / "bare.pdf"
    p = pikepdf.new()
    p.add_blank_page(page_size=(612, 792))
    p.save(str(bare))
    p.close()

    out = tmp_path / "out.pdf"
    res = fix_focus_order(str(bare), str(out))
    assert res["errors"] == []
    assert res["pages_modified"] == 0
    assert res["pages_skipped"] == 1

    with pikepdf.open(str(out)) as pdf:
        assert pdf.pages[0].get("/Tabs") is None


def test_no_regressions_on_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    for src in ALL_PDFS:
        baseline = _statuses(audit_pdf(src))
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_focus_order(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        new = _statuses(audit_pdf(out))
        for cid in ("C-39", "C-13", "C-03", "C-46"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed"
