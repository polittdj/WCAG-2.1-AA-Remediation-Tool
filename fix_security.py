"""fix_security.py — Ensure accessibility permissions are set.

Covers checkpoint:
  C-08: Security permissions allow accessibility

For unencrypted PDFs this is always PASS (nothing to fix).
For encrypted PDFs, we can only detect the issue — fixing
requires re-encrypting which needs the owner password.
"""

from __future__ import annotations

import pathlib
import shutil
from typing import Any

import pikepdf


def fix_security(input_path: str, output_path: str) -> dict[str, Any]:
    """Check and report accessibility permissions."""
    result: dict[str, Any] = {"errors": [], "changes": []}
    try:
        pdf = pikepdf.open(input_path)
    except Exception as e:
        result["errors"].append(f"Could not open PDF: {e}")
        pathlib.Path(output_path).write_bytes(pathlib.Path(input_path).read_bytes())
        return result

    try:
        encrypt = pdf.Root.get("/Encrypt")
        if encrypt is None:
            result["changes"].append("Document is not encrypted — no security fix needed")
        else:
            result["changes"].append(
                "Document is encrypted — accessibility permissions cannot be modified without owner password"
            )

        pdf.save(output_path)
    except Exception as e:
        result["errors"].append(f"fix_security error: {e}")
        shutil.copy2(input_path, output_path)
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return result
