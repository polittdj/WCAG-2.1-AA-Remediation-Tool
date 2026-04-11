"""fix_widget_mapper.py — connect every AcroForm Widget to the structure
tree by creating /Form structure elements and writing a flat /Nums
ParentTree. Never modifies the input file.

For every leaf field with /Rect (collected recursively from /AcroForm
/Fields, including kids of container fields), create a /Form
StructElem whose /K points to an /OBJR referencing the widget. Assign
the widget a fresh /StructParent integer key, attach the new /Form to
the document's top-level structure element, and rebuild the
ParentTree as a flat /Nums array containing all old entries plus the
new ones.
"""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_INDEX_ONLY_RE = re.compile(r"^\d+$")


def _clean_name(t: str) -> str:
    """Normalise a field's /T value into a readable accessible name."""
    if not t or _INDEX_ONLY_RE.match(t.strip()):
        return ""
    clean = t.strip()
    for suffix in ("_af_date", "_af_number", "_af_currency", "_af_percent"):
        if clean.lower().endswith(suffix):
            clean = clean[: -len(suffix)]
    clean = clean.replace("_", " ").replace("-", " ")
    clean = re.sub(r"\s+", " ", clean).strip()
    return clean


def _safe_str(value: Any) -> str:
    if value is None:
        return ""
    try:
        return str(value)
    except Exception:
        return ""


def _name_eq(value: Any, expected: str) -> bool:
    s = _safe_str(value)
    if s.startswith("/"):
        s = s[1:]
    target = expected[1:] if expected.startswith("/") else expected
    return s == target


def _page_raw(page: Any) -> Any:
    """Return the raw underlying Object for a pikepdf Page helper."""
    obj = getattr(page, "obj", None)
    return obj if obj is not None else page


def _build_page_lookup(pdf: pikepdf.Pdf) -> dict[Any, tuple[int, Any]]:
    """Map widget objgen -> (page_index, raw_page_obj) by scanning /Annots."""
    lookup: dict[Any, tuple[int, Any]] = {}
    for idx, page in enumerate(pdf.pages):
        try:
            annots = page.get("/Annots") or []
        except Exception:
            continue
        try:
            iter_annots = list(annots)
        except Exception:
            continue
        page_raw = _page_raw(page)
        for annot in iter_annots:
            try:
                if not _name_eq(annot.get("/Subtype"), "/Widget"):
                    continue
                lookup[annot.objgen] = (idx, page_raw)
            except Exception:
                continue
    return lookup


def _collect_leaf_widgets(field_array: Any) -> list[Any]:
    """Recursively collect every field with /Rect under field_array."""
    leaves: list[Any] = []
    if field_array is None:
        return leaves
    try:
        items = list(field_array)
    except Exception:
        return leaves
    for field in items:
        try:
            if field.get("/Rect") is not None:
                leaves.append(field)
            kids = field.get("/Kids")
            if kids is not None and len(kids) > 0:
                leaves.extend(_collect_leaf_widgets(kids))
        except Exception as e:
            logger.warning("collect_leaf_widgets: skipping field: %s", e)
            continue
    return leaves


def _read_numtree(tree: Any) -> list[tuple[int, Any]]:
    """Read every (key, value) entry in a number tree (flat /Nums or /Kids)."""
    out: list[tuple[int, Any]] = []
    if tree is None:
        return out
    try:
        nums = tree.get("/Nums")
    except Exception:
        nums = None
    if nums is not None:
        try:
            n = len(nums)
        except Exception:
            n = 0
        for i in range(0, n - 1, 2):
            try:
                out.append((int(nums[i]), nums[i + 1]))
            except Exception:
                continue
    try:
        kids = tree.get("/Kids")
    except Exception:
        kids = None
    if kids is not None:
        try:
            for kid in kids:
                out.extend(_read_numtree(kid))
        except Exception:
            pass
    return out


def _find_document_element(pdf: pikepdf.Pdf) -> Any:
    """Return the StructElem that should parent newly-created /Form elements.

    Prefers an explicit /Document child of /StructTreeRoot; falls back to
    /StructTreeRoot itself if no /Document is found.
    """
    try:
        st = pdf.Root.get("/StructTreeRoot")
    except Exception:
        return None
    if st is None:
        return None
    try:
        k = st.get("/K")
    except Exception:
        k = None
    if isinstance(k, pikepdf.Array):
        for item in k:
            try:
                if _name_eq(item.get("/S"), "/Document"):
                    return item
            except Exception:
                continue
    elif isinstance(k, pikepdf.Dictionary):
        try:
            if _name_eq(k.get("/S"), "/Document"):
                return k
        except Exception:
            pass
    return st


def _append_child(parent: Any, child_ref: Any) -> None:
    """Append child_ref to parent's /K, handling missing/scalar/array forms."""
    try:
        existing = parent.get("/K")
    except Exception:
        existing = None
    if existing is None:
        parent["/K"] = pikepdf.Array([child_ref])
        return
    if isinstance(existing, pikepdf.Array):
        existing.append(child_ref)
        return
    parent["/K"] = pikepdf.Array([existing, child_ref])


def _resolve_page(
    pdf: pikepdf.Pdf,
    widget: Any,
    page_lookup: dict[Any, tuple[int, Any]],
) -> Any:
    """Return the raw underlying page Object that owns this widget, or None."""
    try:
        p_ref = widget.get("/P")
    except Exception:
        p_ref = None
    if p_ref is not None:
        try:
            target_objgen = p_ref.objgen
            for pg in pdf.pages:
                if pg.objgen == target_objgen:
                    return _page_raw(pg)
        except Exception:
            pass
    found = page_lookup.get(getattr(widget, "objgen", None))
    if found is not None:
        return found[1]
    return None


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_widget_mapper(input_path: str, output_path: str) -> dict:
    """Map every AcroForm widget into the structure tree.

    Returns: {"widgets_mapped", "widgets_skipped", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "widgets_mapped": 0,
        "widgets_skipped": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            # STEP 1 — page lookup
            page_lookup = _build_page_lookup(pdf)

            # STEP 2 — collect every leaf widget
            try:
                acroform = pdf.Root.get("/AcroForm")
            except Exception:
                acroform = None
            if acroform is None:
                logger.info("no /AcroForm — nothing to map")
                pdf.save(out_str)
                return result

            try:
                top_fields = acroform.get("/Fields") or pikepdf.Array()
            except Exception:
                top_fields = pikepdf.Array()

            all_widgets = _collect_leaf_widgets(top_fields)
            logger.info("collected %d leaf widgets", len(all_widgets))

            if not all_widgets:
                pdf.save(out_str)
                return result

            # Ensure StructTreeRoot exists. If it doesn't we cannot map.
            try:
                struct_root = pdf.Root.get("/StructTreeRoot")
            except Exception:
                struct_root = None
            if struct_root is None:
                result["errors"].append("no /StructTreeRoot — cannot map widgets")
                logger.warning("no StructTreeRoot — copying input")
                pdf.save(out_str)
                return result

            # STEP 3 — read existing ParentTree entries
            try:
                existing_pt = struct_root.get("/ParentTree")
            except Exception:
                existing_pt = None
            existing_entries: list[tuple[int, Any]] = _read_numtree(existing_pt) if existing_pt is not None else []

            # Compute a safe next_key: max(file's hint, max existing key + 1).
            try:
                file_next_key = int(struct_root.get("/ParentTreeNextKey", 0))
            except Exception:
                file_next_key = 0
            max_existing = max((k for k, _ in existing_entries), default=-1)
            next_key = max(file_next_key, max_existing + 1, 0)

            # STEP 4 — create a /Form StructElem for every widget
            #
            # Idempotency: if the widget already has a /StructParent
            # that resolves to a /Form element in the existing
            # ParentTree, skip it — a prior run already mapped it.
            existing_by_key = dict(existing_entries)
            doc_elem = _find_document_element(pdf)
            new_entries: list[tuple[int, Any]] = []

            for widget in all_widgets:
                try:
                    # Idempotency check: skip widgets already mapped.
                    try:
                        sp_obj = widget.get("/StructParent")
                        if sp_obj is not None:
                            sp_key = int(sp_obj)
                            existing_form = existing_by_key.get(sp_key)
                            if (
                                existing_form is not None
                                and hasattr(existing_form, "get")
                                and _name_eq(existing_form.get("/S"), "/Form")
                            ):
                                result["widgets_skipped"] += 1
                                continue
                    except Exception:
                        pass

                    page_obj = _resolve_page(pdf, widget, page_lookup)
                    if page_obj is None:
                        result["widgets_skipped"] += 1
                        result["errors"].append(f"widget {getattr(widget, 'objgen', '?')}: no page")
                        continue

                    # Accessible name from /TU, falling back to /T
                    tu = _safe_str(widget.get("/TU")).strip()
                    t = _safe_str(widget.get("/T")).strip()
                    name = tu if tu else _clean_name(t)
                    if not name:
                        name = "Form field"

                    # OBJR child node referencing the widget
                    objr = pikepdf.Dictionary(
                        {
                            "/Type": pikepdf.Name("/OBJR"),
                            "/Pg": page_obj,
                            "/Obj": widget,
                        }
                    )
                    objr_ref = pdf.make_indirect(objr)

                    # /Form structure element
                    form_elem = pikepdf.Dictionary(
                        {
                            "/Type": pikepdf.Name("/StructElem"),
                            "/S": pikepdf.Name("/Form"),
                            "/Pg": page_obj,
                            "/Alt": pikepdf.String(name),
                            "/K": objr_ref,
                        }
                    )
                    form_ref = pdf.make_indirect(form_elem)

                    if doc_elem is not None:
                        try:
                            form_elem["/P"] = doc_elem
                        except Exception:
                            pass
                        try:
                            _append_child(doc_elem, form_ref)
                        except Exception as e:
                            logger.warning("could not append form to document: %s", e)

                    widget["/StructParent"] = pikepdf.Integer(next_key)
                    new_entries.append((next_key, form_ref))
                    next_key += 1
                    result["widgets_mapped"] += 1
                except Exception as e:
                    result["widgets_skipped"] += 1
                    label = _safe_str(widget.get("/T")) if widget is not None else "?"
                    msg = f"widget {label!r}: {type(e).__name__}: {e}"
                    result["errors"].append(msg)
                    logger.warning(msg)
                    continue

            # STEP 5 — write a flat /Nums ParentTree
            all_entries = list(existing_entries) + list(new_entries)
            all_entries.sort(key=lambda kv: kv[0])

            seen: set[int] = set()
            deduped: list[tuple[int, Any]] = []
            for k, v in all_entries:
                if k in seen:
                    continue
                seen.add(k)
                deduped.append((k, v))

            flat = pikepdf.Array()
            for k, v in deduped:
                flat.append(pikepdf.Integer(k))
                flat.append(v)

            new_pt = pdf.make_indirect(pikepdf.Dictionary({"/Nums": flat}))
            struct_root["/ParentTree"] = new_pt
            struct_root["/ParentTreeNextKey"] = pikepdf.Integer(next_key)

            pdf.save(out_str)

        logger.info(
            "fix_widget_mapper: mapped=%d skipped=%d errors=%d",
            result["widgets_mapped"],
            result["widgets_skipped"],
            len(result["errors"]),
        )
        return result

    except Exception as e:
        logger.exception("fix_widget_mapper failed for %s", in_str)
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
        print("usage: python fix_widget_mapper.py <input.pdf> <output.pdf>")
        return 2
    res = fix_widget_mapper(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
