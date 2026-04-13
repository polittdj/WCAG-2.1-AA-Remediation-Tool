"""fix_headings.py — Detect heading-like text and create H1-H6 struct elements.

Covers checkpoints:
  C-19: Heading tags present
  C-20: Heading nesting (no skipped levels)

Strategy:
  1. Walk existing struct tree for any H1-H6 elements
  2. If none found, use PyMuPDF to detect large/bold text blocks
  3. Classify by font size into H1-H6
  4. Create struct elements in the tree
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any

import pikepdf


def _has_headings(pdf: pikepdf.Pdf) -> bool:
    """Check if struct tree already has H1-H6 elements."""
    if "/StructTreeRoot" not in pdf.Root:
        return False
    heading_tags = {"H1", "H2", "H3", "H4", "H5", "H6", "H"}
    stack = []
    try:
        kids = pdf.Root["/StructTreeRoot"].get("/K")
        if kids is None:
            return False
        if isinstance(kids, pikepdf.Array):
            stack.extend(list(kids))
        else:
            stack.append(kids)
    except Exception:
        return False
    seen = set()
    while stack:
        node = stack.pop()
        if node is None or not isinstance(node, pikepdf.Dictionary):
            continue
        try:
            key = getattr(node, "objgen", None)
            if key is not None:
                if key in seen:
                    continue
                seen.add(key)
        except Exception:
            pass
        try:
            s = node.get("/S")
            if s is not None:
                tag = str(s).lstrip("/")
                if tag in heading_tags:
                    return True
        except Exception:
            pass
        try:
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(list(sub))
                elif isinstance(sub, pikepdf.Dictionary):
                    stack.append(sub)
        except Exception:
            pass
    return False


def _demote_extra_h1s(pdf: pikepdf.Pdf) -> int:
    """Walk the struct tree and demote all H1 elements after the first to H2.

    IRS forms and many real-world PDFs have multiple H1 elements (one per
    section heading), which fails C-20.  The PDF/UA rule is: exactly one H1.
    We keep the first H1 and silently promote all subsequent H1 nodes to H2.

    Returns the number of H1 elements demoted (0 means nothing changed).
    """
    if "/StructTreeRoot" not in pdf.Root:
        return 0
    try:
        sr = pdf.Root["/StructTreeRoot"]
    except Exception:
        return 0

    h1_seen = 0
    demoted = 0

    # Iterative pre-order DFS in document order (left → right, parent → child).
    stack: list[Any] = []
    try:
        k = sr.get("/K")
        if k is None:
            return 0
        if isinstance(k, pikepdf.Array):
            stack.extend(reversed(list(k)))
        else:
            stack.append(k)
    except Exception:
        return 0

    visited: set[tuple[int, int]] = set()
    while stack:
        node = stack.pop()
        if node is None or not isinstance(node, pikepdf.Dictionary):
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in visited:
                continue
            visited.add(og)
        try:
            s = node.get("/S")
            if s is not None and str(s).lstrip("/") == "H1":
                h1_seen += 1
                if h1_seen > 1:
                    node["/S"] = pikepdf.Name("/H2")
                    demoted += 1
        except Exception:
            pass
        try:
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(reversed(list(sub)))
                elif isinstance(sub, pikepdf.Dictionary):
                    stack.append(sub)
        except Exception:
            pass

    return demoted


def _fix_heading_levels(pdf: pikepdf.Pdf) -> int:
    """Promote headings that skip levels so the sequence has no gaps.

    Example: H1 → H3 → H4 becomes H1 → H2 → H3.
    This satisfies C-20's "no skipped levels" rule.

    Returns the number of heading elements modified.
    """
    if "/StructTreeRoot" not in pdf.Root:
        return 0
    try:
        sr = pdf.Root["/StructTreeRoot"]
    except Exception:
        return 0

    # Collect (level, node) in document order.
    heading_nodes: list[tuple[int, Any]] = []
    stack: list[Any] = []
    try:
        k = sr.get("/K")
        if k is None:
            return 0
        if isinstance(k, pikepdf.Array):
            stack.extend(reversed(list(k)))
        else:
            stack.append(k)
    except Exception:
        return 0

    visited: set[tuple[int, int]] = set()
    while stack:
        node = stack.pop()
        if node is None or not isinstance(node, pikepdf.Dictionary):
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in visited:
                continue
            visited.add(og)
        try:
            s = node.get("/S")
            if s is not None:
                tag = str(s).lstrip("/")
                if tag in ("H1", "H2", "H3", "H4", "H5", "H6"):
                    level = int(tag[1])
                    heading_nodes.append((level, node))
        except Exception:
            pass
        try:
            sub = node.get("/K")
            if sub is not None:
                if isinstance(sub, pikepdf.Array):
                    stack.extend(reversed(list(sub)))
                elif isinstance(sub, pikepdf.Dictionary):
                    stack.append(sub)
        except Exception:
            pass

    if not heading_nodes:
        return 0

    modified = 0
    prev_level = 0
    for level, node in heading_nodes:
        if level == 1:
            prev_level = 1
            continue
        # If this heading jumps more than one level from the previous, promote it.
        max_allowed = prev_level + 1
        if level > max_allowed:
            node["/S"] = pikepdf.Name(f"/H{max_allowed}")
            modified += 1
            prev_level = max_allowed
        else:
            prev_level = level

    return modified


def fix_headings(input_path: str, output_path: str) -> dict[str, Any]:
    """Detect and tag heading elements."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        if _has_headings(pdf):
            result["changes"].append("Document already has heading tags")
            # Enforce single-H1 rule first (C-20): demote extra H1s to H2.
            demoted = _demote_extra_h1s(pdf)
            if demoted:
                result["changes"].append(
                    f"Demoted {demoted} duplicate H1 element(s) to H2 (C-20)"
                )
            # Then fix any remaining level gaps (e.g. H1 → H3 → promote to H2).
            promoted = _fix_heading_levels(pdf)
            if promoted:
                result["changes"].append(
                    f"Promoted {promoted} heading element(s) to fill skipped levels (C-20)"
                )
            pdf.save(output_path)
            return result

        # Use PyMuPDF to detect large text that could be headings
        try:
            import fitz

            doc = fitz.open(input_path)
            heading_candidates = []
            for page_num in range(len(doc)):
                page = doc[page_num]
                blocks = page.get_text("dict", flags=fitz.TEXT_PRESERVE_WHITESPACE)
                for block in blocks.get("blocks", []):
                    if block.get("type") != 0:  # text blocks only
                        continue
                    for line in block.get("lines", []):
                        for span in line.get("spans", []):
                            size = span.get("size", 0)
                            text = span.get("text", "").strip()
                            flags = span.get("flags", 0)
                            is_bold = bool(flags & 16)
                            if text and size >= 14 and len(text) < 200:
                                heading_candidates.append(
                                    {
                                        "text": text,
                                        "size": size,
                                        "bold": is_bold,
                                        "page": page_num,
                                    }
                                )
            doc.close()

            if not heading_candidates:
                result["changes"].append("No heading candidates detected")
                pdf.save(output_path)
                return result

            # Classify sizes into heading levels. Each distinct font
            # size gets a level, with the LARGEST size = H1, next = H2,
            # etc. Cap at 6 levels total.
            sizes = sorted(set(h["size"] for h in heading_candidates), reverse=True)
            size_to_level = {}
            for i, s in enumerate(sizes[:6]):
                size_to_level[s] = i + 1
            # Any remaining sizes map to H6.
            for s in sizes[6:]:
                size_to_level[s] = 6

            # Create heading struct elements. IMPORTANT: only ONE H1
            # allowed in the final struct tree. The first candidate at
            # the largest size becomes H1; any subsequent candidates at
            # that same largest size are demoted to H2 (so screen
            # readers see a proper hierarchy).
            if "/StructTreeRoot" in pdf.Root:
                sr = pdf.Root["/StructTreeRoot"]
                doc_elem = None
                try:
                    k = sr.get("/K")
                    if isinstance(k, pikepdf.Array) and len(k) > 0:
                        doc_elem = k[0]
                    elif isinstance(k, pikepdf.Dictionary):
                        doc_elem = k
                except Exception:
                    pass

                if doc_elem is not None:
                    added = 0
                    h1_used = False
                    for h in heading_candidates[:20]:  # Cap at 20 headings
                        level = size_to_level.get(h["size"], 6)
                        # Ensure only a single H1 in the output tree.
                        if level == 1:
                            if h1_used:
                                level = 2
                            else:
                                h1_used = True
                        h_elem = pdf.make_indirect(
                            pikepdf.Dictionary(
                                {
                                    "/Type": pikepdf.Name("/StructElem"),
                                    "/S": pikepdf.Name(f"/H{level}"),
                                    "/Alt": pikepdf.String(h["text"][:100]),
                                }
                            )
                        )
                        try:
                            dk = doc_elem.get("/K")
                            if dk is None:
                                doc_elem["/K"] = pikepdf.Array([h_elem])
                            elif isinstance(dk, pikepdf.Array):
                                dk.append(h_elem)
                            else:
                                doc_elem["/K"] = pikepdf.Array([dk, h_elem])
                            added += 1
                        except Exception:
                            continue
                    if added:
                        result["changes"].append(f"Added {added} heading struct elements (H1-H6)")

        except ImportError:
            result["errors"].append("PyMuPDF not available for heading detection")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_headings error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
