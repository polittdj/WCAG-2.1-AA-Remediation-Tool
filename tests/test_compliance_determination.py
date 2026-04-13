"""Tests for IRS-01 Fix 1 — correct compliance determination.

Rule: FAIL on ANY checkpoint → "PARTIAL".
MANUAL_REVIEW and NOT_APPLICABLE are not blockers.
No CRITICAL_CHECKPOINTS whitelist — any FAIL is a real failure.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import compute_overall, run_pipeline  # noqa: E402


# ---------------------------------------------------------------------------
# Unit tests for compute_overall()
# ---------------------------------------------------------------------------


def _cps(statuses: list[str]) -> list[dict]:
    """Build a minimal checkpoint list from a list of status strings."""
    return [{"id": f"C-{i+1:02d}", "status": s} for i, s in enumerate(statuses)]


def test_any_fail_means_partial():
    """A single FAIL on any checkpoint must produce PARTIAL."""
    results = _cps(["PASS"] * 46 + ["FAIL"])
    assert compute_overall(results) == "PARTIAL", (
        "Any checkpoint FAIL should produce PARTIAL — the document is not compliant."
    )


def test_any_fail_means_partial_first_checkpoint():
    """FAIL on the first checkpoint also triggers PARTIAL."""
    results = _cps(["FAIL"] + ["PASS"] * 46)
    assert compute_overall(results) == "PARTIAL"


def test_all_pass_means_pass():
    """All PASS checkpoints → PASS."""
    results = _cps(["PASS"] * 47)
    assert compute_overall(results) == "PASS"


def test_manual_review_does_not_block():
    """MANUAL_REVIEW checkpoints must not block PASS."""
    results = _cps(["PASS"] * 44 + ["MANUAL_REVIEW", "MANUAL_REVIEW", "MANUAL_REVIEW"])
    assert compute_overall(results) == "PASS", (
        "MANUAL_REVIEW should not prevent a PASS result — these require human verification."
    )


def test_not_applicable_does_not_block():
    """NOT_APPLICABLE checkpoints must not block PASS."""
    results = _cps(["PASS"] * 40 + ["NOT_APPLICABLE"] * 7)
    assert compute_overall(results) == "PASS", (
        "NOT_APPLICABLE should not prevent a PASS result."
    )


def test_mix_of_na_and_manual_review_no_fail():
    """Mixed NOT_APPLICABLE and MANUAL_REVIEW with no FAIL → PASS."""
    results = _cps(
        ["PASS"] * 30 + ["NOT_APPLICABLE"] * 10 + ["MANUAL_REVIEW"] * 7
    )
    assert compute_overall(results) == "PASS"


def test_fail_among_mix_means_partial():
    """FAIL mixed with MANUAL_REVIEW/NOT_APPLICABLE still yields PARTIAL."""
    results = _cps(
        ["PASS"] * 30 + ["NOT_APPLICABLE"] * 5 + ["MANUAL_REVIEW"] * 5 + ["FAIL"] * 7
    )
    assert compute_overall(results) == "PARTIAL"


def test_empty_checkpoints_returns_pass():
    """No checkpoints (e.g. auditor could not run) → PASS (no failures)."""
    assert compute_overall([]) == "PASS"


def test_non_critical_fail_still_blocks():
    """A FAIL on a formerly non-critical checkpoint must still block PASS."""
    # C-47 was not in the old CRITICAL_CHECKPOINTS whitelist.
    results = [{"id": f"C-{i:02d}", "status": "PASS"} for i in range(1, 47)]
    results.append({"id": "C-47", "status": "FAIL"})
    assert compute_overall(results) == "PARTIAL", (
        "compute_overall must treat FAIL on C-47 as blocking even though it was "
        "previously not in CRITICAL_CHECKPOINTS."
    )


def test_indeterminate_does_not_block():
    """INDETERMINATE (not FAIL) must not block PASS."""
    results = _cps(["PASS"] * 45 + ["INDETERMINATE", "INDETERMINATE"])
    assert compute_overall(results) == "PASS"


# ---------------------------------------------------------------------------
# Integration: pipeline result matches compute_overall
# ---------------------------------------------------------------------------


def test_pipeline_result_consistent_with_compute_overall(tmp_path):
    """run_pipeline result field must equal compute_overall(checkpoints)."""
    test_suite = ROOT / "test_suite"
    pdf_path = test_suite / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
    if not pdf_path.exists():
        pytest.skip("Reference PDF not available")

    res = run_pipeline(str(pdf_path), str(tmp_path))
    expected = compute_overall(res["checkpoints"])
    assert res["result"] == expected, (
        f"Pipeline result '{res['result']}' does not match "
        f"compute_overall() → '{expected}'"
    )


def test_pipeline_partial_when_any_checkpoint_fails(tmp_path):
    """A document that still has a FAIL checkpoint must produce PARTIAL output."""
    # TEST_12_broken_struct_tree.pdf reliably produces a FAIL on C-46 after
    # remediation (the ParentTree is too broken to fully repair).
    test_suite = ROOT / "test_suite"
    pdf_path = test_suite / "TEST_12_broken_struct_tree.pdf"
    if not pdf_path.exists():
        pytest.skip("TEST_12 fixture not available")

    res = run_pipeline(str(pdf_path), str(tmp_path))
    fail_ids = [c["id"] for c in res["checkpoints"] if c["status"] == "FAIL"]
    if not fail_ids:
        pytest.skip("TEST_12 produced no FAILs after remediation — fixture changed")

    assert res["result"] == "PARTIAL", (
        f"Pipeline should return PARTIAL when checkpoints {fail_ids} still FAIL"
    )


def test_output_filename_partial_when_any_fail(tmp_path):
    """Output filename must contain _PARTIAL (not _Compliant) when any FAIL remains."""
    test_suite = ROOT / "test_suite"
    pdf_path = test_suite / "TEST_12_broken_struct_tree.pdf"
    if not pdf_path.exists():
        pytest.skip("TEST_12 fixture not available")

    res = run_pipeline(str(pdf_path), str(tmp_path))
    fail_ids = [c["id"] for c in res["checkpoints"] if c["status"] == "FAIL"]
    if not fail_ids:
        pytest.skip("TEST_12 produced no FAILs — fixture changed")

    import pathlib

    out_pdf = pathlib.Path(res["output_pdf"])
    assert "_PARTIAL" in out_pdf.name, (
        f"Output filename '{out_pdf.name}' must contain '_PARTIAL' when FAILs remain"
    )
    assert "Compliant" not in out_pdf.name, (
        f"Output filename '{out_pdf.name}' must NOT contain 'Compliant' when FAILs remain"
    )
