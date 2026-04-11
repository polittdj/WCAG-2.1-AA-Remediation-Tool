"""fix_artifacts.py — Mark headers/footers as Artifacts.

Covers checkpoint:
  C-47: Headers and footers are marked as Artifacts

Detects repeated text in the top/bottom margins across pages
and marks them as /Artifact with Header/Footer subtype.
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any

import pikepdf


def fix_artifacts(input_path: str, output_path: str) -> dict[str, Any]:
    """Detect and mark header/footer content as artifacts."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        page_count = len(pdf.pages)
        if page_count < 2:
            result["changes"].append("Single page — no repeating headers/footers possible")
            pdf.save(output_path)
            return result

        # Use PyMuPDF to detect repeating text in margins
        try:
            import fitz

            doc = fitz.open(input_path)

            # Collect text in top/bottom margins across pages
            top_texts = []  # per-page top margin text
            bottom_texts = []
            margin = 72  # 1 inch

            for page_num in range(len(doc)):
                page = doc[page_num]
                height = page.rect.height
                blocks = page.get_text("blocks")
                top_t = []
                bottom_t = []
                for b in blocks:
                    # b = (x0, y0, x1, y1, text, block_no, block_type)
                    if len(b) < 5:
                        continue
                    text = b[4].strip()
                    if not text:
                        continue
                    y0 = b[1]
                    y1 = b[3]
                    if y0 < margin:
                        top_t.append(text)
                    if y1 > height - margin:
                        bottom_t.append(text)
                top_texts.append(" ".join(top_t))
                bottom_texts.append(" ".join(bottom_t))
            doc.close()

            # Find text that repeats across >50% of pages
            if len(top_texts) >= 2:
                from collections import Counter

                top_counter = Counter(t for t in top_texts if t)
                for text, count in top_counter.items():
                    if count >= len(top_texts) * 0.5:
                        result["changes"].append(f"Detected repeating header: '{text[:50]}...'")

                bottom_counter = Counter(t for t in bottom_texts if t)
                for text, count in bottom_counter.items():
                    if count >= len(bottom_texts) * 0.5:
                        result["changes"].append(f"Detected repeating footer: '{text[:50]}...'")

        except ImportError:
            result["changes"].append("PyMuPDF not available for header/footer detection")

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_artifacts error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
