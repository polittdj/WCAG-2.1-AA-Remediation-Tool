"""Exhaustive tests for wcag_auditor.py — every checkpoint, every outcome.

For the 10 ported R2 checkpoints (under R3 IDs), we construct minimal
synthetic PDFs that exercise:
  1. PASS — the checkpoint's requirement is fully met
  2. FAIL — the checkpoint's requirement is violated
  3. NOT_APPLICABLE — the checkpoint doesn't apply (no struct tree, no widgets, etc.)
  4. Edge cases — empty strings, None values, partial compliance, multiple items

R2 → R3 Checkpoint ID Mapping:
  R2 C-01 (Figure Alt)        → R3 C-31
  R2 C-02 (Widget TU)         → R3 C-36
  R2 C-13 (Title)             → R3 C-02
  R2 C-16 (Lang)              → R3 C-04
  R2 C-18 (StructParent)      → R3 C-39
  R2 C-19 (SP→Form)           → R3 C-40
  R2 C-25 (MarkInfo)          → R3 C-01
  R2 C-33 (BDC Tags)          → R3 C-13
  R2 C-34 (Title Placeholder) → R3 C-03
  R2 C-35 (ParentTree)        → R3 C-46

These tests validate the AUDITOR logic, not the fix modules. They use
pikepdf to build PDFs from scratch rather than relying on test_suite fixtures.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from wcag_auditor import audit_pdf  # noqa: E402


def _status(report: dict, checkpoint_id: str) -> str:
    for c in report["checkpoints"]:
        if c["id"] == checkpoint_id:
            return c["status"]
    return "MISSING"


def _detail(report: dict, checkpoint_id: str) -> str:
    for c in report["checkpoints"]:
        if c["id"] == checkpoint_id:
            return c.get("detail", "")
    return ""


def _save(pdf: pikepdf.Pdf, tmp_path: pathlib.Path, name: str = "test.pdf") -> pathlib.Path:
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _make_bare(tmp_path: pathlib.Path) -> pathlib.Path:
    """Minimal valid PDF: 1 blank page, no metadata."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(612, 792))
    return _save(pdf, tmp_path)


def _make_with_struct_tree(
    pdf: pikepdf.Pdf,
    children: list | None = None,
) -> None:
    """Add a minimal StructTreeRoot with a Document element."""
    doc_elem = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Document"),
                "/K": pikepdf.Array(children or []),
            }
        )
    )
    parent_tree = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Nums": pikepdf.Array(),
            }
        )
    )
    sr = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructTreeRoot"),
                "/K": pikepdf.Array([doc_elem]),
                "/ParentTree": parent_tree,
                "/ParentTreeNextKey": 0,
            }
        )
    )
    pdf.Root["/StructTreeRoot"] = sr


def _add_widget(
    page: pikepdf.Page,
    pdf: pikepdf.Pdf,
    *,
    tu: str | None = None,
    struct_parent: int | None = None,
) -> pikepdf.Dictionary:
    """Add a Widget annotation to the page and return it."""
    widget = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Widget"),
                "/Rect": pikepdf.Array([100, 100, 200, 120]),
                "/FT": pikepdf.Name("/Tx"),
                "/T": pikepdf.String("field1"),
            }
        )
    )
    if tu is not None:
        widget["/TU"] = pikepdf.String(tu)
    if struct_parent is not None:
        widget["/StructParent"] = struct_parent
    annots = page.get("/Annots")
    if annots is None:
        page["/Annots"] = pikepdf.Array([widget])
    else:
        annots.append(widget)
    return widget


# ============================================================
# C-31: Every Figure has non-empty /Alt (was R2 C-01)
# ============================================================


class TestC31FigureAlt:
    def test_pass_figure_with_alt(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String("A photo of a sunset"),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "PASS"

    def test_fail_figure_without_alt(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "FAIL"

    def test_fail_figure_with_empty_alt(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String(""),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "FAIL"

    def test_fail_figure_with_whitespace_alt(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String("   "),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "FAIL"

    def test_na_no_struct_tree(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-31") == "NOT_APPLICABLE"

    def test_na_no_figures(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        span = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Span"),
                }
            )
        )
        _make_with_struct_tree(pdf, [span])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "NOT_APPLICABLE"

    def test_partial_some_figures_missing_alt(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig_ok = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String("Good alt"),
                }
            )
        )
        fig_bad = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig_ok, fig_bad])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "FAIL"
        assert "1 of 2" in _detail(r, "C-31")

    def test_nested_figure_deep_in_tree(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String("Nested figure"),
                }
            )
        )
        sect = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Sect"),
                    "/K": pikepdf.Array([fig]),
                }
            )
        )
        _make_with_struct_tree(pdf, [sect])
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-31") == "PASS"


# ============================================================
# C-36: Every Widget with /Rect has non-empty /TU (was R2 C-02)
# ============================================================


class TestC36WidgetTU:
    def test_pass_widget_with_tu(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="Employee Name")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-36") == "PASS"

    def test_fail_widget_without_tu(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-36") == "FAIL"

    def test_fail_widget_with_empty_tu(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-36") == "FAIL"

    def test_fail_widget_with_whitespace_tu(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="   ")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-36") == "FAIL"

    def test_na_no_widgets(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-36") == "NOT_APPLICABLE"

    def test_multiple_widgets_one_missing(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="Good")
        _add_widget(pdf.pages[0], pdf)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-36") == "FAIL"
        assert "1 of 2" in _detail(r, "C-36")


# ============================================================
# C-02: DocInfo /Title is non-empty (was R2 C-13)
# ============================================================


class TestC02Title:
    def test_pass_has_title(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "My Document"
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-02") == "PASS"

    def test_fail_no_title(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-02") == "FAIL"

    def test_fail_empty_title(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = ""
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-02") == "FAIL"

    def test_fail_whitespace_title(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "   "
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-02") == "FAIL"


# ============================================================
# C-04: /Lang is set on the document (was R2 C-16)
# ============================================================


class TestC04Lang:
    def test_pass_has_lang(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.Root["/Lang"] = pikepdf.String("en-US")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-04") == "PASS"

    def test_fail_no_lang(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-04") == "FAIL"

    def test_fail_empty_lang(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.Root["/Lang"] = pikepdf.String("")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-04") == "FAIL"

    def test_pass_various_langs(self, tmp_path: pathlib.Path) -> None:
        for lang in ("en", "fr-FR", "de", "es-ES", "zh-CN"):
            pdf = pikepdf.new()
            pdf.add_blank_page()
            pdf.Root["/Lang"] = pikepdf.String(lang)
            r = audit_pdf(_save(pdf, tmp_path, f"lang_{lang}.pdf"))
            assert _status(r, "C-04") == "PASS", f"failed for lang={lang}"


# ============================================================
# C-39: Every Widget has /StructParent (was R2 C-18)
# ============================================================


class TestC39StructParent:
    def test_pass_widget_with_struct_parent(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F", struct_parent=0)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-39") == "PASS"

    def test_fail_widget_without_struct_parent(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-39") == "FAIL"

    def test_na_no_widgets(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-39") == "NOT_APPLICABLE"

    def test_multiple_widgets_one_missing(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="A", struct_parent=0)
        _add_widget(pdf.pages[0], pdf, tu="B")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-39") == "FAIL"
        assert "1 have /StructParent (1 missing)" in _detail(r, "C-39")


# ============================================================
# C-40: Every /StructParent resolves to a /Form struct element (was R2 C-19)
# ============================================================


class TestC40StructParentResolvesToForm:
    def test_pass_resolves_to_form(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F", struct_parent=0)
        form_elem = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Form"),
                }
            )
        )
        _make_with_struct_tree(pdf, [form_elem])
        sr = pdf.Root["/StructTreeRoot"]
        sr["/ParentTree"] = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Nums": pikepdf.Array([0, form_elem]),
                }
            )
        )
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-40") == "PASS"

    def test_fail_resolves_to_non_form(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F", struct_parent=0)
        span_elem = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Span"),
                }
            )
        )
        _make_with_struct_tree(pdf, [span_elem])
        sr = pdf.Root["/StructTreeRoot"]
        sr["/ParentTree"] = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Nums": pikepdf.Array([0, span_elem]),
                }
            )
        )
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-40") == "FAIL"

    def test_fail_no_struct_tree(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F", struct_parent=0)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-40") == "FAIL"

    def test_na_no_widgets(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-40") == "NOT_APPLICABLE"

    def test_na_widgets_without_struct_parent(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _add_widget(pdf.pages[0], pdf, tu="F")
        _make_with_struct_tree(pdf)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-40") == "NOT_APPLICABLE"


# ============================================================
# C-01: /MarkInfo /Marked is true (was R2 C-25)
# ============================================================


class TestC01MarkInfo:
    def test_pass_marked_true(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-01") == "PASS"

    def test_fail_no_markinfo(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-01") == "FAIL"

    def test_fail_marked_false(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": False})
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-01") == "FAIL"


# ============================================================
# C-13: Zero non-standard BDC tags in content streams (was R2 C-33)
# ============================================================


class TestC13BDCTags:
    def test_pass_no_bdc(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-13") == "PASS"

    def test_pass_standard_bdc(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        stream = b"/P <</MCID 0>> BDC\nBT /F1 12 Tf (Hello) Tj ET\nEMC\n"
        pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-13") == "PASS"

    def test_fail_non_standard_bdc(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        stream = b"/ExtraCharSpan <</MCID 0>> BDC\nBT (Hello) Tj ET\nEMC\n"
        pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-13") == "FAIL"
        assert "ExtraCharSpan" in _detail(r, "C-13")

    def test_pass_artifact_bdc(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        stream = b"/Artifact <</Type /Layout>> BDC\n100 200 300 400 re f\nEMC\n"
        pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-13") == "PASS"

    def test_fail_mixed_standard_and_non(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        stream = b"/P <</MCID 0>> BDC\nBT (Ok) Tj ET\nEMC\n/ParagraphSpan <</MCID 1>> BDC\nBT (Bad) Tj ET\nEMC\n"
        pdf.pages[0]["/Contents"] = pdf.make_stream(stream)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-13") == "FAIL"

    def test_multi_page_fail(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.add_blank_page()
        pdf.pages[0]["/Contents"] = pdf.make_stream(b"/P <</MCID 0>> BDC\nBT (Ok) Tj ET\nEMC\n")
        pdf.pages[1]["/Contents"] = pdf.make_stream(b"/InlineShape <</MCID 0>> BDC\nBT (Bad) Tj ET\nEMC\n")
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-13") == "FAIL"
        assert "InlineShape" in _detail(r, "C-13")


# ============================================================
# C-03: Title is not a placeholder (was R2 C-34)
# ============================================================


class TestC03TitleNotPlaceholder:
    def test_pass_real_title(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "Travel Approval Form"
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-03") == "PASS"

    def test_fail_no_title(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-03") == "FAIL"

    def test_fail_untitled(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "Untitled Document"
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-03") == "FAIL"

    def test_fail_untitled_case_insensitive(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "UNTITLED"
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-03") == "FAIL"

    @pytest.mark.parametrize(
        "placeholder",
        [
            "Untitled Document",
            "untitled",
            "Document",
            "document1",
            "Microsoft Word",
            "Word Document",
            "New Document",
            "Draft",
            "Temp",
        ],
    )
    def test_fail_all_blacklisted(self, tmp_path: pathlib.Path, placeholder: str) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = placeholder
        r = audit_pdf(_save(pdf, tmp_path, f"bl_{placeholder[:10]}.pdf"))
        assert _status(r, "C-03") == "FAIL", f"'{placeholder}' should be blacklisted"


# ============================================================
# C-46: ParentTree is a flat /Nums array (was R2 C-35)
# ============================================================


class TestC46ParentTree:
    def test_pass_flat_nums(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        _make_with_struct_tree(pdf)
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-46") == "PASS"

    def test_fail_kids_tree(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        child = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Limits": pikepdf.Array([0, 10]),
                    "/Nums": pikepdf.Array([0, pikepdf.String("")]),
                }
            )
        )
        parent_tree = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Kids": pikepdf.Array([child]),
                }
            )
        )
        sr = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructTreeRoot"),
                    "/K": pikepdf.Array(),
                    "/ParentTree": parent_tree,
                }
            )
        )
        pdf.Root["/StructTreeRoot"] = sr
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-46") == "FAIL"
        assert "Kids" in _detail(r, "C-46")

    def test_fail_no_parent_tree(self, tmp_path: pathlib.Path) -> None:
        pdf = pikepdf.new()
        pdf.add_blank_page()
        sr = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructTreeRoot"),
                    "/K": pikepdf.Array(),
                }
            )
        )
        pdf.Root["/StructTreeRoot"] = sr
        r = audit_pdf(_save(pdf, tmp_path))
        assert _status(r, "C-46") == "FAIL"

    def test_na_no_struct_tree(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert _status(r, "C-46") == "NOT_APPLICABLE"


# ============================================================
# Auditor structural tests
# ============================================================


class TestAuditorStructural:
    def test_all_47_checkpoints_present(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        ids = [c["id"] for c in r["checkpoints"]]
        expected = [f"C-{i:02d}" for i in range(1, 48)]
        assert ids == expected

    def test_report_has_summary(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert "summary" in r
        assert r["summary"]["total"] == 47
        assert (
            r["summary"]["pass"]
            + r["summary"]["fail"]
            + r["summary"]["warn"]
            + r["summary"]["not_applicable"]
            + r["summary"].get("manual_review", 0)
            == 47
        )

    def test_report_has_timestamp(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(_make_bare(tmp_path))
        assert "timestamp" in r
        assert "T" in r["timestamp"]

    def test_corrupt_file_returns_indeterminate(self, tmp_path: pathlib.Path) -> None:
        bad = tmp_path / "corrupt.pdf"
        bad.write_bytes(b"this is not a pdf")
        r = audit_pdf(bad)
        for c in r["checkpoints"]:
            assert c["status"] == "INDETERMINATE"

    def test_nonexistent_file_returns_indeterminate(self, tmp_path: pathlib.Path) -> None:
        r = audit_pdf(tmp_path / "does_not_exist.pdf")
        for c in r["checkpoints"]:
            assert c["status"] == "INDETERMINATE"

    def test_fully_compliant_synthetic(self, tmp_path: pathlib.Path) -> None:
        """Build a PDF that passes EVERY checkpoint (or N/A or MANUAL_REVIEW)."""
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = "Fully Compliant Test Document"
        pdf.Root["/Lang"] = pikepdf.String("en-US")
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
        pdf.Root["/ViewerPreferences"] = pikepdf.Dictionary(
            {
                "/DisplayDocTitle": True,
            }
        )
        # Add minimal XMP metadata with PDF/UA identifier
        xmp = (
            b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>'
            b'<x:xmpmeta xmlns:x="adobe:ns:meta/">'
            b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">'
            b'<rdf:Description rdf:about=""'
            b' xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">'
            b"<pdfuaid:part>1</pdfuaid:part>"
            b"</rdf:Description>"
            b"</rdf:RDF>"
            b"</x:xmpmeta>"
            b'<?xpacket end="w"?>'
        )
        metadata = pdf.make_stream(xmp)
        metadata["/Type"] = pikepdf.Name("/Metadata")
        metadata["/Subtype"] = pikepdf.Name("/XML")
        pdf.Root["/Metadata"] = metadata
        # Focus order
        pdf.pages[0]["/Tabs"] = pikepdf.Name("/S")

        fig = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Figure"),
                    "/Alt": pikepdf.String("Test figure description"),
                }
            )
        )
        form_elem = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/StructElem"),
                    "/S": pikepdf.Name("/Form"),
                }
            )
        )
        _make_with_struct_tree(pdf, [fig, form_elem])

        _add_widget(pdf.pages[0], pdf, tu="Test Field", struct_parent=0)
        sr = pdf.Root["/StructTreeRoot"]
        sr["/ParentTree"] = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Nums": pikepdf.Array([0, form_elem]),
                }
            )
        )
        sr["/ParentTreeNextKey"] = 1

        r = audit_pdf(_save(pdf, tmp_path))
        for c in r["checkpoints"]:
            assert c["status"] in ("PASS", "NOT_APPLICABLE", "MANUAL_REVIEW"), (
                f"{c['id']} expected PASS/NA/MANUAL_REVIEW, got {c['status']}: {c['detail']}"
            )
