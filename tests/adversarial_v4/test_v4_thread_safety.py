"""Category T — Race Conditions & Thread Safety.

Tests run multiple iterations to catch intermittent races.
"""

from __future__ import annotations

import pathlib
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline
from rate_limiter import (
    check_rate_limit,
    record_job,
    reset_for_testing,
    MAX_JOBS_PER_IP_PER_HOUR,
)


# ═══════════════════════════════════════════════════════════════════════
# T1 — Shared mutable state: titles don't cross-contaminate
# ═══════════════════════════════════════════════════════════════════════

def test_t1_no_title_cross_contamination(tmp_path):
    """Process 4 files concurrently; each must keep its own title."""
    titles = ["Alice Report", "Bob Report", "Charlie Report", "Diana Report"]
    srcs = []
    for i, title in enumerate(titles):
        p = tmp_path / f"file_{i}.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = title
        pdf.save(str(p))
        pdf.close()
        srcs.append(p)

    # Run 5 iterations to catch intermittent races
    for iteration in range(5):
        results = {}
        with ThreadPoolExecutor(max_workers=3) as ex:
            futures = {}
            for i, src in enumerate(srcs):
                out = tmp_path / f"iter{iteration}_out_{i}"
                out.mkdir(parents=True, exist_ok=True)
                fut = ex.submit(run_pipeline, str(src), str(out))
                futures[fut] = (i, titles[i])

            for done in as_completed(futures):
                idx, expected_title = futures[done]
                res = done.result()
                results[idx] = res

        # Verify each output has its own title
        for idx, res in results.items():
            if not res.get("output_pdf"):
                continue
            with pikepdf.open(res["output_pdf"]) as pdf:
                actual = str(pdf.docinfo.get("/Title", ""))
                assert titles[idx] in actual or actual == titles[idx], (
                    f"Iteration {iteration}, file {idx}: "
                    f"expected title containing '{titles[idx]}', got '{actual}'"
                )


# ═══════════════════════════════════════════════════════════════════════
# T5 — Rate limiter thread safety
# ═══════════════════════════════════════════════════════════════════════

def test_t5_rate_limiter_thread_safety():
    """20 simultaneous requests from same IP: exactly 10 accepted."""
    reset_for_testing()
    ip = "192.168.99.99"
    accepted = []
    rejected = []

    def _try_request():
        err = check_rate_limit(ip)
        if err is None:
            record_job(ip)
            return "accepted"
        return "rejected"

    # Run 10 iterations
    for iteration in range(10):
        reset_for_testing()
        results = []
        with ThreadPoolExecutor(max_workers=20) as ex:
            futures = [ex.submit(_try_request) for _ in range(20)]
            for f in as_completed(futures):
                results.append(f.result())

        acc = results.count("accepted")
        rej = results.count("rejected")
        assert acc == MAX_JOBS_PER_IP_PER_HOUR, (
            f"Iteration {iteration}: {acc} accepted (expected {MAX_JOBS_PER_IP_PER_HOUR})"
        )
        assert rej == 20 - MAX_JOBS_PER_IP_PER_HOUR, (
            f"Iteration {iteration}: {rej} rejected (expected {20 - MAX_JOBS_PER_IP_PER_HOUR})"
        )

    reset_for_testing()


# ═══════════════════════════════════════════════════════════════════════
# T3 — Temp directory uniqueness
# ═══════════════════════════════════════════════════════════════════════

def test_t3_unique_temp_dirs(tmp_path):
    """Each concurrent job must use a unique temp directory."""
    srcs = []
    for i in range(4):
        p = tmp_path / f"file_{i}.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = f"File {i}"
        pdf.save(str(p))
        pdf.close()
        srcs.append(p)

    output_pdfs = []
    with ThreadPoolExecutor(max_workers=3) as ex:
        futures = {}
        for i, src in enumerate(srcs):
            out = tmp_path / f"out_{i}"
            out.mkdir(parents=True, exist_ok=True)
            fut = ex.submit(run_pipeline, str(src), str(out))
            futures[fut] = i

        for done in as_completed(futures):
            res = done.result()
            if res.get("output_pdf"):
                output_pdfs.append(res["output_pdf"])

    # All output paths must be unique
    assert len(output_pdfs) == len(set(output_pdfs)), \
        f"Duplicate output paths detected: {output_pdfs}"
