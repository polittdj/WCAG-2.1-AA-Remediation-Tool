# Edge-Case Testing Baseline

**Date:** 2026-04-13

This document captures the baseline state of the test suite *before* any
edge-case tests are added under `tests/edge_cases/`. Future QA work that
lands new edge-case tests should compare against these numbers.

## Existing test totals

- **Total tests collected by pytest:** 503
- **Passing:** 495
- **Failing:** 8

## Passing status

**All existing tests are NOT fully passing** — there are 8 pre-existing
failures, but **none of them are product bugs**. All 8 failures come from
the same root cause: Playwright's browser binaries are missing from the
sandbox environment (`/opt/pw-browsers/chromium_headless_shell-1208/...`
does not exist). The affected tests are:

| # | Test |
|---|------|
| 1 | `tests/test_browser_compatibility.py::test_report_renders_chromium` |
| 2 | `tests/test_browser_compatibility.py::test_report_renders_firefox` |
| 3 | `tests/test_browser_compatibility.py::test_report_renders_webkit` |
| 4 | `tests/test_browser_compatibility.py::test_noscript_fallback_renders` |
| 5 | `tests/test_browser_compatibility.py::test_report_responsive_mobile` |
| 6 | `tests/test_ui_accessibility.py::test_html_report_axe_core_scan` |
| 7 | `tests/test_ui_accessibility.py::test_summary_report_axe_core_scan` |
| 8 | `tests/test_ui_accessibility.py::test_keyboard_navigation_report` |

All 8 produce identical errors of the form:

```
playwright._impl._errors.Error: BrowserType.launch:
Executable doesn't exist at /opt/pw-browsers/chromium_headless_shell-1208/...
```

Running `playwright install chromium firefox webkit` in the sandbox
would clear all 8 failures. The remaining **495 tests covering Python
product code all pass** in 144.45 seconds.

## Infrastructure commit confirmation

The edge-case test infrastructure has been committed and merged:

- **Feature branch:** `claude/edge-case-infra`
- **Pull request:** polittdj/WCAG-2.1-AA-Remediation-Tool#8 (merged)
- **Files added:**
  - `tests/edge_cases/__init__.py`
  - `tests/edge_cases/conftest.py` (256 lines)
- **Fixtures exposed:**
  - `edge_tmp_dir` — per-test temp directory with automatic cleanup
  - `make_valid_pdf` — generate a minimal valid 1-page PDF via reportlab
  - `run_through_pipeline` — run an input PDF through `pipeline.run_pipeline`
  - `assert_outputs_contained` — verify pipeline outputs stay inside the
    expected output directory (path-traversal guard)
  - `assert_report_escapes_html` — verify a dangerous string is not
    rendered verbatim in an HTML report (XSS guard)

pytest collection after the merge:

- `pytest tests/edge_cases/ --collect-only` → clean, 0 errors
- `pytest tests/ --collect-only` → still 503 tests collected
- `pytest tests/edge_cases/ --fixtures` → all 5 fixtures discoverable

No new tests have been authored yet. The infrastructure is ready for
edge-case test cases to land in follow-up changes.
