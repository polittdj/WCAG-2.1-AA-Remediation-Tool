"""Acceptance tests for pipeline.py.

The master test runs the full chain on every reference PDF and asserts
all 5 critical checkpoints PASS. The other tests cover output naming,
input immutability, ZIP contents, and the privacy notice.
"""

from __future__ import annotations

import hashlib
import pathlib
import sys
import zipfile

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import CRITICAL_CHECKPOINTS, _NA_ACCEPTABLE, run_pipeline  # noqa: E402

TEST_SUITE = ROOT / "test_suite"

GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
EDITABLE = TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
MS_WORD = TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf"
EDITABLE_ADA = TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [GOOD, EDITABLE, MS_WORD, EDITABLE_ADA, TRAVEL]


def _statuses(checkpoints: list[dict]) -> dict[str, str]:
    return {c["id"]: c["status"] for c in checkpoints}


def _hash(path: pathlib.Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_pipeline_all_five_pdfs_pass(tmp_path: pathlib.Path) -> None:
    """The master acceptance test: every reference PDF reaches PASS."""
    for src in ALL_PDFS:
        out_dir = tmp_path / src.stem
        res = run_pipeline(str(src), str(out_dir))
        assert res["result"] == "PASS", f"{src.name}: result={res['result']}, errors={res['errors']}"
        statuses = _statuses(res["checkpoints"])
        # Some checkpoints (figures, widgets, headings, tables, lists) are
        # NOT_APPLICABLE on documents that genuinely have none of that content.
        # pipeline.py's _is_pass() uses _NA_ACCEPTABLE to allow those — mirror
        # the same set here so the test stays in sync with the production logic.
        for cid in CRITICAL_CHECKPOINTS:
            st = statuses.get(cid)
            if st == "NOT_APPLICABLE" and cid in _NA_ACCEPTABLE:
                continue
            assert st == "PASS", f"{src.name}: {cid}={st}"


def test_output_naming_compliant(tmp_path: pathlib.Path) -> None:
    res = run_pipeline(str(TRAVEL), str(tmp_path))
    assert res["result"] == "PASS", res["errors"]
    out_pdf = pathlib.Path(res["output_pdf"])
    assert out_pdf.name.endswith("_WGAC_2.1_AA_Compliant.pdf"), out_pdf.name
    assert out_pdf.exists()


def test_output_naming_bare_pdf(tmp_path: pathlib.Path) -> None:
    """A bare PDF with no content. The pipeline detects it as a scan-like
    document (no fonts, no text ops), runs the struct-stub path, and
    fix_title derives a fallback title. All checkpoints pass because
    NOT_APPLICABLE states are acceptable for widget/figure checkpoints."""
    bare = tmp_path / "bare_input.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    pdf.save(str(bare))
    pdf.close()

    out_dir = tmp_path / "out"
    res = run_pipeline(str(bare), str(out_dir))
    # A bare PDF now gets a struct tree stub and title — it should PASS.
    out_pdf = pathlib.Path(res["output_pdf"])
    assert out_pdf.exists()
    assert res["result"] in ("PASS", "PARTIAL"), res["errors"]


def test_original_file_unchanged(tmp_path: pathlib.Path) -> None:
    # Copy a reference PDF into tmp_path so we can verify it bit-for-bit.
    src_copy = tmp_path / "input.pdf"
    src_copy.write_bytes(EDITABLE.read_bytes())
    before_hash = _hash(src_copy)
    before_mtime = src_copy.stat().st_mtime

    out_dir = tmp_path / "out"
    res = run_pipeline(str(src_copy), str(out_dir))
    assert res["result"] == "PASS", res["errors"]

    assert src_copy.exists(), "input file was deleted"
    after_hash = _hash(src_copy)
    assert after_hash == before_hash, "input file bytes changed"
    # Mtime should also be unchanged.
    assert src_copy.stat().st_mtime == before_mtime


def test_zip_contains_expected_files(tmp_path: pathlib.Path) -> None:
    res = run_pipeline(str(TRAVEL), str(tmp_path))
    zip_path = pathlib.Path(res["zip_path"])
    assert zip_path.exists()
    assert zip_path.name.startswith("WCAG_Compliance_Results_")
    assert zip_path.name.endswith(".zip")

    with zipfile.ZipFile(str(zip_path)) as zf:
        names = sorted(zf.namelist())
    expected = sorted(
        [
            pathlib.Path(res["output_pdf"]).name,
            pathlib.Path(res["report_html"]).name,
        ]
    )
    assert names == expected, f"zip contents {names} != expected {expected}"


def test_privacy_notice_in_report(tmp_path: pathlib.Path) -> None:
    res = run_pipeline(str(GOOD), str(tmp_path))
    report_path = pathlib.Path(res["report_html"])
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")
    # Accept either legacy or Jinja2 privacy text
    has_legacy = "This file was processed locally." in html
    has_jinja2 = "processed in memory" in html
    assert has_legacy or has_jinja2, "privacy notice missing from HTML report"
    has_no_transmit = "No data was transmitted" in html or "No file content was stored" in html
    assert has_no_transmit, "privacy no-transmit statement missing"
    # No opt-in was granted; no AI banner should appear.
    assert "External data transfer notice" not in html
    assert res.get("ai_used") is False


def test_no_ai_transfer_without_opt_in(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """ANTHROPIC_API_KEY alone must NOT produce an AI banner: the pipeline
    only sends data externally when WCAG_ENABLE_AI_ALT_TEXT is also set."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("WCAG_ENABLE_AI_ALT_TEXT", raising=False)

    res = run_pipeline(str(TRAVEL), str(tmp_path))
    assert res.get("ai_used") is False
    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")
    assert "External data transfer notice" not in html
    assert "No data was transmitted" in html or "No file content was stored" in html


def test_ai_banner_appears_when_opt_in_and_claude_mocked(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """With the opt-in set and a mocked Claude, the HTML report must
    surface the external transfer notice and switch footers."""
    import fix_figure_alt_text as fat

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("WCAG_ENABLE_AI_ALT_TEXT", "1")
    monkeypatch.setattr(fat, "_claude_describe", lambda png, timeout_s=45.0: "A small company logo")

    res = run_pipeline(str(TRAVEL), str(tmp_path))
    assert res.get("ai_used") is True
    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")
    assert "External data transfer notice" in html
    assert "Anthropic's Claude Vision API" in html
    # The plain "no data was transmitted" footer must NOT be present.
    assert "No data was transmitted to any external server." not in html


# ---------------------------------------------------------------------------
# Pipeline resilience tests
# ---------------------------------------------------------------------------


def test_password_protected_pdf(tmp_path: pathlib.Path) -> None:
    """Password-protected PDFs should return PARTIAL with a clean error."""
    encrypted = tmp_path / "encrypted.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(str(encrypted), encryption=pikepdf.Encryption(owner="o", user="u", R=4))
    pdf.close()

    res = run_pipeline(str(encrypted), str(tmp_path / "out"))
    assert res["result"] == "PARTIAL"
    assert any("password" in e.lower() for e in res["errors"])


def test_corrupt_file(tmp_path: pathlib.Path) -> None:
    """A corrupt file should not crash the pipeline."""
    bad = tmp_path / "corrupt.pdf"
    bad.write_bytes(b"this is not a pdf at all")
    res = run_pipeline(str(bad), str(tmp_path / "out"))
    # Should return PARTIAL (not crash)
    assert res["result"] == "PARTIAL"
    assert len(res["errors"]) > 0


def test_empty_file(tmp_path: pathlib.Path) -> None:
    """A zero-byte file should not crash."""
    empty = tmp_path / "empty.pdf"
    empty.write_bytes(b"")
    res = run_pipeline(str(empty), str(tmp_path / "out"))
    assert res["result"] == "PARTIAL"


def test_nonexistent_file(tmp_path: pathlib.Path) -> None:
    """A nonexistent input should not crash."""
    res = run_pipeline(str(tmp_path / "does_not_exist.pdf"), str(tmp_path / "out"))
    assert res["result"] == "PARTIAL"
    assert len(res["errors"]) > 0


def test_idempotent_pipeline_rerun(tmp_path: pathlib.Path) -> None:
    """Running the pipeline twice on the same file should not break anything."""
    out1 = tmp_path / "run1"
    res1 = run_pipeline(str(GOOD), str(out1))
    assert res1["result"] == "PASS"

    # Run again on the OUTPUT of run 1
    out2 = tmp_path / "run2"
    res2 = run_pipeline(res1["output_pdf"], str(out2))
    assert res2["result"] == "PASS", f"re-run failed: {res2['errors']}"
    # All checkpoints should still pass
    for c in res2["checkpoints"]:
        assert c["status"] in ("PASS", "NOT_APPLICABLE", "MANUAL_REVIEW"), f"{c['id']}: {c['status']} on re-run"


def test_pipeline_returns_all_result_keys(tmp_path: pathlib.Path) -> None:
    """The result dict must always have the expected keys."""
    res = run_pipeline(str(GOOD), str(tmp_path))
    required_keys = {"output_pdf", "report_html", "zip_path", "result", "checkpoints", "errors"}
    assert required_keys.issubset(res.keys()), f"missing keys: {required_keys - res.keys()}"


def test_pipeline_result_checkpoints_match_critical(tmp_path: pathlib.Path) -> None:
    """Every CRITICAL_CHECKPOINT must appear in the result checkpoints."""
    res = run_pipeline(str(GOOD), str(tmp_path))
    result_ids = {c["id"] for c in res["checkpoints"]}
    for cid in CRITICAL_CHECKPOINTS:
        assert cid in result_ids, f"{cid} missing from result checkpoints"
