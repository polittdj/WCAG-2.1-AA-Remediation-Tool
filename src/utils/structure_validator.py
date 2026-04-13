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


# ---------------------------------------------------------------------------
# ParentTree rebuild (IRS-03)
# ---------------------------------------------------------------------------


def _build_mcid_to_elem(pdf: pikepdf.Pdf) -> dict[int, dict[int, Any]]:
    """Walk the struct tree and return {page_idx: {mcid: struct_elem}}.

    Only integer MCID /K entries are included (cross-page MCID-ref dicts
    with explicit /Pg are resolved to the correct page index).
    """
    # Map page object → page index for fast lookups
    page_objgen: dict[tuple[int, int], int] = {}
    for i, page in enumerate(pdf.pages):
        og = getattr(page.obj, "objgen", None)
        if og is not None:
            page_objgen[og] = i

    result: dict[int, dict[int, Any]] = defaultdict(dict)

    if "/StructTreeRoot" not in pdf.Root:
        return result

    sr = pdf.Root["/StructTreeRoot"]
    visited: set[tuple[int, int]] = set()
    # Stack items: (node, inherited_page_idx)
    stack: list[tuple[Any, int]] = []
    try:
        k = sr.get("/K")
        if k is None:
            return result
        items = list(k) if isinstance(k, pikepdf.Array) else [k]
        for item in items:
            stack.append((item, -1))
    except Exception:
        return result

    while stack:
        node, page_idx = stack.pop()
        if node is None or not isinstance(node, pikepdf.Dictionary):
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in visited:
                continue
            visited.add(og)

        # Resolve page for this element (may override inherited)
        pg = node.get("/Pg")
        if pg is not None:
            pg_og = getattr(pg, "objgen", None)
            if pg_og in page_objgen:
                page_idx = page_objgen[pg_og]

        # Process /K entries
        try:
            k = node.get("/K")
            if k is not None:
                items = list(k) if isinstance(k, pikepdf.Array) else [k]
                for item in items:
                    try:
                        if isinstance(item, int):
                            # Direct integer MCID on current page
                            if page_idx >= 0:
                                result[page_idx][int(item)] = node
                        elif isinstance(item, pikepdf.Dictionary):
                            # Could be a child struct elem or an MCID-ref dict
                            mcid_obj = item.get("/MCID")
                            if mcid_obj is not None:
                                # This is an MCID-reference dict, not a child elem
                                mcid = int(mcid_obj)
                                pg2 = item.get("/Pg")
                                if pg2 is not None:
                                    pg2_og = getattr(pg2, "objgen", None)
                                    pi = page_objgen.get(pg2_og, page_idx) if pg2_og else page_idx
                                else:
                                    pi = page_idx
                                if pi >= 0:
                                    result[pi][mcid] = node
                            else:
                                # Child struct element — recurse
                                stack.append((item, page_idx))
                    except Exception:
                        continue
        except Exception:
            pass

    return result


def validate_and_rebuild_parent_tree(pdf: pikepdf.Pdf) -> tuple[bool, int]:
    """Validate ParentTree integrity; rebuild it from scratch if broken.

    The ParentTree maps (page_index → array[mcid] → struct_element) so
    that PDF viewers can look up which struct element owns any given marked-
    content sequence.  Our remediation tools can introduce orphaned MCIDs
    (references in the struct tree that have no corresponding BDC marker in
    the content stream), which PAC reports as "4.1 Compatible" failures.

    This function:
    1. Collects all (page_idx, mcid) pairs from both the struct tree and the
       content streams.
    2. If they agree, returns (True, 0) — no changes made.
    3. If they disagree (orphaned or missing MCIDs), rebuilds the ParentTree
       so that only MCIDs actually present in the content streams are mapped,
       and returns (False, num_issues_fixed).

    Parameters
    ----------
    pdf:
        An open pikepdf.Pdf instance (modified in place when rebuild occurs).

    Returns
    -------
    (is_valid, num_fixes):
        is_valid  — True when the original ParentTree was already correct.
        num_fixes — Number of orphaned/missing MCIDs resolved during rebuild.
    """
    struct_root = pdf.Root.get("/StructTreeRoot")
    if struct_root is None:
        return True, 0

    parent_tree = struct_root.get("/ParentTree")
    if parent_tree is None:
        return True, 0

    # Collect MCIDs from both sources
    struct_map = _build_mcid_to_elem(pdf)     # {page_idx: {mcid: elem}}
    content_map = _collect_content_mcids(pdf)  # {page_idx: {mcid, ...}}

    # Compute (page_idx, mcid) sets for comparison
    struct_pairs: set[tuple[int, int]] = set()
    for pg, mcids in struct_map.items():
        for mcid in mcids:
            struct_pairs.add((pg, mcid))

    content_pairs: set[tuple[int, int]] = set()
    for pg, mcids in content_map.items():
        for mcid in mcids:
            content_pairs.add((pg, mcid))

    orphaned_struct = struct_pairs - content_pairs   # In tree, not in streams
    orphaned_content = content_pairs - struct_pairs  # In streams, not in tree

    if not orphaned_struct and not orphaned_content:
        return True, 0  # ParentTree is consistent — nothing to do

    # --- Preserve existing non-content ParentTree entries ---
    # The ParentTree contains two distinct entry types:
    #   Array  values  — page-content entries: page_idx → [elem_mcid0, elem_mcid1, ...]
    #   Dict   values  — widget/annotation entries: widget_key → Form struct elem
    # We only rebuild the Array entries; Dict entries (from fix_widget_mapper etc.)
    # must be preserved so that widget /StructParent references still resolve.
    preserved_dict_entries: dict[int, Any] = {}
    try:
        existing_nums = parent_tree.get("/Nums")
        if existing_nums is None:
            # /Kids-based number tree — flatten to collect all entries
            _flat: pikepdf.Array = pikepdf.Array()
            _flatten_number_tree(parent_tree, _flat)
            existing_nums = _flat
        if existing_nums is not None:
            en_list = list(existing_nums)
            for _i in range(0, len(en_list) - 1, 2):
                try:
                    _key = int(en_list[_i])
                    _val = en_list[_i + 1]
                    if isinstance(_val, pikepdf.Dictionary):
                        preserved_dict_entries[_key] = _val
                except Exception:
                    continue
    except Exception:
        pass  # If we can't read existing entries, just rebuild without them

    # --- Rebuild Array (page-content) entries ---
    # Only include MCIDs that exist in BOTH the struct tree and the content
    # streams (i.e. valid MCIDs that can be properly mapped).
    valid_pairs = struct_pairs & content_pairs

    # Build page_idx → {mcid: struct_elem} using only valid pairs
    page_mcid_elem: dict[int, dict[int, Any]] = defaultdict(dict)
    for pg, mcid_map in struct_map.items():
        for mcid, elem in mcid_map.items():
            if (pg, mcid) in valid_pairs:
                page_mcid_elem[pg][mcid] = elem

    # Build flat /Nums array: [pg0, [elem_mcid0, elem_mcid1, ...], pg1, ...]
    # Array index = MCID; pikepdf.Null() fills gaps for unmapped MCIDs.
    new_nums: list[Any] = []
    for pg_idx in sorted(page_mcid_elem.keys()):
        mcid_map = page_mcid_elem[pg_idx]
        if not mcid_map:
            continue
        max_mcid = max(mcid_map.keys())
        arr = pikepdf.Array()
        for mcid in range(max_mcid + 1):
            if mcid in mcid_map:
                arr.append(mcid_map[mcid])
            else:
                arr.append(pikepdf.Null())
        new_nums.append(pikepdf.Integer(pg_idx))
        new_nums.append(arr)

    # Merge preserved Dict entries back in (avoiding key collisions with
    # the page-content keys we just built).
    page_content_keys: set[int] = {
        int(new_nums[_i]) for _i in range(0, len(new_nums), 2)
    }
    for _key, _val in sorted(preserved_dict_entries.items()):
        if _key not in page_content_keys:
            new_nums.append(pikepdf.Integer(_key))
            new_nums.append(_val)

    # Sort the combined list by key (PDF spec requires number trees to be sorted).
    if new_nums:
        _pairs = [(int(new_nums[_i]), new_nums[_i + 1]) for _i in range(0, len(new_nums), 2)]
        _pairs.sort(key=lambda x: x[0])
        sorted_nums: list[Any] = []
        for _k, _v in _pairs:
            sorted_nums.append(pikepdf.Integer(_k))
            sorted_nums.append(_v)
    else:
        sorted_nums = new_nums

    new_parent_tree = pdf.make_indirect(pikepdf.Dictionary({
        "/Nums": pikepdf.Array(sorted_nums),
    }))
    struct_root["/ParentTree"] = new_parent_tree

    # Update /ParentTreeNextKey to max key + 1 (prevents key collisions).
    if sorted_nums:
        max_key = max(int(sorted_nums[_i]) for _i in range(0, len(sorted_nums), 2))
        struct_root["/ParentTreeNextKey"] = pikepdf.Integer(max_key + 1)

    num_fixes = len(orphaned_struct) + len(orphaned_content)
    return False, num_fixes
