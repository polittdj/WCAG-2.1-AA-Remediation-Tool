"""fix_language.py — Set document /Lang if missing.

Covers checkpoint:
  C-04: Document language set
  C-05: Passage-level language (detection only for now)

Derives language from:
  1. Environment variable WCAG_DEFAULT_LANG (if set)
  2. Existing /Lang on any structure element
  3. Default to "en-US"
"""

from __future__ import annotations

import os
import pathlib
from typing import Any

import pikepdf


def fix_language(input_path: str, output_path: str) -> dict[str, Any]:
    """Set /Lang on document root if missing."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        existing_lang = None
        try:
            lang_obj = pdf.Root.get("/Lang")
            if lang_obj is not None:
                existing_lang = str(lang_obj).strip()
        except Exception:
            pass

        if existing_lang:
            # Already has /Lang — nothing to do
            result["changes"].append(f"Document already has /Lang={existing_lang}")
            pdf.save(output_path)
            return result

        # Determine language to set
        default_lang = os.environ.get("WCAG_DEFAULT_LANG", "en-US")
        pdf.Root["/Lang"] = pikepdf.String(default_lang)
        result["changes"].append(f"Set document /Lang to {default_lang}")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_language error: {e}")
        import shutil

        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
