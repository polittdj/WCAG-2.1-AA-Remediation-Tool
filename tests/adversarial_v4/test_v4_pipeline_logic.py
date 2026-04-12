"""Category N — Pipeline Logic Bombs.

Attack control flow, error propagation, and state management.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile
import shutil

import pikepdf
import fitz
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import run_pipeline
from app import process_files_core


def _run(src: pathlib.Path, tmp_path: pathlib.Path) -> dict:
    out = tmp_path / "out"
    return run_pipeline(str(src), str(out))


# ═══════════════════════════════════════════════════════════════════════
# N1 — Audit report produced even when remediation partially fails
# ═══════════════════════════════════════════════════════════════════════

def test_n1_audit_survives_partial_remediation_failure(tmp_path):
    """A PDF with corrupt content on page 2 should still produce a report."""
    src = tmp_path / "partial_corrupt.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    page1 = pdf.pages[0]
    page1["/Resources"] = pikepdf.Dictionary({
        "/Font": pikepdf.Dictionary({
            "/F1": pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/Font"),
                "/Subtype": pikepdf.Name("/Type1"),
                "/BaseFont": pikepdf.Name("/Helvetica"),
            })),
        }),
    })
    page1["/Contents"] = pdf.make_stream(b"BT\n/F1 12 Tf\n100 700 Td\n(Good page) Tj\nET\n")

    # Add a second page with garbled content stream
    pdf.add_blank_page()
    page2 = pdf.pages[1]
    page2["/Contents"] = pdf.make_stream(b"\xff\xfe\xfd INVALID STREAM DATA \x00\x01")

    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    # Should NOT crash — should produce at least a report
    assert res["report_html"] or res["output_pdf"], \
        "Neither report nor output produced for partially corrupt PDF"
    assert res["result"] in ("PASS", "PARTIAL"), \
        f"Expected PASS or PARTIAL, got {res['result']}"


# ═══════════════════════════════════════════════════════════════════════
# N2 — Exception in one check doesn't skip remaining checks
# ═══════════════════════════════════════════════════════════════════════

def test_n2_exception_in_check_doesnt_skip_others(tmp_path):
    """All 47 checkpoints must produce results even if some hit edge cases."""
    src = tmp_path / "edge_case.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    # Add a /Figure with /Alt as an integer (not string) — edge case
    doc = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructElem"),
        "/S": pikepdf.Name("/Document"),
        "/K": pikepdf.Array([
            pdf.make_indirect(pikepdf.Dictionary({
                "/Type": pikepdf.Name("/StructElem"),
                "/S": pikepdf.Name("/Figure"),
                "/Alt": 42,  # integer, not string — edge case
            })),
        ]),
    }))
    pdf.Root["/StructTreeRoot"] = pdf.make_indirect(pikepdf.Dictionary({
        "/Type": pikepdf.Name("/StructTreeRoot"),
        "/K": pikepdf.Array([doc]),
        "/ParentTree": pikepdf.Dictionary({"/Nums": pikepdf.Array([])}),
    }))
    pdf.Root["/MarkInfo"] = pikepdf.Dictionary({"/Marked": True})
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    # Must have results for all 47 checkpoints
    cps = res.get("checkpoints", [])
    assert len(cps) == 47, f"Expected 47 checkpoints, got {len(cps)}"
    for cp in cps:
        assert cp.get("status") is not None, f"Checkpoint {cp.get('id')} has null status"


# ═══════════════════════════════════════════════════════════════════════
# N6 — Empty batch submission
# ═══════════════════════════════════════════════════════════════════════

def test_n6_empty_batch(tmp_path):
    rows, combined_zip, errs = process_files_core([], work_root=tmp_path)
    assert rows == []
    assert combined_zip is None
    assert errs == []


# ═══════════════════════════════════════════════════════════════════════
# N8 — File deleted before processing
# ═══════════════════════════════════════════════════════════════════════

def test_n8_file_deleted_before_processing(tmp_path):
    """Missing file should produce error, not crash."""
    ghost = tmp_path / "ghost.pdf"
    ghost.write_bytes(b"")  # create then delete
    ghost.unlink()

    res = _run(ghost, tmp_path)
    assert res["result"] == "PARTIAL"
    assert len(res["errors"]) > 0


# ═══════════════════════════════════════════════════════════════════════
# N9 — Worker thread death recovery
# ═══════════════════════════════════════════════════════════════════════

def test_n9_worker_death_recovery(tmp_path, monkeypatch):
    """If processing one file raises, others should still complete."""
    # Create 3 valid PDFs
    pdfs = []
    for i in range(3):
        p = tmp_path / f"file_{i}.pdf"
        pdf = pikepdf.new()
        pdf.add_blank_page()
        pdf.docinfo["/Title"] = f"File {i}"
        pdf.save(str(p))
        pdf.close()
        pdfs.append(str(p))

    # Monkey-patch _process_one to fail on the 2nd file
    import app
    original = app._process_one
    call_count = [0]

    def _bomb(input_path, out_dir):
        call_count[0] += 1
        if "file_1" in input_path:
            raise RuntimeError("Simulated worker death")
        return original(input_path, out_dir)

    monkeypatch.setattr(app, "_process_one", _bomb)

    rows, combined_zip, errs = process_files_core(pdfs, work_root=tmp_path / "work")
    assert len(rows) == 3, f"Expected 3 rows, got {len(rows)}"

    results = {r[0]: r[1] for r in rows}
    # File 1 should be ERROR, others should have completed
    assert results.get("file_1.pdf") == "ERROR", f"file_1 should be ERROR: {results}"


# ═══════════════════════════════════════════════════════════════════════
# N10 — Output naming with existing suffix
# ═══════════════════════════════════════════════════════════════════════

def test_n10_no_double_suffix(tmp_path):
    """File already named with the compliant suffix shouldn't double it."""
    src = tmp_path / "report_WGAC_2.1_AA_Compliant.pdf"
    pdf = pikepdf.new()
    pdf.add_blank_page()
    pdf.docinfo["/Title"] = "Already Compliant"
    pdf.save(str(src))
    pdf.close()

    res = _run(src, tmp_path)
    if res["output_pdf"]:
        name = pathlib.Path(res["output_pdf"]).name
        # Should NOT have double suffix
        double = "_WGAC_2.1_AA_Compliant_WGAC_2.1_AA_Compliant"
        assert double not in name, f"Double suffix detected: {name}"
