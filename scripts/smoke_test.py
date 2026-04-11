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

import requests

DEFAULT_URL = (
    "https://polittdj-wcag-2-1-aa-conversion-and-verification-tool-v3"
    ".hf.space"
)

TIMEOUT_SECONDS = 30

EXPECTED_STRINGS = [
    "WCAG 2.1 AA",
    "Upload PDF",
    "Privacy Notice",
]


def smoke_test(url: str) -> bool:
    """Run the smoke test. Returns True on pass."""
    print(f"Smoke test: {url}")
    print(f"Timeout: {TIMEOUT_SECONDS}s")
    print()

    try:
        resp = requests.get(url, timeout=TIMEOUT_SECONDS)
    except requests.RequestException as e:
        print(f"FAIL: Could not reach URL — {e}")
        return False

    print(f"HTTP status: {resp.status_code}")

    if resp.status_code != 200:
        print(f"FAIL: Expected 200, got {resp.status_code}")
        return False

    body = resp.text
    all_found = True
    for expected in EXPECTED_STRINGS:
        if expected in body:
            print(f"  FOUND: '{expected}'")
        else:
            print(f"  MISSING: '{expected}'")
            all_found = False

    if all_found:
        print("\nPASS: All checks passed.")
        return True
    else:
        print("\nFAIL: Some expected strings were not found in the response.")
        return False


def main() -> int:
    url = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_URL
    return 0 if smoke_test(url) else 1


if __name__ == "__main__":
    raise SystemExit(main())
