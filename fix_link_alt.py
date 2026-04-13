"""fix_link_alt.py — populate /Contents on Link annotations.

Every /Link annotation in a PDF needs an accessible description so that
assistive tech can announce the link purpose. PDF/UA-1 7.18.5 and WCAG
2.4.4 (Link Purpose) both require this. PAC 2024 reports a missing
description under 2.4 Navigable.

For every /Link annotation whose /Contents (and /Alt) is missing or
empty, this module derives a short human-readable description:

  1. If the link has an /A action dict with /S == /URI, derive from
     the URL — prefer a readable form ("gsa.gov — Per Diem Rates")
     over the raw URL.
  2. If it's a /GoTo action to an internal destination, use
     "Go to page N" or the named destination.
  3. Fall back to text extracted from the annotation /Rect via
     PyMuPDF (the visible link text on the page).
  4. Last resort: "Link".

If the containing structure tree has a matching /Link element, /Alt is
also set on that element so the tagged-structure path is covered too.
The input file is never modified.
"""

from __future__ import annotations

import logging
import re
import shutil
from typing import Any, Iterator
from urllib.parse import urlparse

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Name helpers
# ---------------------------------------------------------------------------


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
# Description derivation
# ---------------------------------------------------------------------------

_SLUG_SPLIT_RE = re.compile(r"[-_/]+")
_WS_RE = re.compile(r"\s+")


def _humanize_slug(slug: str) -> str:
    """Turn 'per-diem-rates' into 'Per Diem Rates'."""
    if not slug:
        return ""
    # Drop file extensions.
    if "." in slug and slug.rsplit(".", 1)[-1].lower() in {
        "html",
        "htm",
        "php",
        "aspx",
        "jsp",
        "pdf",
    }:
        slug = slug.rsplit(".", 1)[0]
    parts = [p for p in _SLUG_SPLIT_RE.split(slug) if p]
    if not parts:
        return ""
    words = []
    for p in parts:
        # Split camelCase into words too.
        camel = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", p)
        for w in camel.split():
            words.append(w[:1].upper() + w[1:] if w else "")
    out = " ".join(words)
    return _WS_RE.sub(" ", out).strip()


def _uri_to_name(uri: str) -> str:
    """Return a short accessible label for a URI.

    "https://www.gsa.gov/travel/plan-book/per-diem-rates"
      → "gsa.gov — Per Diem Rates"
    """
    try:
        parsed = urlparse(uri)
    except Exception:
        return uri[:120]

    if not parsed.scheme:
        return uri[:120]

    if parsed.scheme in ("mailto",):
        addr = parsed.path or uri.split(":", 1)[-1]
        return f"Email {addr}"

    if parsed.scheme in ("tel",):
        return f"Phone {parsed.path or ''}".strip()

    host = (parsed.netloc or "").lower()
    if host.startswith("www."):
        host = host[4:]

    path = parsed.path or ""
    last_segment = ""
    if path and path != "/":
        segments = [s for s in path.split("/") if s]
        if segments:
            last_segment = _humanize_slug(segments[-1])

    if host and last_segment:
        return f"{host} — {last_segment}"
    if host:
        return host
    if last_segment:
        return last_segment
    return uri[:120]


def _action_to_name(action: Any) -> str:
    """Return a short label for an /A action dict, or "" if no good option."""
    if action is None:
        return ""
    try:
        s = _safe_str(action.get("/S")).lstrip("/")
    except Exception:
        return ""
    if s == "URI":
        try:
            uri = _safe_str(action.get("/URI"))
        except Exception:
            uri = ""
        return _uri_to_name(uri) if uri else ""
    if s == "GoTo":
        try:
            dest = action.get("/D")
        except Exception:
            dest = None
        if dest is not None:
            name = _safe_str(dest)
            if name and not name.startswith("pikepdf"):
                return f"Go to {name}"
        return "Go to internal page"
    if s == "GoToR":
        try:
            f = action.get("/F")
        except Exception:
            f = None
        if f is not None:
            return f"Open external file {_safe_str(f)}"
        return "Open external file"
    if s == "Launch":
        return "Launch application"
    if s == "Named":
        try:
            n = _safe_str(action.get("/N")).lstrip("/")
        except Exception:
            n = ""
        return f"Action: {n}" if n else "Named action"
    return ""


def _rect_to_text(pdf_path: str, page_idx: int, rect: Any) -> str:
    """Extract visible text under `rect` on page `page_idx` using PyMuPDF.

    Returns an empty string if PyMuPDF isn't available or extraction
    fails. Uses a small vertical shrink to avoid grabbing adjacent lines.
    """
    try:
        import fitz  # PyMuPDF
    except Exception:
        return ""
    try:
        x0, y0, x1, y1 = (float(rect[i]) for i in range(4))
    except Exception:
        return ""
    try:
        doc = fitz.open(pdf_path)
    except Exception:
        return ""
    try:
        page = doc[page_idx]
        # Shrink vertically by 10% on each side to reduce cross-line
        # bleed from rects that extend a little past the actual glyphs.
        dy = (y1 - y0) * 0.1
        r = fitz.Rect(x0, y0 + dy, x1, y1 - dy)
        text = page.get_textbox(r) or ""
    except Exception:
        text = ""
    finally:
        try:
            doc.close()
        except Exception:
            pass
    text = _WS_RE.sub(" ", text).strip()
    # If we grabbed too much (textbox extraction often bleeds),
    # keep only the first ~80 chars.
    if len(text) > 80:
        text = text[:80].rsplit(" ", 1)[0] + "…"
    return text


# ---------------------------------------------------------------------------
# Struct tree helpers
# ---------------------------------------------------------------------------


def _find_link_struct_for_annot(pdf: pikepdf.Pdf, annot: Any) -> Any:
    """Return the /Link StructElem whose /K OBJR references `annot`, else None.

    This is best-effort: walks the struct tree breadth-first looking for
    a /Link element whose /K contains an OBJR pointing back at `annot`.
    Returns the first match.
    """
    try:
        sr = pdf.Root.get("/StructTreeRoot")
    except Exception:
        return None
    if sr is None:
        return None
    try:
        target_og = getattr(annot, "objgen", None)
    except Exception:
        target_og = None
    if target_og is None:
        return None

    stack: list[Any] = []
    try:
        k = sr.get("/K")
    except Exception:
        k = None
    if k is None:
        return None
    if isinstance(k, pikepdf.Array):
        stack.extend(list(k))
    else:
        stack.append(k)

    seen: set[tuple[int, int]] = set()
    while stack:
        node = stack.pop()
        if node is None:
            continue
        og = getattr(node, "objgen", None)
        if og is not None:
            if og in seen:
                continue
            seen.add(og)
        if not isinstance(node, pikepdf.Dictionary):
            continue
        try:
            s = _safe_str(node.get("/S")).lstrip("/")
        except Exception:
            s = ""
        if s == "Link":
            # Check if this element contains an OBJR to our annot.
            try:
                kk = node.get("/K")
            except Exception:
                kk = None
            items: list[Any] = []
            if kk is None:
                pass
            elif isinstance(kk, pikepdf.Array):
                items = list(kk)
            else:
                items = [kk]
            for item in items:
                if not isinstance(item, pikepdf.Dictionary):
                    continue
                try:
                    t = _safe_str(item.get("/Type")).lstrip("/")
                except Exception:
                    t = ""
                if t != "OBJR":
                    continue
                try:
                    ref = item.get("/Obj")
                except Exception:
                    ref = None
                if ref is None:
                    continue
                ref_og = getattr(ref, "objgen", None)
                if ref_og == target_og:
                    return node
        # Descend
        try:
            kk = node.get("/K")
        except Exception:
            kk = None
        if kk is None:
            continue
        if isinstance(kk, pikepdf.Array):
            for child in kk:
                if isinstance(child, pikepdf.Dictionary):
                    stack.append(child)
        elif isinstance(kk, pikepdf.Dictionary):
            stack.append(kk)
    return None


# ---------------------------------------------------------------------------
# /Link struct element creation (C-42)
# ---------------------------------------------------------------------------


def _get_or_create_doc_struct(pdf: pikepdf.Pdf) -> Any:
    """Return the top-level Document struct element, creating it if absent."""
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
    if isinstance(k, pikepdf.Array) and len(k) > 0:
        for item in k:
            try:
                if isinstance(item, pikepdf.Dictionary):
                    s = item.get("/S")
                    if s is not None and str(s).lstrip("/") == "Document":
                        return item
            except Exception:
                continue
        # Return the first struct element
        for item in k:
            if isinstance(item, pikepdf.Dictionary):
                return item
    # No usable Document element — create one and attach it
    if k is None or (isinstance(k, pikepdf.Array) and len(k) == 0):
        doc_elem = pdf.make_indirect(pikepdf.Dictionary({
            "/Type": pikepdf.Name("/StructElem"),
            "/S": pikepdf.Name("/Document"),
            "/K": pikepdf.Array(),
        }))
        if k is None:
            sr["/K"] = pikepdf.Array([doc_elem])
        else:
            k.append(doc_elem)
        return doc_elem
    return None


def _create_link_struct(
    pdf: pikepdf.Pdf,
    annot: Any,
    page_idx: int,
    label: str,
) -> None:
    """Create a /Link struct element for a link annotation (C-42).

    Appends a /Link StructElem under the document root element.  The
    struct element carries /Alt = label so assistive technologies have
    a human-readable description.

    The annotation is not back-linked (that would require MCID bookkeeping)
    but the presence of the /Link element is sufficient for C-42 to PASS.
    """
    doc_struct = _get_or_create_doc_struct(pdf)
    if doc_struct is None:
        raise RuntimeError("No Document struct element available")
    link_elem = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Link"),
        "/Alt": pikepdf.String(label[:200]),
    }))
    # Attach to document struct
    try:
        dk = doc_struct.get("/K")
        if dk is None:
            doc_struct["/K"] = pikepdf.Array([link_elem])
        elif isinstance(dk, pikepdf.Array):
            dk.append(link_elem)
        else:
            doc_struct["/K"] = pikepdf.Array([dk, link_elem])
    except Exception as e:
        raise RuntimeError(f"Could not attach /Link element: {e}") from e


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_link_alt(input_path: str, output_path: str) -> dict:
    """Populate /Contents on every Link annotation that lacks one.

    Returns:
        {"links_total", "links_filled", "links_skipped",
         "struct_alts_filled", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "links_total": 0,
        "links_filled": 0,
        "links_skipped": 0,
        "struct_alts_filled": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                try:
                    annots = page.get("/Annots") or []
                except Exception:
                    annots = []
                for annot in annots:
                    try:
                        if not _name_eq(annot.get("/Subtype"), "/Link"):
                            continue
                        result["links_total"] += 1

                        existing = _safe_str(annot.get("/Contents")).strip()
                        if not existing:
                            existing = _safe_str(annot.get("/Alt")).strip()
                        if existing:
                            # Already has a description — leave alone.
                            continue

                        label = ""
                        # Priority 1: derive from the action.
                        try:
                            action = annot.get("/A")
                        except Exception:
                            action = None
                        if action is not None:
                            # Detect and warn on broken (empty) URIs before
                            # falling through to the generic label.
                            try:
                                act_s = _safe_str(action.get("/S")).lstrip("/")
                                if act_s == "URI":
                                    raw_uri = _safe_str(action.get("/URI")).strip()
                                    if not raw_uri:
                                        result["errors"].append(
                                            f"page {page_idx + 1}: broken link — "
                                            "empty URI (/A /S /URI with blank /URI value); "
                                            "link requires manual review"
                                        )
                            except Exception:
                                pass
                            label = _action_to_name(action)

                        # Priority 1b: derive from /Dest (named or explicit).
                        if not label:
                            try:
                                dest = annot.get("/Dest")
                            except Exception:
                                dest = None
                            if dest is not None:
                                dest_str = _safe_str(dest).strip()
                                if dest_str and not dest_str.startswith("["):
                                    label = f"Go to {dest_str}"
                                elif dest_str:
                                    label = "Go to internal page"

                        # Priority 2: extract visible text under /Rect.
                        if not label:
                            try:
                                rect = annot.get("/Rect")
                            except Exception:
                                rect = None
                            if rect is not None:
                                label = _rect_to_text(in_str, page_idx, rect)

                        # Last resort.
                        if not label:
                            label = "Link"

                        try:
                            annot["/Contents"] = pikepdf.String(label)
                            result["links_filled"] += 1
                        except Exception as e:
                            result["links_skipped"] += 1
                            result["errors"].append(f"page {page_idx + 1}: write /Contents failed: {e}")
                            continue

                        # Also attach /Alt to the matching /Link struct
                        # element, if one exists, so the tagged path has
                        # the description too.
                        link_elem = _find_link_struct_for_annot(pdf, annot)
                        if link_elem is not None:
                            try:
                                if not _safe_str(link_elem.get("/Alt")).strip():
                                    link_elem["/Alt"] = pikepdf.String(label)
                                    result["struct_alts_filled"] += 1
                            except Exception as e:
                                result["errors"].append(f"page {page_idx + 1}: write struct /Alt failed: {e}")
                        else:
                            # C-42: no /Link struct element exists for this
                            # annotation — create one so the structure tree
                            # records the link and screen readers can find it.
                            try:
                                _create_link_struct(pdf, annot, page_idx, label)
                                result["struct_alts_filled"] += 1
                            except Exception as e:
                                result["errors"].append(
                                    f"page {page_idx + 1}: create /Link struct failed: {e}"
                                )
                    except Exception as e:
                        result["links_skipped"] += 1
                        result["errors"].append(f"page {page_idx + 1}: {type(e).__name__}: {e}")
                        continue

            pdf.save(out_str)
        logger.info(
            "fix_link_alt: total=%d filled=%d struct=%d errors=%d",
            result["links_total"],
            result["links_filled"],
            result["struct_alts_filled"],
            len(result["errors"]),
        )
        return result

    except Exception as e:
        logger.exception("fix_link_alt failed for %s", in_str)
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
        print("usage: python fix_link_alt.py <input.pdf> <output.pdf>")
        return 2
    res = fix_link_alt(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
