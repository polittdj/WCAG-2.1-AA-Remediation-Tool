#!/usr/bin/env python3
"""Generate test fixture PDFs for the test suite.

These fixtures replicate the structural characteristics of the original
production PDFs that were stored in Git LFS. Each fixture is built with
pikepdf to match the specific properties that tests assert against.
"""

from __future__ import annotations

import pathlib

import pikepdf

ROOT = pathlib.Path(__file__).resolve().parents[1]
DEST = ROOT / "test_suite"


def _font(pdf):
    """Return a shared Helvetica font indirect object."""
    return pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Font"),
        "/Subtype": pikepdf.Name("/Type1"),
        "/BaseFont": pikepdf.Name("/Helvetica"),
    }))


def _add_page(pdf, text_lines, font_ref, page_size=(612, 792)):
    """Add a page with BDC-tagged text content. Returns the page object."""
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    page["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({"/F1": font_ref}),
    })

    lines = ["q"]
    y = 700
    for i, text in enumerate(text_lines):
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        lines.append(f"/P <</MCID {i}>> BDC")
        lines.append("BT")
        lines.append("/F1 12 Tf")
        lines.append(f"72 {y} Td")
        lines.append(f"({escaped}) Tj")
        lines.append("ET")
        lines.append("EMC")
        y -= 20
    lines.append("Q")
    page["/Contents"] = pdf.make_stream("\n".join(lines).encode())
    return page


def _setup_base(pdf, title, lang="en-US"):
    """Set common metadata: title, lang, MarkInfo."""
    pdf.docinfo["/Title"] = title
    pdf.Root["/Lang"] = pikepdf.String(lang)
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})


def _build_struct_tree_flat(pdf, *, extra_elems=None, role_map=None):
    """Build a StructTreeRoot with flat /Nums ParentTree.

    Sets /StructParents on each page pointing to arrays of struct elements.
    """
    doc_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([]),
    }))

    nums_array = pikepdf.Array([])

    for pg_idx in range(len(pdf.pages)):
        page = pdf.pages[pg_idx]
        page_obj = page.obj if hasattr(page, "obj") else page

        # Set /StructParents on the page
        page["/StructParents"] = pg_idx

        # Build struct elements for each BDC MCID on this page
        # We scan the content to count MCIDs
        c = page.get("/Contents")
        data = b""
        if c is not None:
            if isinstance(c, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in c)
            else:
                data = bytes(c.read_bytes())

        mcid_count = data.count(b"MCID")
        page_pt_array = pikepdf.Array()
        for mcid in range(mcid_count):
            p_elem = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/P"),
                "/P": doc_elem,
                "/K": pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/MCR"),
                    "/MCID": mcid,
                    "/Pg": page_obj,
                }),
            }))
            doc_elem["/K"].append(p_elem)
            page_pt_array.append(p_elem)

        nums_array.append(pg_idx)
        nums_array.append(pdf.make_indirect(page_pt_array))

    if extra_elems:
        for elem in extra_elems:
            doc_elem["/K"].append(elem)

    parent_tree = pdf.make_indirect(pikepdf.Dictionary({
        "/Nums": nums_array,
    }))

    st_dict = pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc_elem]),
        "/ParentTree": parent_tree,
        "/ParentTreeNextKey": len(pdf.pages),
    })

    if role_map:
        rm = pikepdf.Dictionary()
        for k, v in role_map.items():
            rm[pikepdf.Name(f"/{k}")] = pikepdf.Name(f"/{v}")
        st_dict["/RoleMap"] = rm

    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(st_dict)
    doc_elem["/P"] = pdf.Root["/StructTreeRoot"]
    return doc_elem


def _build_struct_tree_kids(pdf, *, role_map=None):
    """Build a StructTreeRoot with /Kids-based ParentTree (NOT flat /Nums)."""
    doc_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([]),
    }))

    # Build one num-tree leaf per page, then wrap in /Kids
    kids = pikepdf.Array([])

    for pg_idx in range(len(pdf.pages)):
        page = pdf.pages[pg_idx]
        page_obj = page.obj if hasattr(page, "obj") else page
        page["/StructParents"] = pg_idx

        c = page.get("/Contents")
        data = b""
        if c is not None:
            if isinstance(c, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in c)
            else:
                data = bytes(c.read_bytes())

        mcid_count = data.count(b"MCID")
        page_pt_array = pikepdf.Array()
        for mcid in range(mcid_count):
            p_elem = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/P"),
                "/P": doc_elem,
                "/K": pikepdf.Dictionary({
                    "/Type": pikepdf.Name("/MCR"),
                    "/MCID": mcid,
                    "/Pg": page_obj,
                }),
            }))
            doc_elem["/K"].append(p_elem)
            page_pt_array.append(p_elem)

        leaf = pdf.make_indirect(pikepdf.Dictionary({
            "/Nums": pikepdf.Array([pg_idx, pdf.make_indirect(page_pt_array)]),
            "/Limits": pikepdf.Array([pg_idx, pg_idx]),
        }))
        kids.append(leaf)

    parent_tree = pdf.make_indirect(pikepdf.Dictionary({
        "/Kids": kids,
    }))

    st_dict = pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc_elem]),
        "/ParentTree": parent_tree,
        "/ParentTreeNextKey": len(pdf.pages),
    })

    if role_map:
        rm = pikepdf.Dictionary()
        for k, v in role_map.items():
            rm[pikepdf.Name(f"/{k}")] = pikepdf.Name(f"/{v}")
        st_dict["/RoleMap"] = rm

    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(st_dict)
    doc_elem["/P"] = pdf.Root["/StructTreeRoot"]
    return doc_elem


def _add_widgets_to_page(pdf, page, count, *, with_tu=False,
                         group_children=False, include_sig=False,
                         include_tx_bmc=False, start_idx=0):
    """Add widget annotations to a page. Returns the widget refs."""
    if "/Annots" not in page:
        page["/Annots"] = pikepdf.Array([])

    widgets = []
    y = 680
    for i in range(count):
        x = 72 + (i % 3) * 180
        if i % 3 == 0 and i > 0:
            y -= 25
        if y < 50:
            y = 680

        idx = start_idx + i

        if include_sig and i >= count - 3:
            ft = "/Sig"
            field_name = f"Signature{idx}"
        else:
            ft = "/Tx"
            if group_children and i < count // 2:
                field_name = str(i % 5)  # bare index — group child
            else:
                field_name = f"Field_{idx}"

        widget = pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Annot"),
            "/Subtype": pikepdf.Name("/Widget"),
            "/FT": pikepdf.Name(ft),
            "/T": pikepdf.String(field_name),
            "/Rect": pikepdf.Array([x, y, x + 150, y + 18]),
        })

        if with_tu and i % 3 == 0:
            widget["/TU"] = pikepdf.String(f"Description for {field_name}")

        if include_tx_bmc and ft == "/Tx":
            f1 = _font(pdf)
            ap_stream = pdf.make_stream(
                b"q\n0.95 0.95 0.95 rg\n0 0 150 18 re\nf\n"
                b"/Tx BMC\nBT\n/F1 10 Tf\n2 4 Td\n(text) Tj\nET\nEMC\nQ\n",
                {
                    "/Type": pikepdf.Name("/XObject"),
                    "/Subtype": pikepdf.Name("/Form"),
                    "/BBox": pikepdf.Array([0, 0, 150, 18]),
                    "/Resources": pikepdf.Dictionary({
                        "/Font": pikepdf.Dictionary({"/F1": f1}),
                    }),
                },
            )
            widget["/AP"] = pikepdf.Dictionary({"/N": ap_stream})

        ref = pdf.make_indirect(widget)
        page["/Annots"].append(ref)
        widgets.append(ref)

    return widgets


def _setup_acroform(pdf, fields):
    """Create /AcroForm with given field references."""
    if "/AcroForm" not in pdf.Root:
        pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary({
            "/Fields": pikepdf.Array([]),
        }))
    for f in fields:
        pdf.Root["/AcroForm"]["/Fields"].append(f)


def _add_struct_parents_to_widgets(pdf, start_sp=100):
    """Give every widget a /StructParent index."""
    sp = start_sp
    for page in pdf.pages:
        for annot in page.get("/Annots") or []:
            if str(annot.get("/Subtype", "")) == "/Widget":
                annot["/StructParent"] = sp
                sp += 1
    return sp


def _inject_untagged_content(pdf, page_idx):
    """Append untagged BT/ET + path content to a page's content stream."""
    page = pdf.pages[page_idx]
    c = page.get("/Contents")
    existing = b""
    if c is not None:
        if isinstance(c, pikepdf.Array):
            existing = b"\n".join(bytes(s.read_bytes()) for s in c)
        else:
            existing = bytes(c.read_bytes())

    untagged = (
        b"\nBT\n/F1 10 Tf\n72 50 Td\n(Untagged travel form text) Tj\nET\n"
        b"\n0.5 0.5 0.5 rg\n100 30 200 10 re\nf\n"
    )
    page["/Contents"] = pdf.make_stream(existing + untagged)


def _inject_nonstandard_bdc(pdf, page_idx):
    """Add ExtraCharSpan non-standard BDC tags to a page's content stream."""
    page = pdf.pages[page_idx]
    c = page.get("/Contents")
    existing = b""
    if c is not None:
        if isinstance(c, pikepdf.Array):
            existing = b"\n".join(bytes(s.read_bytes()) for s in c)
        else:
            existing = bytes(c.read_bytes())

    non_standard = (
        b"\n/ExtraCharSpan <</MCID 99>> BDC\n"
        b"BT\n/F1 8 Tf\n72 30 Td\n(extra) Tj\nET\n"
        b"EMC\n"
    )
    page["/Contents"] = pdf.make_stream(existing + non_standard)


# ═══════════════════════════════════════════════════════════════════════
# Fixture builders
# ═══════════════════════════════════════════════════════════════════════


def build_good(dest):
    """12.0_updated - WCAG 2.1 AA Compliant.pdf

    Clean 3-page tagged PDF. Good title, /Lang, /MarkInfo, flat ParentTree.
    Has a few widgets with /StructParent so C-39 returns PASS.
    No figures (C-31 N/A). Standard BDC tags only.
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "CPSS Personnel System Form 12.0 Updated")

    for pg in range(3):
        _add_page(pdf, [
            f"CPSS Personnel System Form 12.0 — Page {pg + 1}",
            "Application for Certificate of Transfer",
            "This form is used for personnel transfer requests.",
            "All fields must be completed before submission.",
        ], font)

    # Add a few widgets so C-39 returns PASS (not N/A)
    all_widgets = []
    for pg in range(3):
        w = _add_widgets_to_page(pdf, pdf.pages[pg], 3,
                                 with_tu=True, start_idx=pg * 3)
        all_widgets.extend(w)
    _setup_acroform(pdf, all_widgets)
    _add_struct_parents_to_widgets(pdf)

    _build_struct_tree_flat(pdf)

    pdf.save(str(dest))
    pdf.close()


def build_editable(dest):
    """12.0_updated_editable - WCAG 2.1 AA Compliant.pdf

    3-page tagged PDF with form widgets. /Kids-based ParentTree (not flat).
    Has ExtraCharSpan non-standard BDC tags and RoleMap entries.
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "CPSS Personnel System Form 12.0 Editable")

    for pg in range(3):
        _add_page(pdf, [
            f"CPSS Editable Form — Page {pg + 1}",
            "Employee Name: _______________",
            "Department: _______________",
        ], font)

    # Add form widgets (10 per page)
    all_widgets = []
    for pg in range(3):
        w = _add_widgets_to_page(pdf, pdf.pages[pg], 10,
                                 with_tu=True, start_idx=pg * 10)
        all_widgets.extend(w)
    _setup_acroform(pdf, all_widgets)
    _add_struct_parents_to_widgets(pdf)

    # Add non-standard BDC tags to page 0
    _inject_nonstandard_bdc(pdf, 0)

    # Build struct tree with /Kids ParentTree (NOT flat)
    _build_struct_tree_kids(pdf, role_map={
        "ExtraCharSpan": "Span",
        "ParagraphSpan": "Span",
    })

    pdf.save(str(dest))
    pdf.close()


def build_ms_word(dest):
    """12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf

    3-page tagged PDF with blacklisted title. Content has keywords for
    title derivation: certificate, transfer, application.
    Has a few widgets so C-39 returns PASS (not N/A).
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "Untitled Document")

    _add_page(pdf, [
        "Application for Certificate of Transfer",
        "This document was converted from Microsoft Word.",
        "Please complete all sections of this application.",
        "Certificate of Transfer — Official Use Only",
    ], font)
    _add_page(pdf, [
        "Section 2: Transfer Details",
        "Application requirements and procedures.",
        "Date of transfer request: ___________",
    ], font)
    _add_page(pdf, [
        "Section 3: Approval",
        "Authorized signature required for certificate issuance.",
        "Application approved: Yes / No",
    ], font)

    # Add a few widgets so C-39 returns PASS
    all_widgets = []
    for pg in range(3):
        w = _add_widgets_to_page(pdf, pdf.pages[pg], 2,
                                 with_tu=True, start_idx=pg * 2)
        all_widgets.extend(w)
    _setup_acroform(pdf, all_widgets)
    _add_struct_parents_to_widgets(pdf)

    _build_struct_tree_flat(pdf)

    pdf.save(str(dest))
    pdf.close()


def build_editable_ada(dest):
    """12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf

    3-page tagged PDF with form widgets. ADA-compliant variant.
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "CPSS Personnel System Form 12.0 ADA")

    for pg in range(3):
        _add_page(pdf, [
            f"CPSS ADA Accessible Form — Page {pg + 1}",
            "This form meets ADA accessibility requirements.",
            "Employee Information Section",
        ], font)

    all_widgets = []
    for pg in range(3):
        w = _add_widgets_to_page(pdf, pdf.pages[pg], 8,
                                 with_tu=True, start_idx=pg * 8)
        all_widgets.extend(w)
    _setup_acroform(pdf, all_widgets)
    _add_struct_parents_to_widgets(pdf)

    _build_struct_tree_flat(pdf)

    pdf.save(str(dest))
    pdf.close()


def build_travel_compliant(dest):
    """CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf

    2-page form with 96 widgets, /Link annotations, /Figure elements with
    MCIDs for rendering, untagged content, /Tx BMC in widget appearances,
    missing /TU fields, group-child widgets, and /Sig fields.
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "Untitled Document")

    # Page 0
    _add_page(pdf, [
        "CPSSPPC TRAVEL AUTHORIZATION FORM",
        "CGI Federal Travel Request — Version 1.9",
        "Employee travel authorization and expense reporting.",
        "Traveler Name: _______________",
        "Destination: _______________",
        "Purpose of Travel: Official business travel required.",
    ], font)

    # Page 1
    _add_page(pdf, [
        "Travel Expense Report — Page 2",
        "Estimated costs and approvals.",
        "Supervisor Approval: _______________",
    ], font)

    # Add 96 widgets: 64 on page 0 + 32 on page 1
    w0 = _add_widgets_to_page(pdf, pdf.pages[0], 64,
                               with_tu=False, group_children=True,
                               include_tx_bmc=True, start_idx=0)
    w1 = _add_widgets_to_page(pdf, pdf.pages[1], 32,
                               with_tu=False, include_sig=True,
                               include_tx_bmc=True, start_idx=64)
    _setup_acroform(pdf, w0 + w1)

    # Add /Link annotations on page 0
    page0 = pdf.pages[0]
    gsa_link = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/Annot"),
        "/Subtype": pikepdf.Name("/Link"),
        "/Rect": pikepdf.Array([72, 650, 300, 665]),
        "/A": pikepdf.Dictionary({
            "/S": pikepdf.Name("/URI"),
            "/URI": pikepdf.String("https://www.gsa.gov/travel/plan-book/per-diem-rates"),
        }),
    }))
    page0["/Annots"].append(gsa_link)

    # Add untagged content to both pages
    _inject_untagged_content(pdf, 0)
    _inject_untagged_content(pdf, 1)

    # Add a figure MCID to page 0 content — image-only (Do operator, no text)
    page0 = pdf.pages[0]
    c = page0.get("/Contents")
    existing = bytes(c.read_bytes()) if c is not None else b""
    fig_mcid = 99  # unique MCID for the figure
    fig_content = (
        f"\n/Figure <</MCID {fig_mcid}>> BDC\n"
        f"q\n0.8 0 0 0.8 400 700 cm\n/Im0 Do\nQ\n"
        f"EMC\n"
    ).encode()
    page0["/Contents"] = pdf.make_stream(existing + fig_content)

    # Create a tiny 1x1 image XObject for the figure
    img_stream = pdf.make_stream(b"\xff\xff\xff", {
        "/Type": pikepdf.Name("/XObject"),
        "/Subtype": pikepdf.Name("/Image"),
        "/Width": 1,
        "/Height": 1,
        "/ColorSpace": pikepdf.Name("/DeviceRGB"),
        "/BitsPerComponent": 8,
    })
    if "/Resources" not in page0:
        page0["/Resources"] = pikepdf.Dictionary({})
    res = page0["/Resources"]
    if "/XObject" not in res:
        res["/XObject"] = pikepdf.Dictionary({})
    res["/XObject"]["/Im0"] = img_stream

    # Build struct tree with /Figure and /Link elements
    doc_elem = _build_struct_tree_flat(pdf)

    # Add a /Figure struct element referencing the image MCID
    page0_obj = pdf.pages[0].obj if hasattr(pdf.pages[0], "obj") else pdf.pages[0]
    fig_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Figure"),
        "/P": doc_elem,
        "/K": pikepdf.Dictionary({
            "/Type": pikepdf.Name("/MCR"),
            "/MCID": fig_mcid,
            "/Pg": page0_obj,
        }),
    }))
    doc_elem["/K"].append(fig_elem)

    # Add /Link struct element
    link_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Link"),
        "/P": doc_elem,
    }))
    doc_elem["/K"].append(link_elem)

    pdf.save(str(dest))
    pdf.close()


def build_travel_raw(dest):
    """CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte.pdf

    Raw (unremediated) travel form. Has /Tabs /W (not /S).
    Non-terminal AcroForm parent fields missing /TU, including
    "Departure Location".
    """
    pdf = pikepdf.new()
    font = _font(pdf)
    _setup_base(pdf, "Untitled Document")

    _add_page(pdf, [
        "CPSSPPC TRAVEL AUTHORIZATION FORM",
        "CGI Federal Travel Request — Version 1.9",
        "Travel expense reporting document.",
    ], font)
    _add_page(pdf, [
        "Travel Expense Report — Page 2",
        "Estimated costs and approvals.",
    ], font)

    # Set /Tabs to /W (not /S) on all pages
    for pg in pdf.pages:
        pg["/Tabs"] = pikepdf.Name("/W")

    # Build AcroForm with non-terminal parent fields
    pdf.Root["/AcroForm"] = pdf.make_indirect(pikepdf.Dictionary({
        "/Fields": pikepdf.Array([]),
    }))
    acroform = pdf.Root["/AcroForm"]
    page0 = pdf.pages[0]
    if "/Annots" not in page0:
        page0["/Annots"] = pikepdf.Array([])

    parent_specs = {
        "Departure Location": ["City", "State", "Zip"],
        "Destination": ["0", "1", "2", "3", "4"],
        "Return Information": ["Date", "Flight"],
        "Traveler Info": ["Name", "ID", "Phone"],
    }

    for pf_name, kid_names in parent_specs.items():
        kids_arr = pikepdf.Array()
        for kn in kid_names:
            kid = pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Annot"),
                "/Subtype": pikepdf.Name("/Widget"),
                "/FT": pikepdf.Name("/Tx"),
                "/T": pikepdf.String(kn),
                "/Rect": pikepdf.Array([72, 500, 222, 518]),
            }))
            page0["/Annots"].append(kid)
            kids_arr.append(kid)

        parent = pdf.make_indirect(pikepdf.Dictionary({
            "/T": pikepdf.String(pf_name),
            "/Kids": kids_arr,
        }))
        for k in kids_arr:
            k["/Parent"] = parent
        acroform["/Fields"].append(parent)

    # Extra widgets on page 1
    page1 = pdf.pages[1]
    page1["/Annots"] = pikepdf.Array([])
    for i in range(10):
        w = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/Annot"),
            "/Subtype": pikepdf.Name("/Widget"),
            "/FT": pikepdf.Name("/Tx"),
            "/T": pikepdf.String(f"Extra_{i}"),
            "/Rect": pikepdf.Array([72, 600 - i * 25, 222, 618 - i * 25]),
        }))
        page1["/Annots"].append(w)
        acroform["/Fields"].append(w)

    _build_struct_tree_flat(pdf)

    pdf.save(str(dest))
    pdf.close()


def main():
    DEST.mkdir(parents=True, exist_ok=True)

    fixtures = [
        ("12.0_updated - WCAG 2.1 AA Compliant.pdf", build_good),
        ("12.0_updated_editable - WCAG 2.1 AA Compliant.pdf", build_editable),
        ("12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf", build_ms_word),
        ("12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf", build_editable_ada),
        ("CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf", build_travel_compliant),
        ("CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte.pdf", build_travel_raw),
    ]

    for name, builder in fixtures:
        path = DEST / name
        print(f"Generating: {name}")
        builder(path)
        size = path.stat().st_size
        print(f"  -> {size:,} bytes")

    print(f"\nAll {len(fixtures)} fixtures generated in {DEST}/")


if __name__ == "__main__":
    main()
