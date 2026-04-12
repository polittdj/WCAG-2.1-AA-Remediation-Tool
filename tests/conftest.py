"""Pytest configuration and shared fixtures.

This conftest.py:

1. Configures the Playwright browsers path so browser tests find the
   shared browser install in /opt/pw-browsers (if present).
2. Auto-generates missing TEST_*.pdf fixtures in test_suite/ before
   any integration test runs. Generated fixtures mirror the conditions
   the tests check (untagged, no language, broken struct tree, etc.).
3. Provides a session-scoped fixture `axe_core_js_path` that points
   to a bundled axe.min.js file so tests don't need to hit a CDN.
"""

from __future__ import annotations

import os
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Playwright browsers
# ---------------------------------------------------------------------------

# If Playwright's shared browser install is available in /opt/pw-browsers,
# point PLAYWRIGHT_BROWSERS_PATH at it so tests don't need to re-download
# chromium. This is the standard location on hosted sandboxes and CI.
_SHARED_BROWSERS = pathlib.Path("/opt/pw-browsers")
if _SHARED_BROWSERS.exists() and "PLAYWRIGHT_BROWSERS_PATH" not in os.environ:
    os.environ["PLAYWRIGHT_BROWSERS_PATH"] = str(_SHARED_BROWSERS)


# ---------------------------------------------------------------------------
# Axe-core local script
# ---------------------------------------------------------------------------


def _find_axe_script() -> pathlib.Path | None:
    """Return the path to a local axe.min.js file (or None if not found).

    Checks the following locations in order:
      1. tests/_vendor/axe.min.js  (committed copy)
      2. axe_core_python package   (pip install axe-core-python)
      3. axe-selenium-python package
    """
    candidates = [
        ROOT / "tests" / "_vendor" / "axe.min.js",
    ]
    # axe_core_python bundles the axe.min.js file.
    try:
        import axe_core_python  # type: ignore
        axe_pkg = pathlib.Path(axe_core_python.__file__).parent
        candidates.append(axe_pkg / "axe.min.js")
    except Exception:
        pass
    for c in candidates:
        if c.exists():
            return c
    return None


@pytest.fixture(scope="session")
def axe_core_js_path() -> pathlib.Path:
    """Return path to a local axe.min.js file. Fails loudly if not found.

    Tests that need axe-core should depend on this fixture so the scan
    runs offline against a known version.
    """
    p = _find_axe_script()
    if p is None:
        pytest.fail(
            "axe.min.js not found. Install with: pip install axe-core-python "
            "or commit a copy to tests/_vendor/axe.min.js"
        )
    return p


# ---------------------------------------------------------------------------
# Integration test fixture PDFs (TEST_*.pdf)
# ---------------------------------------------------------------------------

TEST_SUITE_DIR = ROOT / "test_suite"


@pytest.fixture(scope="session", autouse=True)
def _generate_integration_fixtures():
    """Before any tests run, ensure all TEST_*.pdf fixtures exist.

    These fixtures are generated programmatically with pikepdf so the
    test suite works in any environment without committing large
    binaries or relying on Git LFS.
    """
    try:
        from tests.integration_fixtures import generate_all_test_fixtures
    except Exception as e:
        # If the generator module can't be imported, don't block tests
        # that don't need these fixtures.
        print(f"[conftest] WARNING: could not import integration_fixtures: {e}")
        return
    try:
        generate_all_test_fixtures(TEST_SUITE_DIR)
    except Exception as e:
        print(f"[conftest] WARNING: fixture generation failed: {e}")
