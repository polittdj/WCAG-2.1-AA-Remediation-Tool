"""fix_title.py — set a meaningful, non-placeholder title in a PDF.

Reads `input_path`, derives a title (existing → page content → filename →
date), writes it to both DocInfo /Title and XMP dc:title, and saves to
`output_path`. The input file is never modified.
"""

from __future__ import annotations

import logging
import re
import shutil
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF — content extraction only
import pikepdf  # all PDF reading and writing

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

BLACKLIST: frozenset[str] = frozenset(
    {
        "untitled document",
        "untitled",
        "untitled-1",
        "untitled1",
        "untitled 1",
        "document",
        "document1",
        "word document",
        "microsoft word",
        "microsoft word document",
        "new document",
        "draft",
        "temp",
        "copy",
        "",
    }
)

PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"APPLICATION FOR .+", re.IGNORECASE),
    re.compile(r".+ APPROVAL FORM", re.IGNORECASE),
    re.compile(r".+ REQUEST FORM", re.IGNORECASE),
    re.compile(r"FORM \d+\.\d+.+", re.IGNORECASE),
    re.compile(r"REQUEST FOR .+", re.IGNORECASE),
    re.compile(r"CERTIFICATE OF .+", re.IGNORECASE),
    re.compile(r"NOTICE OF .+", re.IGNORECASE),
    re.compile(r"ORDER .+", re.IGNORECASE),
    re.compile(r"PETITION .+", re.IGNORECASE),
    re.compile(r"AGREEMENT .+", re.IGNORECASE),
    re.compile(r"CONTRACT .+", re.IGNORECASE),
]

MIN_TITLE_LENGTH = 6
MIN_FONT_SIZE = 11.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _norm(s: str) -> str:
    return s.strip().lower()


def _is_blacklisted(s: str) -> bool:
    return _norm(s) in BLACKLIST


def _is_meaningful(s: str) -> bool:
    """Non-blacklisted, length >= 6 after strip."""
    if s is None:
        return False
    s = s.strip()
    return len(s) >= MIN_TITLE_LENGTH and not _is_blacklisted(s)


def _has_alpha(s: str) -> bool:
    return any(c.isalpha() for c in s)


def _read_existing_title(pdf: pikepdf.Pdf) -> str:
    """Return DocInfo /Title as a stripped string ('' if missing/unreadable)."""
    try:
        title_obj = pdf.docinfo.get("/Title")
    except Exception:
        return ""
    if title_obj is None:
        return ""
    try:
        return str(title_obj).strip()
    except Exception:
        return ""


# ---------------------------------------------------------------------------
# STEP 2 — content-based derivation
# ---------------------------------------------------------------------------


def _collect_page1_candidates(input_path: str) -> list[tuple[float, str]]:
    """Return [(font_size, text)] sorted by size descending."""
    candidates: list[tuple[float, str]] = []
    try:
        doc = fitz.open(input_path)
    except Exception as e:
        logger.warning("fitz could not open %s: %s", input_path, e)
        return candidates
    try:
        if doc.page_count == 0:
            return candidates
        page = doc[0]
        try:
            data = page.get_text("dict")
        except Exception as e:
            logger.warning("get_text failed: %s", e)
            return candidates
        for block in data.get("blocks", []):
            if block.get("type") != 0:  # 0 == text
                continue
            for line in block.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                text = " ".join(s.get("text", "") for s in spans)
                text = re.sub(r"\s+", " ", text).strip()
                if not text:
                    continue
                try:
                    max_size = max(float(s.get("size", 0.0)) for s in spans)
                except Exception:
                    continue
                if max_size < MIN_FONT_SIZE:
                    continue
                if len(text) < MIN_TITLE_LENGTH:
                    continue
                if not _has_alpha(text):
                    continue
                if _is_blacklisted(text):
                    continue
                candidates.append((max_size, text))
    finally:
        try:
            doc.close()
        except Exception:
            pass
    candidates.sort(key=lambda r: -r[0])
    return candidates


def _derive_from_content(input_path: str) -> str | None:
    candidates = _collect_page1_candidates(input_path)
    if not candidates:
        return None
    # Try patterns first, in font-size descending order. The first
    # candidate that matches any pattern wins.
    for _size, text in candidates:
        for pat in PATTERNS:
            if pat.search(text):
                return text
    # No pattern hit — fall back to the largest candidate.
    largest = candidates[0][1]
    if _is_meaningful(largest):
        return largest
    return None


# ---------------------------------------------------------------------------
# STEP 3 — filename fallback
# ---------------------------------------------------------------------------

_FILENAME_SUFFIXES = (
    "_wcag_2_1_aa_compliant",
    "_wcag_2.1_aa_compliant",
    " - wcag 2.1 aa compliant",
    "-wcag_2_1_aa_compliant",
)

_FILENAME_NOISE = (
    "_converted_from_ms_word",
    "_converted_from_word",
    " converted from ms word",
)


def _strip_suffix_ci(name: str, suffix: str) -> str:
    if name.lower().endswith(suffix.lower()):
        return name[: len(name) - len(suffix)]
    return name


def _strip_substr_ci(name: str, needle: str) -> str:
    low = name.lower()
    nlow = needle.lower()
    idx = low.find(nlow)
    if idx == -1:
        return name
    return name[:idx] + name[idx + len(nlow) :]


def _derive_from_filename(input_path: str) -> str | None:
    name = Path(input_path).stem
    for suffix in _FILENAME_SUFFIXES:
        new = _strip_suffix_ci(name, suffix)
        if new != name:
            name = new
            break
    for noise in _FILENAME_NOISE:
        name = _strip_substr_ci(name, noise)
    name = name.replace("_", " ").replace("-", " ")
    name = re.sub(r"\s+", " ", name).strip()
    # Strip leading numbers and dots (e.g. "12 0 ").
    name = re.sub(r"^[\d.\s]+", "", name).strip()
    # Strip trailing version numbers (e.g. " v1" or " v1.9").
    name = re.sub(r"\s+v\d+(?:\.\d+)?\s*$", "", name, flags=re.IGNORECASE).strip()
    name = name.title()
    if _is_meaningful(name):
        return name
    return None


# ---------------------------------------------------------------------------
# STEP 4 — date fallback
# ---------------------------------------------------------------------------


def _date_fallback() -> str:
    return f"PDF Document {datetime.now().strftime('%Y-%m-%d')}"


# ---------------------------------------------------------------------------
# Writing
# ---------------------------------------------------------------------------


def write_title(pdf: pikepdf.Pdf, title: str) -> None:
    """Write title to both DocInfo /Title and XMP dc:title."""
    pdf.docinfo["/Title"] = title
    with pdf.open_metadata() as meta:
        meta["dc:title"] = title


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def fix_title(input_path: str, output_path: str) -> dict:
    """Fix a PDF's title and save to output_path. Never modifies the input.

    Returns: {"title_set", "method", "original_title", "error"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result = {
        "title_set": "",
        "method": "",
        "original_title": "",
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            original = _read_existing_title(pdf)
            result["original_title"] = original

            chosen: str | None = None
            method: str = ""

            # STEP 1 — keep existing title if it's already meaningful
            if _is_meaningful(original):
                chosen = original
                method = "existing"

            # STEP 2 — content-based derivation
            if chosen is None:
                derived = _derive_from_content(in_str)
                if derived and _is_meaningful(derived):
                    chosen = derived
                    method = "content"

            # STEP 3 — filename fallback
            if chosen is None:
                derived = _derive_from_filename(in_str)
                if derived and _is_meaningful(derived):
                    chosen = derived
                    method = "filename"

            # STEP 4 — date fallback (last resort)
            if chosen is None:
                chosen = _date_fallback()
                method = "date_fallback"
                logger.warning(
                    "fix_title: using date fallback for %s",
                    in_str,
                )

            write_title(pdf, chosen)
            pdf.save(out_str)

            result["title_set"] = chosen
            result["method"] = method
            logger.info(
                "fix_title: %s -> method=%s title=%r",
                in_str,
                method,
                chosen,
            )
            return result

    except Exception as e:
        logger.exception("fix_title failed for %s", in_str)
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
        print("usage: python fix_title.py <input.pdf> <output.pdf>")
        return 2
    res = fix_title(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
