"""Acceptance tests for fix_widget_appearance.py."""

from __future__ import annotations

import contextlib
import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_widget_appearance import _rewrite_stream, fix_widget_appearance  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"
GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"

ALL_PDFS = [
    GOOD,
    TEST_SUITE / "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf",
    TEST_SUITE / "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf",
    TEST_SUITE / "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf",
    TRAVEL,
]


def _statuses(report: dict) -> dict[str, str]:
    return {c["id"]: c["status"] for c in report["checkpoints"]}


def _count_tx_bmc(path: pathlib.Path) -> int:
    with pikepdf.open(str(path)) as pdf:
        n = 0
        for page in pdf.pages:
            for a in page.get("/Annots") or []:
                if str(a.get("/Subtype", "")) != "/Widget":
                    continue
                ap = a.get("/AP")
                if ap is None:
                    continue
                for key in ("/N", "/R", "/D"):
                    node = ap.get(key)
                    if node is None:
                        continue
                    if isinstance(node, pikepdf.Stream):
                        with contextlib.suppress(Exception):
                            n += bytes(node.read_bytes()).count(b"/Tx BMC")
        return n


# ---------------------------------------------------------------------------
# Unit-level rewrite
# ---------------------------------------------------------------------------


def test_rewrite_replaces_tx_bmc() -> None:
    new, count = _rewrite_stream(b"q 1 g 0 0 10 10 re f Q /Tx BMC BT (hi) Tj ET EMC")
    assert count == 1
    assert b"/Tx BMC" not in new
    assert b"/Artifact BMC" in new


def test_rewrite_leaves_standard_tags_alone() -> None:
    _, count = _rewrite_stream(b"/Artifact BMC EMC /P <</MCID 0>> BDC EMC")
    assert count == 0


def test_rewrite_preserves_bdc_properties_dict() -> None:
    new, count = _rewrite_stream(b"/FooBar <</MCID 1>> BDC BT (text) Tj ET EMC")
    assert count == 1
    # Replaced with a minimal properties dict so BDC still has an arg.
    assert b"/Artifact <</Type /Layout>> BDC" in new
    assert new.count(b"EMC") == 1


# ---------------------------------------------------------------------------
# End-to-end on the Travel Form
# ---------------------------------------------------------------------------


def test_travel_form_retags_all_tx_bmc(tmp_path: pathlib.Path) -> None:
    before = _count_tx_bmc(TRAVEL)
    assert before > 0, "test precondition: Travel Form should have /Tx BMC widgets"

    out = tmp_path / "out.pdf"
    res = fix_widget_appearance(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["streams_rewritten"] >= before
    assert res["tags_normalised"] >= before

    assert _count_tx_bmc(out) == 0


def test_auditor_passes_unchanged_after_rewrite(tmp_path: pathlib.Path) -> None:
    """fix_widget_appearance only touches widget appearance content —
    every auditor checkpoint should be unchanged from the baseline.
    (It is NOT this module's job to fill in /TU; that's fix_widget_tu.)"""
    baseline = _statuses(audit_pdf(TRAVEL))
    out = tmp_path / "out.pdf"
    fix_widget_appearance(str(TRAVEL), str(out))
    new = _statuses(audit_pdf(out))
    # Core structural checks must remain identical.
    for cid in ("C-39", "C-40", "C-13", "C-03", "C-46"):
        assert new[cid] == baseline[cid], f"{cid} regressed from {baseline[cid]} to {new[cid]}"


def test_shared_xobject_between_widget_and_page_is_skipped(tmp_path: pathlib.Path) -> None:
    """If a widget /AP /N happens to be the same Form XObject referenced
    from a page's /Resources/XObject dict, mutating it in place would
    globally retag the page's visible content. The module must detect
    the sharing and skip the rewrite."""
    # Build a synthetic PDF with exactly that pathology.
    p = pikepdf.new()
    page = p.add_blank_page(page_size=(612, 792))

    # A Form XObject that contains /Tx BMC so the would-be rewrite
    # has something to target.
    form = p.make_stream(
        b"q\n0 0 100 20 re\nf\n/Tx BMC\nBT\n(hi) Tj\nET\nEMC\nQ\n",
        {
            "/Type": pikepdf.Name("/XObject"),
            "/Subtype": pikepdf.Name("/Form"),
            "/BBox": pikepdf.Array([0, 0, 100, 20]),
            "/Resources": pikepdf.Dictionary({}),
        },
    )

    # Wire it into BOTH the page's /Resources/XObject and a widget
    # annotation's /AP /N. Same object, two references.
    page.Resources = pikepdf.Dictionary({"/XObject": pikepdf.Dictionary({"/Im0": form})})
    widget = p.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Widget"),
                "/FT": pikepdf.Name("/Tx"),
                "/Rect": pikepdf.Array([100, 100, 200, 120]),
                "/AP": pikepdf.Dictionary({"/N": form}),
                "/T": pikepdf.String("field"),
            }
        )
    )
    page.Annots = pikepdf.Array([widget])

    src = tmp_path / "shared.pdf"
    p.save(str(src))
    p.close()

    out = tmp_path / "out.pdf"
    res = fix_widget_appearance(str(src), str(out))
    assert res["errors"] == [], res["errors"]
    # The shared stream must be recognised and skipped.
    assert res["streams_skipped_shared"] == 1
    assert res["streams_rewritten"] == 0

    # Crucially, the content of the XObject must be byte-for-byte
    # unchanged in the output — the page reference would otherwise
    # silently retag its visible content.
    with pikepdf.open(str(out)) as out_pdf:
        out_page = out_pdf.pages[0]
        out_form = out_page.Resources.XObject.Im0
        data = bytes(out_form.read_bytes())
        assert b"/Tx BMC" in data, "shared XObject was mutated in place"


def test_no_regressions_on_all_five_pdfs(tmp_path: pathlib.Path) -> None:
    for src in ALL_PDFS:
        baseline = _statuses(audit_pdf(src))
        out = tmp_path / (src.stem + ".fixed.pdf")
        res = fix_widget_appearance(str(src), str(out))
        assert res["errors"] == [], f"{src.name}: {res['errors']}"
        new = _statuses(audit_pdf(out))
        for cid in ("C-13", "C-03", "C-46"):
            assert new[cid] == baseline[cid], f"{src.name}: {cid} regressed from {baseline[cid]} to {new[cid]}"
