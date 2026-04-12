"""fix_pdfua_meta.py — Set PDF/UA metadata, ViewerPreferences, and Suspects.

Covers checkpoints:
  C-06: PDF/UA identifier (pdfuaid:part=1 in XMP)
  C-07: ViewerPreferences DisplayDocTitle = true
  C-09: /MarkInfo /Suspects = false

This must run LAST in the pipeline because XMP metadata is fragile
and other fix modules may modify the struct tree.
"""

from __future__ import annotations

import pathlib
from typing import Any

import pikepdf


XMP_PDFUA_TEMPLATE = (
    b'<?xpacket begin="\xef\xbb\xbf" id="W5M0MpCehiHzreSzNTczkc9d"?>\n'
    b'<x:xmpmeta xmlns:x="adobe:ns:meta/">\n'
    b'<rdf:RDF xmlns:rdf="http://www.w3.org/1999/02/22-rdf-syntax-ns#">\n'
    b'  <rdf:Description rdf:about=""\n'
    b'    xmlns:dc="http://purl.org/dc/elements/1.1/"\n'
    b'    xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">\n'
    b"    <pdfuaid:part>1</pdfuaid:part>\n"
    b"  </rdf:Description>\n"
    b"</rdf:RDF>\n"
    b"</x:xmpmeta>\n"
    b'<?xpacket end="w"?>'
)


def _flatten_number_tree(node: Any, flat_nums: pikepdf.Array) -> None:
    """Recursively collect /Nums entries from a number tree with /Kids."""
    if "/Nums" in node:
        nums = node["/Nums"]
        for item in list(nums):
            flat_nums.append(item)
    if "/Kids" in node:
        for kid in list(node["/Kids"]):
            _flatten_number_tree(kid, flat_nums)


def fix_pdfua_meta(input_path: str, output_path: str) -> dict[str, Any]:
    """Inject PDF/UA metadata, set DisplayDocTitle, clear Suspects."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        # Copy input as-is
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        # --- C-06: PDF/UA identifier in XMP ---
        metadata = pdf.Root.get("/Metadata")
        if metadata is not None:
            try:
                xmp_bytes = bytes(metadata.read_bytes())
                xmp_str = xmp_bytes.decode("utf-8", errors="replace")
                if "pdfuaid" not in xmp_str.lower():
                    # Inject pdfuaid into existing XMP
                    insertion = (
                        b'  <rdf:Description rdf:about=""\n'
                        b'    xmlns:pdfuaid="http://www.aiim.org/pdfua/ns/id/">\n'
                        b"    <pdfuaid:part>1</pdfuaid:part>\n"
                        b"  </rdf:Description>\n"
                    )
                    # Insert before </rdf:RDF>
                    close_tag = b"</rdf:RDF>"
                    if close_tag in xmp_bytes:
                        new_xmp = xmp_bytes.replace(close_tag, insertion + close_tag)
                        new_stream = pdf.make_stream(new_xmp)
                        new_stream["/Type"] = pikepdf.Name("/Metadata")
                        new_stream["/Subtype"] = pikepdf.Name("/XML")
                        pdf.Root["/Metadata"] = new_stream
                        result["changes"].append("Injected pdfuaid:part=1 into existing XMP")
                    else:
                        # Replace entirely
                        new_stream = pdf.make_stream(XMP_PDFUA_TEMPLATE)
                        new_stream["/Type"] = pikepdf.Name("/Metadata")
                        new_stream["/Subtype"] = pikepdf.Name("/XML")
                        pdf.Root["/Metadata"] = new_stream
                        result["changes"].append("Replaced XMP metadata with PDF/UA template")
            except Exception as e:
                result["errors"].append(f"XMP read error: {e}")
        else:
            # No existing metadata — create from template
            new_stream = pdf.make_stream(XMP_PDFUA_TEMPLATE)
            new_stream["/Type"] = pikepdf.Name("/Metadata")
            new_stream["/Subtype"] = pikepdf.Name("/XML")
            pdf.Root["/Metadata"] = new_stream
            result["changes"].append("Created XMP metadata with pdfuaid:part=1")

        # --- C-07: ViewerPreferences DisplayDocTitle ---
        vp = pdf.Root.get("/ViewerPreferences")
        if vp is None:
            pdf.Root["/ViewerPreferences"] = pikepdf.Dictionary(
                {
                    "/DisplayDocTitle": True,
                }
            )
            result["changes"].append("Created /ViewerPreferences with DisplayDocTitle=true")
        else:
            ddt = vp.get("/DisplayDocTitle")
            if ddt is None or not bool(ddt):
                vp["/DisplayDocTitle"] = True
                result["changes"].append("Set DisplayDocTitle=true")

        # --- C-01: /MarkInfo /Marked = true ---
        mark_info = pdf.Root.get("/MarkInfo")
        if mark_info is None:
            pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
            result["changes"].append("Created /MarkInfo with /Marked=true")
            mark_info = pdf.Root["/MarkInfo"]
        else:
            marked = mark_info.get("/Marked")
            if marked is None or not bool(marked):
                mark_info["/Marked"] = True
                result["changes"].append("Set /MarkInfo /Marked=true")

        # --- C-09: /MarkInfo /Suspects = false ---
        if mark_info is not None:
            suspects = mark_info.get("/Suspects")
            if suspects is not None and bool(suspects):
                del mark_info["/Suspects"]
                result["changes"].append("Removed /Suspects=true from /MarkInfo")

        # --- C-12/C-46: Ensure minimal StructTreeRoot exists ---
        if "/StructTreeRoot" not in pdf.Root:
            doc_elem = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Type": pikepdf.Name("/StructElem"),
                        "/S": pikepdf.Name("/Document"),
                        "/K": pikepdf.Array(),
                    }
                )
            )
            parent_tree = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Nums": pikepdf.Array(),
                    }
                )
            )
            sr = pdf.make_indirect(
                pikepdf.Dictionary(
                    {
                        "/Type": pikepdf.Name("/StructTreeRoot"),
                        "/K": pikepdf.Array([doc_elem]),
                        "/ParentTree": parent_tree,
                        "/ParentTreeNextKey": 0,
                    }
                )
            )
            pdf.Root["/StructTreeRoot"] = sr
            result["changes"].append("Created minimal StructTreeRoot")

        # --- C-46: Flatten /Kids-based ParentTree to /Nums ---
        struct_root = pdf.Root.get("/StructTreeRoot")
        if struct_root is not None:
            parent_tree = struct_root.get("/ParentTree")
            if parent_tree is not None and "/Kids" in parent_tree and "/Nums" not in parent_tree:
                # Collect all entries from /Kids nodes into a flat /Nums array
                flat_nums = pikepdf.Array()
                try:
                    _flatten_number_tree(parent_tree, flat_nums)
                    del parent_tree["/Kids"]
                    parent_tree["/Nums"] = flat_nums
                    if "/Limits" in parent_tree:
                        del parent_tree["/Limits"]
                    result["changes"].append("Flattened ParentTree /Kids to /Nums")
                except Exception as e:
                    result["errors"].append(f"ParentTree flatten error: {e}")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_pdfua_meta error: {e}")
        import shutil

        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
