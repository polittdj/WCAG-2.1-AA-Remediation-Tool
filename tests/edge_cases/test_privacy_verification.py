"""Privacy-verification edge-case tests.

ALL FAILURES IN THIS FILE ARE CRITICAL — failures here indicate real
privacy regressions that must be fixed before any other test failures.

Tests verify:
1. File retention: no temporary or intermediate files linger after processing.
2. Encrypted PDF handling: correct responses to various encryption levels.
3. Embedded-file isolation: the pipeline does not expose embedded file content.
4. Metadata handling: PII fields (/Author, /Producer) are not leaked into reports.
5. Concurrent isolation: simultaneous pipeline runs never cross-contaminate.
"""

from __future__ import annotations

import glob
import os
import pathlib
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import pikepdf
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_pdf(
    path: pathlib.Path,
    title: str = "Privacy Test",
    author: str = "",
    producer: str = "",
) -> pathlib.Path:
    """Write a minimal valid PDF, optionally with /Author and /Producer."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = title
    if author:
        pdf.docinfo["/Author"] = author
    if producer:
        pdf.docinfo["/Producer"] = producer
    pdf.save(str(path))
    return path


def _assert_no_traceback(result: dict) -> None:
    for err in result.get("errors", []):
        assert "Traceback (most recent call last)" not in str(err), (
            f"Raw traceback leaked into errors:\n{str(err)[:400]}"
        )


def _wcag_tmpdirs() -> set[str]:
    """Return the set of wcag_pipe_* directories currently in the system tmpdir."""
    pattern = os.path.join(tempfile.gettempdir(), "wcag_pipe_*")
    return set(glob.glob(pattern))


# ---------------------------------------------------------------------------
# CRITICAL Test 1 — File retention: no remnants after processing
# ---------------------------------------------------------------------------


def test_file_retention_cleanup(tmp_path: pathlib.Path) -> None:
    """Process a file and verify zero temp-dir remnants — repeated 10 times.

    The pipeline creates a ``wcag_pipe_*`` temp directory per run and must
    delete it in a ``finally`` block. Running 10 consecutive times catches
    any intermittent cleanup failure.

    CRITICAL: failures mean uploaded content may persist on disk.
    """
    src = _make_valid_pdf(tmp_path / "retention_src.pdf", title="Retention Test")

    for iteration in range(10):
        before = _wcag_tmpdirs()
        out = tmp_path / f"out_retention_{iteration}"
        result = run_pipeline(str(src), str(out))

        assert isinstance(result, dict), (
            f"Iteration {iteration}: run_pipeline returned {type(result).__name__}"
        )

        after = _wcag_tmpdirs()
        leaked = after - before
        assert not leaked, (
            f"PRIVACY REGRESSION — iteration {iteration}: "
            f"pipeline left {len(leaked)} temp dir(s) on disk: {leaked}. "
            "Uploaded content may persist after processing."
        )


# ---------------------------------------------------------------------------
# CRITICAL Test 2 — Encrypted PDF handling
# ---------------------------------------------------------------------------


def test_encrypted_pdf_handling(tmp_path: pathlib.Path) -> None:
    """Pipeline responds correctly to PDFs with various encryption levels.

    Encryption scenarios
    --------------------
    owner-only (R=4, user='')
        No user password — must open and process normally (PASS or PARTIAL).

    user-password-required (R=4, user='secret')
        Requires a password — pipeline must reject with a clear, human-readable
        message; result must be PARTIAL (not ERROR or silent PASS).

    128-bit RC4 (R=3, aes=False, metadata=False, user='pass')
        Legacy encryption — pipeline must reject with a clear message.

    256-bit AES (R=6, user='secret')
        Strong modern encryption — pipeline must reject with a clear message.

    CRITICAL: if password-protected content silently passes through, sensitive
    PDF content could be processed without the owner's intent.
    """
    src = tmp_path / "src"
    src.mkdir()

    # ---- owner-only (no user password) ----
    owner_only = src / "owner_only.pdf"
    _p = pikepdf.new()
    _p.add_blank_page()
    _p.docinfo["/Title"] = "Owner Only"
    _p.save(str(owner_only), encryption=pikepdf.Encryption(user="", owner="ownerpass", R=4))

    out_owner = tmp_path / "out_owner"
    res_owner = run_pipeline(str(owner_only), str(out_owner))
    assert isinstance(res_owner, dict), "owner-only: non-dict result"
    _assert_no_traceback(res_owner)
    assert res_owner.get("result") in ("PASS", "PARTIAL"), (
        f"Owner-only-encrypted PDF should process normally. "
        f"Got result={res_owner.get('result')!r}, errors={res_owner.get('errors')}"
    )

    # ---- user-password-required (R=4) ----
    user_pw_r4 = src / "user_pw_r4.pdf"
    _p2 = pikepdf.new()
    _p2.add_blank_page()
    _p2.save(str(user_pw_r4), encryption=pikepdf.Encryption(user="secret", owner="owner", R=4))

    out_upw = tmp_path / "out_upw"
    res_upw = run_pipeline(str(user_pw_r4), str(out_upw))
    assert isinstance(res_upw, dict), "user-pw R=4: non-dict result"
    _assert_no_traceback(res_upw)
    upw_errors = " ".join(str(e) for e in res_upw.get("errors", []))
    assert any(
        kw in upw_errors.lower()
        for kw in ("password", "protected", "encrypted")
    ), (
        f"User-password PDF rejected without a clear message. "
        f"errors={res_upw.get('errors')}"
    )
    assert res_upw.get("result") != "PASS", (
        "Password-protected PDF must not silently PASS"
    )

    # ---- 128-bit RC4 legacy (R=3, aes=False, metadata=False) ----
    legacy_r3 = src / "legacy_r3.pdf"
    _p3 = pikepdf.new()
    _p3.add_blank_page()
    _p3.save(
        str(legacy_r3),
        encryption=pikepdf.Encryption(user="pass", owner="owner", R=3, aes=False, metadata=False),
    )

    out_r3 = tmp_path / "out_r3"
    res_r3 = run_pipeline(str(legacy_r3), str(out_r3))
    assert isinstance(res_r3, dict), "R=3 RC4: non-dict result"
    _assert_no_traceback(res_r3)
    r3_errors = " ".join(str(e) for e in res_r3.get("errors", []))
    assert any(
        kw in r3_errors.lower()
        for kw in ("password", "protected", "encrypted")
    ), (
        f"Legacy-encrypted PDF rejected without a clear message. "
        f"errors={res_r3.get('errors')}"
    )
    assert res_r3.get("result") != "PASS", (
        "Legacy-encrypted PDF must not silently PASS"
    )

    # ---- 256-bit AES (R=6) ----
    aes256 = src / "aes256.pdf"
    _p4 = pikepdf.new()
    _p4.add_blank_page()
    _p4.save(str(aes256), encryption=pikepdf.Encryption(user="secret", owner="owner", R=6))

    out_aes = tmp_path / "out_aes"
    res_aes = run_pipeline(str(aes256), str(out_aes))
    assert isinstance(res_aes, dict), "AES-256: non-dict result"
    _assert_no_traceback(res_aes)
    aes_errors = " ".join(str(e) for e in res_aes.get("errors", []))
    assert any(
        kw in aes_errors.lower()
        for kw in ("password", "protected", "encrypted")
    ), (
        f"AES-256-encrypted PDF rejected without a clear message. "
        f"errors={res_aes.get('errors')}"
    )
    assert res_aes.get("result") != "PASS", (
        "AES-256-encrypted PDF must not silently PASS"
    )


# ---------------------------------------------------------------------------
# CRITICAL Test 3 — Embedded-file isolation
# ---------------------------------------------------------------------------


def test_embedded_files_isolation(tmp_path: pathlib.Path) -> None:
    """PDF with /EmbeddedFiles: only the parent is processed; payload not exposed.

    A PDF can carry embedded file attachments under its /Names /EmbeddedFiles
    tree. The remediation pipeline must:

    * Process the parent PDF structure (tagging, metadata, etc.).
    * NOT read, extract, or forward the embedded file's raw bytes.
    * NOT leak the embedded payload into the HTML report or error messages.

    CRITICAL: exposing embedded files could reveal confidential attachments.
    """
    _EMBEDDED_SENTINEL = "CONFIDENTIAL_EMBEDDED_PDF_PAYLOAD_AB12"

    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Embedded Files Test"

    # Build an embedded-file stream containing the sentinel string.
    ef_stream = pikepdf.Stream(pdf, _EMBEDDED_SENTINEL.encode())
    ef_stream["/Type"] = pikepdf.Name("/EmbeddedFile")
    ef_stream["/Subtype"] = pikepdf.Name("/application#2Foctet-stream")

    filespec = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Filespec"),
            F=pikepdf.String("confidential.txt"),
            EF=pikepdf.Dictionary(F=ef_stream),
        )
    )

    # Register in /Names /EmbeddedFiles (PDF catalog-level embedded files).
    pdf.Root["/Names"] = pikepdf.Dictionary(
        EmbeddedFiles=pikepdf.Dictionary(
            Names=pikepdf.Array([pikepdf.String("confidential.txt"), filespec])
        )
    )

    # Also add a FileAttachment annotation so fix_annotations sees it.
    annot = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/FileAttachment"),
            Rect=pikepdf.Array([100, 700, 120, 720]),
            FS=filespec,
            Contents=pikepdf.String("Attached file"),
        )
    )
    pdf.pages[0]["/Annots"] = pikepdf.Array([annot])

    pdf_path = tmp_path / "embedded_files.pdf"
    pdf.save(str(pdf_path))

    out_dir = tmp_path / "out_embedded"
    result = run_pipeline(str(pdf_path), str(out_dir))

    assert isinstance(result, dict), "Expected dict from run_pipeline"
    _assert_no_traceback(result)

    # Pipeline must complete (not crash).
    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )

    # Sentinel must NOT appear in the HTML report.
    report_s = result.get("report_html", "")
    if report_s and pathlib.Path(report_s).exists():
        html = pathlib.Path(report_s).read_text(encoding="utf-8", errors="replace")
        assert _EMBEDDED_SENTINEL not in html, (
            "PRIVACY REGRESSION — Embedded file content leaked into HTML report. "
            f"Sentinel {_EMBEDDED_SENTINEL!r} found in {report_s!r}"
        )

    # Sentinel must NOT appear in any error message.
    for err in result.get("errors", []):
        assert _EMBEDDED_SENTINEL not in str(err), (
            "PRIVACY REGRESSION — Embedded file content appeared in pipeline error: "
            f"{err!r}"
        )


# ---------------------------------------------------------------------------
# CRITICAL Test 4 — Metadata handling: PII not leaked into HTML report
# ---------------------------------------------------------------------------


def test_metadata_handling(tmp_path: pathlib.Path) -> None:
    """Original /Author and /Producer metadata must not appear in the HTML report.

    The HTML compliance report is shared with end-users. It must show the
    document title (needed for identification) but must not unexpectedly
    render fields like /Author or /Producer that could contain PII or
    internal tooling information.

    Verified fields
    ---------------
    /Author   — may contain a person's full name (PII).
    /Producer — may contain internal software version strings.

    CRITICAL: leaking /Author into a shared report exposes PII.
    """
    _AUTHOR = "John Smith"
    _PRODUCER = "Secret Software v3"

    pdf_path = _make_valid_pdf(
        tmp_path / "metadata_test.pdf",
        title="Metadata Handling Test",
        author=_AUTHOR,
        producer=_PRODUCER,
    )
    out_dir = tmp_path / "out_metadata"
    result = run_pipeline(str(pdf_path), str(out_dir))

    assert isinstance(result, dict), "Expected dict from run_pipeline"
    _assert_no_traceback(result)
    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )

    report_s = result.get("report_html", "")
    assert report_s and pathlib.Path(report_s).exists(), (
        "No HTML report produced — cannot verify metadata handling"
    )
    html = pathlib.Path(report_s).read_text(encoding="utf-8", errors="replace")

    assert _AUTHOR not in html, (
        f"PRIVACY REGRESSION — /Author value {_AUTHOR!r} appeared verbatim in "
        f"the HTML report. PII must not be included in the compliance report."
    )
    assert _PRODUCER not in html, (
        f"PRIVACY REGRESSION — /Producer value {_PRODUCER!r} appeared verbatim "
        f"in the HTML report. Internal tooling strings must not be included."
    )


# ---------------------------------------------------------------------------
# CRITICAL Test 5 — Concurrent isolation: no cross-contamination
# ---------------------------------------------------------------------------


def test_concurrent_file_isolation(tmp_path: pathlib.Path) -> None:
    """Two files processed simultaneously must never share content.

    Uses ``ThreadPoolExecutor`` to submit two pipeline jobs concurrently
    and then verifies that each output contains only its own content and
    none of the other file's sentinel text.

    CRITICAL: cross-contamination would mean one user's content is visible
    in another user's report — a serious data-isolation breach.
    """
    _SENTINEL_A = "FILE_A_SENTINEL_UNIQUE_K7P3"
    _SENTINEL_B = "FILE_B_SENTINEL_UNIQUE_M9Q8"

    # Create two distinct source PDFs.
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    def _make_reportlab_pdf(path: pathlib.Path, sentinel: str) -> pathlib.Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        c = canvas.Canvas(str(path), pagesize=LETTER)
        c.setTitle(sentinel)
        c.setFont("Helvetica", 12)
        c.drawString(72, 720, sentinel)
        c.showPage()
        c.save()
        return path

    pdf_a = _make_reportlab_pdf(tmp_path / "src" / "file_a.pdf", _SENTINEL_A)
    pdf_b = _make_reportlab_pdf(tmp_path / "src" / "file_b.pdf", _SENTINEL_B)

    out_a = tmp_path / "out_a"
    out_b = tmp_path / "out_b"

    results: dict[str, dict] = {}

    def _run(label: str, path: pathlib.Path, out: pathlib.Path) -> tuple[str, dict]:
        return label, run_pipeline(str(path), str(out))

    with ThreadPoolExecutor(max_workers=2) as ex:
        futures = {
            ex.submit(_run, "A", pdf_a, out_a): "A",
            ex.submit(_run, "B", pdf_b, out_b): "B",
        }
        for fut in as_completed(futures):
            label, result = fut.result()
            results[label] = result

    assert isinstance(results.get("A"), dict), "File A: non-dict result"
    assert isinstance(results.get("B"), dict), "File B: non-dict result"
    _assert_no_traceback(results["A"])
    _assert_no_traceback(results["B"])

    assert results["A"].get("result") in ("PASS", "PARTIAL"), (
        f"File A: unexpected result {results['A'].get('result')!r}"
    )
    assert results["B"].get("result") in ("PASS", "PARTIAL"), (
        f"File B: unexpected result {results['B'].get('result')!r}"
    )

    # Check HTML report for A: must not contain B's sentinel.
    for label, other_sentinel in [("A", _SENTINEL_B), ("B", _SENTINEL_A)]:
        report_s = results[label].get("report_html", "")
        if report_s and pathlib.Path(report_s).exists():
            html = pathlib.Path(report_s).read_text(encoding="utf-8", errors="replace")
            assert other_sentinel not in html, (
                f"PRIVACY REGRESSION — File {label}'s HTML report contains "
                f"content from the other concurrent file ({other_sentinel!r}). "
                "Cross-contamination detected."
            )

    # Check errors for cross-contamination.
    for label, own_sentinel, other_sentinel in [
        ("A", _SENTINEL_A, _SENTINEL_B),
        ("B", _SENTINEL_B, _SENTINEL_A),
    ]:
        errors_text = " ".join(str(e) for e in results[label].get("errors", []))
        assert other_sentinel not in errors_text, (
            f"PRIVACY REGRESSION — File {label}'s error messages contain "
            f"content from the other concurrent file ({other_sentinel!r})."
        )
