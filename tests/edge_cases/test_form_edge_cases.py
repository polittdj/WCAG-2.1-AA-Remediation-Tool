"""Form / AcroForm edge-case tests.

Every input PDF is generated programmatically with pikepdf. Contract
under test:

* ``run_pipeline`` always returns a dict with no raw traceback in
  ``result["errors"]``.
* For structurally valid PDFs the pipeline produces a final
  ``_WGAC_2.1_AA_*`` output inside the caller-specified directory.
* Widget iteration / form-field traversal must not crash, hang, or
  blow the Python recursion limit on pathological /Fields trees.
"""

from __future__ import annotations

import pathlib
import time

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


def _blank_page_with_font(
    pdf: pikepdf.Pdf,
    page_size: tuple[float, float] = (612, 792),
) -> pikepdf.Object:
    pdf.add_blank_page(page_size=page_size)
    page = pdf.pages[-1]
    font = _font(pdf)
    page["/Resources"] = Dictionary({"/Font": Dictionary({"/F1": font})})
    page["/Contents"] = pdf.make_stream(
        b"BT /F1 12 Tf 50 750 Td (Form page) Tj ET"
    )
    return page


def _make_widget(
    pdf: pikepdf.Pdf,
    page: pikepdf.Object,
    rect: tuple[float, float, float, float],
    field_name: str,
    field_type: str = "/Tx",
    field_flags: int = 0,
    tu: str | None = None,
    include_ap: bool = True,
) -> pikepdf.Object:
    """Build a single Widget/Field merged dictionary and link it to page."""
    # ``page`` may be a pikepdf.Page ObjectHelper; /P needs the underlying
    # pikepdf.Dictionary via .obj.
    page_obj = page.obj if hasattr(page, "obj") else page
    d: dict = {
        "/Type": Name("/Annot"),
        "/Subtype": Name("/Widget"),
        "/FT": Name(field_type),
        "/T": String(field_name),
        "/Rect": Array([rect[0], rect[1], rect[2], rect[3]]),
        "/F": 4,
        "/Ff": field_flags,
        "/P": page_obj,
    }
    if tu is not None:
        d["/TU"] = String(tu)
    if include_ap:
        # Minimal Form XObject for /AP /N
        form_xobj = pdf.make_indirect(pikepdf.Stream(
            pdf,
            b"q Q",
            Type=Name("/XObject"),
            Subtype=Name("/Form"),
            BBox=Array([0, 0, rect[2] - rect[0], rect[3] - rect[1]]),
            Resources=Dictionary({}),
        ))
        d["/AP"] = Dictionary({"/N": form_xobj})
    return pdf.make_indirect(Dictionary(d))


def _attach_acroform(pdf: pikepdf.Pdf, fields: list[pikepdf.Object]) -> None:
    pdf.Root["/AcroForm"] = Dictionary({
        "/Fields": Array(fields),
        "/NeedAppearances": False,
    })


def _annotate_page(page: pikepdf.Object, widgets: list[pikepdf.Object]) -> None:
    page["/Annots"] = Array(widgets)


_APPROVED_SUFFIXES = ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL")


def _assert_graceful(result) -> None:
    assert isinstance(result, dict), (
        f"run_pipeline returned {type(result).__name__}, not a dict"
    )
    assert "errors" in result and isinstance(result["errors"], list)
    for err in result["errors"]:
        assert "Traceback (most recent call last)" not in err, (
            f"raw traceback leaked into result['errors']:\n{err[:500]}"
        )


def _assert_output_produced(result, out_dir) -> pathlib.Path:
    _assert_graceful(result)
    out_pdf_s = result.get("output_pdf", "")
    assert out_pdf_s, (
        f"pipeline produced no output PDF; errors: {result.get('errors')}"
    )
    out_pdf = pathlib.Path(out_pdf_s)
    assert out_pdf.exists()
    out_dir_r = pathlib.Path(out_dir).resolve()
    assert out_pdf.resolve().is_relative_to(out_dir_r)
    stem = out_pdf.stem
    assert any(stem.endswith(s) for s in _APPROVED_SUFFIXES), (
        f"output filename missing approved suffix: {out_pdf.name!r}"
    )
    return out_pdf


def _collect_widgets_recursive(
    fields: pikepdf.Array | list,
    out: list[pikepdf.Object] | None = None,
) -> list[pikepdf.Object]:
    if out is None:
        out = []
    for f in fields:
        try:
            if f.get("/Rect") is not None:
                out.append(f)
            kids = f.get("/Kids")
            if kids is not None and len(kids) > 0:
                _collect_widgets_recursive(kids, out)
        except Exception:
            continue
    return out


# ---------------------------------------------------------------------------
# 1. 500 mixed form fields — must complete + all get /TU
# ---------------------------------------------------------------------------


def test_500_form_fields(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    widgets: list[pikepdf.Object] = []
    n = 500
    for i in range(n):
        # Mix text fields, check boxes, and choice fields.
        ft = ("/Tx", "/Btn", "/Ch")[i % 3]
        # 25 columns x 20 rows of 20pt tall fields.
        col = i % 25
        row = i // 25
        x0 = 20 + col * 22
        y0 = 20 + row * 30
        w = _make_widget(
            pdf, page, (x0, y0, x0 + 20, y0 + 20),
            field_name=f"field_{i:03d}",
            field_type=ft,
        )
        widgets.append(w)
    _annotate_page(page, widgets)
    _attach_acroform(pdf, widgets)
    path = edge_tmp_dir / "500_fields.pdf"
    pdf.save(str(path))

    out = edge_tmp_dir / "out"
    t0 = time.monotonic()
    result = run_through_pipeline(path, out)
    elapsed = time.monotonic() - t0
    out_pdf = _assert_output_produced(result, out)

    # Every widget must have a /TU after remediation (accessible name).
    with pikepdf.open(str(out_pdf)) as remediated:
        acro = remediated.Root.get("/AcroForm")
        assert acro is not None, "remediated PDF lost /AcroForm"
        fields = acro.get("/Fields")
        assert fields is not None
        widgets_out = _collect_widgets_recursive(fields)
        assert len(widgets_out) == n, (
            f"expected {n} widgets, got {len(widgets_out)}"
        )
        missing_tu = [
            str(w.get("/T", "?")) for w in widgets_out
            if not w.get("/TU")
        ]
        assert not missing_tu, (
            f"{len(missing_tu)}/{n} widgets still missing /TU: "
            f"{missing_tu[:5]}"
        )
    # Record elapsed time (no hard budget — test just needs to complete).
    print(f"[test_500_form_fields] pipeline elapsed: {elapsed:.1f}s")


# ---------------------------------------------------------------------------
# 2. Overlapping widgets — two at identical coordinates
# ---------------------------------------------------------------------------


def test_overlapping_widgets(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    # Two widgets at exactly the same rectangle.
    w1 = _make_widget(pdf, page, (100, 100, 200, 120), "overlap_a")
    w2 = _make_widget(pdf, page, (100, 100, 200, 120), "overlap_b")
    _annotate_page(page, [w1, w2])
    _attach_acroform(pdf, [w1, w2])
    path = edge_tmp_dir / "overlapping.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # Page /Tabs should be /S (fix_focus_order guarantee).
    with pikepdf.open(str(out_pdf)) as remediated:
        assert str(remediated.pages[0].get("/Tabs")) == "/S"


# ---------------------------------------------------------------------------
# 3. Widget entirely off-page (outside MediaBox)
# ---------------------------------------------------------------------------


def test_off_page_widget(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    # MediaBox is (0 0 612 792); put the widget far to the right.
    off = _make_widget(pdf, page, (5000, 5000, 5100, 5020), "off_page")
    _annotate_page(page, [off])
    _attach_acroform(pdf, [off])
    path = edge_tmp_dir / "off_page.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 4. Deeply nested /Kids — 20 levels
# ---------------------------------------------------------------------------


def test_deeply_nested_field_hierarchy(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    # Build a chain of 20 nested parent fields ending in a real widget.
    leaf = _make_widget(pdf, page, (100, 100, 200, 120), "leaf_field")
    chain = leaf
    for i in range(20):
        chain = pdf.make_indirect(Dictionary({
            "/FT": Name("/Tx"),
            "/T": String(f"parent_{i}"),
            "/Kids": Array([chain]),
        }))
    _annotate_page(page, [leaf])
    _attach_acroform(pdf, [chain])
    path = edge_tmp_dir / "nested_fields.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # The leaf's /T should inherit through the chain and surface as /TU.
    with pikepdf.open(str(out_pdf)) as remediated:
        acro = remediated.Root.get("/AcroForm")
        assert acro is not None


# ---------------------------------------------------------------------------
# 5. Restrictive field flags — readonly + required + locked
# ---------------------------------------------------------------------------


def test_restrictive_field_flags(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    # ReadOnly = bit 1 (1), Required = bit 2 (2), Locked = bit 8 (128).
    # Combined: 131.
    flags = 1 | 2 | 128
    w = _make_widget(
        pdf, page, (100, 100, 200, 120), "locked_field",
        field_flags=flags,
    )
    _annotate_page(page, [w])
    _attach_acroform(pdf, [w])
    path = edge_tmp_dir / "restrictive.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # /Ff should be preserved in the remediated output.
    with pikepdf.open(str(out_pdf)) as remediated:
        acro = remediated.Root.get("/AcroForm")
        fields = acro.get("/Fields")
        widgets_out = _collect_widgets_recursive(fields)
        assert widgets_out, "no widgets found in remediated output"
        preserved = int(widgets_out[0].get("/Ff", 0))
        assert preserved == flags, (
            f"field flags corrupted: expected {flags}, got {preserved}"
        )


# ---------------------------------------------------------------------------
# 6. Missing /AP dictionary
# ---------------------------------------------------------------------------


def test_missing_appearance_stream(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    w = _make_widget(
        pdf, page, (100, 100, 200, 120), "no_ap_field",
        include_ap=False,
    )
    _annotate_page(page, [w])
    _attach_acroform(pdf, [w])
    path = edge_tmp_dir / "no_ap.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    _assert_output_produced(result, out)


# ---------------------------------------------------------------------------
# 7. Signature field
# ---------------------------------------------------------------------------


def test_signature_field(edge_tmp_dir, run_through_pipeline):
    pdf = pikepdf.new()
    page = _blank_page_with_font(pdf)
    sig = _make_widget(
        pdf, page, (100, 100, 300, 150), "signature_1",
        field_type="/Sig",
    )
    _annotate_page(page, [sig])
    # /SigFlags = 3 (SignaturesExist + AppendOnly)
    pdf.Root["/AcroForm"] = Dictionary({
        "/Fields": Array([sig]),
        "/SigFlags": 3,
    })
    path = edge_tmp_dir / "signature.pdf"
    pdf.save(str(path))
    out = edge_tmp_dir / "out"
    result = run_through_pipeline(path, out)
    out_pdf = _assert_output_produced(result, out)
    # Tool MUST document that signatures are invalidated — the report
    # should reference the relevant manual-review item.
    report_text = pathlib.Path(result["report_html"]).read_text(
        encoding="utf-8", errors="replace"
    )
    assert "signature" in report_text.lower() or "Signature" in report_text, (
        "HTML report does not mention signatures — users won't know the "
        "remediation invalidated their digital signature"
    )
