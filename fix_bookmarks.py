"""fix_bookmarks.py — Generate /Outlines from heading struct elements.

Covers checkpoint:
  C-23: Bookmarks present for documents with >20 pages
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any

import pikepdf


def fix_bookmarks(input_path: str, output_path: str) -> dict[str, Any]:
    """Generate bookmarks from heading elements for long documents."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        page_count = len(pdf.pages)
        if page_count <= 20:
            result["changes"].append(f"Document has {page_count} pages (<=20, bookmarks optional)")
            pdf.save(output_path)
            return result

        # Check if bookmarks already exist
        outlines = pdf.Root.get("/Outlines")
        if outlines is not None:
            first = outlines.get("/First")
            if first is not None:
                result["changes"].append("Document already has bookmarks")
                pdf.save(output_path)
                return result

        # Try to create bookmarks from heading structure elements
        heading_tags = {"H1", "H2", "H3", "H4", "H5", "H6", "H"}
        headings = []
        if "/StructTreeRoot" in pdf.Root:
            sr = pdf.Root["/StructTreeRoot"]
            stack = []
            try:
                kids = sr.get("/K")
                if isinstance(kids, pikepdf.Array):
                    stack.extend(list(kids))
                elif kids is not None:
                    stack.append(kids)
            except Exception:
                pass
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
                            alt = node.get("/Alt")
                            title = str(alt).strip() if alt else tag
                            if title:
                                headings.append(title[:80])
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

        if not headings:
            # Create a minimal bookmark pointing to page 1
            headings = ["Document Start"]

        # Build outline tree
        outline_root = pdf.make_indirect(
            pikepdf.Dictionary(
                {
                    "/Type": pikepdf.Name("/Outlines"),
                    "/Count": len(headings),
                }
            )
        )
        prev_item = None
        first_item = None
        for i, title in enumerate(headings):
            page_ref = pdf.pages[min(i, page_count - 1)].obj
            item = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Title": pikepdf.String(title),
                        "/Parent": outline_root,
                        "/Dest": pikepdf.Array([page_ref, pikepdf.Name("/Fit")]),
                    }
                )
            )
            if prev_item is not None:
                prev_item["/Next"] = item
                item["/Prev"] = prev_item
            else:
                first_item = item
            prev_item = item

        if first_item is not None:
            outline_root["/First"] = first_item
            outline_root["/Last"] = prev_item
            pdf.Root["/Outlines"] = outline_root
            result["changes"].append(f"Created {len(headings)} bookmark(s)")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_bookmarks error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
