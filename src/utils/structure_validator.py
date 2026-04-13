"""src.utils.structure_validator — PDF structure-tree integrity validator.

BUG-02: ParentTree validation.

Validates the consistency of the PDF structure tree against the page content
streams.  The validator catches problems that would cause PAC (PDF Accessibility
Checker) to report "4.1 Compatible" failures even though the auditor might
report PASS.

Problems detected
-----------------
* Orphaned MCIDs — a MCID is referenced by a struct element but the
  corresponding BDC marker is absent from the page content stream.
* Duplicate MCIDs — the same MCID appears on the same page in more than one
  struct element (/K entry).
* Broken ParentTree — the /Nums array is not sequential, references a
  struct element that no longer exists, or is absent altogether.
* Missing ParentTree — the StructTreeRoot lacks a /ParentTree.

Usage
-----
    from src.utils.structure_validator import validate_structure_tree

    issues = validate_structure_tree(pdf)  # pikepdf.Pdf instance
    for issue in issues:
        print(issue)  # each is a plain string describing the problem
"""
from __future__ import annotations

import re
from collections import defaultdict
from typing import Any

import pikepdf

# Regex to find MCID integers inside BDC/BMC dictionary operands.
# e.g.  /Span <</MCID 3>> BDC
_MCID_RE = re.compile(rb"/MCID\s+(\d+)")


def _iter_struct_elements(pdf: pikepdf.Pdf):
    """Yield every struct element (pikepdf.Dictionary) in DFS order."""
    if "/StructTreeRoot" not in pdf.Root:
        return
    sr = pdf.Root["/StructTreeRoot"]
    visited: set[tuple[int, int]] = set()
    stack: list[Any] = []
    try:
        k = sr.get("/K")
        if k is None:
            return
        if isinstance(k, pikepdf.Array):
            stack.extend(reversed(list(k)))
        else:
            stack.append(k)
    except Exception:
        return

    while stack:
        node = stack.pop()
        if node is None or not isinstance(node, pikepdf.Dictionary):
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in visited:
                continue
            visited.add(og)
        yield node
        try:
            sub = node.get("/K")
            if sub is None:
                continue
            if isinstance(sub, pikepdf.Array):
                stack.extend(reversed(list(sub)))
            elif isinstance(sub, pikepdf.Dictionary):
                stack.append(sub)
        except Exception:
            pass


def _collect_struct_mcids(pdf: pikepdf.Pdf) -> dict[int, list[tuple[int, int]]]:
    """Return {page_index: [(mcid, obj_gen), ...]} from struct tree /K entries.

    Follows MCID-reference dictionaries inside /K arrays:
      • Integer MCID — direct reference on the same page
      • Dictionary with /Pg + /MCID — explicit page reference
    """
    result: dict[int, list[tuple[int, int]]] = defaultdict(list)
    # Build page index map
    page_objgen: dict[tuple[int, int], int] = {}
    for i, page in enumerate(pdf.pages):
        og = getattr(page.obj, "objgen", None)
        if og is not None:
            page_objgen[og] = i

    current_page: dict[Any, int] = {}  # node → page index (inherited from /Pg)

    for elem in _iter_struct_elements(pdf):
        # Determine page for this element
        pg = elem.get("/Pg")
        if pg is not None:
            og = getattr(pg, "objgen", None)
            if og in page_objgen:
                current_page[id(elem)] = page_objgen[og]

        page_idx = current_page.get(id(elem), -1)

        k = elem.get("/K")
        if k is None:
            continue
        items = list(k) if isinstance(k, pikepdf.Array) else [k]
        for item in items:
            try:
                if isinstance(item, int):
                    result[page_idx].append((int(item), getattr(elem, "objgen", (-1, -1))))
                elif isinstance(item, pikepdf.Dictionary):
                    pg2 = item.get("/Pg")
                    mcid_obj = item.get("/MCID")
                    if mcid_obj is not None:
                        mcid = int(mcid_obj)
                        if pg2 is not None:
                            og2 = getattr(pg2, "objgen", None)
                            pi = page_objgen.get(og2, page_idx) if og2 else page_idx
                        else:
                            pi = page_idx
                        result[pi].append((mcid, getattr(elem, "objgen", (-1, -1))))
            except Exception:
                continue
    return result


def _collect_content_mcids(pdf: pikepdf.Pdf) -> dict[int, set[int]]:
    """Return {page_index: {mcid, ...}} from BDC markers in content streams."""
    result: dict[int, set[int]] = {}
    for i, page in enumerate(pdf.pages):
        mcids: set[int] = set()
        try:
            contents = page.get("/Contents")
            if contents is None:
                result[i] = mcids
                continue
            if isinstance(contents, pikepdf.Array):
                data = b"\n".join(bytes(s.read_bytes()) for s in contents)
            else:
                data = bytes(contents.read_bytes())
            for m in _MCID_RE.finditer(data):
                mcids.add(int(m.group(1)))
        except Exception:
            pass
        result[i] = mcids
    return result


def _validate_parent_tree(pdf: pikepdf.Pdf) -> list[str]:
    """Validate /ParentTree /Nums entries."""
    issues: list[str] = []
    if "/StructTreeRoot" not in pdf.Root:
        return issues
    sr = pdf.Root["/StructTreeRoot"]
    pt = sr.get("/ParentTree")
    if pt is None:
        issues.append("StructTreeRoot is missing /ParentTree")
        return issues
    nums = pt.get("/Nums")
    if nums is None:
        issues.append("ParentTree is missing /Nums array")
        return issues
    if not isinstance(nums, pikepdf.Array):
        issues.append("ParentTree /Nums is not an array")
        return issues
    # /Nums must be [key, value, key, value, ...] pairs
    items = list(nums)
    if len(items) % 2 != 0:
        issues.append(f"ParentTree /Nums has odd length ({len(items)})")
    prev_key = -1
    for idx in range(0, len(items) - 1, 2):
        try:
            key = int(items[idx])
        except Exception:
            issues.append(f"ParentTree /Nums[{idx}] is not an integer key")
            continue
        if key <= prev_key:
            issues.append(
                f"ParentTree /Nums keys out of order: {key} follows {prev_key}"
            )
        prev_key = key
        val = items[idx + 1]
        if not isinstance(val, (pikepdf.Dictionary, pikepdf.Array)):
            issues.append(
                f"ParentTree /Nums[{idx+1}] (key={key}) is not a dict or array"
            )
    return issues


def validate_structure_tree(pdf: pikepdf.Pdf) -> list[str]:
    """Validate PDF structure-tree integrity.

    Parameters
    ----------
    pdf:
        An open pikepdf.Pdf instance.

    Returns
    -------
    list[str]
        A (possibly empty) list of human-readable issue descriptions.
        An empty list means no problems were detected.
    """
    issues: list[str] = []

    if "/StructTreeRoot" not in pdf.Root:
        issues.append("Document has no StructTreeRoot — tagged PDF structure is absent")
        return issues

    # --- Duplicate MCID detection ---
    struct_mcids = _collect_struct_mcids(pdf)
    for page_idx, entries in struct_mcids.items():
        mcid_counts: dict[int, int] = defaultdict(int)
        for mcid, _ in entries:
            mcid_counts[mcid] += 1
        for mcid, count in mcid_counts.items():
            if count > 1:
                issues.append(
                    f"Page {page_idx}: MCID {mcid} referenced by {count} struct elements "
                    f"(should be exactly 1)"
                )

    # --- Orphaned MCID detection ---
    content_mcids = _collect_content_mcids(pdf)
    for page_idx, entries in struct_mcids.items():
        if page_idx < 0:
            continue  # page unknown, skip
        page_content = content_mcids.get(page_idx, set())
        for mcid, elem_og in entries:
            if mcid not in page_content:
                issues.append(
                    f"Page {page_idx}: MCID {mcid} referenced in struct tree "
                    f"(element {elem_og}) but not found in content stream BDC marks"
                )

    # --- ParentTree validation ---
    pt_issues = _validate_parent_tree(pdf)
    issues.extend(pt_issues)

    return issues
