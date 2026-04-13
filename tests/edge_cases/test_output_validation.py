"""Output validation edge-case tests.

Verifies that the artefacts produced by ``run_pipeline`` and
``process_files_core`` are structurally valid, stable under repeated
processing, and safe to share (no unescaped markup, no directory
traversal in archives, parseable JSON data block).
"""

from __future__ import annotations

import json
import pathlib
import re
import sys
import zipfile

import pikepdf
import pytest

_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from pipeline import run_pipeline


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_valid_pdf(
    path: pathlib.Path,
    title: str = "Output Validation Test",
    author: str = "",
    producer: str = "",
) -> pathlib.Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = title
    if author:
        pdf.docinfo["/Author"] = author
    if producer:
        pdf.docinfo["/Producer"] = producer
    pdf.save(str(path))
    return path


def _assert_graceful(result: object) -> None:
    assert isinstance(result, dict)
    assert "errors" in result
    for err in result.get("errors", []):
        assert "Traceback (most recent call last)" not in str(err), (
            f"Raw traceback leaked: {str(err)[:300]}"
        )


# Regex that pulls the JSON payload out of the embedded <script> block.
_JSON_BLOCK_RE = re.compile(
    r'<script[^>]*id="wcag-audit-data"[^>]*>\s*(.*?)\s*</script>',
    re.DOTALL,
)


def _extract_embedded_json(html: str) -> dict:
    match = _JSON_BLOCK_RE.search(html)
    assert match is not None, "Embedded JSON data block not found in HTML report"
    payload = match.group(1)
    return json.loads(payload)


# ---------------------------------------------------------------------------
# Test 1 — Round-trip stability across 3 passes
# ---------------------------------------------------------------------------


def test_round_trip_stability(tmp_path: pathlib.Path) -> None:
    """Process a PDF, then its output, then that output. Results stay stable.

    The 3 passes must produce the same PASS/FAIL pattern — no progressive
    degradation, no spurious extra tags on each re-run. File size may grow
    slightly on the first pass (tags are added) but must stabilise by the
    second.
    """
    src = _make_valid_pdf(tmp_path / "src.pdf", title="Round Trip Test")

    out1 = tmp_path / "out1"
    res1 = run_pipeline(str(src), str(out1))
    _assert_graceful(res1)
    assert res1.get("result") in ("PASS", "PARTIAL")

    out2 = tmp_path / "out2"
    res2 = run_pipeline(res1["output_pdf"], str(out2))
    _assert_graceful(res2)
    assert res2.get("result") in ("PASS", "PARTIAL")

    out3 = tmp_path / "out3"
    res3 = run_pipeline(res2["output_pdf"], str(out3))
    _assert_graceful(res3)
    assert res3.get("result") in ("PASS", "PARTIAL")

    # Same overall verdict across all three passes.
    assert res1["result"] == res2["result"] == res3["result"], (
        f"Overall verdict drifted: pass1={res1['result']!r} "
        f"pass2={res2['result']!r} pass3={res3['result']!r}"
    )

    # Every checkpoint status must be identical across the three passes.
    statuses_by_pass = []
    for res in (res1, res2, res3):
        sm = {c["id"]: c["status"] for c in res["checkpoints"]}
        statuses_by_pass.append(sm)
    s1, s2, s3 = statuses_by_pass
    drift = [
        cid
        for cid in s1
        if s1.get(cid) != s2.get(cid) or s2.get(cid) != s3.get(cid)
    ]
    assert not drift, (
        f"Checkpoint statuses drifted across repeat processing: {drift}. "
        f"pass1 vs pass2 vs pass3 (for drifted): "
        + ", ".join(
            f"{cid}=[{s1.get(cid)},{s2.get(cid)},{s3.get(cid)}]" for cid in drift
        )
    )

    # Struct-tree element count must stabilise — no unbounded growth
    # from re-tagging the same content on each pass.
    def _count_struct_elements(pdf_path: str) -> int:
        n = 0
        try:
            with pikepdf.open(pdf_path) as pdf:
                root = pdf.Root.get("/StructTreeRoot")
                if root is None:
                    return 0
                stack = [root]
                seen: set[int] = set()
                while stack:
                    node = stack.pop()
                    try:
                        oid = int(node.objgen[0]) if hasattr(node, "objgen") else id(node)
                    except Exception:
                        oid = id(node)
                    if oid in seen:
                        continue
                    seen.add(oid)
                    n += 1
                    try:
                        kids = node.get("/K")
                    except Exception:
                        kids = None
                    if kids is None:
                        continue
                    if isinstance(kids, pikepdf.Array):
                        for k in kids:
                            if isinstance(k, pikepdf.Dictionary):
                                stack.append(k)
                    elif isinstance(kids, pikepdf.Dictionary):
                        stack.append(kids)
        except Exception:
            return 0
        return n

    n1 = _count_struct_elements(res1["output_pdf"])
    n2 = _count_struct_elements(res2["output_pdf"])
    n3 = _count_struct_elements(res3["output_pdf"])
    # Second and third passes must not keep adding new structure elements.
    assert n3 <= n2 + 2, (
        f"Struct tree kept growing across passes: pass1={n1} pass2={n2} pass3={n3}"
    )


# ---------------------------------------------------------------------------
# Test 2 — Output opens in all readers (pikepdf + PyMuPDF)
# ---------------------------------------------------------------------------


def test_output_opens_in_all_readers(tmp_path: pathlib.Path) -> None:
    """Remediated PDF opens cleanly in both pikepdf and PyMuPDF."""
    src = _make_valid_pdf(tmp_path / "reader_src.pdf", title="Reader Test")
    out = tmp_path / "reader_out"
    res = run_pipeline(str(src), str(out))
    _assert_graceful(res)
    assert res.get("result") in ("PASS", "PARTIAL")

    out_pdf = res["output_pdf"]
    assert pathlib.Path(out_pdf).exists()

    # ---- pikepdf: must open, have a page tree, and save without rewriting errors
    with pikepdf.open(out_pdf) as pdf:
        assert len(pdf.pages) >= 1
        # Root and page tree must be non-null.
        assert pdf.Root is not None
        assert "/Pages" in pdf.Root
        # Walk each page to catch any dangling references.
        for page in pdf.pages:
            _ = page.get("/MediaBox")
            _ = page.get("/Resources")
            # Walking /Contents forces resolution of any indirect refs.
            contents = page.get("/Contents")
            if contents is not None:
                try:
                    _ = bytes(contents.read_bytes()) if hasattr(contents, "read_bytes") else None
                except Exception:
                    pass

    # ---- PyMuPDF: must open, parse each page, and extract text
    import fitz  # PyMuPDF

    doc = fitz.open(out_pdf)
    try:
        assert doc.page_count >= 1, "PyMuPDF reported zero pages"
        for i in range(doc.page_count):
            page = doc.load_page(i)
            # Text extraction must not raise.
            _ = page.get_text("text")
            # Rect must be valid and non-empty.
            rect = page.rect
            assert rect.width > 0 and rect.height > 0, (
                f"Page {i} has degenerate MediaBox: {rect}"
            )
    finally:
        doc.close()


# ---------------------------------------------------------------------------
# Test 3 — HTML report escapes executable markup in /Title
# ---------------------------------------------------------------------------


def test_html_report_escapes_markup(tmp_path: pathlib.Path) -> None:
    """A malicious <script> payload in /Title appears only escaped in the HTML."""
    _PAYLOAD = "<script>alert('test')</script>"
    src = _make_valid_pdf(tmp_path / "xss.pdf", title=_PAYLOAD)
    out = tmp_path / "xss_out"
    res = run_pipeline(str(src), str(out))
    _assert_graceful(res)
    assert res.get("result") in ("PASS", "PARTIAL")

    report_path = pathlib.Path(res["report_html"])
    assert report_path.exists()
    html = report_path.read_text(encoding="utf-8")

    # The literal payload must NOT appear anywhere in the HTML — not in
    # the body, not inside the JSON data block, not in the <title> tag.
    assert _PAYLOAD not in html, (
        "XSS REGRESSION — the literal <script>alert('test')</script> payload "
        "appears unescaped in the HTML report."
    )

    # No loose </script> that would break out of the embedded JSON block.
    # Count script tags: the only </script> should correspond to the
    # embedded JSON block's own closer.
    script_closes = html.lower().count("</script>")
    script_opens = html.lower().count("<script")
    assert script_closes == script_opens, (
        f"Mismatched <script>/</script> tags: {script_opens} opens vs "
        f"{script_closes} closes — attacker may have broken out of the data block."
    )

    # An escaped form of the payload should be present in at least one
    # location (the visible title rendering).
    assert ("&lt;script&gt;" in html) or ("\\u003cscript" in html), (
        "Expected either HTML-escaped or unicode-escaped form of the payload "
        "to survive in the report; found neither."
    )


# ---------------------------------------------------------------------------
# Test 4 — HTML report special characters (& < > " ' emoji)
# ---------------------------------------------------------------------------


def test_html_report_special_characters(tmp_path: pathlib.Path) -> None:
    """Metadata containing HTML-dangerous chars and emoji render correctly."""
    _TITLE = "Alpha & <em>Beta</em> \"Gamma\" 'Delta' \U0001F389 \u00e9"
    src = _make_valid_pdf(tmp_path / "special.pdf", title=_TITLE)
    out = tmp_path / "special_out"
    res = run_pipeline(str(src), str(out))
    _assert_graceful(res)
    assert res.get("result") in ("PASS", "PARTIAL")

    report_path = pathlib.Path(res["report_html"])
    html = report_path.read_text(encoding="utf-8")

    # &, <, > must be HTML-escaped in the visible body.
    assert "&amp;" in html, "Ampersand not HTML-escaped in report"
    assert "&lt;em&gt;" in html, "<em> tag not HTML-escaped in report"

    # Raw literal <em>Beta</em> must not appear — that would indicate
    # the title rendered unescaped in the HTML body.
    assert "<em>Beta</em>" not in html, "Title rendered unescaped in HTML body"

    # Emoji (a single non-ASCII codepoint) must survive verbatim.
    assert "\U0001F389" in html, "Emoji lost during report rendering"
    # Latin-1 non-ASCII character survives.
    assert "\u00e9" in html, "Accented character lost during report rendering"

    # The file must be valid UTF-8.
    assert report_path.read_bytes().decode("utf-8")  # raises on invalid UTF-8


# ---------------------------------------------------------------------------
# Test 5 — JSON data block is valid, complete, and fully-fielded
# ---------------------------------------------------------------------------


def test_json_data_block_validity(tmp_path: pathlib.Path) -> None:
    """The embedded JSON block parses and every checkpoint has the full schema."""
    src = _make_valid_pdf(tmp_path / "json_block.pdf", title="JSON Test")
    out = tmp_path / "json_out"
    res = run_pipeline(str(src), str(out))
    _assert_graceful(res)
    assert res.get("result") in ("PASS", "PARTIAL")

    html = pathlib.Path(res["report_html"]).read_text(encoding="utf-8")

    # Extract and parse — this is the end-to-end contract.
    data = _extract_embedded_json(html)

    assert isinstance(data, dict)
    for key in ("file", "title", "timestamp", "overall", "checkpoints"):
        assert key in data, f"JSON data block missing top-level key: {key!r}"

    checkpoints = data["checkpoints"]
    assert isinstance(checkpoints, list) and checkpoints, (
        "checkpoints list is missing or empty"
    )

    # All 47 canonical checkpoint IDs must appear.
    ids = {c.get("id") for c in checkpoints}
    expected = {f"C-{i:02d}" for i in range(1, 48)}
    missing = expected - ids
    assert not missing, f"Missing checkpoint IDs in JSON data block: {sorted(missing)}"

    # Every checkpoint must carry the full schema.
    required_fields = {"id", "name", "status", "confidence", "details"}
    for c in checkpoints:
        missing_fields = required_fields - set(c.keys())
        assert not missing_fields, (
            f"Checkpoint {c.get('id')!r} missing required field(s): "
            f"{sorted(missing_fields)}. Actual keys: {sorted(c.keys())}"
        )
        # Sanity: confidence is numeric in [0, 1]; status is a known value.
        conf = c["confidence"]
        assert isinstance(conf, (int, float)) and 0.0 <= float(conf) <= 1.0, (
            f"Checkpoint {c['id']} confidence out of range: {conf!r}"
        )
        assert c["status"] in {
            "PASS",
            "FAIL",
            "NOT_APPLICABLE",
            "INDETERMINATE",
            "MANUAL_REVIEW",
            "WARN",
        }, f"Checkpoint {c['id']} has unexpected status: {c['status']!r}"


# ---------------------------------------------------------------------------
# Test 6 — ZIP archive integrity
# ---------------------------------------------------------------------------


def test_zip_archive_integrity(tmp_path: pathlib.Path) -> None:
    """Batch ZIP contains matched PDF/HTML pairs; no traversal; no orphans."""
    # Build 3 distinct source PDFs.
    inputs = []
    for i in range(3):
        p = _make_valid_pdf(
            tmp_path / "src" / f"file_{i}.pdf",
            title=f"Archive Integrity {i}",
        )
        inputs.append(str(p))

    from app import process_files_core  # noqa: PLC0415

    work = tmp_path / "work"
    _, zip_path, err_log = process_files_core(inputs, work_root=work)
    assert zip_path is not None, (
        f"process_files_core did not produce a ZIP. errors={err_log}"
    )
    zp = pathlib.Path(zip_path)
    assert zp.exists() and zp.is_file()

    with zipfile.ZipFile(zip_path) as zf:
        # testzip() returns None if archive is OK, otherwise name of first bad file.
        bad = zf.testzip()
        assert bad is None, f"ZIP archive is corrupt: bad file {bad!r}"

        entries = zf.namelist()
        assert entries, "ZIP archive contains no entries"

        # No directory-escape paths: absolute paths, parent refs, or root-relative.
        for name in entries:
            assert not name.startswith("/"), (
                f"ZIP entry has absolute path: {name!r}"
            )
            assert not name.startswith("\\"), (
                f"ZIP entry has absolute path: {name!r}"
            )
            assert ".." not in name.split("/"), (
                f"ZIP entry contains parent reference: {name!r}"
            )
            assert ":" not in name, (
                f"ZIP entry contains drive separator: {name!r}"
            )
            # Flat entries only — no nested subdirectories.
            assert "/" not in name and "\\" not in name, (
                f"ZIP entry has directory prefix (expected flat layout): {name!r}"
            )

        pdf_entries = {e for e in entries if e.lower().endswith(".pdf")}
        html_entries = {e for e in entries if e.lower().endswith(".html")}
        other_entries = set(entries) - pdf_entries - html_entries
        assert not other_entries, (
            f"ZIP archive has orphaned entries: {sorted(other_entries)}"
        )

        # Every input file should have produced exactly one PDF entry
        # and exactly one HTML entry.
        assert len(pdf_entries) == len(inputs), (
            f"Expected {len(inputs)} PDF entries, got {len(pdf_entries)}: "
            f"{sorted(pdf_entries)}"
        )
        assert len(html_entries) == len(inputs), (
            f"Expected {len(inputs)} HTML entries, got {len(html_entries)}: "
            f"{sorted(html_entries)}"
        )

        # Every PDF should have a matching HTML with the same stem.
        pdf_stems = {pathlib.PurePosixPath(e).stem for e in pdf_entries}
        html_stems = {
            pathlib.PurePosixPath(e).stem.removesuffix("_report")
            for e in html_entries
        }
        unmatched = pdf_stems.symmetric_difference(html_stems)
        assert not unmatched, (
            f"Unmatched PDF/HTML stems in ZIP: {sorted(unmatched)}"
        )
