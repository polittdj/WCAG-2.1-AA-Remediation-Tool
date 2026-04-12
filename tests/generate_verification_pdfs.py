"""Generate verification PDFs with KNOWN violations for each checkpoint.

Each PDF is purpose-built to trigger exactly one (or a small set of)
checkpoint failure(s). These are used by test_checkpoint_verification.py
to prove detection AND remediation actually work.

Run:  python tests/generate_verification_pdfs.py
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
from pikepdf import Array, Dictionary, Name, String, Pdf

OUT_DIR = pathlib.Path(__file__).parent / "verification_pdfs"


def _ensure_dir():
    OUT_DIR.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _add_content(page, pdf: Pdf, content: bytes):
    """Set content stream on an existing page."""
    stream = pdf.make_stream(content)
    page["/Contents"] = stream


def _add_font_resource(page, pdf: Pdf):
    """Add Helvetica font as /F1 on page resources."""
    font = Dictionary({
        "/Type": Name("/Font"),
        "/Subtype": Name("/Type1"),
        "/BaseFont": Name("/Helvetica"),
    })
    if "/Resources" not in page:
        page["/Resources"] = Dictionary({})
    resources = page["/Resources"]
    if "/Font" not in resources:
        resources["/Font"] = Dictionary({})
    resources["/Font"]["/F1"] = pdf.make_indirect(font)


def _text_content(text: str = "Hello World", font_size: int = 12, x: int = 72, y: int = 700) -> bytes:
    return f"BT /F1 {font_size} Tf {x} {y} Td ({text}) Tj ET".encode()


def _add_struct_tree(pdf: Pdf, children=None) -> Dictionary:
    """Add a minimal StructTreeRoot."""
    parent_tree = pdf.make_indirect(Dictionary({"/Nums": Array([])}))
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array(children or []),
        "/ParentTree": parent_tree,
        "/ParentTreeNextKey": 0,
    }))
    pdf.Root["/StructTreeRoot"] = struct_root
    return struct_root


def _mark_tagged(pdf: Pdf):
    """Set /MarkInfo /Marked = true."""
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True})


def _new_page(pdf: Pdf, content: bytes = b"") -> pikepdf.Page:
    """Add a blank page, optionally with content, return it."""
    pdf.add_blank_page(page_size=(612, 792))
    page = pdf.pages[-1]
    _add_font_resource(page, pdf)
    if content:
        _add_content(page, pdf, content)
    return page


# ---------------------------------------------------------------------------
# C-01: Untagged PDF (no /MarkInfo, no /StructTreeRoot)
# ---------------------------------------------------------------------------


def gen_c01_untagged():
    """2-page PDF with text but NO tagging structure at all."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Page 1 content here", 12))
    _new_page(pdf, _text_content("Page 2 more content", 12))
    # Explicitly NO /MarkInfo, NO /StructTreeRoot
    pdf.save(str(OUT_DIR / "C-01_untagged.pdf"))


# ---------------------------------------------------------------------------
# C-02: No title
# ---------------------------------------------------------------------------


def gen_c02_no_title():
    """Tagged PDF with empty /Title."""
    pdf = Pdf.new()
    content = _text_content("Annual Report 2026", 24)
    content += b"\n" + _text_content("This is body text for the report.", 12, 72, 650)
    _new_page(pdf, content)
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.docinfo["/Title"] = String("")
    pdf.save(str(OUT_DIR / "C-02_no_title.pdf"))


# ---------------------------------------------------------------------------
# C-03: Placeholder title
# ---------------------------------------------------------------------------


def gen_c03_placeholder_title():
    """PDF with a placeholder title like 'Untitled Document'."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Real content here"))
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.docinfo["/Title"] = String("Untitled Document")
    pdf.save(str(OUT_DIR / "C-03_placeholder_title.pdf"))


# ---------------------------------------------------------------------------
# C-04: No document language
# ---------------------------------------------------------------------------


def gen_c04_no_language():
    """Tagged PDF with NO /Lang on catalog."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("English text here"))
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.docinfo["/Title"] = String("Test Document")
    # No /Lang set
    pdf.save(str(OUT_DIR / "C-04_no_language.pdf"))


# ---------------------------------------------------------------------------
# C-05: No passage-level language marking
# ---------------------------------------------------------------------------


def gen_c05_no_passage_lang():
    """PDF with foreign text but no passage-level /Lang."""
    pdf = Pdf.new()
    content = (
        b"BT /F1 12 Tf 72 700 Td (This is English text.) Tj ET\n"
        b"BT /F1 12 Tf 72 680 Td (Este es texto en espanol.) Tj ET\n"
        b"BT /F1 12 Tf 72 660 Td (Ceci est du texte francais.) Tj ET"
    )
    _new_page(pdf, content)
    _mark_tagged(pdf)
    pdf.Root["/Lang"] = String("en-US")
    p1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    p2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    p3 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    _add_struct_tree(pdf, [p1, p2, p3])
    pdf.docinfo["/Title"] = String("Multi-Language Doc")
    pdf.save(str(OUT_DIR / "C-05_no_passage_lang.pdf"))


# ---------------------------------------------------------------------------
# C-06: No PDF/UA identifier in XMP
# ---------------------------------------------------------------------------


def gen_c06_no_pdfua():
    """Tagged PDF with no XMP metadata."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Content"))
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Test Doc")
    # No /Metadata stream
    pdf.save(str(OUT_DIR / "C-06_no_pdfua.pdf"))


# ---------------------------------------------------------------------------
# C-07: No ViewerPreferences / DisplayDocTitle
# ---------------------------------------------------------------------------


def gen_c07_no_display_title():
    """PDF without ViewerPreferences."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Content"))
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Test Doc")
    # No /ViewerPreferences
    pdf.save(str(OUT_DIR / "C-07_no_display_title.pdf"))


# ---------------------------------------------------------------------------
# C-08: Restricted security
# ---------------------------------------------------------------------------


def gen_c08_restricted_security():
    """PDF with accessibility permission NOT set."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Secured content"))
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Secured Doc")
    pdf.save(
        str(OUT_DIR / "C-08_restricted_security.pdf"),
        encryption=pikepdf.Encryption(
            owner="owner123",
            user="",
            allow=pikepdf.Permissions(
                extract=False,
                modify_annotation=False,
                modify_assembly=False,
                modify_form=False,
                modify_other=False,
                print_lowres=True,
                print_highres=True,
                accessibility=False,
            ),
        ),
    )


# ---------------------------------------------------------------------------
# C-09: Suspects flag set
# ---------------------------------------------------------------------------


def gen_c09_suspects():
    """PDF with /Suspects = true."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Content"))
    pdf.Root["/MarkInfo"] = Dictionary({"/Marked": True, "/Suspects": True})
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Suspect Doc")
    pdf.save(str(OUT_DIR / "C-09_suspects.pdf"))


# ---------------------------------------------------------------------------
# C-10: No tab order
# ---------------------------------------------------------------------------


def gen_c10_no_tab_order():
    """3-page PDF with annotations but no /Tabs."""
    pdf = Pdf.new()
    for i in range(3):
        page = _new_page(pdf, _text_content(f"Page {i+1}"))
        widget = pdf.make_indirect(Dictionary({
            "/Type": Name("/Annot"),
            "/Subtype": Name("/Widget"),
            "/Rect": Array([100, 700, 200, 720]),
            "/T": String(f"field_{i}"),
            "/FT": Name("/Tx"),
        }))
        page["/Annots"] = Array([widget])
        # Explicitly remove /Tabs if present
        if "/Tabs" in page:
            del page["/Tabs"]
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Form Doc")
    pdf.save(str(OUT_DIR / "C-10_no_tab_order.pdf"))


# ---------------------------------------------------------------------------
# C-12: Partially tagged (struct tree exists but minimal)
# ---------------------------------------------------------------------------


def gen_c12_partial_tags():
    """StructTreeRoot exists but has zero child elements."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Untagged text on page 1"))
    _new_page(pdf, _text_content("Untagged text on page 2"))
    _mark_tagged(pdf)
    struct_root = _add_struct_tree(pdf)
    # Empty /K — no elements tagged
    struct_root["/K"] = Array([])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Partial Tags Doc")
    pdf.save(str(OUT_DIR / "C-12_partial_tags.pdf"))


# ---------------------------------------------------------------------------
# C-13: Non-standard BDC tags
# ---------------------------------------------------------------------------


def gen_c13_bad_bdc():
    """Content stream with non-standard BDC tag names."""
    pdf = Pdf.new()
    bad_content = (
        b"/CustomTag <</MCID 0>> BDC BT /F1 12 Tf 72 700 Td (Bad tag text) Tj ET EMC\n"
        b"/ExtraCharSpan <</MCID 1>> BDC BT /F1 12 Tf 72 680 Td (More bad) Tj ET EMC"
    )
    _new_page(pdf, bad_content)
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Bad BDC Doc")
    pdf.save(str(OUT_DIR / "C-13_bad_bdc.pdf"))


# ---------------------------------------------------------------------------
# C-14: Ghost text (Tr 3)
# ---------------------------------------------------------------------------


def gen_c14_ghost_text():
    """PDF with invisible text rendering mode."""
    pdf = Pdf.new()
    ghost = b"BT /F1 12 Tf 3 Tr 72 700 Td (Invisible text here) Tj ET"
    _new_page(pdf, ghost)
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Ghost Text Doc")
    pdf.save(str(OUT_DIR / "C-14_ghost_text.pdf"))


# ---------------------------------------------------------------------------
# C-19: No heading tags (6+ page document)
# ---------------------------------------------------------------------------


def gen_c19_no_headings():
    """6-page PDF with only /P elements — no headings."""
    pdf = Pdf.new()
    elems = []
    for i in range(6):
        _new_page(pdf, _text_content(f"Paragraph on page {i+1}"))
        p = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
        elems.append(p)
    _mark_tagged(pdf)
    _add_struct_tree(pdf, elems)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Headings Doc")
    pdf.save(str(OUT_DIR / "C-19_no_headings.pdf"))


# ---------------------------------------------------------------------------
# C-20: Skipped heading levels
# ---------------------------------------------------------------------------


def gen_c20_skipped_headings():
    """H1 followed by H3 (skips H2)."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Document"))
    h1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/H1")}))
    h3 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/H3")}))
    p = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [h1, h3, p])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Skipped Headings")
    pdf.save(str(OUT_DIR / "C-20_skipped_headings.pdf"))


# ---------------------------------------------------------------------------
# C-23: No bookmarks (21 pages)
# ---------------------------------------------------------------------------


def gen_c23_no_bookmarks():
    """21-page PDF with headings but no /Outlines."""
    pdf = Pdf.new()
    elems = []
    for i in range(21):
        _new_page(pdf, _text_content(f"Chapter {i+1}"))
        h = pdf.make_indirect(Dictionary({
            "/Type": Name("/StructElem"),
            "/S": Name("/H1"),
            "/Alt": String(f"Chapter {i+1}"),
        }))
        elems.append(h)
    _mark_tagged(pdf)
    _add_struct_tree(pdf, elems)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Long Doc No Bookmarks")
    # NO /Outlines
    pdf.save(str(OUT_DIR / "C-23_no_bookmarks.pdf"))


# ---------------------------------------------------------------------------
# C-24: Table without /TR
# ---------------------------------------------------------------------------


def gen_c24_flat_table():
    """/Table with /TD children directly (no /TR wrapper)."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Table data"))
    td1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    td2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    td3 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    table = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"),
        "/S": Name("/Table"),
        "/K": Array([td1, td2, td3]),
    }))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [table])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Flat Table Doc")
    pdf.save(str(OUT_DIR / "C-24_flat_table.pdf"))


# ---------------------------------------------------------------------------
# C-25: TH without /Scope
# ---------------------------------------------------------------------------


def gen_c25_no_scope():
    """Table with /TH but no /Scope attribute."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Table"))
    th1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TH")}))
    th2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TH")}))
    td1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    td2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/TD")}))
    tr1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/TR"),
        "/K": Array([th1, th2]),
    }))
    tr2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/TR"),
        "/K": Array([td1, td2]),
    }))
    table = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/Table"),
        "/K": Array([tr1, tr2]),
    }))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [table])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Scope Table")
    pdf.save(str(OUT_DIR / "C-25_no_scope.pdf"))


# ---------------------------------------------------------------------------
# C-28: List without /LI
# ---------------------------------------------------------------------------


def gen_c28_bad_list():
    """/L with /P children instead of /LI."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("List items"))
    p1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    p2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    lst = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/L"),
        "/K": Array([p1, p2]),
    }))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [lst])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Bad List Doc")
    pdf.save(str(OUT_DIR / "C-28_bad_list.pdf"))


# ---------------------------------------------------------------------------
# C-29: LI without /Lbl or /LBody
# ---------------------------------------------------------------------------


def gen_c29_no_lbl_lbody():
    """/LI with just /P child (not /Lbl or /LBody)."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("List content"))
    p1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    li1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/LI"),
        "/K": Array([p1]),
    }))
    li2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/LI"),
        "/K": Array([]),
    }))
    lst = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/L"),
        "/K": Array([li1, li2]),
    }))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [lst])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Lbl LBody Doc")
    pdf.save(str(OUT_DIR / "C-29_no_lbl_lbody.pdf"))


# ---------------------------------------------------------------------------
# C-31: Figures without /Alt
# ---------------------------------------------------------------------------


def gen_c31_no_alt():
    """Three /Figure elements with no or empty /Alt."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Document with images"))
    fig1 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/Figure")}))
    fig2 = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/Figure")}))
    fig3 = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructElem"), "/S": Name("/Figure"),
        "/Alt": String(""),
    }))
    _mark_tagged(pdf)
    _add_struct_tree(pdf, [fig1, fig2, fig3])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Alt Text Doc")
    pdf.save(str(OUT_DIR / "C-31_no_alt.pdf"))


# ---------------------------------------------------------------------------
# C-35: Widgets without /Form struct elements
# ---------------------------------------------------------------------------


def gen_c35_no_form_struct():
    """Widgets exist but no /Form elements in struct tree."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Form page"))
    w1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 300, 720]),
        "/T": String("name"), "/FT": Name("/Tx"),
    }))
    w2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 660, 300, 680]),
        "/T": String("email"), "/FT": Name("/Tx"),
    }))
    page["/Annots"] = Array([w1, w2])
    _mark_tagged(pdf)
    p = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    _add_struct_tree(pdf, [p])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Form Struct Doc")
    pdf.save(str(OUT_DIR / "C-35_no_form_struct.pdf"))


# ---------------------------------------------------------------------------
# C-36: Widgets without /TU
# ---------------------------------------------------------------------------


def gen_c36_no_tu():
    """Widgets with /T but no /TU."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Form"))
    w1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 300, 720]),
        "/T": String("first_name"), "/FT": Name("/Tx"),
    }))
    w2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 660, 300, 680]),
        "/T": String("last_name"), "/FT": Name("/Tx"),
    }))
    w3 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 620, 300, 640]),
        "/T": String("email_addr"), "/FT": Name("/Tx"),
    }))
    page["/Annots"] = Array([w1, w2, w3])
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No TU Doc")
    pdf.save(str(OUT_DIR / "C-36_no_tu.pdf"))


# ---------------------------------------------------------------------------
# C-39: Widgets without /StructParent
# ---------------------------------------------------------------------------


def gen_c39_no_struct_parent():
    """Widgets with no /StructParent."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Form fields"))
    w1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 300, 720]),
        "/T": String("field1"), "/FT": Name("/Tx"),
    }))
    w2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 660, 300, 680]),
        "/T": String("field2"), "/FT": Name("/Tx"),
    }))
    page["/Annots"] = Array([w1, w2])
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No StructParent Doc")
    pdf.save(str(OUT_DIR / "C-39_no_struct_parent.pdf"))


# ---------------------------------------------------------------------------
# C-42: Links without /Link struct elements
# ---------------------------------------------------------------------------


def gen_c42_no_link_struct():
    """Link annotations but no /Link in struct tree."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Click here for info"))
    link1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([72, 700, 200, 720]),
        "/A": Dictionary({"/Type": Name("/Action"), "/S": Name("/URI"), "/URI": String("https://example.com")}),
    }))
    link2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([72, 670, 200, 690]),
        "/A": Dictionary({"/Type": Name("/Action"), "/S": Name("/URI"), "/URI": String("https://test.org/page")}),
    }))
    page["/Annots"] = Array([link1, link2])
    _mark_tagged(pdf)
    p = pdf.make_indirect(Dictionary({"/Type": Name("/StructElem"), "/S": Name("/P")}))
    _add_struct_tree(pdf, [p])
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Link Struct Doc")
    pdf.save(str(OUT_DIR / "C-42_no_link_struct.pdf"))


# ---------------------------------------------------------------------------
# C-43: Links without /Contents
# ---------------------------------------------------------------------------


def gen_c43_no_link_contents():
    """Links with no /Contents."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Click here"))
    link1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([72, 700, 200, 720]),
        "/A": Dictionary({"/Type": Name("/Action"), "/S": Name("/URI"), "/URI": String("https://example.com/page1")}),
    }))
    link2 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([72, 670, 200, 690]),
        "/A": Dictionary({"/Type": Name("/Action"), "/S": Name("/URI"), "/URI": String("https://example.com/page2")}),
    }))
    page["/Annots"] = Array([link1, link2])
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Link Contents Doc")
    pdf.save(str(OUT_DIR / "C-43_no_link_contents.pdf"))


# ---------------------------------------------------------------------------
# C-44: Links without destinations
# ---------------------------------------------------------------------------


def gen_c44_no_link_dest():
    """Link annotations with no /Dest or /A."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Link text"))
    link1 = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([72, 700, 200, 720]),
        # No /A and no /Dest
    }))
    page["/Annots"] = Array([link1])
    _mark_tagged(pdf)
    _add_struct_tree(pdf)
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("No Link Dest Doc")
    pdf.save(str(OUT_DIR / "C-44_no_link_dest.pdf"))


# ---------------------------------------------------------------------------
# C-46: ParentTree with /Kids (not flat)
# ---------------------------------------------------------------------------


def gen_c46_parent_tree_kids():
    """ParentTree uses /Kids instead of flat /Nums."""
    pdf = Pdf.new()
    _new_page(pdf, _text_content("Content"))
    _mark_tagged(pdf)
    child_node = pdf.make_indirect(Dictionary({
        "/Nums": Array([0, pdf.make_indirect(Dictionary({"/S": Name("/P")}))]),
        "/Limits": Array([0, 0]),
    }))
    parent_tree = pdf.make_indirect(Dictionary({"/Kids": Array([child_node])}))
    struct_root = pdf.make_indirect(Dictionary({
        "/Type": Name("/StructTreeRoot"),
        "/K": Array([]),
        "/ParentTree": parent_tree,
    }))
    pdf.Root["/StructTreeRoot"] = struct_root
    pdf.Root["/Lang"] = String("en-US")
    pdf.docinfo["/Title"] = String("Kids ParentTree Doc")
    pdf.save(str(OUT_DIR / "C-46_parent_tree_kids.pdf"))


# ---------------------------------------------------------------------------
# Multi-violation PDF (for cross-cutting tests)
# ---------------------------------------------------------------------------


def gen_multi_violation():
    """PDF that fails many checkpoints simultaneously."""
    pdf = Pdf.new()
    page = _new_page(pdf, _text_content("Multi-violation document"))
    # Widget without TU
    w = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Widget"),
        "/Rect": Array([100, 700, 300, 720]),
        "/T": String("field1"), "/FT": Name("/Tx"),
    }))
    # Link without contents
    lnk = pdf.make_indirect(Dictionary({
        "/Type": Name("/Annot"), "/Subtype": Name("/Link"),
        "/Rect": Array([100, 650, 250, 670]),
        "/A": Dictionary({"/S": Name("/URI"), "/URI": String("https://example.com")}),
    }))
    page["/Annots"] = Array([w, lnk])
    # No /MarkInfo, no /StructTreeRoot, no /Lang, no /Title
    pdf.save(str(OUT_DIR / "multi_violation.pdf"))


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


def generate_all():
    """Generate all verification PDFs."""
    _ensure_dir()
    generators = [
        gen_c01_untagged,
        gen_c02_no_title,
        gen_c03_placeholder_title,
        gen_c04_no_language,
        gen_c05_no_passage_lang,
        gen_c06_no_pdfua,
        gen_c07_no_display_title,
        gen_c08_restricted_security,
        gen_c09_suspects,
        gen_c10_no_tab_order,
        gen_c12_partial_tags,
        gen_c13_bad_bdc,
        gen_c14_ghost_text,
        gen_c19_no_headings,
        gen_c20_skipped_headings,
        gen_c23_no_bookmarks,
        gen_c24_flat_table,
        gen_c25_no_scope,
        gen_c28_bad_list,
        gen_c29_no_lbl_lbody,
        gen_c31_no_alt,
        gen_c35_no_form_struct,
        gen_c36_no_tu,
        gen_c39_no_struct_parent,
        gen_c42_no_link_struct,
        gen_c43_no_link_contents,
        gen_c44_no_link_dest,
        gen_c46_parent_tree_kids,
        gen_multi_violation,
    ]
    for gen_fn in generators:
        name = gen_fn.__name__
        try:
            gen_fn()
            print(f"  OK: {name}")
        except Exception as e:
            print(f"  FAIL: {name} -- {type(e).__name__}: {e}")
    print(f"\nGenerated {len(generators)} verification PDFs in {OUT_DIR}")


if __name__ == "__main__":
    generate_all()
