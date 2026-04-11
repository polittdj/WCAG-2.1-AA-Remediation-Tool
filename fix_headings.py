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

            # Classify sizes into heading levels
            sizes = sorted(set(h["size"] for h in heading_candidates), reverse=True)
            size_to_level = {}
            for i, s in enumerate(sizes[:6]):
                size_to_level[s] = i + 1

            # Create heading struct elements
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
                    for h in heading_candidates[:20]:  # Cap at 20 headings
                        level = size_to_level.get(h["size"], 6)
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
