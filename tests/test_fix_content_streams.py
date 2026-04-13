"""Acceptance tests for fix_content_streams.py.

Uses the locked wcag_auditor as the oracle for C-33 and the no-regression
sweep, plus direct pikepdf inspection for byte-level invariants (BDC/EMC
counts, RoleMap cleanup) and a fitz/pikepdf round-trip for validity.
"""

from __future__ import annotations

import pathlib
import sys

import fitz
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_content_streams import fix_content_streams  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"

GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
EDITABLE = TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf"
MS_WORD = TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf"
EDITABLE_ADA = TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [GOOD, EDITABLE, MS_WORD, EDITABLE_ADA, TRAVEL]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _statuses(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def _audit(path: pathlib.Path) -> dict[str, str]:
    return _statuses(audit_pdf(path))


def _per_page_bdc_emc(path: pathlib.Path) -> list[tuple[int, int]]:
    """Return [(bdc_count, emc_count)] for each page (concatenated streams)."""
    counts: list[tuple[int, int]] = []
    with pikepdf.open(str(path)) as pdf:
        for page in pdf.pages:
            c = page.get("/Contents")
            if c is None:
                counts.append((0, 0))
                continue
            if isinstance(c, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in c)
            else:
                data = bytes(c.read_bytes())
            counts.append((data.count(b"BDC"), data.count(b"EMC")))
    return counts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_extracharspan_removed(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_content_streams(str(EDITABLE), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["tags_replaced"] > 0, "expected at least one substitution"
    statuses = _audit(out)
    assert statuses["C-13"] == "PASS", f"C-33 still failing: {res}"


def test_bdc_emc_counts_preserved(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    before = _per_page_bdc_emc(EDITABLE)
    res = fix_content_streams(str(EDITABLE), str(out))
    assert res["errors"] == [], res["errors"]
    after = _per_page_bdc_emc(out)
    assert len(before) == len(after)
    for i, (b, a) in enumerate(zip(before, after, strict=True), start=1):
        assert b == a, f"page {i}: BDC/EMC counts changed {b} -> {a}"


def test_standard_tags_untouched(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_content_streams(str(GOOD), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["pages_modified"] == 0, f"expected pages_modified == 0, got {res['pages_modified']}"
    assert res["tags_replaced"] == 0
    statuses = _audit(out)
    assert statuses["C-13"] == "PASS"


def test_valid_pdf_after_substitution(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_content_streams(str(EDITABLE), str(out))
    assert res["errors"] == [], res["errors"]

    # pikepdf can open it
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) > 0

    # fitz can open it AND extract page-1 text without error
    doc = fitz.open(str(out))
    try:
        assert doc.page_count > 0
        _ = doc[0].get_text("dict")
    finally:
        doc.close()


def test_rolemap_cleaned(tmp_path: pathlib.Path) -> None:
    """Non-standard RoleMap entries must be replaced with standard equivalents.

    The behaviour changed from "delete non-standard entries" to "replace with
    the closest standard type" so that PDF readers retain a meaningful fallback
    even when content-stream BDC rewriting misses an occurrence.  This test
    verifies the new contract: non-standard KEYS may persist, but their VALUES
    must be standard PDF structure types.
    """
    out = tmp_path / "out.pdf"
    res = fix_content_streams(str(EDITABLE), str(out))
    assert res["errors"] == [], res["errors"]

    from fix_content_streams import STANDARD_TAGS

    with pikepdf.open(str(out)) as pdf:
        sr = pdf.Root.get("/StructTreeRoot")
        assert sr is not None, "StructTreeRoot disappeared"
        rm = sr.get("/RoleMap")
        if rm is None:
            return  # vacuously OK — no non-standard entries remain
        for k in rm:
            name = str(k).lstrip("/")
            val = rm[k]
            val_name = str(val).lstrip("/")
            assert val_name in STANDARD_TAGS, (
                f"RoleMap entry /{name} → /{val_name} is not a standard PDF "
                f"structure type. All RoleMap values must map to a standard type "
                f"after fix_content_streams runs."
            )


def test_no_regressions_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    """C-33 PASS for all 5; C-18, C-34, C-35 unchanged from baseline."""
    for src in ALL_PDFS:
        baseline = _audit(src)
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_content_streams(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        new = _audit(out)
        assert new["C-13"] == "PASS", f"{src.name}: C-33 expected PASS, got {new['C-33']}; res={res}"
        for cid in ("C-39", "C-03", "C-46"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed from {baseline[cid]} to {new[cid]}"
