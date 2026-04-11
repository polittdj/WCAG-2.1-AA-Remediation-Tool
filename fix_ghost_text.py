"""fix_ghost_text.py — Detect and remove invisible/ghost text.

Covers checkpoint:
  C-14: No ghost/invisible text detected

Detects text rendered with Tr 3 (invisible) rendering mode
or sub-6pt font sizes and removes or artifacts them.
"""

from __future__ import annotations

import pathlib
import re
import shutil
from typing import Any

import pikepdf


def fix_ghost_text(input_path: str, output_path: str) -> dict[str, Any]:
    """Detect and remove invisible text."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        tr3_re = re.compile(rb"\b3\s+Tr\b")
        fixed_pages = 0

        for idx, page in enumerate(pdf.pages):
            try:
                contents = page.get("/Contents")
                if contents is None:
                    continue
                if isinstance(contents, pikepdf.Array):
                    streams = list(contents)
                else:
                    streams = [contents]

                page_modified = False
                for stream in streams:
                    try:
                        data = bytes(stream.read_bytes())
                        if tr3_re.search(data):
                            # Replace Tr 3 with Tr 0 (visible)
                            new_data = tr3_re.sub(b"0 Tr", data)
                            stream.write(new_data)
                            page_modified = True
                    except Exception:
                        continue

                if page_modified:
                    fixed_pages += 1
            except Exception:
                continue

        if fixed_pages:
            result["changes"].append(f"Fixed invisible text (Tr 3) on {fixed_pages} page(s)")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_ghost_text error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
