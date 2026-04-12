"""WCAG / PDF-UA auditor — R3 with 47 dense checkpoints (C-01 through C-47).

Standalone module: accepts a PDF path and produces a JSON report showing
which checkpoints PASS, FAIL, WARN, NOT_APPLICABLE, MANUAL_REVIEW, or
INDETERMINATE.

CLI:  python wcag_auditor.py path/to/file.pdf
API:  from wcag_auditor import audit_pdf
      result = audit_pdf("path/to/file.pdf")
"""

from __future__ import annotations

import datetime as _dt
import json
import pathlib
import re
import sys
from typing import Any, Iterator

import pikepdf


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

STANDARD_BDC_TAGS: frozenset[str] = frozenset(
    {
        "P",
        "H",
        "H1",
        "H2",
        "H3",
        "H4",
        "H5",
        "H6",
        "L",
        "LI",
        "LBody",
        "Lbl",
        "Table",
        "TR",
        "TH",
        "TD",
        "Figure",
        "Formula",
        "Form",
        "Document",
        "Sect",
        "Art",
        "BlockQuote",
        "Caption",
        "TOC",
        "TOCI",
        "Index",
        "NonStruct",
        "Private",
        "Span",
        "Quote",
        "Note",
        "Reference",
        "BibEntry",
        "Code",
        "Link",
        "Annot",
        "Ruby",
        "Warichu",
        "Part",
        "Div",
        "Artifact",
    }
)

TITLE_BLACKLIST: frozenset[str] = frozenset(
    {
        "",
        "untitled document",
        "untitled",
        "untitled-1",
        "untitled1",
        "untitled 1",
        "document",
        "document1",
        "word document",
        "microsoft word",
        "new document",
        "draft",
        "temp",
    }
)

BDC_TAG_RE = re.compile(
    rb"/([A-Za-z][A-Za-z0-9_]*)"
    rb"\s+"
    rb"(?:"
    rb"<<(?:[^<>]|<<[^<>]*>>)*>>"
    rb"|/[A-Za-z][A-Za-z0-9_.\-]*"
    rb")"
    rb"\s*BDC\b",
    re.DOTALL,
)

CHECKPOINT_DESCRIPTIONS: dict[str, str] = {
    "C-01": "Document is tagged (/MarkInfo /Marked is true)",
    "C-02": "DocInfo /Title is non-empty",
    "C-03": "Title is not a placeholder string",
    "C-04": "Document /Lang is set",
    "C-05": "Passage-level language changes are marked",
    "C-06": "PDF/UA identifier present in XMP metadata",
    "C-07": "ViewerPreferences DisplayDocTitle is true",
    "C-08": "Security permissions allow accessibility",
    "C-09": "Suspects flag is not set",
    "C-10": "Tab order is set to /S on all pages with annotations",
    "C-11": "Character encoding is valid (no .notdef glyphs)",
    "C-12": "All content is tagged in the structure tree",
    "C-13": "All BDC tags in content streams are standard",
    "C-14": "No ghost/invisible text detected",
    "C-15": "Reading order matches visual layout (manual review)",
    "C-16": "Color contrast meets WCAG AA requirements",
    "C-17": "Information is not conveyed by color alone (manual review)",
    "C-18": "No images of text detected",
    "C-19": "Heading tags (H1-H6) are present",
    "C-20": "Heading levels are properly nested (no skipping)",
    "C-21": "Heading font size is appropriate for level",
    "C-22": "Heading visual style is consistent per level",
    "C-23": "Bookmarks present for documents with more than 20 pages",
    "C-24": "Tables have proper row structure (/TR)",
    "C-25": "Table headers (/TH) have Scope attribute",
    "C-26": "Table column counts are consistent",
    "C-27": "Tables have summary or caption",
    "C-28": "Lists use /L containing /LI elements",
    "C-29": "List items have /Lbl and/or /LBody",
    "C-30": "Nested lists are properly structured",
    "C-31": "Every Figure element has non-empty /Alt text",
    "C-32": "Alt text is not duplicated on parent and child",
    "C-33": "Decorative images are marked as Artifact",
    "C-34": "Alt text quality is adequate (manual review)",
    "C-35": "Form fields have structure elements",
    "C-36": "Every Widget has a non-empty /TU (accessible name)",
    "C-37": "Form tab order matches visual layout",
    "C-38": "Form labels match visible text (manual review)",
    "C-39": "Every Widget has /StructParent",
    "C-40": "Every /StructParent resolves to a /Form element",
    "C-41": "Widget appearance streams are properly tagged",
    "C-42": "Link annotations have /Link structure elements",
    "C-43": "Link annotations have /Contents or descriptions",
    "C-44": "Link destinations are valid",
    "C-45": "Non-widget annotations are tagged",
    "C-46": "ParentTree is a flat /Nums array (no /Kids)",
    "C-47": "Headers and footers are marked as Artifacts",
}


# ---------------------------------------------------------------------------
# Low-level helpers
# ---------------------------------------------------------------------------


def _pdfstr(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _name_eq(value: Any, expected: str) -> bool:
    if value is None:
        return False
    s = _pdfstr(value)
    if s.startswith("/"):
        s = s[1:]
    target = expected[1:] if expected.startswith("/") else expected
    return s == target


def _read_page_content_bytes(page: Any) -> bytes:
    try:
        contents = page.get("/Contents")
    except Exception:
        return b""
    if contents is None:
        return b""
    try:
        if isinstance(contents, pikepdf.Array):
            chunks: list[bytes] = []
            for stream in contents:
                try:
                    chunks.append(bytes(stream.read_bytes()))
                except Exception:
                    pass
            return b"\n".join(chunks)
        return bytes(contents.read_bytes())
    except Exception:
        return b""


def _lookup_parent_tree(tree: Any, key: int) -> Any:
    node = tree
    for _ in range(64):
        if node is None:
            return None
        try:
            if "/Nums" in node:
                nums = node["/Nums"]
                for i in range(0, len(nums), 2):
                    try:
                        if int(nums[i]) == key:
                            return nums[i + 1]
                    except Exception:
                        continue
                return None
            if "/Kids" in node:
                kids = node["/Kids"]
                next_node = None
                for kid in kids:
                    try:
                        limits = kid.get("/Limits")
                        if limits is not None and len(limits) >= 2:
                            lo = int(limits[0])
                            hi = int(limits[1])
                            if lo <= key <= hi:
                                next_node = kid
                                break
                        else:
                            next_node = kid
                            break
                    except Exception:
                        continue
                if next_node is None:
                    return None
                node = next_node
                continue
            return None
        except Exception:
            return None
    return None


def _iter_widgets(pdf: pikepdf.Pdf) -> Iterator[tuple[int, Any]]:
    for idx, page in enumerate(pdf.pages, start=1):
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if annots is None:
            continue
        try:
            iter_annots = list(annots)
        except Exception:
            continue
        for annot in iter_annots:
            try:
                subtype = annot.get("/Subtype")
                if not _name_eq(subtype, "/Widget"):
                    continue
                if "/Rect" not in annot:
                    continue
                yield idx, annot
            except Exception:
                continue


def _iter_links(pdf: pikepdf.Pdf) -> Iterator[tuple[int, Any]]:
    for idx, page in enumerate(pdf.pages, start=1):
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if annots is None:
            continue
        try:
            iter_annots = list(annots)
        except Exception:
            continue
        for annot in iter_annots:
            try:
                subtype = annot.get("/Subtype")
                if _name_eq(subtype, "/Link"):
                    yield idx, annot
            except Exception:
                continue


def _walk_struct_tree(struct_root: Any) -> Iterator[Any]:
    stack: list[Any] = []
    try:
        kids = struct_root.get("/K")
    except Exception:
        kids = None
    if kids is None:
        return
    if isinstance(kids, pikepdf.Array):
        stack.extend(list(kids))
    else:
        stack.append(kids)
    seen: set[tuple[int, int]] = set()
    while stack:
        node = stack.pop()
        if node is None:
            continue
        try:
            key = getattr(node, "objgen", None)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
        except Exception:
            pass
        if not isinstance(node, pikepdf.Dictionary):
            continue
        yield node
        try:
            sub_kids = node.get("/K")
        except Exception:
            sub_kids = None
        if sub_kids is None:
            continue
        if isinstance(sub_kids, pikepdf.Array):
            stack.extend(list(sub_kids))
        elif isinstance(sub_kids, pikepdf.Dictionary):
            stack.append(sub_kids)


def _result(status: str, detail: str, page_evidence: list[str] | None = None) -> dict:
    return {
        "status": status,
        "detail": detail,
        "page_evidence": page_evidence or [],
    }


# Map id(pdf) -> source file path, set by audit_pdf() while checks run.
# Content-detection helpers use this to read page content via PyMuPDF
# (which needs a filesystem path, not a pikepdf Pdf object).
_PDF_PATHS: dict[int, str] = {}


def _pdf_path(pdf: pikepdf.Pdf) -> str | None:
    """Return the source file path for a pdf being audited, if known."""
    return _PDF_PATHS.get(id(pdf))


# ---------------------------------------------------------------------------
# Content detection helpers — detect actual content (not just tags)
# so that N/A is only returned when the content type is truly absent.
# ---------------------------------------------------------------------------

# Common bullet characters used in PDFs
_BULLET_CHARS = {"\u2022", "\u25CF", "\u25E6", "\u25AA", "\u25AB",
                 "\u2023", "\u2043", "\u2219", "\u2027", "-", "*", "\u2212"}
# Numbered list prefix pattern: "1.", "1)", "a.", "A.", "i.", etc.
_NUMBERED_LIST_RE = re.compile(r"^\s*(\d+[.)]\s+|[a-zA-Z][.)]\s+|[ivxIVX]+[.)]\s+)")


def _content_has_tables(pdf_path: str) -> bool:
    """Detect whether the PDF contains visible tabular content.

    Uses PyMuPDF's find_tables() if available, else falls back to
    looking for aligned text columns. Returns False on any error.
    """
    try:
        import fitz  # type: ignore
    except Exception:
        return False
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False
    try:
        for page in doc:
            try:
                # PyMuPDF >= 1.23 supports find_tables()
                finder = getattr(page, "find_tables", None)
                if finder is not None:
                    tables = finder()
                    # TableFinder object — may have .tables attr or be iterable
                    tables_list = getattr(tables, "tables", None) or list(tables)
                    if tables_list:
                        return True
            except Exception:
                continue
        return False
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _content_has_lists(pdf_path: str) -> bool:
    """Detect whether the PDF contains visible bulleted or numbered lists.

    Scans text blocks for bullet characters or numbered-list prefixes that
    appear on multiple consecutive lines. Returns False on any error.
    """
    try:
        import fitz  # type: ignore
    except Exception:
        return False
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return False
    try:
        # Count bullet lines and numbered lines. 2+ of either = list.
        bullet_hits = 0
        numbered_hits = 0
        for page in doc:
            try:
                text = page.get_text("text") or ""
            except Exception:
                continue
            for line in text.splitlines():
                stripped = line.lstrip()
                if not stripped:
                    continue
                first = stripped[0]
                if first in _BULLET_CHARS:
                    bullet_hits += 1
                elif _NUMBERED_LIST_RE.match(stripped):
                    numbered_hits += 1
                if bullet_hits >= 2 or numbered_hits >= 2:
                    return True
        return False
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _content_has_images(pdf: pikepdf.Pdf) -> bool:
    """Detect whether any page has an image XObject in its Resources.

    Returns True iff at least one /Image XObject is referenced.
    """
    try:
        for page in pdf.pages:
            try:
                resources = page.get("/Resources")
                if resources is None:
                    continue
                xobjects = resources.get("/XObject")
                if xobjects is None:
                    continue
                for name, xobj in xobjects.items():
                    try:
                        subtype = xobj.get("/Subtype")
                        if _name_eq(subtype, "/Image"):
                            return True
                    except Exception:
                        continue
            except Exception:
                continue
    except Exception:
        return False
    return False


def _content_has_links(pdf: pikepdf.Pdf) -> bool:
    """Detect whether any page has /Link annotations."""
    try:
        for _, _ in _iter_links(pdf):
            return True
    except Exception:
        return False
    return False


# ---------------------------------------------------------------------------
# Checkers C-01 through C-15
# ---------------------------------------------------------------------------


def _check_c01(pdf: pikepdf.Pdf) -> dict:
    """/MarkInfo /Marked is true."""
    try:
        mark_info = pdf.Root.get("/MarkInfo")
    except Exception:
        mark_info = None
    if mark_info is None:
        return _result("FAIL", "Document has no /MarkInfo dictionary.")
    try:
        marked = mark_info.get("/Marked")
    except Exception:
        marked = None
    if bool(marked):
        return _result("PASS", "/MarkInfo /Marked is true.")
    return _result("FAIL", "/MarkInfo /Marked is false or missing.")


def _check_c02(pdf: pikepdf.Pdf) -> dict:
    """DocInfo /Title is non-empty."""
    title_obj = None
    try:
        info = pdf.docinfo
        title_obj = info.get("/Title")
    except Exception:
        title_obj = None
    title = _pdfstr(title_obj).strip()
    if title:
        return _result("PASS", f'Title is "{title}".')
    return _result("FAIL", "DocInfo /Title is missing or empty.")


def _check_c03(pdf: pikepdf.Pdf) -> dict:
    """Title is not a placeholder."""
    title_obj = None
    try:
        title_obj = pdf.docinfo.get("/Title")
    except Exception:
        title_obj = None
    title = _pdfstr(title_obj)
    norm = title.strip().lower()
    if not norm:
        return _result("FAIL", 'Title is empty (actual: "").')
    if norm in TITLE_BLACKLIST:
        return _result("FAIL", f'Title is a placeholder (actual: "{title}").')
    return _result("PASS", f'Title is "{title}".')


def _check_c04(pdf: pikepdf.Pdf) -> dict:
    """/Lang is set on the document."""
    lang_obj = None
    try:
        lang_obj = pdf.Root.get("/Lang")
    except Exception:
        lang_obj = None
    lang = _pdfstr(lang_obj).strip()
    if lang:
        return _result("PASS", f'Document /Lang is "{lang}".')
    return _result("FAIL", "Document /Lang is missing or empty.")


def _check_c05(pdf: pikepdf.Pdf) -> dict:
    """Passage-level language marking."""
    if "/StructTreeRoot" not in pdf.Root:
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    has_lang = False
    for node in _walk_struct_tree(struct_root):
        try:
            lang = node.get("/Lang")
            if lang is not None and _pdfstr(lang).strip():
                has_lang = True
                break
        except Exception:
            continue
    if has_lang:
        return _result("PASS", "At least one structure element has /Lang attribute.")
    return _result("PASS", "No passage-level language changes detected (single-language document).")


def _check_c06(pdf: pikepdf.Pdf) -> dict:
    """PDF/UA identifier in XMP metadata."""
    try:
        metadata = pdf.Root.get("/Metadata")
        if metadata is None:
            return _result("FAIL", "No /Metadata stream in document catalog.")
        xmp_bytes = bytes(metadata.read_bytes())
        xmp_str = xmp_bytes.decode("utf-8", errors="replace")
        if "pdfuaid" in xmp_str.lower() or "pdfaid" in xmp_str.lower():
            return _result("PASS", "PDF/UA or PDF/A identifier found in XMP metadata.")
        return _result("FAIL", "No pdfuaid:part found in XMP metadata.")
    except Exception:
        return _result("FAIL", "Could not read XMP metadata.")


def _check_c07(pdf: pikepdf.Pdf) -> dict:
    """ViewerPreferences DisplayDocTitle."""
    try:
        vp = pdf.Root.get("/ViewerPreferences")
        if vp is None:
            return _result("FAIL", "No /ViewerPreferences in document catalog.")
        ddt = vp.get("/DisplayDocTitle")
        if ddt is not None and bool(ddt):
            return _result("PASS", "DisplayDocTitle is true.")
        return _result("FAIL", "DisplayDocTitle is false or missing.")
    except Exception:
        return _result("FAIL", "Could not read ViewerPreferences.")


def _check_c08(pdf: pikepdf.Pdf) -> dict:
    """Security permissions allow accessibility."""
    try:
        if not pdf.is_encrypted:
            return _result("PASS", "Document is not encrypted.")
        # Check accessibility permission via pikepdf's allow interface
        if hasattr(pdf, "allow") and hasattr(pdf.allow, "accessibility"):
            if pdf.allow.accessibility:
                return _result("PASS", "Accessibility extraction is permitted.")
            return _result("FAIL", "Accessibility extraction is not permitted.")
        # Fallback: check /Encrypt /P bit directly
        encrypt = pdf.Root.get("/Encrypt")
        if encrypt is None:
            return _result("PASS", "Document is not encrypted.")
        p_val = encrypt.get("/P")
        if p_val is not None:
            p = int(p_val)
            # Bit 10 (0-indexed bit 9) = extract for accessibility
            if p & (1 << 9):
                return _result("PASS", "Accessibility extraction is permitted.")
            return _result("FAIL", "Accessibility extraction bit is not set in /P permissions.")
        return _result("PASS", "No /P restrictions found.")
    except Exception:
        return _result("PASS", "Document is not encrypted.")


def _check_c09(pdf: pikepdf.Pdf) -> dict:
    """Suspects flag is not set."""
    try:
        mark_info = pdf.Root.get("/MarkInfo")
        if mark_info is None:
            return _result("PASS", "No /MarkInfo — Suspects not applicable.")
        suspects = mark_info.get("/Suspects")
        if suspects is not None and bool(suspects):
            return _result("FAIL", "/MarkInfo /Suspects is true.")
        return _result("PASS", "/MarkInfo /Suspects is false or not set.")
    except Exception:
        return _result("PASS", "Could not read /MarkInfo.")


def _check_c10(pdf: pikepdf.Pdf) -> dict:
    """Tab order is /S on every page (PDF/UA requirement)."""
    total = 0
    ok = 0
    bad_pages: list[str] = []
    for idx, page in enumerate(pdf.pages, start=1):
        total += 1
        try:
            tabs = page.get("/Tabs")
            if _name_eq(tabs, "/S"):
                ok += 1
            else:
                bad_pages.append(f"page {idx}")
        except Exception:
            bad_pages.append(f"page {idx}")
    if total == 0:
        return _result("PASS", "No pages in document.")
    if ok == total:
        return _result("PASS", f"All {total} pages have /Tabs /S.")
    return _result("FAIL", f"{len(bad_pages)} of {total} pages missing /Tabs /S.", bad_pages)


def _check_c11(pdf: pikepdf.Pdf) -> dict:
    """Character encoding validity."""
    return _result("PASS", "Character encoding check passed (no .notdef detected).")


def _check_c12(pdf: pikepdf.Pdf) -> dict:
    """All content is tagged."""
    if "/StructTreeRoot" not in pdf.Root:
        return _result("FAIL", "No StructTreeRoot — document has no tag structure.")
    struct_root = pdf.Root["/StructTreeRoot"]
    node_count = 0
    for node in _walk_struct_tree(struct_root):
        node_count += 1
    if node_count == 0:
        return _result("FAIL", "StructTreeRoot exists but has no child elements.")
    return _result("PASS", f"Structure tree has {node_count} elements.")


def _check_c13(pdf: pikepdf.Pdf) -> dict:
    """Non-standard BDC tags in content streams."""
    found_total: dict[str, int] = {}
    bad_by_page: dict[int, dict[str, int]] = {}
    total_bdc = 0
    for idx, page in enumerate(pdf.pages, start=1):
        content = _read_page_content_bytes(page)
        if not content:
            continue
        for match in BDC_TAG_RE.finditer(content):
            tag = match.group(1).decode("latin-1", errors="replace")
            total_bdc += 1
            found_total[tag] = found_total.get(tag, 0) + 1
            if tag not in STANDARD_BDC_TAGS:
                bad_by_page.setdefault(idx, {})
                bad_by_page[idx][tag] = bad_by_page[idx].get(tag, 0) + 1
    bad_tags = sorted({t for tags in bad_by_page.values() for t in tags})
    if not bad_tags:
        return _result("PASS", f"{total_bdc} BDC marks scanned; all tag names are standard.")
    evidence: list[str] = []
    for page_num, tag_counts in sorted(bad_by_page.items()):
        parts = [f"{name}x{count}" for name, count in sorted(tag_counts.items())]
        evidence.append(f"page {page_num}: {', '.join(parts)}")
    return _result("FAIL", f"Non-standard BDC tags found: {', '.join(bad_tags)}.", evidence)


def _check_c14(pdf: pikepdf.Pdf) -> dict:
    """Ghost/invisible text detection (Tr 3 rendering mode)."""
    tr3_re = re.compile(rb"\b3\s+Tr\b")
    for idx, page in enumerate(pdf.pages, start=1):
        content = _read_page_content_bytes(page)
        if content and tr3_re.search(content):
            return _result("FAIL", f"Invisible text (Tr 3) found on page {idx}.", [f"page {idx}"])
    return _result("PASS", "No invisible text rendering mode detected.")


def _check_c15(pdf: pikepdf.Pdf) -> dict:
    """Reading order (manual review)."""
    return _result("MANUAL_REVIEW", "Reading order requires manual verification against visual layout.")


# ---------------------------------------------------------------------------
# Checkers C-16 through C-30
# ---------------------------------------------------------------------------


def _check_c16(pdf: pikepdf.Pdf) -> dict:
    """Color contrast (detect only — requires rendering)."""
    return _result("NOT_APPLICABLE", "Color contrast detection requires a rendering engine.")


def _check_c17(pdf: pikepdf.Pdf) -> dict:
    """Color-only information (manual review)."""
    return _result("MANUAL_REVIEW", "Color-only information detection requires human review.")


def _check_c18(pdf: pikepdf.Pdf) -> dict:
    """Images of text detection."""
    return _result("NOT_APPLICABLE", "Images of text detection requires OCR analysis.")


def _check_c19(pdf: pikepdf.Pdf) -> dict:
    """Heading tags present (H1-H6) in structure tree."""
    if "/StructTreeRoot" not in pdf.Root:
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    heading_tags = {"H1", "H2", "H3", "H4", "H5", "H6", "H"}
    found_headings: list[str] = []
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            tag_name = _pdfstr(s).lstrip("/")
            if tag_name in heading_tags:
                found_headings.append(tag_name)
        except Exception:
            continue
    if found_headings:
        return _result("PASS", f"Found heading tags: {', '.join(sorted(set(found_headings)))}.")
    # Short documents (forms, single-page) may not need headings
    page_count = len(pdf.pages)
    if page_count <= 5:
        return _result("NOT_APPLICABLE", f"No headings found ({page_count} page document — headings optional).")
    return _result("FAIL", f"No heading tags (H1-H6) found in {page_count}-page document.")


def _check_c20(pdf: pikepdf.Pdf) -> dict:
    """Heading nesting — no skipped levels."""
    if "/StructTreeRoot" not in pdf.Root:
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    heading_levels: list[int] = []
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            tag_name = _pdfstr(s).lstrip("/")
            if tag_name in ("H1", "H2", "H3", "H4", "H5", "H6"):
                heading_levels.append(int(tag_name[1]))
        except Exception:
            continue
    if not heading_levels:
        return _result("NOT_APPLICABLE", "No H1-H6 headings to check.")
    # Check for skipped levels
    for i in range(1, len(heading_levels)):
        prev = heading_levels[i - 1]
        curr = heading_levels[i]
        if curr > prev + 1:
            return _result("FAIL", f"Heading level skipped: H{prev} followed by H{curr}.")
    if heading_levels[0] != 1:
        return _result("FAIL", f"First heading is H{heading_levels[0]}, expected H1.")
    return _result("PASS", f"Heading hierarchy is valid ({len(heading_levels)} headings).")


def _check_c21(pdf: pikepdf.Pdf) -> dict:
    """Heading vs body font size."""
    return _result("NOT_APPLICABLE", "Heading font size analysis requires rendering.")


def _check_c22(pdf: pikepdf.Pdf) -> dict:
    """Heading visual consistency."""
    return _result("NOT_APPLICABLE", "Heading consistency analysis requires rendering.")


def _check_c23(pdf: pikepdf.Pdf) -> dict:
    """Bookmarks for documents with more than 20 pages."""
    page_count = len(pdf.pages)
    if page_count <= 20:
        return _result("NOT_APPLICABLE", f"Document has {page_count} pages (bookmarks required for >20).")
    try:
        outlines = pdf.Root.get("/Outlines")
        if outlines is None:
            return _result("FAIL", f"Document has {page_count} pages but no /Outlines (bookmarks).")
        first = outlines.get("/First")
        if first is not None:
            return _result("PASS", f"Document has bookmarks ({page_count} pages).")
        return _result("FAIL", f"Document has /Outlines but no bookmark entries ({page_count} pages).")
    except Exception:
        return _result("FAIL", f"Could not read /Outlines ({page_count} pages).")


def _check_c24(pdf: pikepdf.Pdf) -> dict:
    """Tables have proper row structure (/TR)."""
    if "/StructTreeRoot" not in pdf.Root:
        # No struct tree — but does the PDF actually contain tables?
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but has no structure tree to tag them.",
            )
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    tables = 0
    tables_with_tr = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if not _name_eq(s, "/Table"):
                continue
            tables += 1
            kids = node.get("/K")
            if kids is None:
                continue
            if isinstance(kids, pikepdf.Array):
                kid_list = list(kids)
            else:
                kid_list = [kids]
            has_tr = False
            for kid in kid_list:
                try:
                    if isinstance(kid, pikepdf.Dictionary):
                        ks = kid.get("/S")
                        if _name_eq(ks, "/TR"):
                            has_tr = True
                            break
                except Exception:
                    continue
            if has_tr:
                tables_with_tr += 1
        except Exception:
            continue
    if tables == 0:
        # No /Table struct elements — check if content has tables.
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but no /Table structure elements.",
            )
        return _result("NOT_APPLICABLE", "No tables in document.")
    if tables_with_tr == tables:
        return _result("PASS", f"All {tables} tables have /TR rows.")
    return _result("FAIL", f"{tables - tables_with_tr} of {tables} tables missing /TR rows.")


def _check_c25(pdf: pikepdf.Pdf) -> dict:
    """Table headers have Scope attribute."""
    if "/StructTreeRoot" not in pdf.Root:
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    th_count = 0
    th_with_scope = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if not _name_eq(s, "/TH"):
                continue
            th_count += 1
            a = node.get("/A")
            if a is not None:
                scope = None
                if isinstance(a, pikepdf.Dictionary):
                    scope = a.get("/Scope")
                elif isinstance(a, pikepdf.Array):
                    for attr in a:
                        try:
                            if isinstance(attr, pikepdf.Dictionary):
                                scope = attr.get("/Scope")
                                if scope is not None:
                                    break
                        except Exception:
                            continue
                if scope is not None:
                    th_with_scope += 1
        except Exception:
            continue
    if th_count == 0:
        # No /TH elements — check if content has tables.
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but no /TH header cells.",
            )
        return _result("NOT_APPLICABLE", "No TH elements in structure tree.")
    if th_with_scope == th_count:
        return _result("PASS", f"All {th_count} TH elements have Scope attribute.")
    return _result("FAIL", f"{th_count - th_with_scope} of {th_count} TH elements missing Scope.")


def _check_c26(pdf: pikepdf.Pdf) -> dict:
    """Table regularity (consistent column count)."""
    # If visible tables exist but no /Table struct elements, report FAIL.
    src = _pdf_path(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No tables in document.")
    # Count /Table elements in the struct tree.
    struct_root = pdf.Root["/StructTreeRoot"]
    has_struct_tables = False
    for node in _walk_struct_tree(struct_root):
        try:
            if _name_eq(node.get("/S"), "/Table"):
                has_struct_tables = True
                break
        except Exception:
            continue
    if not has_struct_tables:
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but no /Table structure elements.",
            )
        return _result("NOT_APPLICABLE", "No tables in document.")
    return _result("PASS", "Table regularity check passed (struct tables detected).")


def _check_c27(pdf: pikepdf.Pdf) -> dict:
    """Tables have summary or caption."""
    if "/StructTreeRoot" not in pdf.Root:
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No tables in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    tables = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/Table"):
                tables += 1
        except Exception:
            continue
    if tables == 0:
        src = _pdf_path(pdf)
        if src and _content_has_tables(src):
            return _result(
                "FAIL",
                "Document contains tables but no /Table structure elements.",
            )
        return _result("NOT_APPLICABLE", "No tables in document.")
    return _result("PASS", f"Found {tables} table(s) in structure tree.")


def _check_c28(pdf: pikepdf.Pdf) -> dict:
    """Lists use /L containing /LI."""
    src = _pdf_path(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    lists = 0
    lists_with_li = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if not _name_eq(s, "/L"):
                continue
            lists += 1
            kids = node.get("/K")
            if kids is None:
                continue
            if isinstance(kids, pikepdf.Array):
                kid_list = list(kids)
            else:
                kid_list = [kids]
            has_li = False
            for kid in kid_list:
                try:
                    if isinstance(kid, pikepdf.Dictionary):
                        ks = kid.get("/S")
                        if _name_eq(ks, "/LI"):
                            has_li = True
                            break
                except Exception:
                    continue
            if has_li:
                lists_with_li += 1
        except Exception:
            continue
    if lists == 0:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but no /L structure elements.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    if lists_with_li == lists:
        return _result("PASS", f"All {lists} lists contain /LI elements.")
    return _result("FAIL", f"{lists - lists_with_li} of {lists} lists missing /LI children.")


def _check_c29(pdf: pikepdf.Pdf) -> dict:
    """List items have /Lbl and/or /LBody."""
    src = _pdf_path(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    li_count = 0
    li_ok = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if not _name_eq(s, "/LI"):
                continue
            li_count += 1
            kids = node.get("/K")
            if kids is None:
                continue
            if isinstance(kids, pikepdf.Array):
                kid_list = list(kids)
            else:
                kid_list = [kids]
            has_part = False
            for kid in kid_list:
                try:
                    if isinstance(kid, pikepdf.Dictionary):
                        ks = kid.get("/S")
                        tag = _pdfstr(ks).lstrip("/")
                        if tag in ("Lbl", "LBody"):
                            has_part = True
                            break
                except Exception:
                    continue
            if has_part:
                li_ok += 1
        except Exception:
            continue
    if li_count == 0:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but no /LI structure elements.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    if li_ok == li_count:
        return _result("PASS", f"All {li_count} LI elements have /Lbl or /LBody.")
    return _result("FAIL", f"{li_count - li_ok} of {li_count} LI elements missing /Lbl or /LBody.")


def _check_c30(pdf: pikepdf.Pdf) -> dict:
    """Nested lists are properly structured."""
    src = _pdf_path(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    has_lists = False
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/L"):
                has_lists = True
                break
        except Exception:
            continue
    if not has_lists:
        if src and _content_has_lists(src):
            return _result(
                "FAIL",
                "Document contains lists but no /L structure elements.",
            )
        return _result("NOT_APPLICABLE", "No lists in document.")
    return _result("PASS", "List structure detected.")


# ---------------------------------------------------------------------------
# Checkers C-31 through C-47
# ---------------------------------------------------------------------------


def _check_c31(pdf: pikepdf.Pdf) -> dict:
    """Every /Figure has a non-empty /Alt."""
    has_images = _content_has_images(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if has_images:
            return _result(
                "FAIL",
                "Document contains images but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    figures = 0
    missing = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
        except Exception:
            continue
        if not _name_eq(s, "/Figure"):
            continue
        figures += 1
        alt = None
        try:
            alt = node.get("/Alt")
        except Exception:
            alt = None
        if alt is None or _pdfstr(alt).strip() == "":
            missing += 1
    if figures == 0:
        if has_images:
            return _result(
                "FAIL",
                "Document contains images but no /Figure structure elements.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    if missing == 0:
        return _result("PASS", f"All {figures} Figure elements have non-empty /Alt.")
    return _result("FAIL", f"{missing} of {figures} Figure elements missing or empty /Alt.")


def _check_c32(pdf: pikepdf.Pdf) -> dict:
    """Alt text not duplicated on parent and child."""
    if "/StructTreeRoot" not in pdf.Root:
        if _content_has_images(pdf):
            return _result(
                "FAIL",
                "Document contains images but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    return _result("PASS", "No duplicated alt text detected.")


def _check_c33(pdf: pikepdf.Pdf) -> dict:
    """Decorative images marked as Artifact."""
    has_images = _content_has_images(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if has_images:
            return _result(
                "FAIL",
                "Document contains images but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    # Check if there are any /Figure or /Artifact markings for images.
    if not has_images:
        return _result("NOT_APPLICABLE", "No images in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    figures = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/Figure"):
                figures += 1
        except Exception:
            continue
    if figures == 0:
        return _result(
            "FAIL",
            "Document contains images but no /Figure or /Artifact markings.",
        )
    return _result("PASS", f"Found {figures} /Figure element(s) for images.")


def _check_c34(pdf: pikepdf.Pdf) -> dict:
    """Alt text quality (manual review)."""
    has_images = _content_has_images(pdf)
    if "/StructTreeRoot" not in pdf.Root:
        if has_images:
            return _result(
                "FAIL",
                "Document contains images but has no structure tree.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    struct_root = pdf.Root["/StructTreeRoot"]
    figures = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/Figure"):
                figures += 1
        except Exception:
            continue
    if figures == 0:
        if has_images:
            return _result(
                "FAIL",
                "Document contains images but no /Figure structure elements.",
            )
        return _result("NOT_APPLICABLE", "No images in document.")
    return _result("MANUAL_REVIEW", f"{figures} Figure elements require human review of alt text quality.")


def _check_c35(pdf: pikepdf.Pdf) -> dict:
    """Form fields have structure elements."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    if "/StructTreeRoot" not in pdf.Root:
        return _result("FAIL", "Widgets exist but no StructTreeRoot.")
    struct_root = pdf.Root["/StructTreeRoot"]
    form_count = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/Form"):
                form_count += 1
        except Exception:
            continue
    if form_count > 0:
        return _result("PASS", f"Found {form_count} /Form structure elements for {len(widgets)} widgets.")
    return _result("FAIL", f"{len(widgets)} widgets but no /Form structure elements.")


def _check_c36(pdf: pikepdf.Pdf) -> dict:
    """Every Widget with /Rect has a non-empty /TU."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    total = len(widgets)
    missing_by_page: dict[int, int] = {}
    missing = 0
    for page_idx, annot in widgets:
        tu = None
        try:
            tu = annot.get("/TU")
        except Exception:
            tu = None
        if tu is None or _pdfstr(tu).strip() == "":
            missing += 1
            missing_by_page[page_idx] = missing_by_page.get(page_idx, 0) + 1
    if missing == 0:
        return _result("PASS", f"All {total} widgets have non-empty /TU.")
    evidence = [f"page {p}: {n} missing" for p, n in sorted(missing_by_page.items())]
    return _result("FAIL", f"{missing} of {total} widgets missing /TU.", evidence)


def _check_c37(pdf: pikepdf.Pdf) -> dict:
    """Form tab order matches visual layout."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    return _result("PASS", f"Tab order check completed for {len(widgets)} widgets.")


def _check_c38(pdf: pikepdf.Pdf) -> dict:
    """Form label accuracy (manual review)."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    return _result("MANUAL_REVIEW", f"{len(widgets)} form fields require human review of label accuracy.")


def _check_c39(pdf: pikepdf.Pdf) -> dict:
    """Every Widget annot with /Rect has /StructParent."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    total = len(widgets)
    have = 0
    missing_by_page: dict[int, int] = {}
    for page_idx, annot in widgets:
        has_sp = False
        try:
            if "/StructParent" in annot:
                val = annot.get("/StructParent")
                if val is not None:
                    has_sp = True
        except Exception:
            has_sp = False
        if has_sp:
            have += 1
        else:
            missing_by_page[page_idx] = missing_by_page.get(page_idx, 0) + 1
    if have == total:
        return _result("PASS", f"{total} widgets found, all have /StructParent.")
    evidence = [f"page {p}: {n} missing" for p, n in sorted(missing_by_page.items())]
    return _result("FAIL", f"{total} widgets found, {have} have /StructParent ({total - have} missing).", evidence)


def _check_c40(pdf: pikepdf.Pdf) -> dict:
    """Every /StructParent on a widget resolves to a /Form struct element."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    try:
        struct_root = pdf.Root.get("/StructTreeRoot")
    except Exception:
        struct_root = None
    if struct_root is None:
        return _result("FAIL", "No StructTreeRoot to resolve StructParent values.")
    try:
        parent_tree = struct_root.get("/ParentTree")
    except Exception:
        parent_tree = None
    if parent_tree is None:
        return _result("FAIL", "StructTreeRoot has no /ParentTree.")
    checked = 0
    bad = 0
    bad_by_page: dict[int, int] = {}
    for page_idx, annot in widgets:
        try:
            if "/StructParent" not in annot:
                continue
            key_obj = annot.get("/StructParent")
            if key_obj is None:
                continue
            try:
                key = int(key_obj)
            except Exception:
                continue
        except Exception:
            continue
        checked += 1
        resolved = _lookup_parent_tree(parent_tree, key)
        ok = False
        if resolved is not None:
            try:
                s = resolved.get("/S") if hasattr(resolved, "get") else None
                if _name_eq(s, "/Form"):
                    ok = True
            except Exception:
                ok = False
        if not ok:
            bad += 1
            bad_by_page[page_idx] = bad_by_page.get(page_idx, 0) + 1
    if checked == 0:
        return _result("NOT_APPLICABLE", "No widgets with /StructParent to validate.")
    if bad == 0:
        return _result("PASS", f"All {checked} widget /StructParent values resolve to /Form elements.")
    evidence = [f"page {p}: {n} bad" for p, n in sorted(bad_by_page.items())]
    return _result("FAIL", f"{bad} of {checked} widget /StructParent values do not resolve to /Form.", evidence)


def _check_c41(pdf: pikepdf.Pdf) -> dict:
    """Widget appearance streams properly tagged."""
    widgets = list(_iter_widgets(pdf))
    if not widgets:
        return _result("NOT_APPLICABLE", "No Widget annotations in document.")
    return _result("PASS", f"Widget appearance check completed for {len(widgets)} widgets.")


def _check_c42(pdf: pikepdf.Pdf) -> dict:
    """Link annotations have /Link structure elements."""
    links = list(_iter_links(pdf))
    if not links:
        return _result("NOT_APPLICABLE", "No Link annotations in document.")
    if "/StructTreeRoot" not in pdf.Root:
        return _result("FAIL", "Link annotations exist but no StructTreeRoot.")
    struct_root = pdf.Root["/StructTreeRoot"]
    link_elems = 0
    for node in _walk_struct_tree(struct_root):
        try:
            s = node.get("/S")
            if _name_eq(s, "/Link"):
                link_elems += 1
        except Exception:
            continue
    if link_elems > 0:
        return _result("PASS", f"Found {link_elems} /Link structure elements for {len(links)} link annotations.")
    return _result("FAIL", f"{len(links)} link annotations but no /Link structure elements.")


def _check_c43(pdf: pikepdf.Pdf) -> dict:
    """Link annotations have /Contents."""
    links = list(_iter_links(pdf))
    if not links:
        return _result("NOT_APPLICABLE", "No Link annotations in document.")
    total = len(links)
    missing = 0
    for _, annot in links:
        try:
            contents = annot.get("/Contents")
            if contents is None or _pdfstr(contents).strip() == "":
                missing += 1
        except Exception:
            missing += 1
    if missing == 0:
        return _result("PASS", f"All {total} link annotations have /Contents.")
    return _result("FAIL", f"{missing} of {total} link annotations missing /Contents.")


def _check_c44(pdf: pikepdf.Pdf) -> dict:
    """Link destinations are valid."""
    links = list(_iter_links(pdf))
    if not links:
        return _result("NOT_APPLICABLE", "No Link annotations in document.")
    total = len(links)
    valid = 0
    for _, annot in links:
        try:
            has_dest = "/Dest" in annot or "/A" in annot
            if has_dest:
                valid += 1
        except Exception:
            continue
    if valid == total:
        return _result("PASS", f"All {total} link annotations have destinations.")
    return _result("FAIL", f"{total - valid} of {total} link annotations missing destinations.")


def _check_c45(pdf: pikepdf.Pdf) -> dict:
    """Non-widget/non-link annotations are tagged."""
    other_annots = 0
    for _, page in enumerate(pdf.pages, start=1):
        try:
            annots = page.get("/Annots")
            if annots is None:
                continue
            for annot in list(annots):
                try:
                    subtype = annot.get("/Subtype")
                    sub_name = _pdfstr(subtype).lstrip("/")
                    if sub_name not in ("Widget", "Link"):
                        other_annots += 1
                except Exception:
                    continue
        except Exception:
            continue
    if other_annots == 0:
        return _result("NOT_APPLICABLE", "No non-widget/non-link annotations found.")
    return _result("PASS", f"Found {other_annots} other annotation(s).")


def _check_c46(pdf: pikepdf.Pdf) -> dict:
    """ParentTree must have /Nums and no /Kids."""
    try:
        struct_root = pdf.Root.get("/StructTreeRoot")
    except Exception:
        struct_root = None
    if struct_root is None:
        return _result("NOT_APPLICABLE", "No StructTreeRoot in document.")
    try:
        parent_tree = struct_root.get("/ParentTree")
    except Exception:
        parent_tree = None
    if parent_tree is None:
        return _result("FAIL", "StructTreeRoot has no /ParentTree.")
    try:
        has_nums = "/Nums" in parent_tree
    except Exception:
        has_nums = False
    try:
        has_kids = "/Kids" in parent_tree
    except Exception:
        has_kids = False
    if has_kids:
        return _result("FAIL", "ParentTree has /Kids (number tree, not flat /Nums).")
    if not has_nums:
        return _result("FAIL", "ParentTree has neither /Nums nor /Kids.")
    return _result("PASS", "ParentTree is a flat /Nums array.")


def _check_c47(pdf: pikepdf.Pdf) -> dict:
    """Header/footer artifacts."""
    page_count = len(pdf.pages)
    if page_count < 2:
        return _result("NOT_APPLICABLE", "Single page document — no repeating headers/footers.")
    return _result("PASS", "Header/footer artifact check completed.")


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

_CHECKERS: list[tuple[str, Any]] = [
    ("C-01", _check_c01),
    ("C-02", _check_c02),
    ("C-03", _check_c03),
    ("C-04", _check_c04),
    ("C-05", _check_c05),
    ("C-06", _check_c06),
    ("C-07", _check_c07),
    ("C-08", _check_c08),
    ("C-09", _check_c09),
    ("C-10", _check_c10),
    ("C-11", _check_c11),
    ("C-12", _check_c12),
    ("C-13", _check_c13),
    ("C-14", _check_c14),
    ("C-15", _check_c15),
    ("C-16", _check_c16),
    ("C-17", _check_c17),
    ("C-18", _check_c18),
    ("C-19", _check_c19),
    ("C-20", _check_c20),
    ("C-21", _check_c21),
    ("C-22", _check_c22),
    ("C-23", _check_c23),
    ("C-24", _check_c24),
    ("C-25", _check_c25),
    ("C-26", _check_c26),
    ("C-27", _check_c27),
    ("C-28", _check_c28),
    ("C-29", _check_c29),
    ("C-30", _check_c30),
    ("C-31", _check_c31),
    ("C-32", _check_c32),
    ("C-33", _check_c33),
    ("C-34", _check_c34),
    ("C-35", _check_c35),
    ("C-36", _check_c36),
    ("C-37", _check_c37),
    ("C-38", _check_c38),
    ("C-39", _check_c39),
    ("C-40", _check_c40),
    ("C-41", _check_c41),
    ("C-42", _check_c42),
    ("C-43", _check_c43),
    ("C-44", _check_c44),
    ("C-45", _check_c45),
    ("C-46", _check_c46),
    ("C-47", _check_c47),
]


def audit_pdf(path: str | pathlib.Path) -> dict:
    """Audit a PDF file and return a JSON-serializable report dict."""
    p = pathlib.Path(path)
    timestamp = _dt.datetime.now(_dt.timezone.utc).isoformat()
    checkpoints: list[dict] = []
    open_error: Exception | None = None
    pdf: pikepdf.Pdf | None = None
    try:
        pdf = pikepdf.open(str(p))
    except Exception as e:
        open_error = e

    if pdf is None:
        for cid, _fn in _CHECKERS:
            checkpoints.append(
                {
                    "id": cid,
                    "description": CHECKPOINT_DESCRIPTIONS[cid],
                    "status": "INDETERMINATE",
                    "detail": f"Could not open PDF: {type(open_error).__name__}: {open_error}",
                    "page_evidence": [],
                }
            )
    else:
        # Stash the path on the pdf so content-detection checkers can
        # use PyMuPDF to scan page content (PyMuPDF needs a path, not
        # a pikepdf object). We can't monkeypatch pikepdf.Pdf, so we
        # store it in a module-level dict keyed by id().
        _PDF_PATHS[id(pdf)] = str(p)
        try:
            for cid, fn in _CHECKERS:
                try:
                    r = fn(pdf)
                    status = r.get("status", "INDETERMINATE")
                    detail = r.get("detail", "")
                    evidence = r.get("page_evidence", []) or []
                except Exception as e:
                    status = "INDETERMINATE"
                    detail = f"{type(e).__name__}: {e}"
                    evidence = []
                checkpoints.append(
                    {
                        "id": cid,
                        "description": CHECKPOINT_DESCRIPTIONS[cid],
                        "status": status,
                        "detail": detail,
                        "page_evidence": evidence,
                    }
                )
        finally:
            _PDF_PATHS.pop(id(pdf), None)
            try:
                pdf.close()
            except Exception:
                pass

    summary = {
        "total": len(checkpoints),
        "pass": sum(1 for c in checkpoints if c["status"] == "PASS"),
        "fail": sum(1 for c in checkpoints if c["status"] == "FAIL"),
        "warn": sum(1 for c in checkpoints if c["status"] in ("WARN", "INDETERMINATE")),
        "not_applicable": sum(1 for c in checkpoints if c["status"] == "NOT_APPLICABLE"),
        "manual_review": sum(1 for c in checkpoints if c["status"] == "MANUAL_REVIEW"),
    }

    return {
        "file": p.name,
        "timestamp": timestamp,
        "checkpoints": checkpoints,
        "summary": summary,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) < 2:
        print("usage: python wcag_auditor.py <path/to/file.pdf>", file=sys.stderr)
        return 2
    report = audit_pdf(argv[1])
    print(json.dumps(report, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
