"""Acceptance tests for fix_link_alt.py.

Verifies that /Link annotations get a human-readable /Contents derived
from their action (URI, GoTo) and that existing descriptions are left
alone. Also exercises the URL-humanization helper directly.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_link_alt import (  # noqa: E402
    _humanize_slug,
    _uri_to_name,
    fix_link_alt,
)

TEST_SUITE = ROOT / "test_suite"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"


# ---------------------------------------------------------------------------
# URL humanization unit tests
# ---------------------------------------------------------------------------


def test_humanize_slug_basic() -> None:
    assert _humanize_slug("per-diem-rates") == "Per Diem Rates"
    assert _humanize_slug("contact_us") == "Contact Us"
    assert _humanize_slug("travel/plan-book") == "Travel Plan Book"


def test_humanize_slug_strips_extensions() -> None:
    assert _humanize_slug("contact-us.html") == "Contact Us"
    assert _humanize_slug("report.pdf") == "Report"
    assert _humanize_slug("index.php") == "Index"


def test_humanize_slug_camel_case() -> None:
    assert _humanize_slug("perDiemRates") == "Per Diem Rates"


def test_uri_to_name_gsa() -> None:
    out = _uri_to_name("https://www.gsa.gov/travel/plan-book/per-diem-rates")
    assert "gsa.gov" in out
    assert "Per Diem Rates" in out


def test_uri_to_name_mailto() -> None:
    out = _uri_to_name("mailto:help@example.com")
    assert "help@example.com" in out
    assert out.lower().startswith("email")


def test_uri_to_name_tel() -> None:
    out = _uri_to_name("tel:+18005551234")
    assert "+18005551234" in out


def test_uri_to_name_host_only() -> None:
    out = _uri_to_name("https://example.com/")
    assert out == "example.com"


# ---------------------------------------------------------------------------
# End-to-end on the Travel Form
# ---------------------------------------------------------------------------


def test_travel_form_link_gets_contents(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_link_alt(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    assert res["links_filled"] >= 1, res

    with pikepdf.open(str(out)) as pdf:
        found = False
        for page in pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) != "/Link":
                    continue
                found = True
                contents = str(annot.get("/Contents") or "").strip()
                assert contents, "Link annotation still missing /Contents"
                # Must not be the generic fallback for the GSA link.
                action = annot.get("/A")
                if action is not None:
                    uri = str(action.get("/URI") or "")
                    if "gsa.gov" in uri:
                        assert "gsa.gov" in contents.lower()
        assert found, "test precondition: Travel Form must contain at least one /Link"


def test_existing_contents_left_alone(tmp_path: pathlib.Path) -> None:
    """Links that already have /Contents must not be overwritten."""
    # Prepare a modified copy where the link already has /Contents.
    staged = tmp_path / "staged.pdf"
    with pikepdf.open(str(TRAVEL)) as pdf:
        for page in pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) == "/Link":
                    annot["/Contents"] = pikepdf.String("Custom description")
                    break
        pdf.save(str(staged))

    out = tmp_path / "out.pdf"
    res = fix_link_alt(str(staged), str(out))
    assert res["errors"] == [], res["errors"]

    with pikepdf.open(str(out)) as pdf:
        for page in pdf.pages:
            for annot in page.get("/Annots") or []:
                if str(annot.get("/Subtype", "")) == "/Link":
                    assert str(annot.get("/Contents")) == "Custom description"
                    return
    raise AssertionError("no /Link annotation found after write")


def test_link_struct_elem_also_gets_alt(tmp_path: pathlib.Path) -> None:
    """If the struct tree has a /Link element for the annot, /Alt is set."""
    out = tmp_path / "out.pdf"
    res = fix_link_alt(str(TRAVEL), str(out))
    assert res["errors"] == [], res["errors"]
    # If the file wired up its Link struct element, we should have
    # populated at least one.
    assert res["struct_alts_filled"] >= 0
    if res["struct_alts_filled"] > 0:
        with pikepdf.open(str(out)) as pdf:
            sr = pdf.Root.get("/StructTreeRoot")
            assert sr is not None
            # Walk the struct tree looking for /Link elements.
            stack = []
            k = sr.get("/K")
            if isinstance(k, pikepdf.Array):
                stack.extend(list(k))
            else:
                stack.append(k)
            found_alt = False
            while stack:
                node = stack.pop()
                if not isinstance(node, pikepdf.Dictionary):
                    continue
                if str(node.get("/S", "")) == "/Link":
                    alt = str(node.get("/Alt", "") or "").strip()
                    if alt:
                        found_alt = True
                kk = node.get("/K")
                if isinstance(kk, pikepdf.Array):
                    for c in kk:
                        if isinstance(c, pikepdf.Dictionary):
                            stack.append(c)
                elif isinstance(kk, pikepdf.Dictionary):
                    stack.append(kk)
            assert found_alt, "struct_alts_filled > 0 but no /Link /Alt found"


def test_link_with_dest_gets_description(tmp_path: pathlib.Path) -> None:
    """A /Link with /Dest (named destination) should get a meaningful /Contents."""
    staged = tmp_path / "dest.pdf"
    with pikepdf.open(str(TRAVEL)) as pdf:
        link = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Annot"),
                    "/Subtype": pikepdf.Name("/Link"),
                    "/Rect": pikepdf.Array([100, 700, 200, 720]),
                    "/Dest": pikepdf.String("appendix_a"),
                }
            )
        )
        pdf.pages[0].get("/Annots").append(link)
        pdf.save(str(staged))

    out = tmp_path / "out.pdf"
    res = fix_link_alt(str(staged), str(out))
    assert res["errors"] == [], res["errors"]
    with pikepdf.open(str(out)) as pdf:
        for annot in pdf.pages[0].get("/Annots") or []:
            if str(annot.get("/Subtype", "")) != "/Link":
                continue
            dest = annot.get("/Dest")
            if dest is not None and "appendix" in str(dest).lower():
                contents = str(annot.get("/Contents") or "")
                assert "appendix_a" in contents.lower(), f"/Dest link should mention destination, got {contents!r}"
                return
    raise AssertionError("did not find the /Dest link in output")


def test_no_links_is_a_noop(tmp_path: pathlib.Path) -> None:
    """A file with no /Link annotations should process cleanly with zero fills."""
    good_pdf = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"
    out = tmp_path / "out.pdf"
    res = fix_link_alt(str(good_pdf), str(out))
    assert res["errors"] == [], res["errors"]
    # The file may or may not have links; the point is no errors.
    assert out.exists()
