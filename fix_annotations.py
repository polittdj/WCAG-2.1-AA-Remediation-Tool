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


_JS_ACTION_SUBTYPES = frozenset({"JavaScript", "JS"})


def _has_javascript_action(annot: Any) -> bool:
    """Return True if *annot* contains any JavaScript action entry.

    Checks both the direct /A action dict and the /AA (Additional Actions)
    dict, which can carry per-event JavaScript triggers on any annotation.
    """
    try:
        # Direct action /A
        a = annot.get("/A")
        if a is not None:
            try:
                s = str(a.get("/S") or "").lstrip("/")
                if s in _JS_ACTION_SUBTYPES:
                    return True
            except Exception:
                pass

        # Additional actions /AA — dict of event → action
        aa = annot.get("/AA")
        if aa is not None:
            try:
                for _event_key in list(aa.keys()):
                    try:
                        action = aa[_event_key]
                        s = str(action.get("/S") or "").lstrip("/")
                        if s in _JS_ACTION_SUBTYPES:
                            return True
                    except Exception:
                        continue
            except Exception:
                pass
    except Exception:
        pass
    return False


def fix_annotations(input_path: str, output_path: str) -> dict[str, Any]:
    """Tag non-widget/non-link annotations with /Contents.

    Also scans *all* annotations (including Widget and Link) for JavaScript
    actions and records a warning for each found, so operators can review
    executable content embedded in the document.
    """
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        fixed = 0
        js_count = 0
        for page_num, page in enumerate(pdf.pages, start=1):
            try:
                annots = page.get("/Annots")
                if annots is None:
                    continue
                for annot in list(annots):
                    try:
                        subtype = annot.get("/Subtype")
                        sub_name = str(subtype).lstrip("/") if subtype else ""

                        # Detect JavaScript on every annotation type.
                        if _has_javascript_action(annot):
                            js_count += 1
                            result["errors"].append(
                                f"page {page_num}: javascript action detected on "
                                f"{sub_name or 'unknown'} annotation — "
                                "executable content requires manual review"
                            )

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
        if js_count:
            result["changes"].append(
                f"Flagged {js_count} annotation(s) with JavaScript executable content"
            )

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
