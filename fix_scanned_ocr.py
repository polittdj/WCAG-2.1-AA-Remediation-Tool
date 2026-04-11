"""fix_scanned_ocr.py — detect and OCR scanned PDF pages.

Adds a searchable text layer to image-only PDF pages via ocrmypdf
(Tesseract), then creates a minimal tagged-PDF structure stub so the
downstream pipeline steps can process the file normally.

Detection uses three per-page signals:
  1. No /Font resources on the page → strong scan indicator
  2. No text-showing operators (Tj/TJ/'/") in the content stream
  3. PyMuPDF get_text("text") returns empty or near-empty

Classification:
  * All pages image-only  → "scanned"  (OCR whole document)
  * Mixed pages           → "hybrid"   (OCR with --skip-text)
  * All pages have text   → "digital"  (no-op, copy input to output)

After OCR, the module adds:
  * /MarkInfo /Marked = true
  * /Lang = "en-US" (when not already set)
  * Minimal /StructTreeRoot with a Document element and flat /ParentTree

These stubs let the downstream pipeline (fix_title, fix_content_streams,
wcag_auditor, etc.) work without modification. fix_title derives the
document title from the OCR text via get_text("dict").

Environment variables:
  WCAG_FORCE_OCR=1  — force OCR even on pages that have text
  WCAG_OCR_LANG     — Tesseract language hint (default "eng")

The input file is never modified.
"""

from __future__ import annotations

import logging
import os
import shutil
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-page scan detection
# ---------------------------------------------------------------------------

# Text-showing PDF operators (per ISO 32000 §9.4.3).
_TEXT_OPS = (b" Tj", b" TJ", b" '", b' "')


def _page_content_bytes(page: Any) -> bytes:
    """Return decompressed content stream bytes for a page."""
    try:
        c = page.get("/Contents")
    except Exception:
        return b""
    if c is None:
        return b""
    try:
        if isinstance(c, pikepdf.Array):
            chunks = []
            for s in c:
                try:
                    chunks.append(bytes(s.read_bytes()))
                except Exception:
                    pass
            return b"\n".join(chunks)
        return bytes(c.read_bytes())
    except Exception:
        return b""


def _page_has_fonts(page: Any) -> bool:
    """Return True if the page (or inherited resources) declares any /Font."""
    try:
        res = page.get("/Resources")
    except Exception:
        return False
    if res is None:
        return False
    try:
        fonts = res.get("/Font")
    except Exception:
        return False
    if fonts is None:
        return False
    try:
        return len(list(fonts.keys())) > 0
    except Exception:
        return False


def _page_has_text_ops(data: bytes) -> bool:
    """Return True if the content stream contains any text-show operator."""
    return any(op in data for op in _TEXT_OPS)


def _fitz_extractable_text(pdf_path: str, page_idx: int) -> str:
    """Return text extracted by PyMuPDF; empty on failure."""
    try:
        import fitz
    except Exception:
        return ""
    doc = None
    try:
        doc = fitz.open(pdf_path)
        if page_idx < 0 or page_idx >= doc.page_count:
            return ""
        return doc[page_idx].get_text("text").strip()
    except Exception:
        return ""
    finally:
        if doc is not None:
            try:
                doc.close()
            except Exception:
                pass


def classify_pages(
    pdf_path: str,
) -> list[str]:
    """Return a list of per-page classifications: 'scan' or 'digital'.

    Uses pikepdf for structural checks and PyMuPDF for text extraction.
    """
    result: list[str] = []
    try:
        with pikepdf.open(str(pdf_path)) as pdf:
            for idx, page in enumerate(pdf.pages):
                has_fonts = _page_has_fonts(page)
                data = _page_content_bytes(page)
                has_ops = _page_has_text_ops(data)

                if not has_fonts and not has_ops:
                    result.append("scan")
                    continue

                # Fonts present or ops present — check if fitz can actually
                # extract readable text (catches bad/invisible OCR layers).
                fitz_text = _fitz_extractable_text(pdf_path, idx)
                if len(fitz_text) < 10:
                    result.append("scan")
                else:
                    result.append("digital")
    except Exception as e:
        logger.warning("classify_pages failed: %s", e)
    return result


def classify_document(pdf_path: str) -> str:
    """Return 'scanned', 'hybrid', or 'digital'.

    A file that already has a StructTreeRoot is treated as 'digital'
    regardless of whether its pages contain text — it's already tagged
    and ocrmypdf would reject it with TaggedPDFError anyway.
    """
    # Fast path: if the file already has a struct tree, it's digital.
    try:
        with pikepdf.open(str(pdf_path)) as pdf:
            if pdf.Root.get("/StructTreeRoot") is not None:
                return "digital"
    except Exception:
        pass

    pages = classify_pages(pdf_path)
    if not pages:
        return "digital"
    scans = sum(1 for p in pages if p == "scan")
    if scans == len(pages):
        return "scanned"
    if scans > 0:
        return "hybrid"
    return "digital"


# ---------------------------------------------------------------------------
# Struct tree stub
# ---------------------------------------------------------------------------


def _add_struct_stub(pdf: pikepdf.Pdf) -> None:
    """Add a minimal tagged-PDF structure if one doesn't already exist.

    Creates /MarkInfo, /StructTreeRoot with a Document element, and
    a flat /ParentTree. Also sets /Lang if absent.
    """
    # /MarkInfo
    try:
        mi = pdf.Root.get("/MarkInfo")
    except Exception:
        mi = None
    if mi is None:
        pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    else:
        try:
            mi["/Marked"] = True
        except Exception:
            pass

    # /Lang
    try:
        lang = pdf.Root.get("/Lang")
    except Exception:
        lang = None
    if lang is None:
        ocr_lang = os.environ.get("WCAG_OCR_LANG", "eng")
        lang_tag = {"eng": "en-US", "fra": "fr-FR", "deu": "de-DE", "spa": "es-ES"}.get(ocr_lang, "en-US")
        pdf.Root["/Lang"] = pikepdf.String(lang_tag)

    # /StructTreeRoot
    try:
        existing_sr = pdf.Root.get("/StructTreeRoot")
    except Exception:
        existing_sr = None
    if existing_sr is not None:
        return  # already has a struct tree — don't overwrite

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
    struct_root = pdf.make_indirect(
        pikepdf.Dictionary(
            {
                "/Type": pikepdf.Name("/StructTreeRoot"),
                "/K": pikepdf.Array([doc_elem]),
                "/ParentTree": parent_tree,
                "/ParentTreeNextKey": 0,
            }
        )
    )
    pdf.Root["/StructTreeRoot"] = struct_root


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_scanned_ocr(input_path: str, output_path: str) -> dict:
    """Detect scanned pages and run OCR if needed.

    Returns: {
      "classification", "ocr_applied", "pages_total", "pages_ocred",
      "tool", "errors"
    }
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "classification": "",
        "ocr_applied": False,
        "pages_total": 0,
        "pages_ocred": 0,
        "tool": "",
        "errors": [],
    }

    force_ocr = os.environ.get("WCAG_FORCE_OCR", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )

    try:
        classification = classify_document(in_str)
        result["classification"] = classification

        with pikepdf.open(in_str) as pdf:
            result["pages_total"] = len(pdf.pages)

        if classification == "digital" and not force_ocr:
            logger.info("fix_scanned_ocr: digital document, skipping OCR")
            shutil.copy2(in_str, out_str)
            return result

        # Try to import ocrmypdf
        try:
            import ocrmypdf
        except ImportError:
            result["errors"].append(
                "ocrmypdf is not installed; cannot OCR scanned pages. "
                "Install with: pip install ocrmypdf && "
                "apt install tesseract-ocr tesseract-ocr-eng"
            )
            shutil.copy2(in_str, out_str)
            return result

        # Check tesseract binary
        if shutil.which("tesseract") is None:
            result["errors"].append(
                "tesseract binary not found on PATH; cannot OCR. "
                "Install with: apt install tesseract-ocr tesseract-ocr-eng"
            )
            shutil.copy2(in_str, out_str)
            return result

        # Run OCR
        ocr_lang = os.environ.get("WCAG_OCR_LANG", "eng")
        ocr_kwargs: dict[str, Any] = {
            "language": [ocr_lang],
            "output_type": "pdf",
            "progress_bar": False,
            "deskew": True,
            "clean": False,
        }

        if force_ocr:
            ocr_kwargs["force_ocr"] = True
            result["classification"] = "forced"
        elif classification == "hybrid":
            ocr_kwargs["skip_text"] = True

        try:
            ocrmypdf.ocr(in_str, out_str, **ocr_kwargs)
        except Exception as e:
            err_msg = f"ocrmypdf failed: {type(e).__name__}: {e}"
            logger.warning(err_msg)
            result["errors"].append(err_msg)
            shutil.copy2(in_str, out_str)
            return result

        result["ocr_applied"] = True
        result["tool"] = f"ocrmypdf {ocrmypdf.__version__}"

        # Count OCR'd pages
        page_classes = classify_pages(in_str)
        result["pages_ocred"] = sum(1 for p in page_classes if p == "scan")

        # Post-process: add struct tree stub so downstream steps work.
        try:
            with pikepdf.open(out_str, allow_overwriting_input=True) as pdf:
                _add_struct_stub(pdf)
                pdf.save(out_str)
        except Exception as e:
            result["errors"].append(f"struct stub failed: {e}")

        logger.info(
            "fix_scanned_ocr: %s, ocr_applied=%s, pages=%d/%d, tool=%s",
            classification,
            result["ocr_applied"],
            result["pages_ocred"],
            result["pages_total"],
            result["tool"],
        )
        return result

    except Exception as e:
        logger.exception("fix_scanned_ocr failed for %s", in_str)
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
        print("usage: python fix_scanned_ocr.py <input.pdf> <output.pdf>")
        return 2
    res = fix_scanned_ocr(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
