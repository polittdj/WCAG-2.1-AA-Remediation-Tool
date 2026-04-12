"""Category U — Gradio UI Edge Cases."""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import app
from app import process_files, process_files_core, build_ui


# ═══════════════════════════════════════════════════════════════════════
# U1 — Upload with None
# ═══════════════════════════════════════════════════════════════════════

def test_u1_none_files():
    status, rows, download = process_files(None)
    assert "No files" in status or "no files" in status.lower()
    assert rows == []


# ═══════════════════════════════════════════════════════════════════════
# U2 — Upload with empty list
# ═══════════════════════════════════════════════════════════════════════

def test_u2_empty_list():
    status, rows, download = process_files([])
    assert "No files" in status or "no files" in status.lower()
    assert rows == []


# ═══════════════════════════════════════════════════════════════════════
# U5 — Privacy notice present in UI
# ═══════════════════════════════════════════════════════════════════════

def test_u5_privacy_notice():
    assert "Privacy" in app.PRIVACY_NOTICE_MD
    assert "deleted" in app.PRIVACY_NOTICE_MD.lower() or \
           "no file" in app.PRIVACY_NOTICE_MD.lower()


# ═══════════════════════════════════════════════════════════════════════
# U3 — Double submit doesn't crash
# ═══════════════════════════════════════════════════════════════════════

def test_u3_double_submit(tmp_path):
    src = tmp_path / "double.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Double Submit"
    pdf.save(str(src))
    pdf.close()

    # Process twice rapidly
    r1 = process_files_core([str(src)], work_root=tmp_path / "w1")
    r2 = process_files_core([str(src)], work_root=tmp_path / "w2")

    rows1, zip1, err1 = r1
    rows2, zip2, err2 = r2

    assert len(rows1) == 1
    assert len(rows2) == 1


# ═══════════════════════════════════════════════════════════════════════
# U6 — Build UI doesn't crash
# ═══════════════════════════════════════════════════════════════════════

def test_u6_build_ui_no_crash():
    demo = build_ui()
    assert demo is not None
