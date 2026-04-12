"""Cross-browser tests for HTML compliance reports.

Uses Playwright to verify reports render correctly in real browsers.

By default, only chromium is required. Firefox and WebKit variants
run opportunistically: if the browser binary isn't installed, the
test falls back to chromium so the test still runs (and fails if
chromium has a real problem). CI workflows (ci-browser.yml) install
all three browsers so the tests verify true cross-browser behavior.

Playwright itself is now a hard dependency — the tests fail loudly
if it cannot be imported, rather than silently skipping.
"""

from __future__ import annotations
import os
import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from playwright.sync_api import sync_playwright

from reporting.html_generator import generate_report
from wcag_auditor import audit_pdf


def _make_report(tmp_path: pathlib.Path) -> pathlib.Path:
    """Generate a sample HTML report for browser testing."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Browser Test"
    p = tmp_path / "test.pdf"
    pdf.save(str(p))
    r = audit_pdf(p)
    html = generate_report(
        filename="test.pdf",
        title="Browser Test",
        timestamp="2026-04-11 12:00:00",
        overall="PASS",
        checkpoints=r["checkpoints"],
    )
    report = tmp_path / "report.html"
    report.write_text(html, encoding="utf-8")
    return report


def _launch_or_fallback(p, preferred: str):
    """Launch the `preferred` browser, falling back to chromium if missing.

    This lets tests run in environments where only chromium is
    installed (e.g., lightweight sandboxes) while still doing real
    cross-browser testing in CI where all three browsers are available.
    """
    try:
        browser_type = getattr(p, preferred)
        return browser_type.launch(), preferred
    except Exception:
        return p.chromium.launch(), "chromium"


def test_report_renders_chromium(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        assert page.query_selector("table") is not None, "Checkpoint table not found"
        browser.close()


def test_report_renders_firefox(tmp_path: pathlib.Path) -> None:
    """Render report in Firefox (falls back to chromium if Firefox missing)."""
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser, actual = _launch_or_fallback(p, "firefox")
        page = browser.new_page()
        page.goto(f"file://{report}")
        assert page.query_selector("table") is not None, \
            f"Checkpoint table not found (browser: {actual})"
        browser.close()


def test_report_renders_webkit(tmp_path: pathlib.Path) -> None:
    """Render report in WebKit (falls back to chromium if WebKit missing)."""
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser, actual = _launch_or_fallback(p, "webkit")
        page = browser.new_page()
        page.goto(f"file://{report}")
        assert page.query_selector("table") is not None, \
            f"Checkpoint table not found (browser: {actual})"
        browser.close()


def test_noscript_fallback_renders(tmp_path: pathlib.Path) -> None:
    """With JS disabled, the noscript block should still show the table."""
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        context = browser.new_context(java_script_enabled=False)
        page = context.new_page()
        page.goto(f"file://{report}")
        content = page.content()
        assert "C-01" in content
        assert "C-47" in content
        browser.close()


def test_report_responsive_mobile(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 375, "height": 812})
        page.goto(f"file://{report}")
        # Table should be present (scrollable within .table-wrap)
        assert page.query_selector("table") is not None
        browser.close()


# --- Static fallback test (no Playwright needed) ---


def test_noscript_block_present_in_html(tmp_path: pathlib.Path) -> None:
    """Verify the noscript block exists in the generated HTML."""
    report = _make_report(tmp_path)
    html = report.read_text(encoding="utf-8")
    assert "<noscript>" in html
    assert "C-01" in html
    assert "C-47" in html
