"""fix_widget_tu.py — populate missing /TU (accessible name) on form widgets.

PDF form widgets need a /TU entry ("user-visible name") so that assistive
technology announces something meaningful when a user tabs onto the
control. The absence of /TU fails WCAG 1.1.1 (Non-text Content), 2.4.6
(Headings and Labels), and 4.1.2 (Name, Role, Value), and PAC 2024
reports each one as an error.

For every widget whose /TU is missing or empty, this module derives a
name in this order:

  1. /TU on the widget itself (already correct — skipped).
  2. Visible text NEAR the widget (~50pt above or to the left of the
     widget's /Rect) — this is the user-facing label and is what a
     sighted user sees. This is the most important source.
  3. /T on the widget, if it's a real label (not empty / not a bare
     digit like "0" / "1" / ...).
  4. /T on the field's /Parent, same rules.
  5. Walk further up the /Parent chain until we find something usable.
  6. Last resort: "Form field" / "Text field" / etc. based on /FT.

The name is normalised: trailing "_af_date" / "_af_number" suffixes
(Acrobat date/number widgets) are stripped, underscores and hyphens
become spaces, runs of whitespace collapse to a single space, and the
result is trimmed. The input file is never modified.
"""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Iterator

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Name normalisation
# ---------------------------------------------------------------------------

# Numeric /T values on group children ("0", "1", "2"…) carry no meaning
# on their own — they're just indices into a parent /Kids array.
_INDEX_ONLY_RE = re.compile(r"^\d+$")

_AF_SUFFIXES = (
    "_af_date",
    "_af_time",
    "_af_number",
    "_af_currency",
    "_af_percent",
    "_af_zip",
    "_af_phone",
    "_af_ssn",
)


def _clean_label(raw: str) -> str:
    """Normalise a /T or /TU string into a human-readable accessible name.

    Returns an empty string when the input is empty or a bare index.
    """
    if raw is None:
        return ""
    s = str(raw).strip()
    if not s or _INDEX_ONLY_RE.match(s):
        return ""
    lowered = s.lower()
    for suffix in _AF_SUFFIXES:
        if lowered.endswith(suffix):
            s = s[: -len(suffix)]
            break
    s = s.replace("_", " ").replace("-", " ")
    s = re.sub(r"\s+", " ", s).strip()
    return s


def _clean_visible_label(raw: str) -> str:
    """Normalise a visible label extracted from page text.

    Unlike _clean_label, this keeps the original spacing and case but
    strips trailing colons/asterisks/parentheses and excess whitespace.
    """
    if not raw:
        return ""
    s = str(raw).strip()
    # Strip trailing punctuation commonly used on form labels.
    s = re.sub(r"[\s:*\u00a0()]+$", "", s)
    # Collapse whitespace.
    s = re.sub(r"\s+", " ", s).strip()
    # Don't accept obviously generic strings.
    if not s or s.lower() in ("field", "form field", "input"):
        return ""
    if _INDEX_ONLY_RE.match(s):
        return ""
    return s


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


# ---------------------------------------------------------------------------
# Widget iteration
# ---------------------------------------------------------------------------


def _iter_widgets(pdf: pikepdf.Pdf) -> Iterator[Any]:
    """Yield every Widget annotation with a /Rect from every page."""
    for page in pdf.pages:
        try:
            annots = page.get("/Annots")
        except Exception:
            annots = None
        if annots is None:
            continue
        try:
            iter_annots = list(annots)
        except Exception:
            continue
        for annot in iter_annots:
            try:
                if not _name_eq(annot.get("/Subtype"), "/Widget"):
                    continue
                if "/Rect" not in annot:
                    continue
                yield annot
            except Exception:
                continue


def _iter_form_fields(pdf: pikepdf.Pdf) -> Iterator[Any]:
    """Yield every field dict reachable from /AcroForm /Fields.

    Walks the field tree recursively so non-terminal field nodes (parents
    of /Kids) are visited in addition to terminal widget annotations. PAC
    2024 audits /TU on non-terminal field nodes too — if a parent field
    has a meaningful /T, it needs a matching /TU or PAC flags it under
    WCAG 1.1.1 ("Alternate field name entry missing in form field …").

    Fields are yielded depth-first parent-before-children. Cycles (a
    malformed PDF pointing /Kids at itself) are guarded against by
    tracking objgens.
    """
    try:
        acroform = pdf.Root.get("/AcroForm")
    except Exception:
        acroform = None
    if acroform is None:
        return
    try:
        fields = acroform.get("/Fields")
    except Exception:
        fields = None
    if fields is None:
        return

    seen: set[tuple[int, int]] = set()
    stack: list[Any] = []
    try:
        for f in fields:
            stack.append(f)
    except Exception:
        return

    while stack:
        node = stack.pop()
        if node is None:
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in seen:
                continue
            seen.add(og)
        yield node
        try:
            kids = node.get("/Kids")
        except Exception:
            kids = None
        if kids is None:
            continue
        try:
            for k in kids:
                stack.append(k)
        except Exception:
            continue


def _find_page_for_widget(pdf: pikepdf.Pdf, widget: Any) -> int | None:
    """Return the 0-indexed page number of the page containing `widget`."""
    try:
        widget_og = getattr(widget, "objgen", None)
    except Exception:
        widget_og = None
    for i, page in enumerate(pdf.pages):
        try:
            annots = page.get("/Annots")
            if annots is None:
                continue
            for annot in list(annots):
                try:
                    og = getattr(annot, "objgen", None)
                    if og is not None and og == widget_og:
                        return i
                except Exception:
                    continue
        except Exception:
            continue
    return None


def _extract_nearby_label(
    pdf_path: str,
    page_index: int,
    rect: tuple[float, float, float, float],
    search_radius: float = 50.0,
) -> str:
    """Use PyMuPDF to find visible text near a widget's rectangle.

    `rect` is (x0, y0, x1, y1) in PDF user space where y grows upward.
    PyMuPDF uses a y-down coordinate system (y grows downward), so we
    translate via the page height.

    Looks for text blocks whose bounding box is within `search_radius`
    points of the widget's left or top edge. Returns the closest text
    block after cleaning, or "" if no suitable label is found.
    """
    try:
        import fitz  # type: ignore
    except Exception:
        return ""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    try:
        if page_index < 0 or page_index >= len(doc):
            return ""
        page = doc[page_index]
        page_height = page.rect.height
        # PDF user space -> fitz space (y flipped)
        x0, y0, x1, y1 = rect
        if y0 > y1:
            y0, y1 = y1, y0
        if x0 > x1:
            x0, x1 = x1, x0
        # Flip y-axis: PDF y-up to fitz y-down
        fitz_y0 = page_height - y1  # top of widget in fitz coords
        fitz_y1 = page_height - y0  # bottom of widget in fitz coords

        # Collect all text spans on this page with their bounding boxes.
        try:
            data = page.get_text("dict")
        except Exception:
            return ""
        candidates: list[tuple[float, str]] = []  # (distance, text)
        for block in data.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    text = span.get("text", "").strip()
                    if not text:
                        continue
                    bbox = span.get("bbox")
                    if not bbox or len(bbox) < 4:
                        continue
                    sx0, sy0, sx1, sy1 = bbox
                    # Horizontal band: label is to the left of the
                    # widget. Require vertical overlap AND left of field.
                    # Fitz y grows down, so vertical overlap means
                    # the span's y-range intersects the field's y-range.
                    vertical_overlap = not (sy1 < fitz_y0 or sy0 > fitz_y1)
                    if vertical_overlap and sx1 <= x0 + 2:
                        distance = x0 - sx1
                        if 0 <= distance <= search_radius * 2:
                            candidates.append((distance, text))
                        continue
                    # Above the widget: label sits directly above the
                    # field. Require horizontal overlap and span's
                    # bottom within `search_radius` above the field top.
                    horizontal_overlap = not (sx1 < x0 or sx0 > x1)
                    if horizontal_overlap and sy1 <= fitz_y0 + 2:
                        distance = fitz_y0 - sy1
                        if 0 <= distance <= search_radius:
                            candidates.append((distance, text))
        if not candidates:
            return ""
        # Closest wins.
        candidates.sort(key=lambda c: c[0])
        for _d, text in candidates:
            cleaned = _clean_visible_label(text)
            if cleaned:
                return cleaned
        return ""
    finally:
        try:
            doc.close()
        except Exception:
            pass


def _parent_chain(widget: Any, max_depth: int = 16) -> Iterator[Any]:
    """Yield widget → parent → grandparent … following /Parent links.

    Bounded to `max_depth` to guard against pathological cycles.
    """
    node = widget
    seen: set[tuple[int, int]] = set()
    for _ in range(max_depth):
        if node is None:
            return
        key = getattr(node, "objgen", None)
        if key is not None:
            if key in seen:
                return
            seen.add(key)
        yield node
        try:
            node = node.get("/Parent")
        except Exception:
            return


# ---------------------------------------------------------------------------
# Name derivation
# ---------------------------------------------------------------------------


def _derive_name(
    widget: Any,
    pdf: pikepdf.Pdf | None = None,
    pdf_path: str | None = None,
) -> str:
    """Compute a /TU value for `widget` without touching the PDF.

    Prefers visible nearby text (what a sighted user sees) over /T
    (internal field name). Falls back through the /Parent chain, then
    to a role-based generic label.

    Returns "" only when the widget, all ancestors, and every fallback
    produced an empty string — in practice this never happens because
    we fall back to a generic label.
    """
    # STEP 0 — try to find a visible label near the widget's /Rect.
    # This is the MOST meaningful source since it's what sighted users
    # actually see on the page.
    if pdf is not None and pdf_path:
        try:
            rect = widget.get("/Rect")
            if rect is not None:
                coords = [float(x) for x in list(rect)]
                if len(coords) >= 4:
                    page_idx = _find_page_for_widget(pdf, widget)
                    if page_idx is not None:
                        visible = _extract_nearby_label(
                            pdf_path, page_idx,
                            (coords[0], coords[1], coords[2], coords[3]),
                        )
                        if visible:
                            return visible
        except Exception:
            pass

    chain = list(_parent_chain(widget))

    # STEP 1 — first ancestor with a non-empty, non-index /T.
    best_label = ""
    best_idx = -1
    for idx, node in enumerate(chain):
        try:
            t = node.get("/T")
        except Exception:
            t = None
        cleaned = _clean_label(_safe_str(t))
        if cleaned:
            best_label = cleaned
            best_idx = idx
            break

    if not best_label:
        # No label anywhere up the chain — fall back to role.
        try:
            ft = _safe_str(widget.get("/FT")).lstrip("/")
        except Exception:
            ft = ""
        role_label = {
            "Tx": "Text field",
            "Ch": "Choice field",
            "Btn": "Button",
            "Sig": "Signature field",
        }.get(ft, "Form field")
        return role_label

    # STEP 2 — if the widget's own /T was a bare index (e.g. "0")
    # but its parent had a label ("Destination"), combine them so
    # screen readers announce "Destination 1", "Destination 2" etc.
    try:
        own_t = _safe_str(widget.get("/T")).strip()
    except Exception:
        own_t = ""
    if best_idx > 0 and own_t and _INDEX_ONLY_RE.match(own_t):
        try:
            n = int(own_t) + 1
            return f"{best_label} {n}"
        except Exception:
            pass

    return best_label


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_widget_tu(input_path: str, output_path: str) -> dict:
    """Populate /TU on every widget that lacks one.

    Returns: {"widgets_total", "widgets_filled", "widgets_skipped", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "widgets_total": 0,
        "widgets_filled": 0,
        "widgets_skipped": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            # Pass 1: widgets reachable from page /Annots.
            widgets = list(_iter_widgets(pdf))
            result["widgets_total"] = len(widgets)

            # Pass 2: every field in the AcroForm /Fields tree, so
            # non-terminal parent fields also get /TU filled in. Merge
            # uniquely by objgen so a widget that's both an annotation
            # and a terminal field is only processed once.
            seen: set[tuple[int, int]] = set()
            targets: list[Any] = []
            for w in widgets:
                og = getattr(w, "objgen", None)
                if og is None or og not in seen:
                    if og is not None:
                        seen.add(og)
                    targets.append(w)
            for field in _iter_form_fields(pdf):
                og = getattr(field, "objgen", None)
                if og is not None and og in seen:
                    continue
                if og is not None:
                    seen.add(og)
                targets.append(field)

            if not targets:
                pdf.save(out_str)
                return result

            for target in targets:
                try:
                    # Only fill /TU when the field has a meaningful /T
                    # (or at least SOMETHING derivable). Blank-/T
                    # anonymous leaf widgets inherit their name from a
                    # parent via _derive_name, which walks /Parent.
                    tu_obj = target.get("/TU")
                    tu = _safe_str(tu_obj).strip()
                    if tu:
                        # Already has an accessible name; leave alone.
                        continue

                    name = _derive_name(target, pdf=pdf, pdf_path=in_str)
                    if not name:
                        result["widgets_skipped"] += 1
                        continue

                    # Skip generic role fallbacks ("Text field", "Form
                    # field") on non-terminal field nodes — the kids
                    # each have their own /TU and the parent having a
                    # generic label would be misleading. Only fill with
                    # a derived label that came from somewhere in the
                    # chain.
                    is_widget = _name_eq(target.get("/Subtype"), "/Widget")
                    if not is_widget and name in (
                        "Text field",
                        "Choice field",
                        "Button",
                        "Signature field",
                        "Form field",
                    ):
                        result["widgets_skipped"] += 1
                        continue

                    try:
                        target["/TU"] = pikepdf.String(name)
                        result["widgets_filled"] += 1
                    except Exception as e:
                        result["widgets_skipped"] += 1
                        result["errors"].append(f"field {getattr(target, 'objgen', '?')}: write /TU failed: {e}")
                except Exception as e:
                    result["widgets_skipped"] += 1
                    result["errors"].append(f"field {getattr(target, 'objgen', '?')}: {type(e).__name__}: {e}")
                    continue

            pdf.save(out_str)
        logger.info(
            "fix_widget_tu: total=%d filled=%d skipped=%d errors=%d",
            result["widgets_total"],
            result["widgets_filled"],
            result["widgets_skipped"],
            len(result["errors"]),
        )
        return result

    except Exception as e:
        logger.exception("fix_widget_tu failed for %s", in_str)
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
        print("usage: python fix_widget_tu.py <input.pdf> <output.pdf>")
        return 2
    res = fix_widget_tu(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
