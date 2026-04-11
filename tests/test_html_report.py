"""Tests for Jinja2 HTML compliance reports — GAP 1 requirement."""

from __future__ import annotations
import json
import pathlib
import sys
import re

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from reporting.html_generator import generate_report
from reporting.summary_generator import generate_summary
from wcag_auditor import audit_pdf
from pipeline import run_pipeline, _build_html_report_legacy


def _make_audit(tmp_path, title="Test Doc", lang="en-US", mark=True):
    """Create a minimal PDF and audit it."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = title
    if lang:
        pdf.Root["/Lang"] = pikepdf.String(lang)
    if mark:
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    p = tmp_path / "test.pdf"
    pdf.save(str(p))
    return audit_pdf(p)


def _generate(tmp_path, overall="PASS"):
    r = _make_audit(tmp_path)
    return generate_report(
        filename="test.pdf",
        title="Test Doc",
        timestamp="2026-04-11 12:00:00",
        overall=overall,
        checkpoints=r["checkpoints"],
    )


# --- Per-file report tests ---


def test_report_generates_for_pass_file(tmp_path):
    html = _generate(tmp_path, overall="PASS")
    assert "PASS" in html
    assert "WCAG 2.1 AA Compliance Report" in html


def test_report_generates_for_partial_file(tmp_path):
    html = _generate(tmp_path, overall="PARTIAL")
    assert "PARTIAL" in html


def test_report_generates_for_manual_review_file(tmp_path):
    html = _generate(tmp_path, overall="PASS")
    assert "Manual Review" in html or "MANUAL_REVIEW" in html


def test_all_47_checkpoint_rows_present(tmp_path):
    html = _generate(tmp_path)
    for i in range(1, 48):
        cid = f"C-{i:02d}"
        assert cid in html, f"Checkpoint {cid} missing from report"


def test_json_data_block_is_valid_json(tmp_path):
    html = _generate(tmp_path)
    match = re.search(r'<script type="application/json" id="wcag-audit-data">\s*(.*?)\s*</script>', html, re.DOTALL)
    assert match, "JSON data block not found"
    data = json.loads(match.group(1))
    assert isinstance(data, dict)


def test_json_data_block_contains_required_fields(tmp_path):
    html = _generate(tmp_path)
    match = re.search(r'<script type="application/json" id="wcag-audit-data">\s*(.*?)\s*</script>', html, re.DOTALL)
    data = json.loads(match.group(1))
    assert "file" in data
    assert "checkpoints" in data
    assert "overall" in data
    assert "timestamp" in data
    assert len(data["checkpoints"]) == 47


def test_noscript_block_contains_checkpoint_table(tmp_path):
    html = _generate(tmp_path)
    noscript_match = re.search(r"<noscript>(.*?)</noscript>", html, re.DOTALL)
    assert noscript_match, "noscript block not found"
    noscript_content = noscript_match.group(1)
    assert "<table>" in noscript_content or "<table" in noscript_content
    assert "C-01" in noscript_content
    assert "C-47" in noscript_content


def test_privacy_notice_present_in_report(tmp_path):
    html = _generate(tmp_path)
    assert "processed in memory" in html or "processed locally" in html
    assert "No file content was stored" in html or "No data was transmitted" in html


def test_report_filename_follows_convention(tmp_path):
    """Pipeline output should follow the _WCAG_2.1_AA_Compliant suffix."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Convention Test"
    src = tmp_path / "myfile.pdf"
    pdf.save(str(src))
    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    if res["result"] == "PASS":
        assert "_WCAG_2.1_AA_Compliant.html" in res["report_html"]
    else:
        assert "_WCAG_2.1_AA_PARTIAL.html" in res["report_html"]


def test_report_has_lang_attribute(tmp_path):
    html = _generate(tmp_path)
    assert 'lang="en"' in html


def test_report_has_skip_nav_link(tmp_path):
    html = _generate(tmp_path)
    assert "skip-link" in html
    assert "Skip to main content" in html


# --- Summary report tests ---


def test_summary_generates_for_batch(tmp_path):
    file_results = [
        {"filename": "a.pdf", "result": "PASS", "checkpoints": [{"status": "PASS"}] * 47},
        {"filename": "b.pdf", "result": "PARTIAL", "checkpoints": [{"status": "FAIL"}] * 47},
    ]
    html = generate_summary(file_results=file_results, timestamp="2026-04-11 12:00:00")
    assert "Batch Summary" in html
    assert "a.pdf" in html
    assert "b.pdf" in html


def test_summary_contains_per_file_breakdown(tmp_path):
    file_results = [
        {
            "filename": "x.pdf",
            "result": "PASS",
            "checkpoints": [{"status": "PASS"}] * 47,
            "report_name": "x_report.html",
        },
    ]
    html = generate_summary(file_results=file_results, timestamp="2026-04-11")
    assert "x.pdf" in html
    assert "PASS" in html


# --- Legacy fallback test ---


def test_legacy_fallback_works_when_jinja2_fails(tmp_path, monkeypatch):
    """If Jinja2 fails, pipeline should fall back to legacy HTML."""
    # Monkeypatch the generate_report to raise
    import reporting.html_generator as hg

    original = hg.generate_report

    def _fail(**kwargs):
        raise RuntimeError("Simulated Jinja2 failure")

    monkeypatch.setattr(hg, "generate_report", _fail)

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Fallback Test"
    src = tmp_path / "fallback.pdf"
    pdf.save(str(src))

    out = tmp_path / "out"
    res = run_pipeline(str(src), str(out))
    # Should still produce a report (via legacy)
    assert res["report_html"]
    html = pathlib.Path(res["report_html"]).read_text()
    assert "Compliance Report" in html
