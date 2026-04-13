"""Tests for IRS-01 Fix 2 — post-remediation re-audit.

The compliance report must describe the OUTPUT file, not the input.
Before BUG-07 was fixed the pipeline audited an intermediate file and
then applied further modifications (belt-and-suspenders /Tabs = /S),
so the report could describe a state that didn't match the output.

After BUG-07 the flow is:
  last_good → copy to final_candidate → /Tabs fix → audit → determine
  overall → copy to out_pdf_path.

Tests here verify that the report checkpoints reflect the actual output.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402


def _statuses(checkpoints: list[dict]) -> dict[str, str]:
    return {c["id"]: c["status"] for c in checkpoints}


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_report_reflects_output_not_input(tmp_path):
    """The pipeline report's C-10 must equal auditing the OUTPUT file directly.

    C-10 (tab order /Tabs = /S) is the checkpoint most likely to differ
    between an intermediate and the final output because the belt-and-
    suspenders /Tabs fix runs after all remediation steps.

    Before BUG-07: audit was on last_good (before /Tabs fix on out_pdf_path).
    After BUG-07:  audit is on final_candidate (after /Tabs fix, before copy).

    We verify that the C-10 status in the pipeline report matches a direct
    audit of the output PDF.
    """
    test_suite = ROOT / "test_suite"
    src = test_suite / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
    if not src.exists():
        pytest.skip("Reference PDF not available")

    out_dir = tmp_path / "out"
    res = run_pipeline(str(src), str(out_dir))
    assert "output_pdf" in res and res["output_pdf"], "pipeline must produce output_pdf"

    # Re-audit the output PDF independently
    out_pdf = pathlib.Path(res["output_pdf"])
    assert out_pdf.exists()
    direct_audit = audit_pdf(out_pdf)
    direct_statuses = _statuses(direct_audit["checkpoints"])
    pipeline_statuses = _statuses(res["checkpoints"])

    # C-10 must agree between the two audits
    c10_pipeline = pipeline_statuses.get("C-10")
    c10_direct = direct_statuses.get("C-10")
    assert c10_pipeline == c10_direct, (
        f"C-10 in pipeline report ({c10_pipeline}) differs from direct audit of "
        f"output ({c10_direct}).  BUG-07: audit must run on the final output file."
    )


def test_pipeline_report_matches_direct_audit_all_checkpoints(tmp_path):
    """Every checkpoint in the pipeline report must match a direct re-audit.

    If the pipeline audits before final modifications the statuses will
    diverge.  This test catches any such divergence across all checkpoints.
    """
    test_suite = ROOT / "test_suite"
    src = test_suite / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
    if not src.exists():
        pytest.skip("Reference PDF not available")

    out_dir = tmp_path / "out"
    res = run_pipeline(str(src), str(out_dir))
    out_pdf = pathlib.Path(res["output_pdf"])
    assert out_pdf.exists()

    direct_audit = audit_pdf(out_pdf)
    direct_statuses = _statuses(direct_audit["checkpoints"])
    pipeline_statuses = _statuses(res["checkpoints"])

    mismatches = []
    for cid, pipeline_st in pipeline_statuses.items():
        direct_st = direct_statuses.get(cid)
        if direct_st is not None and pipeline_st != direct_st:
            mismatches.append(f"{cid}: pipeline={pipeline_st}, direct={direct_st}")

    assert not mismatches, (
        "Pipeline report checkpoints differ from direct audit of the output PDF "
        f"(BUG-07 regression):\n" + "\n".join(mismatches)
    )


def test_no_tabs_deviation_between_audit_and_output(tmp_path):
    """After the pipeline, every page of the output PDF must have /Tabs = /S.

    This verifies that the /Tabs fix runs before the audit (not after),
    so the audit correctly reports C-10 = PASS.
    """
    test_suite = ROOT / "test_suite"
    src = test_suite / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"
    if not src.exists():
        pytest.skip("Travel form reference PDF not available")

    out_dir = tmp_path / "out"
    res = run_pipeline(str(src), str(out_dir))
    out_pdf = pathlib.Path(res["output_pdf"])
    assert out_pdf.exists()

    with pikepdf.open(str(out_pdf)) as pdf:
        bad_pages = []
        for i, page in enumerate(pdf.pages):
            tabs = page.get("/Tabs")
            if tabs is None or str(tabs) != "/S":
                bad_pages.append(i + 1)

    assert not bad_pages, (
        f"Pages {bad_pages} in output PDF lack /Tabs=/S.  "
        "The belt-and-suspenders /Tabs fix must run before the audit and "
        "before the final output is written."
    )
