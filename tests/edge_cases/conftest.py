"""Shared fixtures for edge-case tests.

Edge-case tests live under ``tests/edge_cases/`` and probe the tool with
unusual / hostile inputs (oversized PDFs, special characters in filenames,
malformed metadata, traversal-shaped paths, etc.). This module is the
infrastructure layer — it provides reusable helpers so the individual test
files can stay focused on *what* they exercise rather than *how* they wire
up the pipeline.

Exposed fixtures
----------------

``edge_tmp_dir``
    Per-test temporary directory (pytest's ``tmp_path``) that is cleaned
    up automatically on teardown. Use this for any files the test writes.

``make_valid_pdf``
    Factory fixture. Call it to generate a minimal valid 1-page PDF on
    disk. Signature: ``make_valid_pdf(path, text="Hello", title="Edge Case Test")``.

``run_through_pipeline``
    Factory fixture that runs an input PDF through ``pipeline.run_pipeline``
    and returns the raw result dict plus the output directory it wrote to.
    Signature: ``run_through_pipeline(input_pdf, output_dir=None)``.

``assert_outputs_contained``
    Assertion helper that verifies every file path reported by the
    pipeline (output PDF, HTML report, ZIP) lives *inside* the expected
    output directory. Catches path-traversal or absolute-path regressions.
    Signature: ``assert_outputs_contained(result, expected_dir)``.

``assert_report_escapes_html``
    Assertion helper that reads an HTML report and verifies a given
    "dangerous" string (e.g. ``<script>alert(1)</script>``) was escaped
    rather than rendered literally.
    Signature: ``assert_report_escapes_html(report_path, raw_string)``.

Design notes
------------

* PDFs are generated with ``reportlab`` because it is already a hard
  dependency of the project (see requirements.txt) and produces structurally
  valid PDFs without needing network access or binary fixtures.
* The fixtures are deliberately thin wrappers — they do not hide what the
  pipeline returns. Tests can still inspect ``result["checkpoints"]``,
  ``result["errors"]``, etc.
* No test cases live in this module. It is infrastructure only; test
  functions belong in sibling ``test_*.py`` files.
"""

from __future__ import annotations

import pathlib
import shutil
import sys
from typing import Any, Callable

import pytest

# Make the repo root importable so ``pipeline`` resolves when the edge_cases
# package is collected directly.
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))


# ---------------------------------------------------------------------------
# Helper: generate a minimal valid 1-page PDF
# ---------------------------------------------------------------------------


def _generate_valid_pdf(
    path: pathlib.Path,
    text: str = "Hello",
    title: str = "Edge Case Test",
) -> pathlib.Path:
    """Write a minimal, structurally valid 1-page PDF to ``path``.

    The PDF has:
      * A single US Letter page
      * One line of body text rendered with Helvetica 12
      * A /Title metadata entry

    Returns the absolute path of the written file.

    Uses reportlab, which is already a hard dependency of the project.
    """
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    c = canvas.Canvas(str(path), pagesize=LETTER)
    c.setTitle(title)
    c.setFont("Helvetica", 12)
    c.drawString(72, 720, text)
    c.showPage()
    c.save()
    return path.resolve()


# ---------------------------------------------------------------------------
# Helper: run a PDF through the full pipeline
# ---------------------------------------------------------------------------


def _run_through_pipeline(
    input_pdf: pathlib.Path,
    output_dir: pathlib.Path,
) -> dict[str, Any]:
    """Run ``pipeline.run_pipeline`` on ``input_pdf`` writing into ``output_dir``.

    Returns the raw result dict from the pipeline. The caller is
    responsible for assertions — this helper only handles wiring.
    """
    # Imported lazily so that collection doesn't fail in environments where
    # the heavy pipeline deps aren't installed. Tests that use this fixture
    # will still need pikepdf/PyMuPDF at run time.
    from pipeline import run_pipeline

    output_dir = pathlib.Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    return run_pipeline(str(input_pdf), str(output_dir))


# ---------------------------------------------------------------------------
# Helper: assert all output files live inside the expected directory
# ---------------------------------------------------------------------------


def _assert_outputs_contained(
    result: dict[str, Any],
    expected_dir: pathlib.Path,
) -> None:
    """Assert every output path in ``result`` is inside ``expected_dir``.

    Guards against regressions that would cause the pipeline to write
    outside the caller-specified directory (path traversal, absolute
    paths leaking from user input, tempdir cleanup bugs, etc.).
    """
    expected_dir = pathlib.Path(expected_dir).resolve()
    keys = ("output_pdf", "report_html", "zip_path")
    for key in keys:
        value = result.get(key)
        if not value:
            # Empty string means the pipeline short-circuited before
            # producing that artifact. That is a legitimate failure mode
            # for some edge cases, so the assertion is limited to paths
            # that do exist.
            continue
        resolved = pathlib.Path(value).resolve()
        assert resolved.exists(), f"{key} path does not exist: {resolved}"
        try:
            resolved.relative_to(expected_dir)
        except ValueError:
            pytest.fail(
                f"{key} escaped the expected output directory:\n"
                f"  got:      {resolved}\n"
                f"  expected: inside {expected_dir}"
            )


# ---------------------------------------------------------------------------
# Helper: assert the HTML report escaped a dangerous string
# ---------------------------------------------------------------------------


def _assert_report_escapes_html(
    report_path: pathlib.Path,
    raw_string: str,
) -> None:
    """Assert ``raw_string`` does not appear verbatim in the HTML report.

    The check is intentionally conservative: it fails if the literal
    ``raw_string`` is found anywhere in the report body. Tests can pass
    classic XSS probes (``<script>...``, ``" onerror=...``) and trust
    that the assertion catches any regression in the report's escaping
    layer.

    A corresponding HTML-escaped form (``&lt;script&gt;...``) is
    *not* required by this helper — the only requirement is that the
    raw, unescaped string is absent.
    """
    report_path = pathlib.Path(report_path)
    assert report_path.exists(), f"HTML report not found: {report_path}"
    html = report_path.read_text(encoding="utf-8", errors="replace")
    if raw_string and raw_string in html:
        pytest.fail(
            "HTML report contains an unescaped dangerous string.\n"
            f"  report: {report_path}\n"
            f"  string: {raw_string!r}"
        )


# ---------------------------------------------------------------------------
# Pytest fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def edge_tmp_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a clean temp directory scoped to the current test.

    Wraps ``tmp_path`` so edge-case tests get a consistently named fixture
    and can rely on automatic teardown. pytest removes ``tmp_path`` after
    the test; this fixture additionally guarantees the directory exists
    at entry even if a previous fixture removed it.
    """
    tmp_path.mkdir(parents=True, exist_ok=True)
    yield tmp_path
    # pytest handles tmp_path cleanup, but be defensive: if the test
    # created files with odd permissions, try once to remove them so
    # the next session's tmp roots don't accumulate.
    if tmp_path.exists():
        shutil.rmtree(tmp_path, ignore_errors=True)


@pytest.fixture
def make_valid_pdf() -> Callable[..., pathlib.Path]:
    """Factory fixture: generate a minimal valid 1-page PDF.

    Usage::

        def test_something(edge_tmp_dir, make_valid_pdf):
            pdf = make_valid_pdf(edge_tmp_dir / "input.pdf", text="Hi")
            ...
    """
    return _generate_valid_pdf


@pytest.fixture
def run_through_pipeline() -> Callable[..., dict[str, Any]]:
    """Factory fixture: run a PDF through the full remediation pipeline.

    Usage::

        def test_something(edge_tmp_dir, make_valid_pdf, run_through_pipeline):
            pdf = make_valid_pdf(edge_tmp_dir / "in.pdf")
            out = edge_tmp_dir / "out"
            result = run_through_pipeline(pdf, out)
            assert result["result"] in ("PASS", "PARTIAL")
    """
    return _run_through_pipeline


@pytest.fixture
def assert_outputs_contained() -> Callable[..., None]:
    """Factory fixture: verify pipeline outputs stay inside a directory."""
    return _assert_outputs_contained


@pytest.fixture
def assert_report_escapes_html() -> Callable[..., None]:
    """Factory fixture: verify an HTML report escaped a dangerous string."""
    return _assert_report_escapes_html
