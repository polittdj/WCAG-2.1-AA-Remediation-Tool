"""fix_content_streams.py — replace non-standard BDC tag identifiers in
PDF content streams with their standard equivalents.

Reads `input_path`, walks every page's content streams, finds every BDC
operator whose tag name is in NON_STANDARD_TO_STANDARD, and rewrites the
tag (or replaces the whole BDC block with /Artifact when the mapping is
None). Pages whose content streams contain no non-standard tags are left
byte-for-byte untouched. After all pages are processed, any non-standard
keys in /StructTreeRoot /RoleMap are removed. The input file is never
modified.
"""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

NON_STANDARD_TO_STANDARD: dict[str, str | None] = {
    # Generic content containers used by Acrobat/IRS forms
    "Content": "Span",      # IRS/Acrobat: /Content BDC for marked content
    "Textbody": "P",        # Word-export: body text paragraphs
    "TextBody": "P",
    "Normal": "P",          # Common non-standard paragraph type (Word/Acrobat)
    # Word/Office export types
    "ExtraCharSpan": "Span",
    "ParagraphSpan": "Span",
    "Footnote": "Note",
    "Endnote": "Note",
    "InlineShape": "Figure",
    "TextBox": "Art",
    "DropCap": "Span",
    "Subscript": "Span",
    "Superscript": "Span",
    "Strikeout": "Span",
    "Underline": "Span",
    "Outline": "Span",
    "CommentAnchor": None,
    "Bibliography": "BibEntry",
    "Chart": "Figure",
    "Diagram": "Figure",
    "Annotation": "Span",
    "Chartsheet": None,
    "Dialogsheet": None,
    "Workbook": None,
    "Slide": None,
    "Title": None,
}

STANDARD_TAGS: frozenset[str] = frozenset(
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

BDC_TAG_RE = re.compile(
    rb"/([A-Za-z][A-Za-z0-9_]*)"
    rb"\s+"
    rb"(?:<<(?:[^<>]|<<[^<>]*>>)*>>|/[A-Za-z][A-Za-z0-9_.\-]*)"
    rb"\s*BDC\b",
    re.DOTALL,
)

ARTIFACT_REPLACEMENT = b"/Artifact <</Type /Layout>> BDC"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _get_content_streams(page: Any) -> list[Any]:
    """Return list of stream objects on this page (possibly empty)."""
    try:
        contents = page.get("/Contents")
    except Exception:
        return []
    if contents is None:
        return []
    if isinstance(contents, pikepdf.Array):
        return [s for s in contents]
    return [contents]


def _scan_non_standard(text_bytes: bytes) -> set[str]:
    """Return the set of non-standard BDC tag names found in `text_bytes`."""
    found: set[str] = set()
    for m in BDC_TAG_RE.finditer(text_bytes):
        try:
            tag = m.group(1).decode("latin-1")
        except Exception:
            continue
        if tag in NON_STANDARD_TO_STANDARD or tag not in STANDARD_TAGS:
            found.add(tag)
    return found


def _substitute(text_bytes: bytes) -> tuple[bytes, int]:
    """Apply NON_STANDARD_TO_STANDARD substitutions.

    Returns: (new_bytes, number_of_replacements_made).
    Standard tags and unknown non-standard tags are left untouched.
    """
    count = 0

    def repl(m: re.Match[bytes]) -> bytes:
        nonlocal count
        try:
            tag = m.group(1).decode("latin-1")
        except Exception:
            return m.group(0)
        if tag in STANDARD_TAGS:
            return m.group(0)
        # Determine replacement: use mapping if known, else default to Span
        if tag in NON_STANDARD_TO_STANDARD:
            replacement = NON_STANDARD_TO_STANDARD[tag]
        else:
            replacement = "Span"
        count += 1
        if replacement is None:
            return ARTIFACT_REPLACEMENT
        # Replace only the tag-name token in the matched text. The token
        # is at position 0 of m.group(0) (regex anchors `/<name>` first),
        # so a single .replace(..., 1) cleanly substitutes only the tag.
        old_token = b"/" + tag.encode("latin-1")
        new_token = b"/" + replacement.encode("latin-1")
        return m.group(0).replace(old_token, new_token, 1)

    new_bytes = BDC_TAG_RE.sub(repl, text_bytes)
    return new_bytes, count


def _clean_role_map(pdf: pikepdf.Pdf) -> int:
    """Replace non-standard /RoleMap entries with their standard equivalents.

    Previously this deleted non-standard entries outright.  Deletion is risky:
    if content-stream BDC rewriting misses an occurrence (e.g. an unusual
    token format), the PDF ends up with the non-standard tag still in the
    stream but no RoleMap fallback, which makes PAC's 4.1-Compatible check
    even angrier than it would have been.

    New behaviour: map every non-standard key to its closest standard type
    (/Content → /Span, etc.) so PDF readers retain a meaningful fallback
    regardless of whether the content-stream pass succeeded.  Only keys that
    explicitly map to ``None`` (marker for "treat as Artifact") are removed.

    Returns the number of entries modified (set or removed).
    """
    try:
        struct_root = pdf.Root.get("/StructTreeRoot")
    except Exception:
        return 0
    if struct_root is None:
        return 0
    try:
        role_map = struct_root.get("/RoleMap")
    except Exception:
        return 0
    if role_map is None:
        return 0

    try:
        keys = list(role_map.keys())
    except Exception:
        return 0

    modified = 0
    for key in keys:
        try:
            name = str(key).lstrip("/")
        except Exception:
            continue
        if name in STANDARD_TAGS:
            continue  # already a standard type — leave untouched
        # Determine replacement
        if name in NON_STANDARD_TO_STANDARD:
            replacement = NON_STANDARD_TO_STANDARD[name]
        else:
            replacement = "Span"  # unknown non-standard → safest catch-all
        try:
            if replacement is None:
                # "Treat as Artifact" mapping — remove the entry (no standard
                # equivalent; keeping it would confuse viewers).
                del role_map[key]
            else:
                role_map[key] = pikepdf.Name(f"/{replacement}")
            modified += 1
        except Exception as e:
            logger.warning("rolemap: could not update %r → %r: %s", key, replacement, e)
    return modified


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_content_streams(input_path: str, output_path: str) -> dict:
    """Replace non-standard BDC tags in content streams. Never modifies input.

    Returns: {"pages_modified", "tags_replaced", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "pages_modified": 0,
        "tags_replaced": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            for page_idx, page in enumerate(pdf.pages, start=1):
                streams = _get_content_streams(page)
                if not streams:
                    continue

                page_modified = False
                for stream_idx, stream in enumerate(streams):
                    # STEP 1 — read & decompress
                    try:
                        original_bytes = bytes(stream.read_bytes())
                    except Exception as e:
                        result["errors"].append(f"page {page_idx} stream {stream_idx}: read failed: {e}")
                        continue

                    # STEP 2 — does this stream need any work?
                    non_std = _scan_non_standard(original_bytes)
                    if not non_std:
                        continue  # leave the stream byte-untouched

                    # STEP 3 — count BDC/EMC before
                    orig_bdc = original_bytes.count(b"BDC")
                    orig_emc = original_bytes.count(b"EMC")

                    # STEP 4 — apply substitutions
                    new_bytes, n_repl = _substitute(original_bytes)

                    # STEP 5 — verify counts
                    new_bdc = new_bytes.count(b"BDC")
                    new_emc = new_bytes.count(b"EMC")
                    if new_bdc != orig_bdc or new_emc != orig_emc:
                        result["errors"].append(
                            f"page {page_idx} stream {stream_idx}: "
                            f"count mismatch BDC {orig_bdc}->{new_bdc} "
                            f"EMC {orig_emc}->{new_emc}; reverted"
                        )
                        logger.error(
                            "page %d: BDC/EMC count mismatch — stream not written",
                            page_idx,
                        )
                        continue

                    # STEP 6 — write the new stream
                    try:
                        stream.write(new_bytes)
                    except Exception as e:
                        result["errors"].append(f"page {page_idx} stream {stream_idx}: write failed: {e}")
                        continue

                    page_modified = True
                    result["tags_replaced"] += n_repl
                    logger.info(
                        "page %d: replaced %d non-standard BDC tag(s) (%s)",
                        page_idx,
                        n_repl,
                        sorted(non_std),
                    )

                if page_modified:
                    result["pages_modified"] += 1

            # STEP 7 — clean RoleMap
            removed = _clean_role_map(pdf)
            if removed:
                logger.info("RoleMap: removed %d non-standard key(s)", removed)

            pdf.save(out_str)
        return result

    except Exception as e:
        logger.exception("fix_content_streams failed for %s", in_str)
        result["errors"].append(f"{type(e).__name__}: {e}")
        try:
            shutil.copy2(in_str, out_str)
        except Exception as copy_err:
            result["errors"].append(f"copy failed: {copy_err}")
        return result


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python fix_content_streams.py <input.pdf> <output.pdf>")
        return 2
    res = fix_content_streams(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
