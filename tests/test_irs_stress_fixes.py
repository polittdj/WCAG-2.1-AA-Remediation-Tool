"""Regression tests for the IRS stress-test findings.

Covers all 6 production fixes (P1–P6) plus BUG-02/07/08/09:
  P1 — pipeline.py: C-20/C-24/C-25/C-28 are now CRITICAL_CHECKPOINTS
  P2 — fix_headings.py: extra H1s are demoted to H2 (even for existing headings)
  P3 — fix_content_tagger.py: Scope added to pre-existing TH elements
  P4 — fix_content_streams.py: RoleMap entries replaced, not deleted
  P5 — report.html.j2: status icons render as Unicode, not double-encoded entities
  P6 — report.html.j2: progress % excludes N/A from denominator
  BUG-02 — src/utils/structure_validator: detects orphaned/duplicate MCIDs & broken ParentTree
  BUG-07 — pipeline.py: audit now runs on the final output (after /Tabs fix)
  BUG-08 — fix_content_tagger.py: /Table > /TH+/TD cells wrapped in /TR (C-24)
  BUG-09 — fix_content_tagger.py: /L > /Lbl+/LBody items wrapped in /LI (C-28)
"""

from __future__ import annotations

import json
import pathlib
import re
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_content_streams import fix_content_streams
from fix_content_tagger import (
    fix_content_tagger,
    _fix_existing_th_scope,
    _fix_table_tr_structure,
    _fix_list_li_structure,
)
from fix_headings import fix_headings, _demote_extra_h1s, _fix_heading_levels
from pipeline import CRITICAL_CHECKPOINTS, _NA_ACCEPTABLE, run_pipeline
from src.utils.structure_validator import validate_structure_tree


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tagged_pdf(tmp_path: pathlib.Path, name: str = "test.pdf") -> pikepdf.Pdf:
    """Return a minimal tagged PDF (not saved yet — caller must pdf.save())."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})
    pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()}))
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/ParentTree": pt,
        "/K": pikepdf.Array(),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    return pdf


def _add_struct_elem(pdf: pikepdf.Pdf, tag: str, parent_k: pikepdf.Array,
                     *, attrs: dict | None = None) -> pikepdf.Dictionary:
    d: dict = {
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name(f"/{tag}"),
    }
    if attrs:
        d.update(attrs)
    elem = pdf.make_indirect(pikepdf.Dictionary(d))
    parent_k.append(elem)
    return elem


def _save(pdf: pikepdf.Pdf, tmp_path: pathlib.Path, name: str = "test.pdf") -> pathlib.Path:
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _audit_statuses(result: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in result.get("checkpoints", [])}


# ---------------------------------------------------------------------------
# P1 — CRITICAL_CHECKPOINTS completeness
# ---------------------------------------------------------------------------


def test_c20_is_critical():
    """C-20 (heading hierarchy) must be a critical checkpoint."""
    assert "C-20" in CRITICAL_CHECKPOINTS, (
        "C-20 is not in CRITICAL_CHECKPOINTS — files with multiple H1 headers "
        "will be falsely labeled PASS"
    )


def test_c24_is_critical():
    """C-24 (table /TR structure) must be a critical checkpoint."""
    assert "C-24" in CRITICAL_CHECKPOINTS


def test_c25_is_critical():
    """C-25 (TH Scope) must be a critical checkpoint."""
    assert "C-25" in CRITICAL_CHECKPOINTS, (
        "C-25 is not in CRITICAL_CHECKPOINTS — files with TH elements missing "
        "Scope will be falsely labeled PASS"
    )


def test_c28_is_critical():
    """C-28 (list /LI structure) must be a critical checkpoint."""
    assert "C-28" in CRITICAL_CHECKPOINTS


def test_na_acceptable_includes_new_criticals():
    """N/A is valid for C-20/C-24/C-25/C-28 when content doesn't apply."""
    for cid in ("C-20", "C-24", "C-25", "C-28"):
        assert cid in _NA_ACCEPTABLE, (
            f"{cid} must be in _NA_ACCEPTABLE so documents without "
            "headings/tables/lists can still PASS"
        )


def test_pipeline_partial_when_c20_fails(tmp_path):
    """A pipeline result with C-20 FAIL must produce overall PARTIAL."""
    # Build a PDF that will get multiple H1 headings in its struct tree
    # by creating headings directly and then checking the outcome.
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    doc_k = pikepdf.Array()
    doc["/K"] = doc_k
    # Add TWO H1s — this is what C-20 flags
    _add_struct_elem(pdf, "H1", doc_k)
    _add_struct_elem(pdf, "H1", doc_k)
    pdf.docinfo["/Title"] = "Dual H1 Test"
    pdf.Root["/Lang"] = pikepdf.String("en-US")
    inp = _save(pdf, tmp_path, "dual_h1_input.pdf")

    out_dir = tmp_path / "out"
    res = run_pipeline(str(inp), str(out_dir))
    # The result should be PARTIAL (C-20 may FAIL or auditor demoted them — either
    # way it should not be a clean PASS with a known heading-hierarchy issue).
    # We only assert on the overall result being determined correctly when FAIL.
    statuses = _audit_statuses(res)
    # If C-20 is still FAIL after pipeline, overall must be PARTIAL.
    if statuses.get("C-20") == "FAIL":
        assert res["result"] == "PARTIAL", (
            "Pipeline marked result PASS despite C-20 FAIL checkpoint"
        )


# ---------------------------------------------------------------------------
# P2 — _demote_extra_h1s and fix_headings H1 demotion
# ---------------------------------------------------------------------------


def test_demote_extra_h1s_no_op_single_h1(tmp_path):
    """Single H1 is left unchanged."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    doc["/K"] = pikepdf.Array()
    _add_struct_elem(pdf, "H1", doc["/K"])
    count = _demote_extra_h1s(pdf)
    assert count == 0


def test_demote_extra_h1s_demotes_second_and_third(tmp_path):
    """Three H1s → first stays H1, second and third become H2."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    h1a = _add_struct_elem(pdf, "H1", k)
    h1b = _add_struct_elem(pdf, "H1", k)
    h1c = _add_struct_elem(pdf, "H1", k)

    count = _demote_extra_h1s(pdf)
    assert count == 2
    assert str(h1a["/S"]).lstrip("/") == "H1"   # first H1 unchanged
    assert str(h1b["/S"]).lstrip("/") == "H2"   # demoted
    assert str(h1c["/S"]).lstrip("/") == "H2"   # demoted


def test_fix_headings_demotes_existing_duplicate_h1s(tmp_path):
    """fix_headings demotes extra H1s even when headings already exist."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    _add_struct_elem(pdf, "H1", k)
    _add_struct_elem(pdf, "H1", k)  # duplicate
    inp = _save(pdf, tmp_path, "two_h1.pdf")
    out = tmp_path / "out.pdf"

    res = fix_headings(str(inp), str(out))
    # Must still report "already has heading tags"
    assert any("already has heading tags" in ch for ch in res["changes"])
    # Must report the demotion
    assert any("Demoted" in ch for ch in res["changes"])

    # Verify the output PDF has exactly one H1
    with pikepdf.open(str(out)) as out_pdf:
        sr = out_pdf.Root["/StructTreeRoot"]
        h1_count = 0
        h2_count = 0
        stack = [sr]
        seen: set = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            og = getattr(node, "objgen", None)
            if og is not None:
                if og in seen:
                    continue
                seen.add(og)
            s = node.get("/S")
            if s is not None:
                tag = str(s).lstrip("/")
                if tag == "H1":
                    h1_count += 1
                elif tag == "H2":
                    h2_count += 1
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(list(sub))
                elif isinstance(sub, pikepdf.Dictionary):
                    stack.append(sub)
    assert h1_count == 1, f"Expected 1 H1 after fix, got {h1_count}"
    assert h2_count >= 1, "Expected at least one H2 after demotion"


def test_fix_heading_levels_promotes_skipped_level(tmp_path):
    """H1 → H3 (skipped H2) must be promoted to H1 → H2."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    h1 = _add_struct_elem(pdf, "H1", k)
    h3 = _add_struct_elem(pdf, "H3", k)  # skips H2

    count = _fix_heading_levels(pdf)
    assert count == 1
    assert str(h1["/S"]).lstrip("/") == "H1"  # unchanged
    assert str(h3["/S"]).lstrip("/") == "H2"  # promoted from H3 to H2


def test_fix_heading_levels_no_op_valid_sequence(tmp_path):
    """A valid H1 → H2 → H3 sequence is not modified."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    _add_struct_elem(pdf, "H1", k)
    _add_struct_elem(pdf, "H2", k)
    _add_struct_elem(pdf, "H3", k)

    count = _fix_heading_levels(pdf)
    assert count == 0


def test_fix_headings_fixes_skipped_levels_in_existing_doc(tmp_path):
    """fix_headings promotes skipped heading levels in documents with headings."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    _add_struct_elem(pdf, "H1", k)
    _add_struct_elem(pdf, "H3", k)  # skip H2
    inp = _save(pdf, tmp_path, "skip_h2.pdf")
    out = tmp_path / "out.pdf"

    res = fix_headings(str(inp), str(out))
    assert any("Promoted" in ch for ch in res["changes"])

    with pikepdf.open(str(out)) as out_pdf:
        sr = out_pdf.Root["/StructTreeRoot"]
        levels = []
        stack = [sr]
        seen: set = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            og = getattr(node, "objgen", None)
            if og is not None:
                if og in seen:
                    continue
                seen.add(og)
            s = node.get("/S")
            if s is not None:
                tag = str(s).lstrip("/")
                if tag in ("H1","H2","H3","H4","H5","H6"):
                    levels.append(tag)
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(list(sub))
                else:
                    stack.append(sub)
    level_set = set(levels)
    assert "H1" in level_set, f"H1 missing after fix, levels={levels}"
    assert "H2" in level_set, f"H2 missing after fix (H3 should have been promoted), levels={levels}"
    assert "H3" not in level_set, f"H3 still present after fix (should have been promoted to H2), levels={levels}"


def test_fix_headings_preserves_single_h1(tmp_path):
    """fix_headings does NOT modify a document that has exactly one H1."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    doc["/K"] = pikepdf.Array()
    _add_struct_elem(pdf, "H1", doc["/K"])
    inp = _save(pdf, tmp_path, "single_h1.pdf")
    out = tmp_path / "out.pdf"

    res = fix_headings(str(inp), str(out))
    assert "already has heading tags" in res["changes"][0]
    # No demotion message for a valid single-H1 document
    assert not any("Demoted" in ch for ch in res["changes"])


# ---------------------------------------------------------------------------
# P3 — _fix_existing_th_scope and fix_content_tagger TH scope repair
# ---------------------------------------------------------------------------


def test_fix_existing_th_scope_adds_scope(tmp_path):
    """TH elements without /Scope get /Scope /Column added."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    table = _add_struct_elem(pdf, "Table", k)
    tr_k = pikepdf.Array()
    table["/K"] = tr_k
    tr = _add_struct_elem(pdf, "TR", tr_k)
    th_k = pikepdf.Array()
    tr["/K"] = th_k
    # TH without /A /Scope
    th = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TH"),
    }))
    th_k.append(th)

    count = _fix_existing_th_scope(pdf)
    assert count == 1
    a = th.get("/A")
    assert a is not None
    scope = a.get("/Scope") if isinstance(a, pikepdf.Dictionary) else None
    assert scope is not None
    assert str(scope).lstrip("/") == "Column"


def test_fix_existing_th_scope_skips_th_with_existing_scope(tmp_path):
    """TH elements that already have /Scope are not modified."""
    pdf = _make_tagged_pdf(tmp_path)
    sr_k = pdf.Root["/StructTreeRoot"]["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    k = pikepdf.Array()
    doc["/K"] = k
    th = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TH"),
        "/A": pikepdf.Dictionary({
            "/O": pikepdf.Name("/Table"),
            "/Scope": pikepdf.Name("/Row"),
        }),
    }))
    k.append(th)

    count = _fix_existing_th_scope(pdf)
    assert count == 0
    # Scope should still be /Row (untouched)
    assert str(th["/A"].get("/Scope")).lstrip("/") == "Row"


def test_fix_existing_th_scope_no_tables_no_error(tmp_path):
    """Document with no TH elements returns 0 without error."""
    pdf = _make_tagged_pdf(tmp_path)
    count = _fix_existing_th_scope(pdf)
    assert count == 0


def test_fix_content_tagger_adds_scope_to_existing_table(tmp_path):
    """fix_content_tagger adds /Scope to TH cells in pre-existing tables."""
    # Build a PDF that already has a Table/TR/TH structure but TH has no Scope.
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    sr_k = sr["/K"]
    doc = _add_struct_elem(pdf, "Document", sr_k)
    doc_k = pikepdf.Array()
    doc["/K"] = doc_k

    table = _add_struct_elem(pdf, "Table", doc_k)
    tr = _add_struct_elem(pdf, "TR", pikepdf.Array())
    table["/K"] = pikepdf.Array([tr])
    th = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TH"),
    }))
    tr["/K"] = pikepdf.Array([th])

    pdf.docinfo["/Title"] = "Table Scope Test"
    inp = _save(pdf, tmp_path, "table_no_scope.pdf")
    out = tmp_path / "out.pdf"

    fix_content_tagger(str(inp), str(out))

    with pikepdf.open(str(out)) as out_pdf:
        # Walk struct tree to find the TH and verify it now has /Scope
        sr2 = out_pdf.Root["/StructTreeRoot"]
        stack = [sr2]
        seen: set = set()
        th_scopes: list[str] = []
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            og = getattr(node, "objgen", None)
            if og is not None:
                if og in seen:
                    continue
                seen.add(og)
            s = node.get("/S")
            if s is not None and str(s).lstrip("/") == "TH":
                a = node.get("/A")
                if a is not None and isinstance(a, pikepdf.Dictionary):
                    scope = a.get("/Scope")
                    if scope is not None:
                        th_scopes.append(str(scope).lstrip("/"))
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(list(sub))
                else:
                    stack.append(sub)
    assert th_scopes, "No /Scope found on any TH element after fix_content_tagger"


# ---------------------------------------------------------------------------
# P4 — fix_content_streams RoleMap replacement
# ---------------------------------------------------------------------------


def test_rolemap_replaces_non_standard_entry(tmp_path):
    """Non-standard RoleMap entry is replaced with standard equivalent."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    role_map = pikepdf.Dictionary({
        "/Content": pikepdf.Name("/Span"),   # already correct, but test presence
    })
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/RoleMap": role_map,
        "/K": pikepdf.Array(),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    inp = tmp_path / "rolemap_test.pdf"
    pdf.save(str(inp))
    out = tmp_path / "rolemap_out.pdf"

    fix_content_streams(str(inp), str(out))

    with pikepdf.open(str(out)) as out_pdf:
        rm = out_pdf.Root["/StructTreeRoot"].get("/RoleMap")
        assert rm is not None
        # /Content should map to /Span (not be deleted)
        content_val = rm.get("/Content")
        assert content_val is not None, "/Content entry was deleted from RoleMap (should be preserved)"
        assert str(content_val).lstrip("/") == "Span"


def test_rolemap_maps_unknown_non_standard_to_span(tmp_path):
    """Unknown non-standard RoleMap entry maps to /Span (not deleted)."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    role_map = pikepdf.Dictionary({
        "/MyCustomTag": pikepdf.Name("/P"),  # non-standard key
    })
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/RoleMap": role_map,
        "/K": pikepdf.Array(),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    inp = tmp_path / "custom_rolemap.pdf"
    pdf.save(str(inp))
    out = tmp_path / "custom_rolemap_out.pdf"

    fix_content_streams(str(inp), str(out))

    with pikepdf.open(str(out)) as out_pdf:
        rm = out_pdf.Root["/StructTreeRoot"].get("/RoleMap")
        assert rm is not None
        val = rm.get("/MyCustomTag")
        assert val is not None, "/MyCustomTag was deleted — should map to /Span"
        assert str(val).lstrip("/") == "Span"


def test_content_bdc_tag_in_non_standard_to_standard():
    """'Content' must be in NON_STANDARD_TO_STANDARD so it maps to Span."""
    from fix_content_streams import NON_STANDARD_TO_STANDARD
    assert "Content" in NON_STANDARD_TO_STANDARD, (
        "'Content' BDC tag (used by IRS/Acrobat PDFs) is missing from "
        "NON_STANDARD_TO_STANDARD — it will fall back to generic 'Span' "
        "mapping but having it explicit ensures intent is documented."
    )
    assert NON_STANDARD_TO_STANDARD["Content"] == "Span"


# ---------------------------------------------------------------------------
# P5 — HTML report entity encoding
# ---------------------------------------------------------------------------


def test_html_report_no_double_encoded_entities(tmp_path):
    """Status icons must render as Unicode characters, not &amp;#x2713;."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Entity Encoding Test"
    inp = tmp_path / "entity_test.pdf"
    pdf.save(str(inp))
    out_dir = tmp_path / "out"

    res = run_pipeline(str(inp), str(out_dir))
    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    # The double-encoded form must NOT appear anywhere
    assert "&amp;#x2713;" not in html, "Double-encoded checkmark (&amp;#x2713;) found in report"
    assert "&amp;#x2717;" not in html, "Double-encoded cross (&amp;#x2717;) found in report"
    assert "&amp;#x26A0;" not in html, "Double-encoded warning (&amp;#x26A0;) found in report"

    # The Unicode characters OR their single-encoded forms must appear
    # (either the literal char or &#x2713; are both acceptable)
    has_check = "✓" in html or "&#x2713;" in html or "\\u2713" in html
    assert has_check, "No checkmark character found in report (expected ✓ or &#x2713;)"


# ---------------------------------------------------------------------------
# P6 — Progress bar percentage excludes N/A
# ---------------------------------------------------------------------------


def test_progress_percentage_excludes_na(tmp_path):
    """Compliance % in the HTML report must exclude N/A checkpoints."""
    from reporting.html_generator import generate_report

    # Craft a checkpoint set: 10 PASS, 5 NOT_APPLICABLE, 5 FAIL
    checkpoints = (
        [{"id": f"C-{i:02d}", "name": f"Check {i}", "description": f"Check {i}",
          "status": "PASS", "confidence": 1.0, "details": "", "detail": ""}
         for i in range(1, 11)]
        + [{"id": f"C-{i:02d}", "name": f"Check {i}", "description": f"Check {i}",
            "status": "NOT_APPLICABLE", "confidence": 1.0, "details": "", "detail": ""}
           for i in range(11, 16)]
        + [{"id": f"C-{i:02d}", "name": f"Check {i}", "description": f"Check {i}",
            "status": "FAIL", "confidence": 1.0, "details": "", "detail": ""}
           for i in range(16, 21)]
    )

    html = generate_report(
        filename="test.pdf",
        title="Percentage Test",
        timestamp="2026-01-01 00:00:00",
        overall="PARTIAL",
        checkpoints=checkpoints,
    )

    # Expected: 10 PASS out of 15 applicable (20 total - 5 N/A) = 66%
    # Old formula: 10/20 = 50%. New formula: 10/15 = 66%.
    # Extract the percentage from aria-valuenow attribute
    match = re.search(r'aria-valuenow="(\d+)"', html)
    assert match is not None, "Could not find aria-valuenow in progress bar"
    pct = int(match.group(1))
    # New formula: 10/15 * 100 = 66 (integer division)
    assert pct == 66, (
        f"Expected 66% (10 PASS / 15 applicable), got {pct}%. "
        "N/A items may still be included in the denominator."
    )


def test_progress_percentage_all_na(tmp_path):
    """All N/A checkpoints → percentage should be 100 (not division-by-zero)."""
    from reporting.html_generator import generate_report

    checkpoints = [
        {"id": f"C-{i:02d}", "name": f"Check {i}", "description": f"Check {i}",
         "status": "NOT_APPLICABLE", "confidence": 1.0, "details": "", "detail": ""}
        for i in range(1, 6)
    ]
    html = generate_report(
        filename="test.pdf",
        title="All NA Test",
        timestamp="2026-01-01 00:00:00",
        overall="PASS",
        checkpoints=checkpoints,
    )
    match = re.search(r'aria-valuenow="(\d+)"', html)
    assert match is not None
    pct = int(match.group(1))
    assert pct == 100, f"All-N/A document should show 100%, got {pct}%"


# ---------------------------------------------------------------------------
# BUG-02 — structure_validator
# ---------------------------------------------------------------------------


def test_structure_validator_clean_pdf_returns_no_issues(tmp_path):
    """A well-formed tagged PDF should produce zero validator issues."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    sr_k = sr.get("/K")
    if not isinstance(sr_k, pikepdf.Array):
        sr["/K"] = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array(),
    }))
    pdf.Root["/StructTreeRoot"]["/K"].append(doc)
    issues = validate_structure_tree(pdf)
    assert issues == [], f"Expected no issues for clean PDF, got: {issues}"


def test_structure_validator_missing_struct_tree(tmp_path):
    """A PDF with no StructTreeRoot should report a structural issue."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    issues = validate_structure_tree(pdf)
    assert any("StructTreeRoot" in i for i in issues), (
        f"Expected StructTreeRoot issue, got: {issues}"
    )


def test_structure_validator_missing_parent_tree(tmp_path):
    """A tagged PDF without /ParentTree should be flagged."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array(),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    issues = validate_structure_tree(pdf)
    assert any("ParentTree" in i for i in issues), (
        f"Expected ParentTree issue, got: {issues}"
    )


def test_structure_validator_unordered_parent_tree_keys(tmp_path):
    """ParentTree /Nums with out-of-order keys should be flagged."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})
    # Build a StructTreeRoot with a stub document element
    doc_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array(),
    }))
    # /Nums with keys out of order: [3, ..., 1, ...]
    pt = pdf.make_indirect(pikepdf.Dictionary({
        "/Nums": pikepdf.Array([
            pikepdf.Integer(3), doc_elem,
            pikepdf.Integer(1), doc_elem,
        ])
    }))
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/ParentTree": pt,
        "/K": pikepdf.Array([doc_elem]),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    issues = validate_structure_tree(pdf)
    assert any("out of order" in i.lower() for i in issues), (
        f"Expected out-of-order key issue, got: {issues}"
    )


# ---------------------------------------------------------------------------
# BUG-07 — audit runs on final output (not intermediate)
# ---------------------------------------------------------------------------


def test_bug07_audit_on_final_output(tmp_path):
    """The pipeline result must reflect the FINAL output PDF state, not an
    intermediate.  BUG-07: previously the belt-and-suspenders /Tabs=/S pass
    ran AFTER the audit, so the audit report could describe a different
    (earlier) state than what the user receives.

    We verify indirectly: after run_pipeline the reported C-10 (tab order)
    status must be PASS, because the /Tabs=/S fix now happens before the audit.
    """
    TEST_SUITE = ROOT / "test_suite"
    pdf_path = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
    if not pdf_path.exists():
        pytest.skip("Reference PDF not available")
    out_dir = tmp_path / "out"
    res = run_pipeline(str(pdf_path), str(out_dir))
    statuses = _audit_statuses(res)
    assert statuses.get("C-10") == "PASS", (
        f"C-10 (tab order) should be PASS after pipeline; got {statuses.get('C-10')}. "
        "BUG-07: audit may still be running on an intermediate file."
    )


# ---------------------------------------------------------------------------
# BUG-08 — _fix_table_tr_structure wraps orphan cells in /TR
# ---------------------------------------------------------------------------


def test_fix_table_tr_structure_wraps_orphan_cells(tmp_path):
    """/TH and /TD direct children of /Table must be wrapped in /TR."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    # Build a /Table with TH/TD as DIRECT children (no /TR)
    th = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TH"),
        "/A": pikepdf.Dictionary({"/O": pikepdf.Name("/Table"), "/Scope": pikepdf.Name("/Column")}),
    }))
    td1 = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TD"),
    }))
    td2 = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TD"),
    }))
    table = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Table"),
        "/K": pikepdf.Array([th, td1, td2]),  # no /TR wrapper — this is the bug
    }))
    doc_k.append(table)

    modified = _fix_table_tr_structure(pdf)
    assert modified == 1, f"Expected 1 table modified, got {modified}"

    # The /Table's /K should now be a single /TR (or multiple /TR elements)
    table_k = list(table.get("/K"))
    for child in table_k:
        assert isinstance(child, pikepdf.Dictionary), "Expected Dictionary child"
        child_tag = str(child.get("/S", "")).lstrip("/")
        assert child_tag == "TR", (
            f"Expected all direct /Table children to be /TR, got /{child_tag}"
        )


def test_fix_table_tr_structure_leaves_well_formed_table_unchanged(tmp_path):
    """A /Table with /TR children must not be modified."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    tr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TR"),
        "/K": pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/TD"),
            }))
        ]),
    }))
    table = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Table"),
        "/K": pikepdf.Array([tr]),  # already has /TR wrapper
    }))
    doc_k.append(table)

    modified = _fix_table_tr_structure(pdf)
    assert modified == 0, f"Expected 0 tables modified (already well-formed), got {modified}"


def test_fix_content_tagger_calls_tr_fix(tmp_path):
    """`fix_content_tagger` must run the /TR repair on existing orphan cells."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    # Create a broken table with orphan cells
    th = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TH"),
        "/A": pikepdf.Dictionary({"/O": pikepdf.Name("/Table"), "/Scope": pikepdf.Name("/Column")}),
    }))
    td = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/TD"),
    }))
    table = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Table"),
        "/K": pikepdf.Array([th, td]),
    }))
    doc_k.append(table)

    src = tmp_path / "in.pdf"
    pdf.save(str(src))
    pdf.close()

    out = tmp_path / "out.pdf"
    fix_content_tagger(str(src), str(out))

    with pikepdf.open(str(out)) as fixed:
        sr2 = fixed.Root["/StructTreeRoot"]
        doc2 = list(sr2["/K"])[0]
        table2 = list(doc2["/K"])[0]
        table_children = list(table2["/K"])
        for child in table_children:
            child_tag = str(child.get("/S", "")).lstrip("/")
            assert child_tag == "TR", (
                f"fix_content_tagger should have wrapped orphan cells into /TR, "
                f"but found /{child_tag}"
            )


# ---------------------------------------------------------------------------
# BUG-09 — _fix_list_li_structure wraps orphan items in /LI
# ---------------------------------------------------------------------------


def test_fix_list_li_structure_wraps_orphan_items(tmp_path):
    """/Lbl and /LBody direct children of /L must be wrapped in /LI."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    lbl = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Lbl"),
    }))
    lbody = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/LBody"),
    }))
    l_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/L"),
        "/K": pikepdf.Array([lbl, lbody]),  # no /LI wrapper — this is the bug
    }))
    doc_k.append(l_elem)

    modified = _fix_list_li_structure(pdf)
    assert modified == 1, f"Expected 1 list modified, got {modified}"

    # The /L's /K should now contain /LI children
    l_k = list(l_elem.get("/K"))
    for child in l_k:
        assert isinstance(child, pikepdf.Dictionary)
        child_tag = str(child.get("/S", "")).lstrip("/")
        assert child_tag == "LI", (
            f"Expected all /L children to be /LI after repair, got /{child_tag}"
        )


def test_fix_list_li_structure_leaves_well_formed_list_unchanged(tmp_path):
    """A /L with /LI children must not be modified."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    li = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/LI"),
        "/K": pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/LBody"),
            }))
        ]),
    }))
    l_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/L"),
        "/K": pikepdf.Array([li]),  # already has /LI wrapper
    }))
    doc_k.append(l_elem)

    modified = _fix_list_li_structure(pdf)
    assert modified == 0, f"Expected 0 lists modified (already well-formed), got {modified}"


def test_fix_content_tagger_calls_li_fix(tmp_path):
    """`fix_content_tagger` must run the /LI repair on orphan list items."""
    pdf = _make_tagged_pdf(tmp_path)
    sr = pdf.Root["/StructTreeRoot"]
    doc_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": doc_k,
    }))
    sr["/K"] = pikepdf.Array([doc])

    lbl = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Lbl"),
    }))
    lbody = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/LBody"),
    }))
    l_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/L"),
        "/K": pikepdf.Array([lbl, lbody]),  # orphan items — the bug
    }))
    doc_k.append(l_elem)

    src = tmp_path / "in.pdf"
    pdf.save(str(src))
    pdf.close()

    out = tmp_path / "out.pdf"
    fix_content_tagger(str(src), str(out))

    with pikepdf.open(str(out)) as fixed:
        sr2 = fixed.Root["/StructTreeRoot"]
        doc2 = list(sr2["/K"])[0]
        l_elem2 = list(doc2["/K"])[0]
        l_children = list(l_elem2["/K"])
        for child in l_children:
            child_tag = str(child.get("/S", "")).lstrip("/")
            assert child_tag == "LI", (
                f"fix_content_tagger should have wrapped orphan items in /LI, "
                f"but found /{child_tag}"
            )
