"""rate_limiter.py — Pre-queue validation and rate limiting.

Enforces file size, batch size, MIME type, and per-IP rate limits
before any file reaches the processing pipeline.
"""

from __future__ import annotations

import collections
import mimetypes
import pathlib
import time
import threading


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

MAX_FILE_SIZE_MB = 50
MAX_BATCH_SIZE_MB = 500
MAX_JOBS_PER_IP_PER_HOUR = 10
RATE_WINDOW_SECONDS = 3600


# ---------------------------------------------------------------------------
# Rate tracker (thread-safe)
# ---------------------------------------------------------------------------

_lock = threading.Lock()
_ip_timestamps: dict[str, list[float]] = collections.defaultdict(list)


def _prune_old(ip: str, now: float) -> None:
    """Remove timestamps older than the rate window."""
    cutoff = now - RATE_WINDOW_SECONDS
    _ip_timestamps[ip] = [t for t in _ip_timestamps[ip] if t > cutoff]


def _record_job(ip: str) -> None:
    """Record a job for rate limiting."""
    with _lock:
        _ip_timestamps[ip].append(time.time())


def _jobs_in_window(ip: str) -> int:
    """Count jobs in the current rate window."""
    now = time.time()
    with _lock:
        _prune_old(ip, now)
        return len(_ip_timestamps[ip])


def _minutes_until_reset(ip: str) -> int:
    """Minutes until the oldest job in the window expires."""
    now = time.time()
    with _lock:
        _prune_old(ip, now)
        if not _ip_timestamps[ip]:
            return 0
        oldest = min(_ip_timestamps[ip])
        remaining = RATE_WINDOW_SECONDS - (now - oldest)
        return max(1, int(remaining / 60) + 1)


# ---------------------------------------------------------------------------
# Validation functions
# ---------------------------------------------------------------------------


def validate_file(file_path: str) -> str | None:
    """Validate a single file. Returns error message or None if OK."""
    p = pathlib.Path(file_path)
    if not p.exists():
        return "File not found."

    # Size check
    size_mb = p.stat().st_size / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        return f"This file exceeds the {MAX_FILE_SIZE_MB} MB limit. Please compress or split it."

    # MIME type check
    mime, _ = mimetypes.guess_type(str(p))
    if p.suffix.lower() != ".pdf":
        detected = mime or "unknown"
        return f"Only PDF files are accepted. This file appears to be {detected}."

    # Basic PDF header check
    try:
        header = p.read_bytes()[:5]
        if header != b"%PDF-":
            return "Only PDF files are accepted. This file does not have a valid PDF header."
    except Exception:
        return "Could not read file."

    return None


def validate_batch(file_paths: list[str]) -> str | None:
    """Validate a batch of files. Returns error message or None if OK."""
    total_size = 0
    for fp in file_paths:
        p = pathlib.Path(fp)
        if p.exists():
            total_size += p.stat().st_size
    total_mb = total_size / (1024 * 1024)
    if total_mb > MAX_BATCH_SIZE_MB:
        return f"Total batch size exceeds {MAX_BATCH_SIZE_MB} MB. Please reduce the number of files."
    return None


def check_rate_limit(ip: str) -> str | None:
    """Check rate limit for an IP. Returns error message or None if OK."""
    count = _jobs_in_window(ip)
    if count >= MAX_JOBS_PER_IP_PER_HOUR:
        minutes = _minutes_until_reset(ip)
        return f"You have reached the processing limit. Please try again in {minutes} minutes."
    return None


def record_job(ip: str) -> None:
    """Record a job submission for rate limiting."""
    _record_job(ip)


def reset_for_testing() -> None:
    """Reset rate limiter state (for tests only)."""
    with _lock:
        _ip_timestamps.clear()
