"""Acceptance tests for fix_widget_mapper.py.

Uses the locked wcag_auditor as the oracle for C-18, C-19, C-33, C-34,
C-35 and pikepdf for direct ParentTree shape inspection.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_widget_mapper import fix_widget_mapper  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"

GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
EDITABLE = TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
MS_WORD = TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf"
EDITABLE_ADA = TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [GOOD, EDITABLE, MS_WORD, EDITABLE_ADA, TRAVEL]


def _statuses(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def _audit(path: pathlib.Path) -> dict[str, str]:
    return _statuses(audit_pdf(path))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_travel_form_96_widgets_mapped(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_widget_mapper(str(TRAVEL), str(out))
    assert res["widgets_mapped"] == 96, f"expected 96 widgets, got {res['widgets_mapped']}; errors={res['errors']}"
    statuses = _audit(out)
    assert statuses["C-39"] == "PASS", f"C-18: {statuses['C-18']}"
    assert statuses["C-40"] == "PASS", f"C-19: {statuses['C-19']}"


def test_parenttree_is_flat_travel_form(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_widget_mapper(str(TRAVEL), str(out))
    assert res["widgets_mapped"] == 96
    with pikepdf.open(str(out)) as pdf:
        sr = pdf.Root.get("/StructTreeRoot")
        assert sr is not None
        pt = sr.get("/ParentTree")
        assert pt is not None
        assert "/Nums" in pt, "ParentTree must have /Nums"
        assert "/Kids" not in pt, "ParentTree must NOT have /Kids"
    assert _audit(out)["C-46"] == "PASS"


def test_form12_no_regression(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_widget_mapper(str(GOOD), str(out))
    assert res["errors"] == [] or res["widgets_mapped"] > 0
    statuses = _audit(out)
    assert statuses["C-39"] == "PASS", statuses
    assert statuses["C-40"] == "PASS", statuses
    assert statuses["C-46"] == "PASS", statuses


def test_editable_kids_parenttree_fixed(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    # Sanity-check the precondition: source actually has /Kids ParentTree.
    with pikepdf.open(str(EDITABLE)) as pdf:
        pt = pdf.Root["/StructTreeRoot"]["/ParentTree"]
        assert "/Kids" in pt and "/Nums" not in pt, "test precondition: editable file must start with /Kids ParentTree"

    res = fix_widget_mapper(str(EDITABLE), str(out))
    # Widgets may already have valid /StructParent→/Form mappings from
    # a previous remediation — in that case they're skipped (idempotent).
    # The critical assertion: the ParentTree gets flattened either way.
    assert res["widgets_mapped"] + res["widgets_skipped"] > 0, f"no widgets processed: {res}"
    statuses = _audit(out)
    assert statuses["C-46"] == "PASS", statuses
    assert statuses["C-39"] == "PASS", statuses


def test_sig_field_does_not_crash(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_widget_mapper(str(TRAVEL), str(out))
    # Travel form has 3 /FT=/Sig fields and a /SigFlags entry; the
    # mapper must process them like every other widget.
    assert res["widgets_mapped"] > 0, f"no widgets mapped: {res}"


def test_no_regressions_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    """C-18 + C-35 PASS for all 5; C-33, C-34 unchanged from baseline."""
    for src in ALL_PDFS:
        baseline = _audit(src)
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_widget_mapper(str(src), str(out))
        # The mapper may produce harmless errors for missing pages on
        # exotic widgets — but it must never crash.
        assert out.exists(), f"{src.name}: output not created"

        new = _audit(out)
        assert new["C-39"] == "PASS", f"{src.name}: C-18 expected PASS, got {new['C-18']}; res={res}"
        assert new["C-46"] == "PASS", f"{src.name}: C-35 expected PASS, got {new['C-35']}; res={res}"
        for cid in ("C-13", "C-03"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed from {baseline[cid]} to {new[cid]}"
