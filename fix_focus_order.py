"""fix_focus_order.py — force every page's /Tabs entry to /S.

PDF/UA-1 and PAC 2024 require that every page declare its tab order
to follow the logical structure tree (/Tabs /S), not the row-order
default or the legacy widget-array order. Screen reader users rely on
/Tabs /S for document-flow navigation even on pages that don't have
annotations (because future-tool compatibility and PDF/UA conformance
require it unconditionally).

For EVERY page in the PDF, this module sets /Tabs to /S, regardless of
whether the page has annotations. The input file is never modified.
"""

from __future__ import annotations

import logging
import shutil
from typing import Any

import pikepdf

logger = logging.getLogger(__name__)


def fix_focus_order(input_path: str, output_path: str) -> dict:
    """Set /Tabs /S on every page unconditionally.

    Returns: {"pages_total", "pages_modified", "pages_skipped", "errors"}
    """
    in_str = str(input_path)
    out_str = str(output_path)
    result: dict[str, Any] = {
        "pages_total": 0,
        "pages_modified": 0,
        "pages_skipped": 0,
        "errors": [],
    }

    try:
        with pikepdf.open(in_str) as pdf:
            for idx, page in enumerate(pdf.pages, start=1):
                result["pages_total"] += 1
                try:
                    existing = page.get("/Tabs")
                except Exception:
                    existing = None
                if existing is not None:
                    s = str(existing)
                    if s == "/S":
                        result["pages_skipped"] += 1
                        continue
                try:
                    page["/Tabs"] = pikepdf.Name("/S")
                    result["pages_modified"] += 1
                except Exception as e:
                    result["errors"].append(f"page {idx}: set /Tabs failed: {e}")
                    continue
            pdf.save(out_str)
        logger.info(
            "fix_focus_order: total=%d modified=%d skipped=%d errors=%d",
            result["pages_total"],
            result["pages_modified"],
            result["pages_skipped"],
            len(result["errors"]),
        )
        return result

    except Exception as e:
        logger.exception("fix_focus_order failed for %s", in_str)
        result["errors"].append(f"{type(e).__name__}: {e}")
        try:
            shutil.copy2(in_str, out_str)
        except Exception as copy_err:
            result["errors"].append(f"copy failed: {copy_err}")
        return result


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python fix_focus_order.py <input.pdf> <output.pdf>")
        return 2
    res = fix_focus_order(argv[1], argv[2])
    print(res)
    return 0 if not res["errors"] else 1


if __name__ == "__main__":
    import sys

    raise SystemExit(_main(sys.argv))
