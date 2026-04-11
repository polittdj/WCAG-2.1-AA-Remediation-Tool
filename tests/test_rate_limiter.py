"""Tests for rate_limiter.py — GAP 2 requirement."""

from __future__ import annotations
import pathlib
import sys
import time

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from rate_limiter import (
    validate_file,
    validate_batch,
    check_rate_limit,
    record_job,
    reset_for_testing,
    MAX_FILE_SIZE_MB,
    MAX_BATCH_SIZE_MB,
    MAX_JOBS_PER_IP_PER_HOUR,
)


@pytest.fixture(autouse=True)
def _reset():
    """Reset rate limiter state before each test."""
    reset_for_testing()
    yield
    reset_for_testing()


def _make_pdf(tmp_path, name="test.pdf", size_bytes=None):
    """Create a valid PDF. Optionally pad to a specific size."""
    p = tmp_path / name
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.save(str(p))
    if size_bytes and p.stat().st_size < size_bytes:
        # Pad file to reach target size
        with open(p, "ab") as f:
            f.write(b"\x00" * (size_bytes - p.stat().st_size))
    return p


def test_oversized_file_rejected(tmp_path):
    big = _make_pdf(tmp_path, "big.pdf", size_bytes=(MAX_FILE_SIZE_MB + 1) * 1024 * 1024)
    err = validate_file(str(big))
    assert err is not None
    assert "50 MB" in err
    assert "compress" in err.lower() or "split" in err.lower()


def test_oversized_batch_rejected(tmp_path):
    # Create enough files to exceed batch limit
    paths = []
    # Each file ~100MB to exceed 500MB total with 6 files
    for i in range(6):
        p = _make_pdf(tmp_path, f"f{i}.pdf", size_bytes=100 * 1024 * 1024)
        paths.append(str(p))
    err = validate_batch(paths)
    assert err is not None
    assert "500 MB" in err


def test_rate_limit_enforced_per_ip(tmp_path):
    ip = "192.168.1.1"
    for _ in range(MAX_JOBS_PER_IP_PER_HOUR):
        assert check_rate_limit(ip) is None
        record_job(ip)
    # Next check should fail
    err = check_rate_limit(ip)
    assert err is not None
    assert "limit" in err.lower()
    assert "minutes" in err.lower()


def test_non_pdf_mime_rejected(tmp_path):
    txt = tmp_path / "not_a_pdf.txt"
    txt.write_text("hello world")
    err = validate_file(str(txt))
    assert err is not None
    assert "Only PDF" in err


def test_valid_pdf_accepted(tmp_path):
    p = _make_pdf(tmp_path)
    err = validate_file(str(p))
    assert err is None


def test_rejection_messages_are_user_friendly(tmp_path):
    # Non-PDF
    txt = tmp_path / "bad.txt"
    txt.write_text("not pdf")
    err = validate_file(str(txt))
    assert err is not None
    # No class names or stack traces
    assert "Exception" not in err
    assert "Traceback" not in err
    assert "Error" not in err

    # Rate limit
    ip = "10.0.0.1"
    for _ in range(MAX_JOBS_PER_IP_PER_HOUR):
        record_job(ip)
    err2 = check_rate_limit(ip)
    assert err2 is not None
    assert "Exception" not in err2
    assert "please" in err2.lower()


def test_rate_limit_resets_after_window(tmp_path):
    """Rate limit should reset when window expires."""
    ip = "10.0.0.2"
    # Manually inject old timestamps
    import rate_limiter

    now = time.time()
    with rate_limiter._lock:
        # Add timestamps that are already expired (older than window)
        rate_limiter._ip_timestamps[ip] = [now - 7200] * MAX_JOBS_PER_IP_PER_HOUR
    # Should be allowed now (all old timestamps pruned)
    err = check_rate_limit(ip)
    assert err is None
