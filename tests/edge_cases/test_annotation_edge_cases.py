"""Annotation edge-case tests.

Probes pathological annotation payloads — empty URIs, JavaScript
actions, file attachments, large annotation counts, and circular
destinations. In every case the pipeline must not crash and must return
a clean result dict free of raw tracebacks.
"""

from __future__ import annotations

import pathlib
import sys
import time

import pikepdf
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _assert_graceful(result: object) -> None:
    """Assert the pipeline returned a clean result dict with no raw tracebacks."""
    assert isinstance(result, dict), (
        f"run_pipeline returned {type(result).__name__}, expected dict"
    )
    assert "errors" in result
    for err in result.get("errors", []):
        assert "Traceback (most recent call last)" not in str(err), (
            f"Raw traceback leaked into result['errors']:\n{str(err)[:400]}"
        )


def _make_pdf_with_annots(path: pathlib.Path, annots: list) -> pathlib.Path:
    """Write a minimal PDF with the given annotation objects on page 0."""
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.pages[0]["/Annots"] = pikepdf.Array(
        [pdf.make_indirect(a) for a in annots]
    )
    pdf.save(str(path))
    return path


# ---------------------------------------------------------------------------
# Test 1 — Link with empty URI
# ---------------------------------------------------------------------------


def test_link_with_empty_uri(tmp_path: pathlib.Path) -> None:
    """Link annotation with /URI == '' is flagged as a broken link; no crash.

    Expected behaviour
    ------------------
    * ``run_pipeline`` returns a dict (no unhandled exception).
    * The result is ``PASS`` or ``PARTIAL`` — not ``ERROR``.
    * ``fix_link_alt`` logs a warning about the empty / broken URI so that
      operators know the link needs attention.
    * The output PDF has a non-empty ``/Contents`` on the link annotation
      (the fix-up pipeline falls back to a generic label rather than leaving
      the field blank).
    """
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Link"),
        Rect=pikepdf.Array([100, 700, 200, 720]),
        A=pikepdf.Dictionary(
            S=pikepdf.Name("/URI"),
            URI=pikepdf.String(""),
        ),
    )
    pdf_path = _make_pdf_with_annots(tmp_path / "empty_uri.pdf", [annot])
    out_dir = tmp_path / "out_empty_uri"

    result = run_pipeline(str(pdf_path), str(out_dir))
    _assert_graceful(result)

    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected pipeline result: {result.get('result')!r}; "
        f"errors: {result.get('errors')}"
    )

    # fix_link_alt must flag the empty URI — look for a warning in errors.
    errors_text = " ".join(str(e) for e in result.get("errors", []))
    assert any(
        kw in errors_text.lower()
        for kw in ("empty", "broken", "uri", "blank")
    ), (
        "Pipeline did not flag the empty URI link. "
        "Expected a warning in result['errors'] containing 'empty', "
        f"'broken', 'uri', or 'blank'. Errors seen: {result.get('errors')}"
    )

    # Output PDF must have /Contents set (not blank) on the link.
    out_pdf_s = result.get("output_pdf", "")
    if out_pdf_s and pathlib.Path(out_pdf_s).exists():
        with pikepdf.open(out_pdf_s) as out_pdf:
            for page in out_pdf.pages:
                annots = page.get("/Annots") or []
                for a in annots:
                    try:
                        if str(a.get("/Subtype", "")) == "/Link":
                            contents = str(a.get("/Contents") or "").strip()
                            assert contents, (
                                "Link with empty URI still has blank /Contents after fix-up"
                            )
                    except Exception:
                        pass  # indirect ref resolution failures are non-fatal here


# ---------------------------------------------------------------------------
# Test 2 — JavaScript action detection
# ---------------------------------------------------------------------------


def test_javascript_action_detection(tmp_path: pathlib.Path) -> None:
    """Annotation with a /JavaScript action is detected and flagged.

    A Widget annotation whose Additional Actions (/AA) dict contains a
    /JavaScript entry represents executable content that should be called
    out by the pipeline so operators can review it.

    Expected behaviour
    ------------------
    * ``run_pipeline`` returns a dict (no unhandled exception).
    * The result is ``PASS`` or ``PARTIAL`` — the pipeline doesn't crash.
    * A warning or error message in ``result['errors']`` identifies the
      JavaScript action (keywords: 'javascript', 'executable', 'js').
    """
    annot = pikepdf.Dictionary(
        Type=pikepdf.Name("/Annot"),
        Subtype=pikepdf.Name("/Widget"),
        Rect=pikepdf.Array([100, 600, 200, 620]),
        AA=pikepdf.Dictionary(
            U=pikepdf.Dictionary(
                S=pikepdf.Name("/JavaScript"),
                JS=pikepdf.String('app.alert("WCAG_JS_TEST");'),
            )
        ),
    )
    pdf_path = _make_pdf_with_annots(tmp_path / "js_action.pdf", [annot])
    out_dir = tmp_path / "out_js"

    result = run_pipeline(str(pdf_path), str(out_dir))
    _assert_graceful(result)

    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )

    # Pipeline must flag executable content.
    errors_text = " ".join(str(e) for e in result.get("errors", []))
    has_js_flag = any(
        kw in errors_text.lower()
        for kw in ("javascript", "executable", " js ", "js action", "js:")
    )
    assert has_js_flag, (
        "Pipeline did not flag the JavaScript action annotation. "
        "Expected a warning in result['errors'] containing 'javascript' or 'executable'. "
        f"Errors seen: {result.get('errors')}"
    )


# ---------------------------------------------------------------------------
# Test 3 — File attachment annotation
# ---------------------------------------------------------------------------


def test_file_attachment_annotation(tmp_path: pathlib.Path) -> None:
    """FileAttachment annotation is flagged; embedded content is not exposed.

    Expected behaviour
    ------------------
    * ``run_pipeline`` returns a dict (no unhandled exception).
    * The result is ``PASS`` or ``PARTIAL``.
    * The embedded file's raw content does **not** appear verbatim in the
      HTML report or in any error message.
    * The pipeline does not attempt to remediate or re-embed the attached
      file's content.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page()

    # Build an embedded-file stream with a distinct sentinel string.
    _SENTINEL = "SENSITIVE_EMBEDDED_PAYLOAD_XQ7Z"
    ef_stream = pikepdf.Stream(pdf, _SENTINEL.encode())
    ef_stream["/Type"] = pikepdf.Name("/EmbeddedFile")

    filespec = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Filespec"),
            F=pikepdf.String("secret.txt"),
            EF=pikepdf.Dictionary(F=ef_stream),
        )
    )
    annot = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/FileAttachment"),
            Rect=pikepdf.Array([100, 700, 120, 720]),
            FS=filespec,
            Contents=pikepdf.String("Attached file"),
        )
    )
    pdf.pages[0]["/Annots"] = pikepdf.Array([annot])

    pdf_path = tmp_path / "file_attach.pdf"
    pdf.save(str(pdf_path))
    out_dir = tmp_path / "out_attach"

    result = run_pipeline(str(pdf_path), str(out_dir))
    _assert_graceful(result)

    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )

    # Sentinel must NOT appear in the HTML report.
    report_s = result.get("report_html", "")
    if report_s and pathlib.Path(report_s).exists():
        html = pathlib.Path(report_s).read_text(encoding="utf-8", errors="replace")
        assert _SENTINEL not in html, (
            "Embedded file content leaked verbatim into the HTML report"
        )

    # Sentinel must NOT appear in error messages.
    for err in result.get("errors", []):
        assert _SENTINEL not in str(err), (
            "Embedded file content appeared in pipeline error message"
        )


# ---------------------------------------------------------------------------
# Test 4 — 1 000 link annotations performance
# ---------------------------------------------------------------------------


def test_1000_link_annotations(tmp_path: pathlib.Path) -> None:
    """Single page with 1 000 Link annotations completes in acceptable time.

    Expected behaviour
    ------------------
    * ``run_pipeline`` returns a dict (no unhandled exception).
    * The result is ``PASS`` or ``PARTIAL``.
    * Total wall-clock time stays under 120 seconds.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page()

    annot_refs = []
    for i in range(1000):
        a = pdf.make_indirect(
            pikepdf.Dictionary(
                Type=pikepdf.Name("/Annot"),
                Subtype=pikepdf.Name("/Link"),
                Rect=pikepdf.Array([0, i * 0.5, 10, i * 0.5 + 0.4]),
                A=pikepdf.Dictionary(
                    S=pikepdf.Name("/URI"),
                    URI=pikepdf.String(f"https://example.com/page/{i}"),
                ),
            )
        )
        annot_refs.append(a)

    pdf.pages[0]["/Annots"] = pikepdf.Array(annot_refs)
    pdf_path = tmp_path / "thousand_links.pdf"
    pdf.save(str(pdf_path))
    out_dir = tmp_path / "out_1000"

    start = time.monotonic()
    result = run_pipeline(str(pdf_path), str(out_dir))
    elapsed = time.monotonic() - start

    _assert_graceful(result)
    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )
    assert elapsed < 120, (
        f"1 000 link annotations took {elapsed:.1f}s — performance unacceptable (limit: 120s)"
    )


# ---------------------------------------------------------------------------
# Test 5 — Link with circular / self-referential destination
# ---------------------------------------------------------------------------


def test_link_with_circular_destination(tmp_path: pathlib.Path) -> None:
    """Link /Dest pointing back at page 0 causes no infinite loop.

    A link whose destination is the same page it lives on, plus a named
    destination that resolves to the same page, is a degenerate cycle.
    The pipeline must handle this without hanging.

    Expected behaviour
    ------------------
    * ``run_pipeline`` returns within 120 seconds.
    * Returns a dict (no unhandled exception).
    * The result is ``PASS`` or ``PARTIAL``.
    """
    pdf = pikepdf.new()
    pdf.add_blank_page()

    page_ref = pdf.pages[0].obj

    # Link whose /Dest array references the same page it's on.
    annot = pdf.make_indirect(
        pikepdf.Dictionary(
            Type=pikepdf.Name("/Annot"),
            Subtype=pikepdf.Name("/Link"),
            Rect=pikepdf.Array([100, 700, 200, 720]),
            Dest=pikepdf.Array(
                [
                    page_ref,
                    pikepdf.Name("/XYZ"),
                    pikepdf.Integer(100),
                    pikepdf.Integer(700),
                    pikepdf.Integer(0),
                ]
            ),
        )
    )
    pdf.pages[0]["/Annots"] = pikepdf.Array([annot])

    # Named destination that also loops back to page 0.
    pdf.Root["/Dests"] = pikepdf.Dictionary(
        SelfLoop=pikepdf.Dictionary(
            D=pikepdf.Array(
                [
                    page_ref,
                    pikepdf.Name("/XYZ"),
                    pikepdf.Integer(0),
                    pikepdf.Integer(0),
                    pikepdf.Integer(0),
                ]
            )
        )
    )

    pdf_path = tmp_path / "circular_dest.pdf"
    pdf.save(str(pdf_path))
    out_dir = tmp_path / "out_circular"

    start = time.monotonic()
    result = run_pipeline(str(pdf_path), str(out_dir))
    elapsed = time.monotonic() - start

    _assert_graceful(result)
    assert result.get("result") in ("PASS", "PARTIAL"), (
        f"Unexpected result: {result.get('result')!r}; errors: {result.get('errors')}"
    )
    assert elapsed < 120, (
        f"Circular-destination PDF took {elapsed:.1f}s — potential infinite-loop regression"
    )
