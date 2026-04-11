"""Cross-browser tests for HTML compliance reports — GAP 4 requirement.

Uses Playwright to verify reports render correctly in Chromium, Firefox,
and WebKit. Tests are skipped if Playwright is not installed.

In CI environments with Playwright and browsers available, these tests
will run automatically.
"""

from __future__ import annotations
import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

try:
    from playwright.sync_api import sync_playwright

    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

skip_no_playwright = pytest.mark.skipif(
    not PLAYWRIGHT_AVAILABLE,
    reason="Playwright not installed — install with: pip install playwright && playwright install",
)

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


@skip_no_playwright
def test_report_renders_chromium(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        errors = page.evaluate("() => window.__playwright_errors || []")
        assert page.query_selector("table") is not None, "Checkpoint table not found"
        browser.close()


@skip_no_playwright
def test_report_renders_firefox(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.firefox.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        assert page.query_selector("table") is not None
        browser.close()


@skip_no_playwright
def test_report_renders_webkit(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.webkit.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        assert page.query_selector("table") is not None
        browser.close()


@skip_no_playwright
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


@skip_no_playwright
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
