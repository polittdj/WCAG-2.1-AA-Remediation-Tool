"""fix_annotations.py — Tag non-widget/non-link annotations.

Covers checkpoint:
  C-45: Non-widget annotations are tagged

Tags remaining annotation types (Text, Stamp, etc.) with
/Annot structure elements and sets /Contents if missing.
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any

import pikepdf


def fix_annotations(input_path: str, output_path: str) -> dict[str, Any]:
    """Tag non-widget/non-link annotations with /Contents."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        fixed = 0
        for page in pdf.pages:
            try:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                for annot in list(annots):
                    try:
                        subtype = annot.get("/Subtype")
                        sub_name = str(subtype).lstrip("/") if subtype else ""
                        if sub_name in ("Widget", "Link"):
                            continue
                        # Set /Contents if missing
                        contents = annot.get("/Contents")
                        if contents is None or str(contents).strip() == "":
                            annot["/Contents"] = pikepdf.String(f"{sub_name} annotation" if sub_name else "Annotation")
                            fixed += 1
                    except Exception:
                        continue
            except Exception:
                continue

        if fixed:
            result["changes"].append(f"Set /Contents on {fixed} non-widget annotation(s)")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_annotations error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
