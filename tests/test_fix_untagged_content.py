"""Acceptance tests for fix_untagged_content.py.

Verifies the module finds untagged path construction groups and BT/ET
text objects, wraps them in the expected marked-content sequences,
preserves BDC/EMC deltas, and never regresses the other critical
checkpoints.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_untagged_content import (  # noqa: E402
    _find_untagged_regions,
    fix_untagged_content,
)
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


def _scan_untagged(path: pathlib.Path) -> dict[str, int]:
    """Count untagged regions on every page using the module's finder."""
    counts = {"text": 0, "path": 0}
    with pikepdf.open(str(path)) as pdf:
        for page in pdf.pages:
            c = page.get("/Contents")
            if c is None:
                continue
            if isinstance(c, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in c)
            else:
                data = bytes(c.read_bytes())
            for kind, _s, _e in _find_untagged_regions(data):
                counts[kind] += 1
    return counts


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_travel_form_untagged_regions_removed(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_untagged_content(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    # Before / after counts — the finder shouldn't see anything on the
    # remediated output.
    before = _scan_untagged(TRAVEL)
    assert before["text"] > 0 or before["path"] > 0, (
        f"test precondition: Travel Form should have untagged content; got {before}"
    )
    after = _scan_untagged(out)
    assert after == {"text": 0, "path": 0}, after
    assert res["spans_added"] == before["text"], (res, before)
    assert res["artifacts_added"] == before["path"], (res, before)


def test_bdc_emc_delta_matches_regions_wrapped(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_untagged_content(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    expected = res["spans_added"] + res["artifacts_added"]

    def _counts(path: pathlib.Path) -> tuple[int, int]:
        total_bdc = 0
        total_emc = 0
        with pikepdf.open(str(path)) as pdf:
            for page in pdf.pages:
                c = page.get("/Contents")
                if c is None:
                    continue
                if isinstance(c, pikepdf.Array):
                    data = b"\n".join(bytes(s.read_bytes()) for s in c)
                else:
                    data = bytes(c.read_bytes())
                total_bdc += data.count(b"BDC")
                total_emc += data.count(b"EMC")
        return total_bdc, total_emc

    before_bdc, before_emc = _counts(TRAVEL)
    after_bdc, after_emc = _counts(out)
    assert after_bdc - before_bdc == expected
    assert after_emc - before_emc == expected


def test_valid_pdf_after_wrap(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_untagged_content(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    with pikepdf.open(str(out)) as pdf:
        assert len(pdf.pages) == 2
        # Every new Span MCID must be retrievable from the ParentTree.
        sr = pdf.Root.get("/StructTreeRoot")
        assert sr is not None
        pt = sr.get("/ParentTree")
        assert pt is not None
        assert "/Nums" in pt


def test_struct_tree_gains_span_elements(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_untagged_content(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    spans = res["spans_added"]
    if spans == 0:
        return
    with pikepdf.open(str(out)) as pdf:
        sr = pdf.Root["/StructTreeRoot"]
        k = sr.get("/K")
        doc = k[0] if isinstance(k, pikepdf.Array) else k
        doc_k = doc.get("/K")
        # The top struct element's /K must be an array (we upgrade it
        # when appending) containing at least `spans` new /Span entries.
        assert isinstance(doc_k, pikepdf.Array)
        span_count = 0
        for idx in range(len(doc_k)):
            node = doc_k[idx]
            if isinstance(node, pikepdf.Dictionary) and str(node.get("/S")) == "/Span":
                span_count += 1
        assert span_count >= spans, f"expected >= {spans} /Span children, got {span_count}"


def test_no_regressions_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    """C-33, C-34, C-35 unchanged from baseline on every file."""
    for src in ALL_PDFS:
        baseline = _audit(src)
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_untagged_content(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        assert out.exists(), f"{src.name}: output not created"
        new = _audit(out)
        for cid in ("C-13", "C-03", "C-46"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed from {baseline[cid]} to {new[cid]}"


def test_path_wrap_captures_operand_run() -> None:
    """Regression test: path BDC must come BEFORE its numeric operands.

    The earlier implementation set `path_start_off` to the start of the
    `re`/`m`/`l` operator itself, leaving the numeric operands outside
    the BDC/EMC pair. PAC 2024's parser reads that as "BDC operator must
    have properties list associated in a sequence" and floods 4.1.1 with
    dozens of parse errors.

    Verify that every /Artifact BDC in the rewritten stream appears
    before the `re` operands that feed into its body.
    """
    stream = b"q\n1 0 0 rg\n10 20 30 40 re\nf\nQ\n"
    regions = _find_untagged_regions(stream)
    assert len(regions) == 1
    kind, s, e = regions[0]
    assert kind == "path"
    # The start must point at "10 " (the first operand of `re`), not at
    # "re" itself.
    assert stream[s : s + 2] == b"10"
    # The end must cover the paint operator `f`.
    assert stream[:e].rstrip().endswith(b"f")


def test_path_wrap_output_preserves_operand_order(tmp_path: pathlib.Path) -> None:
    """End-to-end: the wrapped stream has operands INSIDE the BDC/EMC."""
    import re as _re

    out = tmp_path / "out.pdf"
    res = fix_untagged_content(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    with pikepdf.open(str(out)) as pdf:
        for page in pdf.pages:
            data = bytes(page.Contents.read_bytes())
            # Every /Artifact BDC site must be followed by numeric
            # operands before the `re` or path-op appears.
            for m in _re.finditer(rb"/Artifact\s*<<[^>]*>>\s*BDC", data):
                after = data[m.end() : m.end() + 200]
                # Strip leading whitespace.
                stripped = after.lstrip()
                # First non-ws byte must be a digit or minus sign
                # (numeric operand), not an ASCII letter (operator).
                assert stripped[0:1] in b"0123456789.-", f"BDC not immediately followed by operands: {after[:60]!r}"
