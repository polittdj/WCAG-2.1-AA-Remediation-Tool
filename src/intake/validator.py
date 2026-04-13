"""src.intake.validator — PDF input validation.

Performs lightweight pre-flight checks on a candidate PDF file before
it enters the remediation pipeline.  Designed to be called as the first
step so that the pipeline receives only files it can actually process.

Checks performed
----------------
1. File exists and is non-empty.
2. File starts with the PDF magic bytes (``%PDF-``).
3. pikepdf can open the file (catches structural corruption).
4. The file is not password-protected (encrypted with a user password).
"""
from __future__ import annotations

import pathlib
from typing import NamedTuple

import pikepdf

# PDF file signature
_PDF_MAGIC = b"%PDF-"


class ValidationResult(NamedTuple):
    """Outcome of :func:`validate_input_pdf`."""

    ok: bool
    """``True`` if the file passed all checks."""

    errors: list[str]
    """Human-readable error messages (empty when *ok* is ``True``)."""


def validate_input_pdf(path: str | pathlib.Path) -> ValidationResult:
    """Run pre-flight checks on *path* and return a :class:`ValidationResult`.

    Parameters
    ----------
    path:
        Absolute or relative path to the PDF file to validate.

    Returns
    -------
    ValidationResult
        ``.ok`` is ``True`` when the file passes all checks.
        ``.errors`` lists each failure reason.
    """
    errors: list[str] = []
    p = pathlib.Path(path)

    # 1. Existence and size
    if not p.exists():
        return ValidationResult(ok=False, errors=[f"File not found: {p}"])
    if p.stat().st_size == 0:
        return ValidationResult(ok=False, errors=["File is empty (0 bytes)"])

    # 2. Magic bytes
    try:
        header = p.read_bytes()[:8]
    except OSError as exc:
        return ValidationResult(ok=False, errors=[f"Cannot read file: {exc}"])
    if not header.startswith(_PDF_MAGIC):
        errors.append(
            f"File does not start with PDF magic bytes "
            f"(got {header[:8]!r}, expected {_PDF_MAGIC!r}...)"
        )

    # 3. pikepdf open
    try:
        pdf = pikepdf.open(str(p))
    except pikepdf.PasswordError:
        errors.append("File is password-protected and cannot be processed")
        return ValidationResult(ok=len(errors) == 0, errors=errors)
    except Exception as exc:
        errors.append(f"pikepdf could not open file: {exc}")
        return ValidationResult(ok=False, errors=errors)

    # 4. Encrypted check (user password)
    try:
        if pdf.is_encrypted:
            errors.append(
                "File is encrypted — the remediation pipeline cannot modify "
                "an encrypted PDF without the owner password"
            )
    except Exception:
        pass
    finally:
        try:
            pdf.close()
        except Exception:
            pass

    return ValidationResult(ok=len(errors) == 0, errors=errors)
