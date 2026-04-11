"""fix_untagged_content.py — wrap untagged content objects in marked content.

Scans every page content stream for content that executes outside any
BDC/EMC marked-content sequence (depth == 0) and wraps it so nothing
appears as "untagged" to a PAC 1.3 audit:

  * Path construction/paint groups at depth 0 are wrapped as
    /Artifact <</Type /Layout /Subtype /Rule>> BDC ... EMC.
  * BT ... ET text objects whose BT token is at depth 0 are wrapped as
    /Span <</MCID N>> BDC ... EMC. For every new MCID a matching /Span
    structure element is added to the tree and the page's entry in
    /StructTreeRoot /ParentTree is extended so the new MCID resolves.

BDC/EMC counts are preserved-plus-delta — every wrap adds exactly one
BDC and one EMC. If the delta check fails, the page is left untouched.
The input file is never modified.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any, Iterator

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Operator sets
# ---------------------------------------------------------------------------

PATH_CONSTRUCT: frozenset[bytes] = frozenset(
    {
        b"m",
        b"l",
        b"c",
        b"v",
        b"y",
        b"h",
        b"re",
    }
)
PATH_PAINT: frozenset[bytes] = frozenset(
    {
        b"S",
        b"s",
        b"f",
        b"F",
        b"f*",
        b"B",
        b"b",
        b"B*",
        b"b*",
    }
)
# `n` ends a path without painting (typically after W for clipping);
# we must close the path region on `n` but must NOT wrap clipping-only
# paths as artifacts.
PATH_NOPAINT: frozenset[bytes] = frozenset({b"n"})
CLIP_OPS: frozenset[bytes] = frozenset({b"W", b"W*"})


# ---------------------------------------------------------------------------
# Content-stream tokenizer
# ---------------------------------------------------------------------------

_WS = b" \t\r\n\x00\x0c"
_DELIMS = b" \t\r\n\x00\x0c()<>[]/%"


def _tokenize(data: bytes) -> Iterator[tuple[str, bytes, int, int]]:
    """Yield (kind, bytes, start, end) for every token in a content stream.

    `kind` is one of: op, name, num, str, hex, dict, arr.
    Comments and whitespace are consumed and not emitted.
    """
    i = 0
    n = len(data)
    while i < n:
        c = data[i]
        if c in _WS:
            i += 1
            continue
        if c == 0x25:  # '%'
            j = data.find(b"\n", i)
            i = (j + 1) if j != -1 else n
            continue
        if c == 0x28:  # '('
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                cc = data[j]
                if cc == 0x5C:  # backslash
                    j += 2
                    continue
                if cc == 0x28:
                    depth += 1
                elif cc == 0x29:
                    depth -= 1
                j += 1
            yield ("str", data[i:j], i, j)
            i = j
            continue
        if c == 0x3C:  # '<'
            if i + 1 < n and data[i + 1] == 0x3C:
                depth = 1
                j = i + 2
                while j < n and depth > 0:
                    if data[j : j + 2] == b"<<":
                        depth += 1
                        j += 2
                    elif data[j : j + 2] == b">>":
                        depth -= 1
                        j += 2
                    else:
                        j += 1
                yield ("dict", data[i:j], i, j)
                i = j
                continue
            j = data.find(b">", i)
            j = (j + 1) if j != -1 else n
            yield ("hex", data[i:j], i, j)
            i = j
            continue
        if c == 0x5B:  # '['
            depth = 1
            j = i + 1
            while j < n and depth > 0:
                cc = data[j]
                if cc == 0x28:  # string inside array
                    d2 = 1
                    j += 1
                    while j < n and d2 > 0:
                        ccc = data[j]
                        if ccc == 0x5C:
                            j += 2
                            continue
                        if ccc == 0x28:
                            d2 += 1
                        elif ccc == 0x29:
                            d2 -= 1
                        j += 1
                    continue
                if cc == 0x5B:
                    depth += 1
                elif cc == 0x5D:
                    depth -= 1
                j += 1
            yield ("arr", data[i:j], i, j)
            i = j
            continue
        if c == 0x2F:  # '/'
            j = i + 1
            while j < n and data[j] not in _DELIMS:
                j += 1
            yield ("name", data[i:j], i, j)
            i = j
            continue
        if c in b"+-.0123456789":
            j = i + 1
            while j < n and data[j : j + 1] in b"+-.0123456789eE":
                j += 1
            yield ("num", data[i:j], i, j)
            i = j
            continue
        j = i + 1
        while j < n and data[j] not in _DELIMS:
            j += 1
        yield ("op", data[i:j], i, j)
        i = j


# ---------------------------------------------------------------------------
# Region finder
# ---------------------------------------------------------------------------


def _find_untagged_regions(data: bytes) -> list[tuple[str, int, int]]:
    """Return list of (kind, start, end) regions to wrap.

    kind: 'text' — BT...ET at depth 0 that contains no inner BDC/BMC.
          'path' — contiguous path construction+paint group at depth 0,
                   including the numeric operands that precede the first
                   path-construction operator.
    Offsets are byte offsets into `data` and point at the first/past-last
    byte of the region.
    """
    regions: list[tuple[str, int, int]] = []
    tokens = list(_tokenize(data))

    depth = 0
    in_bt = False
    bt_start_off: int | None = None
    bt_depth: int | None = None
    bt_contains_bdc = False

    path_start_off: int | None = None
    path_has_construct = False
    saw_clip = False

    # Start byte of the current operand run — i.e. the position of the
    # first non-operator token since the previous operator. Used so that
    # when the FIRST path-construction op in a group fires, the wrap
    # includes the numeric operands that were pushed onto the stack for
    # it (e.g. `201.85 317.394 8.973 0.945 re`). Without this, the BDC
    # would be injected between the operands and the operator and PAC
    # parses the BDC as being outside any valid operator sequence.
    operand_run_start: int | None = None

    for kind, tok, s, e in tokens:
        if kind != "op":
            # Non-operator tokens don't affect depth or state machines,
            # but they do mark the start of a potential operand run.
            if operand_run_start is None:
                operand_run_start = s
            continue

        # Capture the operand-run start for this operator before we
        # clear it below. Operators consume any pending operands.
        op_operand_start = operand_run_start if operand_run_start is not None else s
        operand_run_start = None

        # Marked content depth tracking
        if tok in (b"BDC", b"BMC"):
            if in_bt:
                bt_contains_bdc = True
            depth += 1
            continue
        if tok == b"EMC":
            depth -= 1
            if depth < 0:
                depth = 0
            continue

        # Text object tracking
        if tok == b"BT":
            if depth == 0 and not in_bt:
                bt_start_off = s
                bt_depth = 0
                bt_contains_bdc = False
            in_bt = True
            continue
        if tok == b"ET":
            # Only record the BT/ET as needing a wrap when (a) the BT
            # was at depth 0 and (b) the block has no inner BDC/BMC —
            # i.e. its text shows are genuinely not in marked content.
            if in_bt and bt_depth == 0 and bt_start_off is not None and not bt_contains_bdc:
                regions.append(("text", bt_start_off, e))
            in_bt = False
            bt_start_off = None
            bt_depth = None
            bt_contains_bdc = False
            continue

        if in_bt:
            # Inside a BT/ET we only care about BDC/EMC (handled above).
            continue

        if depth != 0:
            # Already inside marked content — nothing to wrap.
            continue

        # Depth 0, outside any BT/ET: track path groups.
        if tok in CLIP_OPS:
            saw_clip = True
            continue

        if tok in PATH_CONSTRUCT:
            if path_start_off is None:
                # Start the wrap at the first operand of this op, not
                # at the op itself — otherwise the numeric operands end
                # up outside the BDC/EMC pair.
                path_start_off = op_operand_start
                path_has_construct = True
                saw_clip = False
            continue

        if path_start_off is not None:
            if tok in PATH_PAINT:
                if path_has_construct and not saw_clip:
                    regions.append(("path", path_start_off, e))
                path_start_off = None
                path_has_construct = False
                saw_clip = False
                continue
            if tok in PATH_NOPAINT:
                # W n — clipping path, no visible artifact, do not wrap.
                path_start_off = None
                path_has_construct = False
                saw_clip = False
                continue
            # Any other operator while we thought we were in a path —
            # reset. (Paths should only contain construct/paint ops.)
            path_start_off = None
            path_has_construct = False
            saw_clip = False

    return regions


# ---------------------------------------------------------------------------
# Stream rewriter
# ---------------------------------------------------------------------------


def _rewrite(
    data: bytes,
    regions: list[tuple[str, int, int]],
    start_mcid: int,
) -> tuple[bytes, int, int]:
    """Insert BDC/EMC wrappers around each region.

    Returns (new_bytes, spans_added, artifacts_added). MCIDs are assigned
    sequentially starting at `start_mcid`.
    """
    if not regions:
        return data, 0, 0

    regions = sorted(regions, key=lambda r: r[1])
    parts: list[bytes] = []
    cursor = 0
    mcid = start_mcid
    spans = 0
    artifacts = 0

    for kind, s, e in regions:
        if s < cursor:
            # Overlapping regions — defensive skip.
            continue
        parts.append(data[cursor:s])
        if kind == "path":
            parts.append(b"/Artifact <</Type /Layout /Subtype /Rule>> BDC\n")
            parts.append(data[s:e])
            parts.append(b"\nEMC\n")
            artifacts += 1
        else:  # text
            parts.append(f"/Span <</MCID {mcid}>> BDC\n".encode("latin-1"))
            parts.append(data[s:e])
            parts.append(b"\nEMC\n")
            mcid += 1
            spans += 1
        cursor = e

    parts.append(data[cursor:])
    return b"".join(parts), spans, artifacts


# ---------------------------------------------------------------------------
# Struct-tree helpers
# ---------------------------------------------------------------------------


def _get_doc_struct(pdf: pikepdf.Pdf) -> Any:
    """Return the top-level struct element (or None) to attach new Spans to."""
    try:
        sr = pdf.Root.get("/StructTreeRoot")
    except Exception:
        return None
    if sr is None:
        return None
    try:
        k = sr.get("/K")
    except Exception:
        return None
    if k is None:
        return None
    if isinstance(k, pikepdf.Array):
        if len(k) == 0:
            return None
        # Prefer the Document element if present, else first child.
        for idx in range(len(k)):
            try:
                node = k[idx]
                if isinstance(node, pikepdf.Dictionary):
                    s = node.get("/S")
                    if s is not None:
                        return node
            except Exception:
                continue
        return k[0] if len(k) > 0 else None
    if isinstance(k, pikepdf.Dictionary):
        return k
    return None


def _find_nums_entry(nums: Any, key: int) -> int | None:
    """Return the index i into /Nums where nums[i]==key, else None.

    The value is at nums[i+1].
    """
    try:
        n = len(nums)
    except Exception:
        return None
    for i in range(0, n, 2):
        try:
            if int(nums[i]) == key:
                return i
        except Exception:
            continue
    return None


def _append_struct_child(parent: Any, child: Any) -> None:
    """Append `child` to parent's /K array (upgrading to an array if needed)."""
    try:
        k = parent.get("/K")
    except Exception:
        k = None
    if k is None:
        parent["/K"] = pikepdf.Array([child])
        return
    if isinstance(k, pikepdf.Array):
        k.append(child)
        return
    # Single-child form — wrap in an array.
    parent["/K"] = pikepdf.Array([k, child])


# ---------------------------------------------------------------------------
# Per-page content rewrite
# ---------------------------------------------------------------------------


def _read_page_data(page: Any) -> tuple[bytes, bool]:
    """Return (data, is_array). `is_array` means /Contents was an Array
    of streams and should be replaced wholesale on write-back."""
    try:
        c = page.get("/Contents")
    except Exception:
        return b"", False
    if c is None:
        return b"", False
    if isinstance(c, pikepdf.Array):
        chunks: list[bytes] = []
        for stream in c:
            try:
                chunks.append(bytes(stream.read_bytes()))
            except Exception:
                pass
        return b"\n".join(chunks), True
    try:
        return bytes(c.read_bytes()), False
    except Exception:
        return b"", False


def _write_page_data(pdf: pikepdf.Pdf, page: Any, new_data: bytes, was_array: bool) -> None:
    """Replace the page's content stream with a single stream holding `new_data`."""
    new_stream = pdf.make_stream(new_data)
    if was_array:
        page.Contents = new_stream
    else:
        # In-place update is safe when the original was a single stream.
        try:
            page.Contents.write(new_data)
        except Exception:
            page.Contents = new_stream


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_untagged_content(input_path: str, output_path: str) -> dict:
    """Wrap untagged content objects in marked-content sequences.

    Returns: {"pages_modified", "spans_added", "artifacts_added", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "pages_modified": 0,
        "spans_added": 0,
        "artifacts_added": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            sr = None
            try:
                sr = pdf.Root.get("/StructTreeRoot")
            except Exception:
                sr = None
            if sr is None:
                # No struct tree — nothing to tag against.
                pdf.save(out_str)
                return result

            parent_tree = None
            try:
                parent_tree = sr.get("/ParentTree")
            except Exception:
                parent_tree = None
            nums = None
            if parent_tree is not None:
                try:
                    nums = parent_tree.get("/Nums")
                except Exception:
                    nums = None

            doc_struct = _get_doc_struct(pdf)

            for page_idx, page in enumerate(pdf.pages, start=1):
                data, was_array = _read_page_data(page)
                if not data:
                    continue

                regions = _find_untagged_regions(data)
                if not regions:
                    continue

                # Determine the next MCID for this page. Text regions
                # will consume one MCID each, starting at the length of
                # this page's existing ParentTree array.
                sp_obj = None
                try:
                    sp_obj = page.get("/StructParents")
                except Exception:
                    sp_obj = None
                start_mcid = 0
                pt_array: Any = None
                if sp_obj is not None and nums is not None:
                    try:
                        sp_key = int(sp_obj)
                    except Exception:
                        sp_key = None
                    if sp_key is not None:
                        idx = _find_nums_entry(nums, sp_key)
                        if idx is not None:
                            try:
                                val = nums[idx + 1]
                                if isinstance(val, pikepdf.Array):
                                    pt_array = val
                                    start_mcid = len(pt_array)
                            except Exception:
                                pt_array = None

                text_regions = sum(1 for r in regions if r[0] == "text")
                if text_regions > 0 and pt_array is None:
                    # We cannot safely add Spans without a ParentTree
                    # array to extend — downgrade text regions to path
                    # artifacts? No: leave them alone to avoid breaking
                    # an otherwise-usable page.
                    regions = [r for r in regions if r[0] != "text"]
                    if not regions:
                        continue

                new_data, spans_added, artifacts_added = _rewrite(
                    data,
                    regions,
                    start_mcid,
                )

                # Sanity check: BDC/EMC counts should each rise by the
                # number of wrapped regions.
                expected_delta = spans_added + artifacts_added
                old_bdc = data.count(b"BDC")
                old_emc = data.count(b"EMC")
                new_bdc = new_data.count(b"BDC")
                new_emc = new_data.count(b"EMC")
                if new_bdc - old_bdc != expected_delta or new_emc - old_emc != expected_delta:
                    result["errors"].append(
                        f"page {page_idx}: BDC/EMC delta mismatch "
                        f"BDC {old_bdc}->{new_bdc}, EMC {old_emc}->{new_emc}, "
                        f"expected +{expected_delta}; skipped"
                    )
                    continue

                try:
                    _write_page_data(pdf, page, new_data, was_array)
                except Exception as e:
                    result["errors"].append(f"page {page_idx}: write failed: {e}")
                    continue

                # Register each new Span in the struct tree + ParentTree.
                if spans_added > 0 and pt_array is not None and doc_struct is not None:
                    # pikepdf wraps dict-like objects; dictionaries only
                    # accept raw pikepdf.Object values, so pull out the
                    # underlying Object for the parent and the page.
                    parent_obj = getattr(doc_struct, "obj", doc_struct)
                    page_obj = getattr(page, "obj", page)
                    for k in range(spans_added):
                        new_mcid = start_mcid + k
                        span = pdf.make_indirect(
                            pikepdf.Dictionary(
                                {
                                    "/Type": pikepdf.Name("/StructElem"),
                                    "/S": pikepdf.Name("/Span"),
                                    "/P": parent_obj,
                                    "/Pg": page_obj,
                                    "/K": new_mcid,
                                }
                            )
                        )
                        try:
                            pt_array.append(span)
                        except Exception as e:
                            result["errors"].append(f"page {page_idx}: ParentTree append failed: {e}")
                            break
                        try:
                            _append_struct_child(doc_struct, span)
                        except Exception as e:
                            result["errors"].append(f"page {page_idx}: struct append failed: {e}")
                            break

                result["pages_modified"] += 1
                result["spans_added"] += spans_added
                result["artifacts_added"] += artifacts_added
                logger.info(
                    "page %d: wrapped %d spans, %d artifacts",
                    page_idx,
                    spans_added,
                    artifacts_added,
                )

            pdf.save(out_str)
        return result

    except Exception as e:
        logger.exception("fix_untagged_content failed for %s", in_str)
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
        print("usage: python fix_untagged_content.py <input.pdf> <output.pdf>")
        return 2
    res = fix_untagged_content(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
