"""Tests for rate_limiter.py — GAP #1 requirement."""

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
    check_queue_depth,
    acquire_queue_slot,
    release_queue_slot,
    set_max_queue_depth,
    record_job,
    reset_for_testing,
    MAX_FILE_SIZE_MB,
    MAX_BATCH_SIZE_MB,
    MAX_JOBS_PER_IP_PER_HOUR,
    MSG_FILE_TOO_LARGE,
    MSG_BATCH_TOO_LARGE,
    MSG_RATE_LIMITED,
    MSG_NON_PDF,
    MSG_QUEUE_FULL,
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
        with open(p, "ab") as f:
            f.write(b"\x00" * (size_bytes - p.stat().st_size))
    return p


# --- File size ---


def test_file_at_limit_accepted(tmp_path):
    """A file exactly at 50 MB should be accepted."""
    p = _make_pdf(tmp_path, "exact.pdf", size_bytes=MAX_FILE_SIZE_MB * 1024 * 1024)
    err = validate_file(str(p))
    assert err is None


def test_file_above_limit_rejected(tmp_path):
    """A file exceeding 50 MB must be rejected with exact spec message."""
    big = _make_pdf(tmp_path, "big.pdf", size_bytes=(MAX_FILE_SIZE_MB + 1) * 1024 * 1024)
    err = validate_file(str(big))
    assert err == MSG_FILE_TOO_LARGE


# --- Batch size ---


def test_batch_above_limit_rejected(tmp_path):
    """Total batch exceeding 500 MB must be rejected with exact spec message."""
    paths = []
    for i in range(6):
        p = _make_pdf(tmp_path, f"f{i}.pdf", size_bytes=100 * 1024 * 1024)
        paths.append(str(p))
    err = validate_batch(paths)
    assert err == MSG_BATCH_TOO_LARGE


# --- Rate limiting ---


def test_rate_limit_enforced_per_ip():
    """11th request in the same hour must be rejected."""
    ip = "192.168.1.1"
    for _ in range(MAX_JOBS_PER_IP_PER_HOUR):
        assert check_rate_limit(ip) is None
        record_job(ip)
    err = check_rate_limit(ip)
    assert err == MSG_RATE_LIMITED


def test_rate_limit_resets_after_expiry():
    """Rate limit should reset when window expires."""
    ip = "10.0.0.2"
    import rate_limiter

    now = time.time()
    with rate_limiter._lock:
        rate_limiter._ip_timestamps[ip] = [now - 7200] * MAX_JOBS_PER_IP_PER_HOUR
    err = check_rate_limit(ip)
    assert err is None


def test_different_ips_independent():
    """Rate limits are per-IP."""
    for _ in range(MAX_JOBS_PER_IP_PER_HOUR):
        record_job("10.0.0.1")
    assert check_rate_limit("10.0.0.1") == MSG_RATE_LIMITED
    assert check_rate_limit("10.0.0.2") is None


# --- MIME type ---


def test_non_pdf_extension_rejected(tmp_path):
    """Non-.pdf extension must be rejected with exact spec message."""
    txt = tmp_path / "not_a_pdf.txt"
    txt.write_text("hello world")
    err = validate_file(str(txt))
    assert err == MSG_NON_PDF


def test_pdf_extension_but_bad_header_rejected(tmp_path):
    """A .pdf file with non-PDF header must be rejected."""
    fake = tmp_path / "fake.pdf"
    fake.write_bytes(b"NOT A PDF FILE HEADER")
    err = validate_file(str(fake))
    assert err == MSG_NON_PDF


def test_valid_pdf_accepted(tmp_path):
    p = _make_pdf(tmp_path)
    err = validate_file(str(p))
    assert err is None


# --- Queue depth ---


def test_queue_full_rejected():
    """When queue is full, must return exact spec message."""
    set_max_queue_depth(2)
    assert acquire_queue_slot() is True
    assert acquire_queue_slot() is True
    err = check_queue_depth()
    assert err == MSG_QUEUE_FULL
    release_queue_slot()
    assert check_queue_depth() is None


def test_queue_slot_lifecycle():
    """Acquire and release cycle works correctly."""
    set_max_queue_depth(1)
    assert acquire_queue_slot() is True
    assert acquire_queue_slot() is False
    release_queue_slot()
    assert acquire_queue_slot() is True
    release_queue_slot()


# --- Message format ---


def test_rejection_messages_match_spec():
    """All rejection messages must match the exact spec strings."""
    assert MSG_FILE_TOO_LARGE == "This file exceeds the 50 MB limit. Please reduce the file size and try again."
    assert MSG_BATCH_TOO_LARGE == "Total upload size exceeds the 500 MB limit. Please reduce the number or size of files."
    assert MSG_RATE_LIMITED == "You've reached the processing limit (10 per hour). Please try again later."
    assert MSG_NON_PDF == "Only PDF files are accepted. The uploaded file appears to be a different format."
    assert MSG_QUEUE_FULL == "Processing capacity is currently full. Please try again in a few minutes."
