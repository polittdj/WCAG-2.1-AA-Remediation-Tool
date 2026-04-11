"""Integration tests: every synthetic TEST PDF through the full pipeline."""

from __future__ import annotations
import pathlib, sys
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from pipeline import run_pipeline, CRITICAL_CHECKPOINTS

TEST_SUITE = ROOT / "test_suite"

# PDFs expected to reach PASS
PASS_EXPECTED = [
    "TEST_01_completely_untagged.pdf",
    "TEST_02_scanned_no_text.pdf",
    "TEST_03_forms_no_tooltips.pdf",
    "TEST_04_images_no_alt.pdf",
    "TEST_05_low_contrast.pdf",
    "TEST_06_tables_no_headers.pdf",
    "TEST_07_links_no_description.pdf",
    "TEST_08_multipage_no_bookmarks.pdf",
    "TEST_10_nonstandard_bdc_tags.pdf",
    "TEST_11_javascript_actions.pdf",
    "TEST_13_already_compliant.pdf",
    "TEST_14_everything_wrong.pdf",
    "TEST_15_landscape.pdf",
    "TEST_16_with_attachment.pdf",
    "TEST_18_ghost_text.pdf",
    "TEST_19_multilingual.pdf",
    "TEST_20_no_pdfua_id.pdf",
    "TEST_22_th_no_scope.pdf",
    "TEST_23_heading_hierarchy_wrong.pdf",
    "TEST_24_suspects_true.pdf",
    "TEST_25_fonts_not_embedded.pdf",
    "TEST_26_annotations_no_contents.pdf",
]

# PDFs expected to reach PARTIAL (legitimate limitations)
PARTIAL_EXPECTED = [
    "TEST_09_no_language.pdf",  # OCR warning on tagged PDF
    "TEST_12_broken_struct_tree.pdf",  # Intentionally broken /K
    "TEST_17_encrypted.pdf",  # Password-protected
    "TEST_21_wrong_tabs_order.pdf",  # Widget without AcroForm
]


@pytest.mark.parametrize("filename", PASS_EXPECTED)
def test_pass_expected(filename: str, tmp_path: pathlib.Path) -> None:
    src = TEST_SUITE / filename
    if not src.exists():
        pytest.skip(f"{filename} not found")
    res = run_pipeline(str(src), str(tmp_path))
    assert res["result"] == "PASS", (
        f"{filename}: expected PASS got {res['result']}, "
        f"errors={res.get('errors', [])[:3]}, "
        f"failing={[c['id'] for c in res['checkpoints'] if c['status'] == 'FAIL']}"
    )


@pytest.mark.parametrize("filename", PARTIAL_EXPECTED)
def test_partial_expected(filename: str, tmp_path: pathlib.Path) -> None:
    src = TEST_SUITE / filename
    if not src.exists():
        pytest.skip(f"{filename} not found")
    res = run_pipeline(str(src), str(tmp_path))
    assert res["result"] in ("PASS", "PARTIAL"), f"{filename}: expected PASS/PARTIAL got {res['result']}"


def test_no_crash_on_any_test_pdf(tmp_path: pathlib.Path) -> None:
    """Every TEST PDF should process without crashing."""
    test_pdfs = sorted(TEST_SUITE.glob("TEST_*.pdf"))
    for src in test_pdfs:
        out = tmp_path / src.stem
        out.mkdir(exist_ok=True)
        res = run_pipeline(str(src), str(out))
        assert res["result"] in ("PASS", "PARTIAL"), f"{src.name} crashed: {res.get('errors', [])[:3]}"
