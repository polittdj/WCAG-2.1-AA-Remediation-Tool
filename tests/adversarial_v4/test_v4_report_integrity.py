"""Category P — HTML Report Integrity Attacks."""

from __future__ import annotations

import json
import pathlib
import re
import sys
from html.parser import HTMLParser

import fitz
import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline


def _run(src: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "out"
    return run_pipeline(str(src), str(out))


def _make_bare(tmp_path, name="test.pdf"):
    src = tmp_path / name
    doc = fitz.open()
    page = doc.new_page(width=612, height=792)
    page.insert_text((72, 100), "Test content", fontsize=12, fontname="helv")
    doc.save(str(src))
    doc.close()
    return src


# ═══════════════════════════════════════════════════════════════════════
# P1 — Checkpoint count matches spec (47)
# ═══════════════════════════════════════════════════════════════════════

def test_p1_checkpoint_count(tmp_path):
    src = _make_bare(tmp_path)
    res = _run(src, tmp_path)
    assert res["report_html"]

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")
    match = re.search(
        r'<script type="application/json" id="wcag-audit-data">\s*(.*?)\s*</script>',
        html, re.DOTALL,
    )
    if match:
        data = json.loads(match.group(1))
        cps = data["checkpoints"]
        assert len(cps) == 47, f"Expected 47 checkpoints, got {len(cps)}"
        ids = {cp["id"] for cp in cps}
        for i in range(1, 48):
            expected_id = f"C-{i:02d}"
            assert expected_id in ids, f"Missing checkpoint {expected_id}"
    else:
        # Legacy report — check all IDs appear in HTML
        for i in range(1, 48):
            cid = f"C-{i:02d}"
            assert cid in html, f"Checkpoint {cid} missing from legacy report"


# ═══════════════════════════════════════════════════════════════════════
# P4 — Report HTML structure validity
# ═══════════════════════════════════════════════════════════════════════

def test_p4_html_structure(tmp_path):
    src = _make_bare(tmp_path)
    res = _run(src, tmp_path)
    assert res["report_html"]

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    # DOCTYPE present
    assert html.strip().startswith("<!DOCTYPE html>") or html.strip().startswith("<!doctype html>"), \
        "Missing DOCTYPE"

    # <html lang="en"> present
    assert 'lang="en"' in html, "Missing lang attribute on <html>"

    # Basic tag balance check
    class TagChecker(HTMLParser):
        def __init__(self):
            super().__init__()
            self.stack = []
            self.errors = []
            self.void_tags = {
                "area", "base", "br", "col", "embed", "hr", "img",
                "input", "link", "meta", "param", "source", "track", "wbr",
            }

        def handle_starttag(self, tag, attrs):
            if tag not in self.void_tags:
                self.stack.append(tag)

        def handle_endtag(self, tag):
            if tag in self.void_tags:
                return
            if self.stack and self.stack[-1] == tag:
                self.stack.pop()
            elif tag in self.stack:
                # Find and pop the matching tag (some leniency)
                idx = len(self.stack) - 1 - self.stack[::-1].index(tag)
                self.stack.pop(idx)

    checker = TagChecker()
    checker.feed(html)
    # Allow minor unclosed tags (some are acceptable in HTML5)
    assert len(checker.stack) < 5, f"Too many unclosed tags: {checker.stack}"


# ═══════════════════════════════════════════════════════════════════════
# P5 — Noscript fallback completeness
# ═══════════════════════════════════════════════════════════════════════

def test_p5_noscript_completeness(tmp_path):
    src = _make_bare(tmp_path)
    res = _run(src, tmp_path)
    assert res["report_html"]

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    noscript_match = re.search(r"<noscript>(.*?)</noscript>", html, re.DOTALL)
    if noscript_match:
        noscript = noscript_match.group(1)
        # Must contain a table
        assert "<table" in noscript, "Noscript block missing table"
        # Must contain first and last checkpoint IDs
        assert "C-01" in noscript, "C-01 missing from noscript"
        assert "C-47" in noscript, "C-47 missing from noscript"
    else:
        # Report might be fully static HTML (no JS dependency)
        # In that case, noscript is not strictly needed
        # Verify the report works without JS by checking it has
        # the checkpoint table in the main body
        assert "C-01" in html and "C-47" in html, \
            "Report has neither noscript block nor static checkpoint data"


# ═══════════════════════════════════════════════════════════════════════
# P8 — No absolute file paths in report
# ═══════════════════════════════════════════════════════════════════════

def test_p8_no_absolute_paths(tmp_path):
    src = _make_bare(tmp_path)
    res = _run(src, tmp_path)
    assert res["report_html"]

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    # Check for absolute paths
    bad_patterns = [
        r"/tmp/",
        r"/home/",
        r"/var/",
        r"/usr/",
        r"C:\\",
        r"D:\\",
    ]
    for pattern in bad_patterns:
        matches = re.findall(pattern, html)
        assert len(matches) == 0, \
            f"Absolute path pattern '{pattern}' found in report ({len(matches)} occurrences)"


# ═══════════════════════════════════════════════════════════════════════
# P3 — Remediation actions match actual changes
# ═══════════════════════════════════════════════════════════════════════

def test_p3_remediation_actions_match_reality(tmp_path):
    """If report claims title was set, verify it actually was."""
    src = tmp_path / "no_title.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    # No title, no lang
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    assert res["output_pdf"]

    # Check output PDF actually has what the audit says
    cps = {c["id"]: c for c in res.get("checkpoints", [])}

    with pikepdf.open(res["output_pdf"]) as out_pdf:
        # If C-02 (title) is PASS, title must actually exist
        if cps.get("C-02", {}).get("status") == "PASS":
            title = out_pdf.docinfo.get("/Title")
            assert title is not None and str(title).strip(), \
                "Report says C-02 PASS but /Title is missing/empty"

        # If C-04 (lang) is PASS, lang must actually exist
        if cps.get("C-04", {}).get("status") == "PASS":
            lang = out_pdf.Root.get("/Lang")
            assert lang is not None and str(lang).strip(), \
                "Report says C-04 PASS but /Lang is missing/empty"

        # If C-01 (tagged) is PASS, MarkInfo must exist
        if cps.get("C-01", {}).get("status") == "PASS":
            mi = out_pdf.Root.get("/MarkInfo")
            assert mi is not None, \
                "Report says C-01 PASS but /MarkInfo is missing"
