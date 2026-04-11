"""Acceptance tests for fix_title.py.

Each test runs fix_title against one or more reference PDFs in test_suite/
and uses the locked wcag_auditor.audit_pdf to verify C-34 PASSes (and that
C-18/C-33/C-35 are not regressed).
"""

from __future__ import annotations

import pathlib
import sys

# Make repo root importable so `import fix_title` and `import wcag_auditor`
# work no matter where pytest is invoked from.
ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_title import fix_title  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"

MS_WORD_CONVERTED = TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf"
TRAVEL_FORM = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"
GOOD_TITLE_PDF = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
EDITABLE = TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
EDITABLE_ADA = TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf"

ALL_REFERENCE_PDFS = [
    GOOD_TITLE_PDF,
    EDITABLE,
    MS_WORD_CONVERTED,
    EDITABLE_ADA,
    TRAVEL_FORM,
]


def _status_by_id(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def _audit_path(path: pathlib.Path) -> dict[str, str]:
    return _status_by_id(audit_pdf(path))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_blacklisted_title_replaced(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_title(str(MS_WORD_CONVERTED), str(out))
    assert res["errors"] == [], res["errors"]
    assert out.exists()
    statuses = _audit_path(out)
    assert statuses["C-03"] == "PASS", f"C-34 expected PASS, got {statuses['C-34']}; result={res}"


def test_good_title_preserved(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    before = audit_pdf(GOOD_TITLE_PDF)
    before_title = next(c["detail"] for c in before["checkpoints"] if c["id"] == "C-03")

    res = fix_title(str(GOOD_TITLE_PDF), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["method"] == "existing", f"expected method=existing, got {res['method']}"

    after = audit_pdf(out)
    after_title = next(c["detail"] for c in after["checkpoints"] if c["id"] == "C-03")
    assert _status_by_id(after)["C-03"] == "PASS"
    assert after_title == before_title, f"title changed: before={before_title!r} after={after_title!r}"
    # And the original_title returned by fix_title equals the title_set.
    assert res["title_set"] == res["original_title"]


def test_content_derived_probate_form(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_title(str(MS_WORD_CONVERTED), str(out))
    assert res["errors"] == [], res["errors"]
    title_lower = res["title_set"].lower()
    assert any(keyword in title_lower for keyword in ("certificate", "transfer", "application")), (
        f"Derived title {res['title_set']!r} missing keyword"
    )


def test_content_derived_travel_form(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_title(str(TRAVEL_FORM), str(out))
    assert res["errors"] == [], res["errors"]
    assert "travel" in res["title_set"].lower(), f"Derived title {res['title_set']!r} missing 'travel'"


def test_no_output_has_blacklisted_title(tmp_path: pathlib.Path) -> None:
    """All 5 fixed outputs PASS C-34, and C-18/C-33/C-35 do not regress."""
    for src in ALL_REFERENCE_PDFS:
        original_statuses = _audit_path(src)

        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_title(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        assert out.exists(), f"{src.name}: output not created"

        new_statuses = _audit_path(out)
        assert new_statuses["C-03"] == "PASS", (
            f"{src.name}: C-34 expected PASS, got {new_statuses['C-34']}; result={res}"
        )
        for cid in ("C-39", "C-13", "C-46"):
            assert new_statuses[cid] == original_statuses[cid], (
                f"{src.name}: {cid} regressed from {original_statuses[cid]} to {new_statuses[cid]}"
            )
