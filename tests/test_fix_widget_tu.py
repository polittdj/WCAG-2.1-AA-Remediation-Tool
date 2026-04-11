"""Acceptance tests for fix_widget_tu.py.

Verifies that every widget with missing /TU gets a plausible
accessible name derived from /T or parent /T, and that widgets that
already have /TU are left alone.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_widget_tu import _clean_label, fix_widget_tu  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"

GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
EDITABLE = TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [
    GOOD,
    EDITABLE,
    TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf",
    TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf",
    TRAVEL,
]


def _statuses(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def _count_missing_tu(path: pathlib.Path) -> int:
    with pikepdf.open(str(path)) as pdf:
        missing = 0
        for page in pdf.pages:
            annots = page.get("/Annots") or []
            for a in annots:
                try:
                    if str(a.get("/Subtype", "")) != "/Widget" or "/Rect" not in a:
                        continue
                    tu = a.get("/TU")
                    if tu is None or not str(tu).strip():
                        missing += 1
                except Exception:
                    pass
        return missing


# ---------------------------------------------------------------------------
# Unit-level coverage for the label cleaner
# ---------------------------------------------------------------------------


def test_clean_label_strips_af_suffixes() -> None:
    assert _clean_label("Return Date_af_date") == "Return Date"
    assert _clean_label("Total_af_currency") == "Total"
    assert _clean_label("Zip_af_zip") == "Zip"


def test_clean_label_rejects_bare_index() -> None:
    assert _clean_label("0") == ""
    assert _clean_label("7") == ""
    assert _clean_label("  ") == ""
    assert _clean_label(None) == ""  # type: ignore[arg-type]


def test_clean_label_collapses_whitespace_and_underscores() -> None:
    assert _clean_label("Estimated   Cost") == "Estimated Cost"
    assert _clean_label("Company_Name") == "Company Name"
    assert _clean_label("Task-Order-Number") == "Task Order Number"


# ---------------------------------------------------------------------------
# End-to-end on the Travel Form
# ---------------------------------------------------------------------------


def test_travel_form_fills_all_missing_tu(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    missing_before = _count_missing_tu(TRAVEL)
    assert missing_before > 0, "test precondition: Travel Form must have missing /TU"
    res = fix_widget_tu(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["widgets_filled"] == missing_before
    assert _count_missing_tu(out) == 0
    # C-02 in the auditor is exactly the "all widgets have /TU" check.
    assert _statuses(audit_pdf(out))["C-36"] == "PASS"


def test_group_child_widgets_get_parent_label(tmp_path: pathlib.Path) -> None:
    """Widgets whose /T is a bare index AND that were missing /TU should
    come out with a parent-derived label like 'Destination 1'."""
    # Snapshot which widgets are missing /TU before the fix.
    missing_before: set[tuple[int, int]] = set()
    with pikepdf.open(str(TRAVEL)) as pdf:
        for page in pdf.pages:
            for a in page.get("/Annots") or []:
                if str(a.get("/Subtype", "")) != "/Widget":
                    continue
                tu = a.get("/TU")
                if tu is None or not str(tu).strip():
                    missing_before.add(a.objgen)

    out = tmp_path / "out.pdf"
    res = fix_widget_tu(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]

    checked = 0
    with pikepdf.open(str(out)) as pdf:
        for page in pdf.pages:
            for a in page.get("/Annots") or []:
                if str(a.get("/Subtype", "")) != "/Widget":
                    continue
                if a.objgen not in missing_before:
                    continue  # we didn't touch this one
                t = str(a.get("/T", "")).strip()
                if not t.isdigit():
                    continue
                tu = str(a.get("/TU", "")).strip()
                assert tu, f"widget with /T={t!r} should have /TU after fix"
                # The generated name must not just echo the bare index.
                assert tu != t, f"index-only widget got trivial tu={tu!r}"
                checked += 1
    # Travel Form has several group-index widgets that were missing /TU.
    assert checked > 0, "precondition failed: expected some group-child widgets to need /TU"


def test_existing_tu_left_alone(tmp_path: pathlib.Path) -> None:
    """Widgets with /TU already set must not be overwritten."""
    out = tmp_path / "out.pdf"
    # Capture current /TU values before the fix.
    before: dict[tuple[int, int], str] = {}
    with pikepdf.open(str(TRAVEL)) as pdf:
        for page in pdf.pages:
            for a in page.get("/Annots") or []:
                if str(a.get("/Subtype", "")) != "/Widget":
                    continue
                tu = a.get("/TU")
                if tu is not None and str(tu).strip():
                    before[a.objgen] = str(tu)

    fix_widget_tu(str(TRAVEL), str(out))

    with pikepdf.open(str(out)) as pdf:
        for page in pdf.pages:
            for a in page.get("/Annots") or []:
                og = a.objgen
                if og in before:
                    assert str(a.get("/TU")) == before[og], f"widget {og} /TU was overwritten"


def test_no_regressions_on_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    """Running fix_widget_tu must not regress C-18/C-33/C-34/C-35."""
    for src in ALL_PDFS:
        baseline = _statuses(audit_pdf(src))
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_widget_tu(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        new = _statuses(audit_pdf(out))
        for cid in ("C-39", "C-13", "C-03", "C-46"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed from {baseline[cid]} to {new[cid]}"


def test_non_terminal_parent_field_gets_tu(tmp_path: pathlib.Path) -> None:
    """Non-terminal AcroForm fields (parents with /Kids) also need /TU.

    PAC 2024 audits /TU on the non-terminal field too. The earlier
    implementation only walked /Annots, missing parent field nodes like
    'Departure Location' that carry a non-empty /T but no /TU.

    Uses the raw (unremediated) Travel Form so the precondition holds:
    the already-compliant fixture would have this field fixed up by a
    previous pipeline run.
    """
    raw_travel = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte.pdf"
    out = tmp_path / "out.pdf"
    res = fix_widget_tu(str(raw_travel), str(out))
    assert res["errors"] == [], res["errors"]

    def _walk_parents_missing_tu(path: pathlib.Path) -> list[str]:
        missing: list[str] = []
        with pikepdf.open(str(path)) as pdf:
            acroform = pdf.Root.get("/AcroForm")
            if acroform is None:
                return missing
            stack = list(acroform.get("/Fields") or [])
            seen: set[tuple[int, int]] = set()
            while stack:
                node = stack.pop()
                og = getattr(node, "objgen", None)
                if og is not None:
                    if og in seen:
                        continue
                    seen.add(og)
                kids = node.get("/Kids")
                if kids is None or len(kids) == 0:
                    continue  # terminal field — handled by widget walk
                # Non-terminal field node.
                t = str(node.get("/T", "")).strip()
                tu = str(node.get("/TU", "")).strip()
                if t and not tu and not t.isdigit():
                    missing.append(t)
                for k in kids:
                    stack.append(k)
        return missing

    before = _walk_parents_missing_tu(raw_travel)
    after = _walk_parents_missing_tu(out)
    assert "Departure Location" in before, (
        "test precondition: raw Travel Form should have 'Departure Location' parent field missing /TU"
    )
    assert after == [], f"parent fields still missing /TU after fix: {after}"
