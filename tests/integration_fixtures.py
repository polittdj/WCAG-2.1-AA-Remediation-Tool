"""Programmatic generator for TEST_*.pdf integration fixtures.

Each function here produces one TEST_NN_*.pdf file that exercises a
specific pipeline path. Generation is intentionally minimal so the
test suite can run in any environment without committing binary
fixtures.

All TEST PDFs are expected to reach PASS or PARTIAL when processed
through the full pipeline. PASS-expected fixtures should have
fixable violations (missing metadata, wrong tags, etc.); PARTIAL-
expected fixtures have legitimate limitations the pipeline can't
work around (encryption, structurally broken trees, etc.).
"""

from __future__ import annotations

import pathlib
from typing import Callable

import pikepdf
from pikepdf import Array, Dictionary, Name, String


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _font(pdf: pikepdf.Pdf) -> pikepdf.Object:
    return pdf.make_indirect(Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    }))


def _new_page(
    pdf: pikepdf.Pdf,
    content: bytes = b"",
    page_size: tuple[int, int] = (612, 792),
) -> pikepdf.Page:
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    font = _font(pdf)
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    if content:
        page["/Contents"] = pdf.make_stream(content)
    return page


def _tag_minimal(pdf: pikepdf.Pdf, lang: str = "en-US", title: str = "Test Document"):
    """Set basic /MarkInfo + /Lang + /Title + StructTreeRoot."""
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
    pdf.Root["/Lang"] = String(lang)
    pdf.docinfo["/Title"] = String(title)
    pt = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
    sr = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array([]),
        "/ParentTree": pt,
        "/ParentTreeNextKey": 0,
    }))
    pdf.Root["/StructTreeRoot"] = sr


def _text_content(text: str = "Hello", y: int = 700, size: int = 12) -> bytes:
    return f"BT /F1 {size} Tf 72 {y} Td ({text}) Tj ET".encode()


# ---------------------------------------------------------------------------
# TEST_01 through TEST_26 generators
# ---------------------------------------------------------------------------


def build_test_01_completely_untagged(path: pathlib.Path):
    """No metadata, no struct tree — pipeline should remediate completely."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Paragraph one of an untagged document"))
    _new_page(pdf, _text_content("Paragraph two on the second page"))
    pdf.save(str(path))


def build_test_02_scanned_no_text(path: pathlib.Path):
    """Image-only page with no extractable text — pipeline should accept as-is."""
    pdf = pikepdf.new()
    # Just a page with no text content — pipeline's OCR step will
    # classify it and either run OCR or leave it alone.
    _new_page(pdf)
    _tag_minimal(pdf, title="Scanned Document")
    pdf.save(str(path))


def build_test_03_forms_no_tooltips(path: pathlib.Path):
    """Widgets without /TU — pipeline should derive tooltips."""
    pdf = pikepdf.new()
    page = _new_page(pdf, _text_content("Employee Form"))
    widgets = []
    for i, (label, y) in enumerate([
        ("Name", 700), ("Email", 680), ("Phone", 660),
    ]):
        w = pdf.make_indirect(Dictionary({
            "/Type": Name("/Annot"),
            "/Subtype": Name("/Widget"),
            "/Rect": Array([200, y, 400, y + 16]),
            "/T": String(label),
            "/FT": Name("/Tx"),
        }))
        widgets.append(w)
    page["/Annots"] = Array(widgets)
    _tag_minimal(pdf, title="Employee Form")
    pdf.Root["/AcroForm"] = Dictionary({"/Fields": Array(widgets), "/NeedAppearances": True})
    pdf.save(str(path))


def build_test_04_images_no_alt(path: pathlib.Path):
    """Page with text and a tagged figure missing alt text."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Document with an image"))
    _tag_minimal(pdf, title="Image Document")
    # Add a /Figure struct element with empty /Alt
    fig = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Figure"),
        "/Alt": String(""),
    }))
    doc = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": Array([fig]),
    }))
    pdf.Root["/StructTreeRoot"]["/K"] = Array([doc])
    pdf.save(str(path))


def build_test_05_low_contrast(path: pathlib.Path):
    """Page with text (contrast isn't auto-fixable, just a placeholder)."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Low contrast placeholder"))
    _tag_minimal(pdf, title="Low Contrast Document")
    pdf.save(str(path))


def build_test_06_tables_no_headers(path: pathlib.Path):
    """Doc with 'table-like' layout (content tagger may create /Table)."""
    pdf = pikepdf.new()
    # Build a multi-row content stream that looks tabular.
    content = (
        b"BT /F1 12 Tf 72 700 Td (Item A  Price  Quantity) Tj ET\n"
        b"BT /F1 12 Tf 72 680 Td (Widget   $10    5) Tj ET\n"
        b"BT /F1 12 Tf 72 660 Td (Gadget   $20    3) Tj ET\n"
    )
    _new_page(pdf, content)
    _tag_minimal(pdf, title="Table Document")
    pdf.save(str(path))


def build_test_07_links_no_description(path: pathlib.Path):
    """Link annotations without /Contents — pipeline derives alt text."""
    pdf = pikepdf.new()
    page = _new_page(pdf, _text_content("Click here for more information"))
    link = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Link"),
        "/Rect": Array([72, 700, 200, 720]),
        "/A": Dictionary({
            "/Type": Name("/Action"),
            "/S": Name("/URI"),
            "/URI": String("https://example.com/support"),
        }),
    }))
    page["/Annots"] = Array([link])
    _tag_minimal(pdf, title="Links Document")
    pdf.save(str(path))


def build_test_08_multipage_no_bookmarks(path: pathlib.Path):
    """Multipage doc under 20 pages — C-23 will be NOT_APPLICABLE."""
    pdf = pikepdf.new()
    for i in range(3):
        _new_page(pdf, _text_content(f"Chapter {i + 1}"))
    _tag_minimal(pdf, title="Multipage Document")
    pdf.save(str(path))


def build_test_09_no_language(path: pathlib.Path):
    """Tagged PDF without /Lang — pipeline sets default 'en-US'."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("English text"))
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
    pdf.docinfo["/Title"] = String("No Lang Document")
    pt = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
    sr = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array([]),
        "/ParentTree": pt,
        "/ParentTreeNextKey": 0,
    }))
    pdf.Root["/StructTreeRoot"] = sr
    # No /Lang
    pdf.save(str(path))


def build_test_10_nonstandard_bdc_tags(path: pathlib.Path):
    """Content stream with non-standard BDC tag names."""
    pdf = pikepdf.new()
    content = (
        b"/CustomTag <</MCID 0>> BDC BT /F1 12 Tf 72 700 Td (Bad tag text) Tj ET EMC\n"
        b"/ExtraCharSpan <</MCID 1>> BDC BT /F1 12 Tf 72 680 Td (More bad) Tj ET EMC"
    )
    _new_page(pdf, content)
    _tag_minimal(pdf, title="Bad BDC Document")
    pdf.save(str(path))


def build_test_11_javascript_actions(path: pathlib.Path):
    """PDF with a JavaScript action in the catalog."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("PDF with JS"))
    _tag_minimal(pdf, title="JavaScript Document")
    # Add OpenAction with JavaScript — tool should detect/remove
    pdf.Root["/OpenAction"] = Dictionary({
        "/Type": Name("/Action"),
        "/S": Name("/JavaScript"),
        "/JS": String("app.alert('hello');"),
    })
    pdf.save(str(path))


def build_test_12_broken_struct_tree(path: pathlib.Path):
    """Struct tree with malformed /K entry — pipeline limps but completes."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Broken tree"))
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Broken Struct")
    # /K references a non-indirect dictionary (intentionally broken)
    sr = Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array([Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")})]),
    })
    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(sr)
    pdf.save(str(path))


def build_test_13_already_compliant(path: pathlib.Path):
    """PDF that is already compliant — pipeline is a no-op."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Already compliant"))
    _tag_minimal(pdf, title="Compliant Document")
    # Add a Document struct element so there's something to walk.
    doc = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": Array([]),
    }))
    pdf.Root["/StructTreeRoot"]["/K"] = Array([doc])
    pdf.Root["/ViewerPreferences"] = Dictionary({"/DisplayDocTitle": True})
    pdf.save(str(path))


def build_test_14_everything_wrong(path: pathlib.Path):
    """Kitchen-sink: untagged, no lang, widgets without tu/struct, etc."""
    pdf = pikepdf.new()
    page = _new_page(pdf, _text_content("Everything wrong here"))
    w = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 200, 720]),
        "/T": String("field1"),
        "/FT": Name("/Tx"),
    }))
    page["/Annots"] = Array([w])
    # Must add AcroForm/Fields so widget_mapper can find the widget
    pdf.Root["/AcroForm"] = Dictionary({
        "/Fields": Array([w]),
        "/NeedAppearances": True,
    })
    # No metadata — pipeline fills everything in
    pdf.save(str(path))


def build_test_15_landscape(path: pathlib.Path):
    """Landscape page — content should still process."""
    pdf = pikepdf.new()
    pdf.add_blank_page(page_size=(792, 612))
    page = pdf.pages[-1]
    font = _font(pdf)
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(_text_content("Landscape page content"))
    _tag_minimal(pdf, title="Landscape Document")
    pdf.save(str(path))


def build_test_16_with_attachment(path: pathlib.Path):
    """PDF with an embedded file attachment."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Has attachment"))
    _tag_minimal(pdf, title="Attachment Document")
    # Add an EmbeddedFiles name tree
    ef_stream = pdf.make_stream(b"attached content")
    ef_file = pdf.make_indirect(Dictionary({
        "/Type": Name("/Filespec"),
        "/F": String("attachment.txt"),
        "/UF": String("attachment.txt"),
        "/EF": Dictionary({"/F": ef_stream}),
    }))
    pdf.Root["/Names"] = Dictionary({
        "/EmbeddedFiles": Dictionary({
            "/Names": Array([String("attachment.txt"), ef_file]),
        }),
    })
    pdf.save(str(path))


def build_test_17_encrypted(path: pathlib.Path):
    """Password-protected PDF — pipeline should reject gracefully."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Encrypted content"))
    _tag_minimal(pdf, title="Encrypted Document")
    pdf.save(
        str(path),
        encryption=pikepdf.Encryption(
            owner="ownerpw",
            user="userpw",
            R=4,
        ),
    )


def build_test_18_ghost_text(path: pathlib.Path):
    """Content stream with Tr 3 (invisible text) — pipeline removes it."""
    pdf = pikepdf.new()
    content = b"BT /F1 12 Tf 3 Tr 72 700 Td (Invisible) Tj ET"
    _new_page(pdf, content)
    _tag_minimal(pdf, title="Ghost Text Document")
    pdf.save(str(path))


def build_test_19_multilingual(path: pathlib.Path):
    """PDF with text in multiple languages."""
    pdf = pikepdf.new()
    content = (
        b"BT /F1 12 Tf 72 700 Td (English text here) Tj ET\n"
        b"BT /F1 12 Tf 72 680 Td (Texto en espanol) Tj ET\n"
        b"BT /F1 12 Tf 72 660 Td (Texte en francais) Tj ET\n"
    )
    _new_page(pdf, content)
    _tag_minimal(pdf, title="Multilingual Document")
    pdf.save(str(path))


def build_test_20_no_pdfua_id(path: pathlib.Path):
    """Tagged PDF with no pdfuaid — pipeline adds it."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Tagged without PDF/UA ID"))
    _tag_minimal(pdf, title="No PDF/UA ID")
    # Explicitly no /Metadata stream
    pdf.save(str(path))


def build_test_21_wrong_tabs_order(path: pathlib.Path):
    """Widgets exist but /Tabs is /R (row order) instead of /S."""
    pdf = pikepdf.new()
    page = _new_page(pdf, _text_content("Wrong tab order"))
    w = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 200, 720]),
        "/T": String("field1"),
        "/FT": Name("/Tx"),
    }))
    page["/Annots"] = Array([w])
    page["/Tabs"] = Name("/R")  # wrong!
    _tag_minimal(pdf, title="Wrong Tabs")
    pdf.save(str(path))


def build_test_22_th_no_scope(path: pathlib.Path):
    """Table with /TH elements but no /Scope attribute."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Table without TH scope"))
    _tag_minimal(pdf, title="TH No Scope Document")
    th1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TH")}))
    th2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TH")}))
    td1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    tr1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/TR"),
        "/K": Array([th1, th2]),
    }))
    tr2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/TR"),
        "/K": Array([td1]),
    }))
    table = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/Table"),
        "/K": Array([tr1, tr2]),
    }))
    pdf.Root["/StructTreeRoot"]["/K"] = Array([table])
    pdf.save(str(path))


def build_test_23_heading_hierarchy_wrong(path: pathlib.Path):
    """Struct tree with H1 followed by H3 (skipped H2)."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Heading hierarchy wrong"))
    _tag_minimal(pdf, title="Heading Hierarchy")
    h1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/H1")}))
    h3 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/H3")}))
    p = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    doc = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Document"),
        "/K": Array([h1, h3, p]),
    }))
    pdf.Root["/StructTreeRoot"]["/K"] = Array([doc])
    pdf.save(str(path))


def build_test_24_suspects_true(path: pathlib.Path):
    """/Suspects is true — pipeline clears it."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Suspects flag"))
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True, "/Suspects": True})
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Suspects Document")
    pt = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
    sr = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array([]),
        "/ParentTree": pt,
    }))
    pdf.Root["/StructTreeRoot"] = sr
    pdf.save(str(path))


def build_test_25_fonts_not_embedded(path: pathlib.Path):
    """PDF that references standard 14 fonts (which are never embedded)."""
    pdf = pikepdf.new()
    _new_page(pdf, _text_content("Fonts not embedded"))
    _tag_minimal(pdf, title="Fonts Document")
    pdf.save(str(path))


def build_test_26_annotations_no_contents(path: pathlib.Path):
    """Non-widget/non-link annotation without /Contents."""
    pdf = pikepdf.new()
    page = _new_page(pdf, _text_content("Annotation no contents"))
    text_annot = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Text"),
        "/Rect": Array([72, 700, 92, 720]),
        # No /Contents
    }))
    page["/Annots"] = Array([text_annot])
    _tag_minimal(pdf, title="Annotation Document")
    pdf.save(str(path))


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

FIXTURES: list[tuple[str, Callable[[pathlib.Path], None]]] = [
    ("TEST_01_completely_untagged.pdf", build_test_01_completely_untagged),
    ("TEST_02_scanned_no_text.pdf", build_test_02_scanned_no_text),
    ("TEST_03_forms_no_tooltips.pdf", build_test_03_forms_no_tooltips),
    ("TEST_04_images_no_alt.pdf", build_test_04_images_no_alt),
    ("TEST_05_low_contrast.pdf", build_test_05_low_contrast),
    ("TEST_06_tables_no_headers.pdf", build_test_06_tables_no_headers),
    ("TEST_07_links_no_description.pdf", build_test_07_links_no_description),
    ("TEST_08_multipage_no_bookmarks.pdf", build_test_08_multipage_no_bookmarks),
    ("TEST_09_no_language.pdf", build_test_09_no_language),
    ("TEST_10_nonstandard_bdc_tags.pdf", build_test_10_nonstandard_bdc_tags),
    ("TEST_11_javascript_actions.pdf", build_test_11_javascript_actions),
    ("TEST_12_broken_struct_tree.pdf", build_test_12_broken_struct_tree),
    ("TEST_13_already_compliant.pdf", build_test_13_already_compliant),
    ("TEST_14_everything_wrong.pdf", build_test_14_everything_wrong),
    ("TEST_15_landscape.pdf", build_test_15_landscape),
    ("TEST_16_with_attachment.pdf", build_test_16_with_attachment),
    ("TEST_17_encrypted.pdf", build_test_17_encrypted),
    ("TEST_18_ghost_text.pdf", build_test_18_ghost_text),
    ("TEST_19_multilingual.pdf", build_test_19_multilingual),
    ("TEST_20_no_pdfua_id.pdf", build_test_20_no_pdfua_id),
    ("TEST_21_wrong_tabs_order.pdf", build_test_21_wrong_tabs_order),
    ("TEST_22_th_no_scope.pdf", build_test_22_th_no_scope),
    ("TEST_23_heading_hierarchy_wrong.pdf", build_test_23_heading_hierarchy_wrong),
    ("TEST_24_suspects_true.pdf", build_test_24_suspects_true),
    ("TEST_25_fonts_not_embedded.pdf", build_test_25_fonts_not_embedded),
    ("TEST_26_annotations_no_contents.pdf", build_test_26_annotations_no_contents),
]


def generate_all_test_fixtures(dest_dir: pathlib.Path) -> list[pathlib.Path]:
    """Generate every TEST_*.pdf fixture into `dest_dir`.

    Safe to call multiple times — existing files are only regenerated
    when missing or empty. Returns the list of paths generated.
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    generated: list[pathlib.Path] = []
    for name, builder in FIXTURES:
        path = dest_dir / name
        if path.exists() and path.stat().st_size > 0:
            continue
        try:
            builder(path)
            generated.append(path)
        except Exception as e:
            print(f"[integration_fixtures] WARNING: {name} failed: {e}")
    return generated


if __name__ == "__main__":
    import sys
    dest = pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "test_suite")
    paths = generate_all_test_fixtures(dest)
    print(f"Generated {len(paths)} fixtures in {dest}/")
