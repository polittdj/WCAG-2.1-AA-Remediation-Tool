"""Tests for fix_headings.py."""

from __future__ import annotations
import pathlib, sys
import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from fix_headings import fix_headings, _demote_extra_h1s, _fix_heading_levels
from wcag_auditor import audit_pdf


def _save(pdf, tmp_path, name="test.pdf"):
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _status(r, cid):
    for c in r["checkpoints"]:
        if c["id"] == cid:
            return c["status"]
    return "MISSING"


def test_preserves_existing_headings(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    h1 = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/H1"),
            }
        )
    )
    doc = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
                "/K": pikepdf.Array([h1]),
            }
        )
    )
    pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()}))
    sr = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructTreeRoot"),
                "/K": pikepdf.Array([doc]),
                "/ParentTree": pt,
            }
        )
    )
    pdf.Root["/StructTreeRoot"] = sr
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_headings(str(inp), str(out))
    assert "already has heading tags" in res["changes"][0]


def test_noop_no_struct_tree(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_headings(str(inp), str(out))
    assert out.exists()


def test_idempotent(tmp_path):
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    mid = tmp_path / "mid.pdf"
    out = tmp_path / "out.pdf"
    fix_headings(str(inp), str(mid))
    fix_headings(str(mid), str(out))
    assert out.exists()


# ---------------------------------------------------------------------------
# IRS-02 Fix 1 — C-20: demote extra H1 headings to H2
# ---------------------------------------------------------------------------


def _make_tagged_pdf_with_headings(heading_tags: list[str]) -> pikepdf.Pdf:
    """Return an in-memory tagged PDF whose struct tree contains the given headings."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": pikepdf.Boolean(True)})
    sr_k = pikepdf.Array()
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": sr_k,
    }))
    sr = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc]),
        "/ParentTree": pdf.make_indirect(pikepdf.Dictionary({"/Nums": pikepdf.Array()})),
    }))
    pdf.Root["/StructTreeRoot"] = sr
    for tag in heading_tags:
        h = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"),
            "/S": pikepdf.Name(f"/{tag}"),
        }))
        sr_k.append(h)
    return pdf


def _heading_tags(pdf: pikepdf.Pdf) -> list[str]:
    """Return all H1-H6 tags found in the struct tree."""
    tags = []
    sr = pdf.Root.get("/StructTreeRoot")
    if sr is None:
        return tags
    stack = []
    k = sr.get("/K")
    if k is not None:
        stack.extend(list(k) if isinstance(k, pikepdf.Array) else [k])
    while stack:
        node = stack.pop()
        if not isinstance(node, pikepdf.Dictionary):
            continue
        s = node.get("/S")
        if s is not None:
            t = str(s).lstrip("/")
            if t in ("H1", "H2", "H3", "H4", "H5", "H6"):
                tags.append(t)
        sub = node.get("/K")
        if sub is not None:
            stack.extend(list(sub) if isinstance(sub, pikepdf.Array) else [sub])
    return tags


def test_multiple_h1_demoted(tmp_path):
    """Keep the first H1; demote all subsequent H1s to H2."""
    pdf = _make_tagged_pdf_with_headings(["H1", "H1", "H1", "H1", "H1"])
    count = _demote_extra_h1s(pdf)
    assert count == 4, f"Expected 4 demotions, got {count}"
    tags = _heading_tags(pdf)
    assert tags.count("H1") == 1, f"Expected exactly 1 H1, got {tags}"
    assert tags.count("H2") == 4, f"Expected 4 H2s, got {tags}"


def test_single_h1_unchanged(tmp_path):
    """A document with exactly one H1 must not be modified."""
    pdf = _make_tagged_pdf_with_headings(["H1", "H2", "H3"])
    count = _demote_extra_h1s(pdf)
    assert count == 0, f"Expected 0 demotions for single-H1 document, got {count}"
    tags = _heading_tags(pdf)
    assert tags.count("H1") == 1


def test_demote_nine_h1s(tmp_path):
    """9 H1s (like IRS f11c) → 1 H1 + 8 H2s."""
    pdf = _make_tagged_pdf_with_headings(["H1"] * 9)
    count = _demote_extra_h1s(pdf)
    assert count == 8
    tags = _heading_tags(pdf)
    assert tags.count("H1") == 1
    assert tags.count("H2") == 8


def test_fix_headings_roundtrip_demotes_multiple_h1(tmp_path):
    """fix_headings() end-to-end: multiple H1s in input → single H1 in output."""
    pdf = _make_tagged_pdf_with_headings(["H1", "H1", "H2", "H1"])
    src = tmp_path / "in.pdf"
    pdf.save(str(src))
    pdf.close()
    out = tmp_path / "out.pdf"
    res = fix_headings(str(src), str(out))
    assert out.exists()
    with pikepdf.open(str(out)) as fixed:
        tags = _heading_tags(fixed)
    assert tags.count("H1") == 1, f"Expected 1 H1 in output, got: {tags}"
    assert "Demoted" in " ".join(res.get("changes", [])), (
        "fix_headings should report the demotion in changes"
    )
