"""UI accessibility tests — GAP 5 requirement.

Uses Playwright + axe-core to verify WCAG 2.1 AA compliance of
generated HTML reports. Tests are skipped if Playwright is not available.

Known Gradio 5.x accessibility limitations (cannot be fixed by this tool):
- Upload dropzone may lack proper ARIA labels in some Gradio versions
- Progress bar may not have ARIA live region announcements
- Some Gradio-generated elements may not have focus indicators

These limitations are documented in README.md under Known Limitations.
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
    not PLAYWRIGHT_AVAILABLE, reason="Playwright not installed — axe-core tests require browser automation"
)

from reporting.html_generator import generate_report
from reporting.summary_generator import generate_summary
from wcag_auditor import audit_pdf


def _make_report(tmp_path: pathlib.Path, name: str = "report.html") -> pathlib.Path:
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Accessibility Test"
    p = tmp_path / "test.pdf"
    pdf.save(str(p))
    r = audit_pdf(p)
    html = generate_report(
        filename="test.pdf",
        title="Accessibility Test",
        timestamp="2026-04-11 12:00:00",
        overall="PASS",
        checkpoints=r["checkpoints"],
    )
    report = tmp_path / name
    report.write_text(html, encoding="utf-8")
    return report


def _make_summary(tmp_path: pathlib.Path) -> pathlib.Path:
    html = generate_summary(
        file_results=[
            {"filename": "a.pdf", "result": "PASS", "checkpoints": [{"status": "PASS"}] * 47},
        ],
        timestamp="2026-04-11 12:00:00",
    )
    p = tmp_path / "summary.html"
    p.write_text(html, encoding="utf-8")
    return p


@skip_no_playwright
def test_html_report_axe_core_scan(tmp_path: pathlib.Path) -> None:
    """Run axe-core against the HTML report and assert zero AA violations."""
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        # Inject axe-core
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js")
        results = page.evaluate("""async () => {
            const results = await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']});
            return results.violations;
        }""")
        browser.close()
        assert len(results) == 0, f"axe-core violations: {results}"


@skip_no_playwright
def test_summary_report_axe_core_scan(tmp_path: pathlib.Path) -> None:
    summary = _make_summary(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{summary}")
        page.add_script_tag(url="https://cdnjs.cloudflare.com/ajax/libs/axe-core/4.7.0/axe.min.js")
        results = page.evaluate("""async () => {
            const results = await axe.run(document, {runOnly: ['wcag2a', 'wcag2aa']});
            return results.violations;
        }""")
        browser.close()
        assert len(results) == 0, f"axe-core violations: {results}"


def test_privacy_notice_visible_before_upload() -> None:
    """Verify the privacy notice text is present in the Gradio UI."""
    import app

    assert "Privacy Notice" in app.PRIVACY_NOTICE_MD
    assert "processed locally" in app.PRIVACY_NOTICE_MD
    assert "No file contents are transmitted" in app.PRIVACY_NOTICE_MD


@skip_no_playwright
def test_keyboard_navigation_report(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page()
        page.goto(f"file://{report}")
        # Tab should reach the skip link first
        page.keyboard.press("Tab")
        focused = page.evaluate("document.activeElement.className")
        assert "skip-link" in focused or page.evaluate("document.activeElement.tagName") == "A"
        browser.close()


# --- Static accessibility checks (no Playwright) ---


def test_report_has_semantic_structure(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    html = report.read_text()
    assert "<header>" in html or "<header " in html
    assert "<main" in html
    assert "<footer>" in html or "<footer " in html
    assert "<section" in html
    assert 'lang="en"' in html


def test_report_tables_have_scope(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    html = report.read_text()
    assert 'scope="col"' in html


def test_report_has_skip_navigation(tmp_path: pathlib.Path) -> None:
    report = _make_report(tmp_path)
    html = report.read_text()
    assert "skip-link" in html
    assert "#main-content" in html


def test_report_uses_details_summary(tmp_path: pathlib.Path) -> None:
    """Collapsible sections should use details/summary for keyboard access."""
    report = _make_report(tmp_path)
    html = report.read_text()
    # The template uses details/summary for manual review items
    assert "<details" in html
    assert "<summary" in html
