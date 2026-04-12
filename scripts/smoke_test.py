#!/usr/bin/env python3
"""smoke_test.py — Verify the live Hugging Face Space is operational.

Usage:
    python scripts/smoke_test.py [URL]

Default URL:
    https://huggingface.co/spaces/polittdj/WCAG-2-1-AA-Conversion-and-Verification-Tool-v3

Exit codes:
    0 — PASS
    1 — FAIL
"""

from __future__ import annotations

import sys
import time

import requests

DEFAULT_URL = (
    "https://polittdj-wcag-2-1-aa-conversion-and-verification-tool-v3"
    ".hf.space"
)

REQUEST_TIMEOUT = 30
MAX_RETRIES = 6
RETRY_DELAY = 30  # seconds between retries

EXPECTED_STRINGS = [
    "WCAG 2.1 AA",
    "Upload PDF",
    "Privacy Notice",
]


def smoke_test(url: str) -> bool:
    """Run the smoke test with retries for cold start. Returns True on pass."""
    print(f"Smoke test: {url}")
    print(f"Timeout per request: {REQUEST_TIMEOUT}s")
    print(f"Max retries: {MAX_RETRIES} (every {RETRY_DELAY}s)")
    print()

    last_status = 0
    last_error = ""

    for attempt in range(1, MAX_RETRIES + 1):
        print(f"Attempt {attempt}/{MAX_RETRIES}...")

        try:
            resp = requests.get(url, timeout=REQUEST_TIMEOUT)
            last_status = resp.status_code
        except requests.RequestException as e:
            last_error = str(e)
            print(f"  Connection error: {e}")
            if attempt < MAX_RETRIES:
                print(f"  Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            continue

        print(f"  HTTP status: {resp.status_code}")

        if resp.status_code == 200:
            # Check expected content
            body = resp.text
            all_found = True
            for expected in EXPECTED_STRINGS:
                if expected in body:
                    print(f"  FOUND: '{expected}'")
                else:
                    print(f"  MISSING: '{expected}'")
                    all_found = False

            if all_found:
                print(f"\nPASS: All checks passed on attempt {attempt}.")
                return True
            else:
                print("\nFAIL: HTTP 200 but expected strings missing.")
                return False

        if resp.status_code in (502, 503):
            print(f"  Space still starting (HTTP {resp.status_code}).")
            if attempt < MAX_RETRIES:
                print(f"  Retrying in {RETRY_DELAY}s...")
                time.sleep(RETRY_DELAY)
            continue

        # Any other non-200 is a hard failure
        print(f"\nFAIL: HTTP {resp.status_code}")
        return False

    print(f"\nFAIL: Exhausted {MAX_RETRIES} retries. "
          f"Last status: {last_status}, last error: {last_error}")
    return False


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    return 0 if smoke_test(url) else 1


if __name__ == "__main__":
    raise SystemExit(main())
