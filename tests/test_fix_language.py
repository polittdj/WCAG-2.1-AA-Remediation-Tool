"""Tests for fix_language.py — document /Lang setting."""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from fix_language import fix_language  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402


def _save(pdf: pikepdf.Pdf, tmp_path: pathlib.Path, name: str = "test.pdf") -> pathlib.Path:
    p = tmp_path / name
    pdf.save(str(p))
    return p


def _status(report: dict, checkpoint_id: str) -> str:
    for c in report["checkpoints"]:
        if c["id"] == checkpoint_id:
            return c["status"]
    return "MISSING"


def test_sets_lang_when_missing(tmp_path: pathlib.Path) -> None:
    """Should set /Lang to en-US by default."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_language(str(inp), str(out))
    assert any("en-US" in c for c in res["changes"])
    r = audit_pdf(out)
    assert _status(r, "C-04") == "PASS"


def test_preserves_existing_lang(tmp_path: pathlib.Path) -> None:
    """Should not overwrite existing /Lang."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.Root["/Lang"] = pikepdf.String("fr-FR")
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    fix_language(str(inp), str(out))
    with pikepdf.open(str(out)) as pdf2:
        assert str(pdf2.Root["/Lang"]) == "fr-FR"


def test_custom_lang_from_env(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Should use WCAG_DEFAULT_LANG env var if set."""
    monkeypatch.setenv("WCAG_DEFAULT_LANG", "de-DE")
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    out = tmp_path / "out.pdf"
    res = fix_language(str(inp), str(out))
    assert any("de-DE" in c for c in res["changes"])
    with pikepdf.open(str(out)) as pdf2:
        assert str(pdf2.Root["/Lang"]) == "de-DE"


def test_idempotent(tmp_path: pathlib.Path) -> None:
    """Running fix_language twice should be safe."""
    pdf = pikepdf.new()
    pdf.add_blank_page()
    inp = _save(pdf, tmp_path)
    mid = tmp_path / "mid.pdf"
    out = tmp_path / "out.pdf"
    fix_language(str(inp), str(mid))
    fix_language(str(mid), str(out))
    r = audit_pdf(out)
    assert _status(r, "C-04") == "PASS"
