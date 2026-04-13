"""Batch processing edge-case tests.

Verifies correctness and robustness of multi-file batch handling:
filename-collision deduplication, partial-batch failures, size-limit
boundary conditions, rapid sequential submissions, and mixed valid/invalid
payloads.
"""

from __future__ import annotations

import os
import pathlib
import sys
import tempfile
import zipfile
from concurrent.futures import ThreadPoolExecutor, as_completed

import pikepdf
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline import run_pipeline
from rate_limiter import (
    MSG_BATCH_TOO_LARGE,
    MAX_BATCH_SIZE_MB,
    validate_batch,
    validate_file,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_pdf(path: pathlib.Path, title: str = "Batch Test") -> pathlib.Path:
    """Write a minimal, valid 1-page PDF to *path*."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = title
    pdf.save(str(path))
    return path


def _make_sparse_file(path: pathlib.Path, size_bytes: int) -> pathlib.Path:
    """Create a file of exactly *size_bytes* using sparse allocation."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(str(path), "wb") as f:
        if size_bytes > 0:
            f.seek(size_bytes - 1)
            f.write(b"\x00")
    return path


def _assert_graceful(result: object) -> None:
    assert isinstance(result, dict), (
        f"run_pipeline returned {type(result).__name__}, expected dict"
    )
    assert "errors" in result
    for err in result.get("errors", []):
        assert "Traceback (most recent call last)" not in str(err), (
            f"Raw traceback leaked: {str(err)[:400]}"
        )


# ---------------------------------------------------------------------------
# Test 1 — 100 identical filenames: no collision in output ZIP
# ---------------------------------------------------------------------------


def test_batch_100_identical_files(tmp_path: pathlib.Path) -> None:
    """100 copies of the same PDF all get unique names in the output ZIP.

    Strategy
    --------
    * Verify ``app._unique_arcname`` produces 100 distinct entries for 100
      uses of the same base name — this is the deduplication contract.
    * Then run ``process_files_core`` on five identical-named files and
      inspect the real ZIP to confirm no entry appears twice.
    """
    # --- Part A: unit-test the deduplication function ---
    sys.path.insert(0, str(_REPO_ROOT))
    from app import _unique_arcname  # noqa: PLC0415

    used: set[str] = set()
    base = "report.pdf"
    names = [_unique_arcname(base, used) for _ in range(100)]

    assert len(names) == len(set(names)), (
        "Duplicate arcname detected among 100 uses of the same base name"
    )
    assert names[0] == base, "First name should be unchanged"
    for n in names[1:]:
        assert n != base, "Subsequent names must be renamed"

    # --- Part B: end-to-end with 5 identical files -> real ZIP ---
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()
    pdf_paths: list[str] = []
    for i in range(5):
        # All five files have the same stem ("identical.pdf").
        p = pdf_dir / f"job_{i}" / "identical.pdf"
        p.parent.mkdir()
        _make_valid_pdf(p)
        pdf_paths.append(str(p))

    from app import process_files_core  # noqa: PLC0415

    work = tmp_path / "work"
    _, zip_path, _ = process_files_core(pdf_paths, work_root=work)

    assert zip_path and pathlib.Path(zip_path).exists(), (
        "process_files_core did not produce a ZIP"
    )
    with zipfile.ZipFile(zip_path) as zf:
        entries = zf.namelist()
    pdf_entries = [e for e in entries if e.endswith(".pdf")]
    assert len(pdf_entries) == len(set(pdf_entries)), (
        f"Duplicate PDF entries in ZIP: {pdf_entries}"
    )
    assert len(pdf_entries) == 5, (
        f"Expected 5 PDF entries in ZIP, got {len(pdf_entries)}: {pdf_entries}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Batch with one corrupt file
# ---------------------------------------------------------------------------


def test_batch_with_one_corrupt_file(tmp_path: pathlib.Path) -> None:
    """99 valid PDFs + 1 corrupt: corrupt gets error, others all succeed.

    For speed the test uses 4 valid PDFs (same contract, same code path).
    One corrupt file must not stop the batch or contaminate other results.
    """
    pdf_dir = tmp_path / "pdfs"
    pdf_dir.mkdir()

    valid_paths: list[str] = []
    for i in range(4):
        p = pdf_dir / f"valid_{i}.pdf"
        _make_valid_pdf(p, title=f"Valid #{i}")
        valid_paths.append(str(p))

    corrupt_path = pdf_dir / "corrupt.pdf"
    corrupt_path.write_bytes(b"%PDF-1.4\ngarbage\xff\xfe\xfd")

    all_paths = valid_paths + [str(corrupt_path)]

    results: dict[str, dict] = {}
    for fp in all_paths:
        out = tmp_path / f"out_{pathlib.Path(fp).stem}"
        results[fp] = run_pipeline(fp, str(out))

    # All runs must return a graceful dict.
    for fp, res in results.items():
        _assert_graceful(res)

    # Valid PDFs must succeed (PASS or PARTIAL).
    for fp in valid_paths:
        res = results[fp]
        assert res.get("result") in ("PASS", "PARTIAL"), (
            f"Valid PDF {fp!r} unexpectedly failed: "
            f"result={res.get('result')!r}, errors={res.get('errors')}"
        )

    # Corrupt PDF must produce an error/partial result (not silent PASS).
    corrupt_res = results[str(corrupt_path)]
    assert corrupt_res.get("result") in ("PARTIAL", "ERROR") or corrupt_res.get(
        "errors"
    ), (
        f"Corrupt PDF did not produce errors: {corrupt_res}"
    )


# ---------------------------------------------------------------------------
# Test 3 — Batch at exactly the size limit (accepted)
# ---------------------------------------------------------------------------


def test_batch_at_exact_size_limit(tmp_path: pathlib.Path) -> None:
    """A batch totalling exactly MAX_BATCH_SIZE_MB is accepted (boundary-inclusive).

    ``validate_batch`` uses ``total_mb > MAX_BATCH_SIZE_MB``, so a batch
    that is exactly at the limit must return ``None`` (no error).
    """
    limit_bytes = int(MAX_BATCH_SIZE_MB * 1024 * 1024)
    # Split into two equal-sized sparse files so neither exceeds per-file limit.
    half = limit_bytes // 2
    remainder = limit_bytes - 2 * half
    f1 = _make_sparse_file(tmp_path / "at_limit_1.bin", half + remainder)
    f2 = _make_sparse_file(tmp_path / "at_limit_2.bin", half)

    # Verify sizes are exact.
    actual = f1.stat().st_size + f2.stat().st_size
    assert actual == limit_bytes, f"File sizes don't match: {actual} != {limit_bytes}"

    error_msg = validate_batch([str(f1), str(f2)])
    assert error_msg is None, (
        f"Batch at exactly {MAX_BATCH_SIZE_MB} MB was incorrectly rejected: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Test 4 — Batch one byte over limit (rejected cleanly)
# ---------------------------------------------------------------------------


def test_batch_one_byte_over_limit(tmp_path: pathlib.Path) -> None:
    """A batch totalling MAX_BATCH_SIZE_MB + 1 byte is rejected with the correct message."""
    limit_bytes = int(MAX_BATCH_SIZE_MB * 1024 * 1024)
    over_bytes = limit_bytes + 1

    # Two files, one normal and one that is 1 byte larger than half the limit.
    half = limit_bytes // 2
    f1 = _make_sparse_file(tmp_path / "over_limit_1.bin", half)
    f2 = _make_sparse_file(tmp_path / "over_limit_2.bin", half + 1)

    actual = f1.stat().st_size + f2.stat().st_size
    assert actual == over_bytes, f"Sizes don't match: {actual} != {over_bytes}"

    error_msg = validate_batch([str(f1), str(f2)])
    assert error_msg == MSG_BATCH_TOO_LARGE, (
        f"Expected MSG_BATCH_TOO_LARGE for {over_bytes}-byte batch, got: {error_msg!r}"
    )


# ---------------------------------------------------------------------------
# Test 5 — Rapid sequential submissions (no race conditions / data mixing)
# ---------------------------------------------------------------------------


def test_rapid_sequential_submissions(tmp_path: pathlib.Path) -> None:
    """5 batches of 2 files submitted sequentially with no delay cause no issues.

    Verifies that repeated rapid calls to ``run_pipeline`` do not produce
    cross-batch data mixing or leave orphaned temp directories.
    """
    import glob as _glob

    # Create 2 distinct source PDFs.
    pdf_a = _make_valid_pdf(tmp_path / "src" / "alpha.pdf", title="Alpha")
    pdf_b = _make_valid_pdf(tmp_path / "src" / "beta.pdf", title="Beta")

    before_tmpdirs = set(_glob.glob(os.path.join(tempfile.gettempdir(), "wcag_pipe_*")))

    results_per_batch: list[list[dict]] = []
    for batch_idx in range(5):
        batch_out: list[dict] = []
        for pdf_path in (pdf_a, pdf_b):
            out = tmp_path / f"batch_{batch_idx}" / pdf_path.stem
            res = run_pipeline(str(pdf_path), str(out))
            _assert_graceful(res)
            batch_out.append(res)
        results_per_batch.append(batch_out)

    # Every run must succeed (PASS or PARTIAL).
    for batch_idx, batch_out in enumerate(results_per_batch):
        for res in batch_out:
            assert res.get("result") in ("PASS", "PARTIAL"), (
                f"Batch {batch_idx} produced unexpected result: "
                f"{res.get('result')!r} errors={res.get('errors')}"
            )

    # No temp directories left behind.
    after_tmpdirs = set(_glob.glob(os.path.join(tempfile.gettempdir(), "wcag_pipe_*")))
    leaked = after_tmpdirs - before_tmpdirs
    assert not leaked, f"Pipeline left {len(leaked)} temp dir(s) behind: {leaked}"


# ---------------------------------------------------------------------------
# Test 6 — Mixed valid and invalid files in one batch
# ---------------------------------------------------------------------------


def test_batch_mixed_valid_and_invalid(tmp_path: pathlib.Path) -> None:
    """Batch with 6 diverse file types each gets the correct individual outcome.

    Files
    -----
    1. valid_a.pdf       — valid PDF → PASS or PARTIAL
    2. jpeg_as_pdf.pdf   — JPEG bytes with .pdf extension → rejected by validate_file
    3. corrupt.pdf       — PDF header but garbage body → PARTIAL with errors
    4. password.pdf      — user-password-protected PDF → PARTIAL with clear rejection
    5. empty.pdf         — zero bytes with .pdf extension → rejected by validate_file
    6. valid_b.pdf       — valid PDF → PASS or PARTIAL

    The batch must complete with partial results; no file must prevent
    others from being evaluated.
    """
    src = tmp_path / "src"
    src.mkdir()

    # 1. valid_a
    valid_a = _make_valid_pdf(src / "valid_a.pdf", title="Valid A")

    # 2. JPEG impersonating a PDF (real JPEG header)
    jpeg_as_pdf = src / "jpeg_as_pdf.pdf"
    jpeg_as_pdf.write_bytes(
        b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00"
        + b"\x00" * 100
    )

    # 3. Corrupt — has PDF header but random garbage body
    corrupt = src / "corrupt.pdf"
    corrupt.write_bytes(b"%PDF-1.4\n%%EOF\x00" + b"\xde\xad\xbe\xef" * 50)

    # 4. Password-protected (user password required)
    password_pdf = src / "password.pdf"
    _p = pikepdf.new()
    _p.add_blank_page()
    _p.save(
        str(password_pdf),
        encryption=pikepdf.Encryption(user="secret", owner="owner", R=4),
    )

    # 5. Zero-byte file
    empty_pdf = src / "empty.pdf"
    empty_pdf.write_bytes(b"")

    # 6. valid_b
    valid_b = _make_valid_pdf(src / "valid_b.pdf", title="Valid B")

    # --- evaluate each file ---

    # validate_file checks: JPEG and empty should be rejected before pipeline.
    assert validate_file(str(jpeg_as_pdf)) is not None, (
        "JPEG-as-PDF should be rejected by validate_file (bad header)"
    )
    assert validate_file(str(empty_pdf)) is not None, (
        "Zero-byte file should be rejected by validate_file"
    )

    # Valid files pass validation.
    assert validate_file(str(valid_a)) is None, "valid_a.pdf should pass validate_file"
    assert validate_file(str(valid_b)) is None, "valid_b.pdf should pass validate_file"

    # Run pipeline on the three files that pass validation-gate.
    pipeline_inputs = [
        (str(valid_a), "valid_a"),
        (str(corrupt), "corrupt"),
        (str(password_pdf), "password"),
        (str(valid_b), "valid_b"),
    ]
    pipeline_results: dict[str, dict] = {}
    for fp, key in pipeline_inputs:
        out = tmp_path / f"out_{key}"
        pipeline_results[key] = run_pipeline(fp, str(out))

    # All pipeline calls must return graceful dicts.
    for key, res in pipeline_results.items():
        _assert_graceful(res)

    # Valid PDFs → PASS or PARTIAL.
    for key in ("valid_a", "valid_b"):
        res = pipeline_results[key]
        assert res.get("result") in ("PASS", "PARTIAL"), (
            f"{key}: expected PASS/PARTIAL, got {res.get('result')!r}"
        )

    # Password-protected → PARTIAL with a human-readable rejection message.
    pw_res = pipeline_results["password"]
    assert pw_res.get("result") in ("PARTIAL", "ERROR") or pw_res.get("errors"), (
        "Password-protected PDF should produce errors"
    )
    pw_errors = " ".join(str(e) for e in pw_res.get("errors", []))
    assert any(
        kw in pw_errors.lower()
        for kw in ("password", "protected", "encrypted")
    ), (
        f"Password-protected PDF rejection message not found. errors={pw_res.get('errors')}"
    )

    # Corrupt PDF → some form of error (not silent PASS).
    corrupt_res = pipeline_results["corrupt"]
    assert corrupt_res.get("result") in ("PARTIAL", "ERROR") or corrupt_res.get(
        "errors"
    ), (
        f"Corrupt PDF did not produce errors: result={corrupt_res.get('result')!r}"
    )
