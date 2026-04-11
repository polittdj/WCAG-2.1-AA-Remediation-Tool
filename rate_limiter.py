"""rate_limiter.py — Pre-queue validation and rate limiting.

Enforces file size, batch size, MIME type, per-IP rate limits,
and queue depth before any file reaches the processing pipeline.
"""

from __future__ import annotations

import collections
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

# Rejection messages — must match spec exactly.
MSG_FILE_TOO_LARGE = (
    "This file exceeds the 50 MB limit. Please reduce the file size and try again."
)
MSG_BATCH_TOO_LARGE = (
    "Total upload size exceeds the 500 MB limit. "
    "Please reduce the number or size of files."
)
MSG_RATE_LIMITED = (
    "You've reached the processing limit (10 per hour). Please try again later."
)
MSG_NON_PDF = (
    "Only PDF files are accepted. The uploaded file appears to be a different format."
)
MSG_QUEUE_FULL = (
    "Processing capacity is currently full. Please try again in a few minutes."
)


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


# ---------------------------------------------------------------------------
# Queue depth guard
# ---------------------------------------------------------------------------

_queue_lock = threading.Lock()
_active_jobs = 0
_max_queue_depth = 20  # default; overridden by set_max_queue_depth()


def set_max_queue_depth(n: int) -> None:
    """Set the maximum number of concurrent jobs."""
    global _max_queue_depth
    _max_queue_depth = n


def check_queue_depth() -> str | None:
    """Return error message if queue is full, else None."""
    with _queue_lock:
        if _active_jobs >= _max_queue_depth:
            return MSG_QUEUE_FULL
    return None


def acquire_queue_slot() -> bool:
    """Try to acquire a queue slot. Returns True if successful."""
    global _active_jobs
    with _queue_lock:
        if _active_jobs >= _max_queue_depth:
            return False
        _active_jobs += 1
        return True


def release_queue_slot() -> None:
    """Release a queue slot after processing completes."""
    global _active_jobs
    with _queue_lock:
        _active_jobs = max(0, _active_jobs - 1)


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
        return MSG_FILE_TOO_LARGE

    # MIME type check — extension must be .pdf
    if p.suffix.lower() != ".pdf":
        return MSG_NON_PDF

    # Basic PDF header check
    try:
        header = p.read_bytes()[:5]
        if header != b"%PDF-":
            return MSG_NON_PDF
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
        return MSG_BATCH_TOO_LARGE
    return None


def check_rate_limit(ip: str) -> str | None:
    """Check rate limit for an IP. Returns error message or None if OK."""
    count = _jobs_in_window(ip)
    if count >= MAX_JOBS_PER_IP_PER_HOUR:
        return MSG_RATE_LIMITED
    return None


def record_job(ip: str) -> None:
    """Record a job submission for rate limiting."""
    _record_job(ip)


def reset_for_testing() -> None:
    """Reset rate limiter state (for tests only)."""
    global _active_jobs
    with _lock:
        _ip_timestamps.clear()
    with _queue_lock:
        _active_jobs = 0
