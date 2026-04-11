"""Tests for rollback/smoke test logic — GAP 3 requirement.

Tests the smoke test LOGIC, not actual deployment.
"""

from __future__ import annotations
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


def test_app_starts_without_crash():
    """Import app.py and verify the Gradio Blocks object builds."""
    import app

    demo = app.build_ui()
    assert demo is not None


def test_smoke_test_endpoint_exists():
    """Verify the app module exposes the expected entry points."""
    import app

    assert hasattr(app, "build_ui")
    assert hasattr(app, "process_files_core")
    assert hasattr(app, "main")
    # Verify build_ui returns a Gradio Blocks instance
    demo = app.build_ui()
    assert hasattr(demo, "launch")


def test_smoke_test_detects_failure(monkeypatch):
    """Mock a broken pipeline and verify error propagation."""
    import app

    def _broken_pipeline(input_path, output_dir):
        raise RuntimeError("Simulated pipeline failure")

    monkeypatch.setattr("app.run_pipeline", _broken_pipeline)
    rows, combined_zip, errs = app.process_files_core(
        [str(ROOT / "test_suite" / "12.0_updated - WCAG 2.1 AA Compliant.pdf")],
        work_root=pathlib.Path("/tmp/rollback_test"),
    )
    # Should produce an ERROR row, not crash
    assert len(rows) == 1
    assert rows[0][1] == "ERROR"
