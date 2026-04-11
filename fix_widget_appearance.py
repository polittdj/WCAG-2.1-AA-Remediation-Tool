"""fix_widget_appearance.py — re-tag widget appearance streams as artifacts.

PDF/UA-1 section 7.18.4 requires that the visible appearance content
of form field widgets be marked as /Artifact. In practice, Adobe
Acrobat writes `/Tx BMC … EMC` around the drawn text of text fields
(and similar wrappers for other field types), which PAC 2024 flags
under "4.1 Compatible" because:

  * `/Tx` is not a standard structure element name, so it implies
    structural content that isn't in the tree, AND
  * The widget's visible rendering is rendering, not logical
    structure — it belongs in the artifact namespace.

For every Widget annotation on every page, this module walks the
annotation's /AP /N appearance XObject (and every nested Form
XObject referenced via `Do`) and rewrites every non-standard marked-
content tag (`Tx`, `TxMC`, `Form`, etc.) to `/Artifact`. The BDC/EMC
nesting count is preserved by the same substitution. Standard
structure tags are left alone on the off chance they appear.

The input file is never modified.
"""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Iterator

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Tag names that are valid PDF structure types. Content marked with
# any of these is left alone; anything else is normalised to
# /Artifact per PDF/UA 7.18.4 for appearance content.
_STANDARD_TAGS: frozenset[str] = frozenset(
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

# Match /Name <<props>> BDC      → tag-with-props
# or    /Name /PropRef BDC       → tag-with-name-ref
# or    /Name BMC                → tag-only (BMC variant)
_BDC_TAG_RE = re.compile(
    rb"/(?P<tag>[A-Za-z][A-Za-z0-9_]*)"
    rb"(?:\s+"
    rb"(?:<<(?:[^<>]|<<[^<>]*>>)*>>"
    rb"|/[A-Za-z][A-Za-z0-9_.\-]*))?"
    rb"\s*(?P<op>BDC|BMC)\b",
    re.DOTALL,
)


# ---------------------------------------------------------------------------
# Widget iteration
# ---------------------------------------------------------------------------


def _name_eq(value: Any, expected: str) -> bool:
    if value is None:
        return False
    try:
        s = str(value)
    except Exception:
        return False
    if s.startswith("/"):
        s = s[1:]
    target = expected[1:] if expected.startswith("/") else expected
    return s == target


def _collect_page_xobject_objgens(pdf: pikepdf.Pdf) -> set[tuple[int, int]]:
    """Return the objgens of every stream reachable from a page's
    /Resources/XObject dict.

    Used as a conservative "is this stream shared with page content?"
    filter: if a widget's /AP /N happens to be the same object as a
    page-level XObject, rewriting the stream in place would also
    retag the page's visible content. In that case we skip the
    rewrite rather than globally mutate a shared resource.

    This includes transitive walks into nested Form XObjects via
    their own /Resources/XObject, so content reached indirectly from
    page content is also caught.
    """
    seen: set[tuple[int, int]] = set()
    queue: list[Any] = []
    for page in pdf.pages:
        try:
            res = page.get("/Resources")
        except Exception:
            res = None
        if res is None:
            continue
        try:
            xo = res.get("/XObject")
        except Exception:
            xo = None
        if xo is None:
            continue
        try:
            for k in xo.keys():
                queue.append(xo[k])
        except Exception:
            pass
    while queue:
        node = queue.pop()
        if node is None:
            continue
        og = getattr(node, "objgen", None)
        if og is None:
            continue
        if og in seen:
            continue
        seen.add(og)
        # Descend into nested Form XObjects on their own /Resources.
        if isinstance(node, pikepdf.Stream):
            try:
                inner_res = node.get("/Resources")
            except Exception:
                inner_res = None
            if inner_res is None:
                continue
            try:
                inner_xo = inner_res.get("/XObject")
            except Exception:
                inner_xo = None
            if inner_xo is None:
                continue
            try:
                for k in inner_xo.keys():
                    queue.append(inner_xo[k])
            except Exception:
                pass
    return seen


def _iter_widget_appearance_streams(
    pdf: pikepdf.Pdf,
    excluded: set[tuple[int, int]],
) -> Iterator[pikepdf.Stream]:
    """Yield every top-level /AP /N, /R, /D Form XObject for every Widget.

    We deliberately do NOT recurse into nested Form XObjects on the
    stream's /Resources — nested forms are the most common vector for
    cross-ownership (a nested XObject can be reused by a page content
    stream) and rewriting them would risk globally retagging non-widget
    content. Top-level appearance streams are the safe subset.

    Streams whose objgen is in `excluded` are skipped — that set
    contains every objgen reachable from a page's /Resources/XObject
    dict, so if a widget unfortunately happens to share its /AP /N
    with a page-level XObject we leave it alone.
    """
    yielded: set[tuple[int, int]] = set()

    for page in pdf.pages:
        try:
            annots = page.get("/Annots") or []
        except Exception:
            annots = []
        for annot in annots:
            try:
                if not _name_eq(annot.get("/Subtype"), "/Widget"):
                    continue
                ap = annot.get("/AP")
                if ap is None:
                    continue
                for key in ("/N", "/R", "/D"):
                    try:
                        node = ap.get(key)
                    except Exception:
                        node = None
                    if node is None:
                        continue
                    # Appearance state dict form: { "On": stream, "Off": stream }.
                    candidates: list[Any] = []
                    if isinstance(node, pikepdf.Stream):
                        candidates.append(node)
                    elif isinstance(node, pikepdf.Dictionary):
                        try:
                            for sk in node.keys():
                                candidates.append(node[sk])
                        except Exception:
                            pass
                    for cand in candidates:
                        if not isinstance(cand, pikepdf.Stream):
                            continue
                        og = getattr(cand, "objgen", None)
                        if og is None or og in yielded:
                            continue
                        if og in excluded:
                            logger.info(
                                "skipping widget /AP stream %s: also in page /Resources/XObject",
                                og,
                            )
                            continue
                        yielded.add(og)
                        yield cand
            except Exception:
                continue


# ---------------------------------------------------------------------------
# Stream rewriter
# ---------------------------------------------------------------------------


def _rewrite_stream(data: bytes) -> tuple[bytes, int]:
    """Return (new_bytes, tags_normalised).

    Replaces every BDC/BMC whose tag name is not a standard structure
    type with `/Artifact`. The properties list (if any) is dropped on
    the BMC path and kept on the BDC path.
    """
    count = 0

    def repl(m: re.Match[bytes]) -> bytes:
        nonlocal count
        tag = m.group("tag").decode("latin-1", errors="replace")
        op = m.group("op")  # b"BDC" or b"BMC"
        if tag in _STANDARD_TAGS:
            return m.group(0)
        count += 1
        if op == b"BMC":
            return b"/Artifact BMC"
        # BDC — preserve a minimal properties dict so the BDC still
        # has its required arg.
        return b"/Artifact <</Type /Layout>> BDC"

    return _BDC_TAG_RE.sub(repl, data), count


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_widget_appearance(input_path: str, output_path: str) -> dict:
    """Re-tag every widget appearance stream's marked content as /Artifact.

    Returns: {"streams_scanned", "streams_rewritten", "tags_normalised", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "streams_scanned": 0,
        "streams_rewritten": 0,
        "tags_normalised": 0,
        "streams_skipped_shared": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            # Build the set of stream objgens reachable from page
            # /Resources/XObject dicts so we don't mutate a stream
            # that's shared with page content.
            excluded = _collect_page_xobject_objgens(pdf)
            # Count excluded streams that ALSO appear as widget /AP,
            # so the result dict reflects any skip events.
            all_widget_ap: set[tuple[int, int]] = set()
            for page in pdf.pages:
                try:
                    annots = page.get("/Annots") or []
                except Exception:
                    annots = []
                for annot in annots:
                    try:
                        if not _name_eq(annot.get("/Subtype"), "/Widget"):
                            continue
                        ap = annot.get("/AP")
                        if ap is None:
                            continue
                        for key in ("/N", "/R", "/D"):
                            node = ap.get(key)
                            if node is None:
                                continue
                            candidates: list[Any] = []
                            if isinstance(node, pikepdf.Stream):
                                candidates.append(node)
                            elif isinstance(node, pikepdf.Dictionary):
                                try:
                                    for sk in node.keys():
                                        candidates.append(node[sk])
                                except Exception:
                                    pass
                            for cand in candidates:
                                if isinstance(cand, pikepdf.Stream):
                                    og = getattr(cand, "objgen", None)
                                    if og is not None:
                                        all_widget_ap.add(og)
                    except Exception:
                        continue
            result["streams_skipped_shared"] = len(all_widget_ap & excluded)

            for stream in _iter_widget_appearance_streams(pdf, excluded):
                result["streams_scanned"] += 1
                try:
                    old = bytes(stream.read_bytes())
                except Exception as e:
                    result["errors"].append(f"stream {getattr(stream, 'objgen', '?')}: read failed: {e}")
                    continue

                # Fast path: no BDC/BMC → leave untouched.
                if b"BDC" not in old and b"BMC" not in old:
                    continue

                new, replaced = _rewrite_stream(old)
                if replaced == 0 or new == old:
                    continue

                # Verify BDC/EMC counts stayed balanced.
                if new.count(b"BDC") + new.count(b"BMC") != old.count(b"BDC") + old.count(b"BMC") or new.count(
                    b"EMC"
                ) != old.count(b"EMC"):
                    result["errors"].append(
                        f"stream {getattr(stream, 'objgen', '?')}: marked-content count mismatch; reverted"
                    )
                    continue

                try:
                    stream.write(new)
                except Exception as e:
                    result["errors"].append(f"stream {getattr(stream, 'objgen', '?')}: write failed: {e}")
                    continue

                result["streams_rewritten"] += 1
                result["tags_normalised"] += replaced

            pdf.save(out_str)
        logger.info(
            "fix_widget_appearance: scanned=%d rewritten=%d tags=%d",
            result["streams_scanned"],
            result["streams_rewritten"],
            result["tags_normalised"],
        )
        return result

    except Exception as e:
        logger.exception("fix_widget_appearance failed for %s", in_str)
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
        print("usage: python fix_widget_appearance.py <input.pdf> <output.pdf>")
        return 2
    res = fix_widget_appearance(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
