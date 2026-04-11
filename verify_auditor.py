"""Acceptance harness for the remediation pipeline + wcag_auditor.

Runs the full pipeline (fix_title -> fix_content_streams -> fix_widget_mapper)
against the 5 reference PDFs in test_suite/, then audits the pipeline's
output with wcag_auditor. Prints a comparison table of the critical
checkpoints. Exits non-zero if any row doesn't reach all-PASS.

Previously this script audited the raw test_suite fixtures directly and
compared against GROUND_TRUTH.md (which describes their pre-pipeline state).
The remediation pipeline writes its output into a separate directory; the
fixtures themselves are never modified. Auditing the raw fixtures therefore
obscures whether the pipeline actually produces compliant output — which is
the question that matters. This harness answers it.
"""

from __future__ import annotations

import pathlib
import sys
import tempfile

from pipeline import run_pipeline

TEST_SUITE = pathlib.Path(__file__).parent / "test_suite"

# (display_name, real_filename)
# After the pipeline, every critical checkpoint must PASS on every file.
CASES: list[tuple[str, str]] = [
    (
        "12_0_updated",
        "12.0_updated - WCAG 2.1 AA Compliant.pdf",
    ),
    (
        "12_0_updated_editable",
        "12.0_updated_editable - WCAG 2.1 AA Compliant.pdf",
    ),
    (
        "12_0_updated_converted",
        "12.0_updated - converted from MS Word - WCAG 2.1 AA Compliant.pdf",
    ),
    (
        "12_0_updated_editable_ADA",
        "12.0_updated_editable_ADA - WCAG 2.1 AA Compliant.pdf",
    ),
    (
        "CPSSPPC_TRAVEL_FORM",
        "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf",
    ),
]

CHECK_COLS = ["C-01", "C-02", "C-03", "C-04", "C-10", "C-13", "C-31", "C-36", "C-39", "C-40", "C-46"]
EXPECTED = "P"  # every critical checkpoint must PASS after the pipeline

# C-31/C-36/C-39/C-40 are NOT_APPLICABLE when a file has no figures or
# no form widgets; treat that as equivalent to PASS for scoring purposes.
ALSO_OK_AS_PASS: dict[str, set[str]] = {
    "C-31": {"N"},
    "C-36": {"N"},
    "C-39": {"N"},
    "C-40": {"N"},
}


def _letter(status: str) -> str:
    if status == "PASS":
        return "P"
    if status == "FAIL":
        return "F"
    return "N"


def main() -> int:
    rows: list[tuple[str, dict[str, str], str, list[str]]] = []
    all_match = True

    with tempfile.TemporaryDirectory(prefix="verify_auditor_") as tmpdir:
        tmp_root = pathlib.Path(tmpdir)

        for display, filename in CASES:
            pdf_path = TEST_SUITE / filename
            if not pdf_path.exists():
                print(f"MISSING: {pdf_path}", file=sys.stderr)
                all_match = False
                rows.append((display, {col: "?" for col in CHECK_COLS}, "NO", ["file missing"]))
                continue

            out_dir = tmp_root / display
            out_dir.mkdir(parents=True, exist_ok=True)
            pipe_res = run_pipeline(str(pdf_path), str(out_dir))

            by_id = {c["id"]: c for c in pipe_res.get("checkpoints", [])}
            actual_letters = {col: _letter(by_id.get(col, {}).get("status", "")) for col in CHECK_COLS}

            mismatches: list[str] = []
            for err in pipe_res.get("errors", []):
                mismatches.append(f"pipeline error: {err}")
            for col in CHECK_COLS:
                got = actual_letters[col]
                if got == EXPECTED:
                    continue
                if got in ALSO_OK_AS_PASS.get(col, set()):
                    continue
                mismatches.append(f"{col} expected {EXPECTED} got {got}")
            match = "YES" if not mismatches else "NO"
            if mismatches:
                all_match = False
            rows.append((display, actual_letters, match, mismatches))

    name_w = max(len("File"), max(len(r[0]) for r in rows))
    header = f"  {'File':<{name_w}} | " + " | ".join(f"{c:<4}" for c in CHECK_COLS) + " | Match?"
    sep = "  " + "-" * (len(header) - 2)
    print(header)
    print(sep)
    for display, letters, match, _mm in rows:
        line = f"  {display:<{name_w}} | " + " | ".join(f" {letters[c]:<3}" for c in CHECK_COLS) + f" | {match}"
        print(line)
    print()

    if not all_match:
        print("MISMATCHES:")
        for display, _letters, match, mm in rows:
            if match != "YES":
                for m in mm:
                    print(f"  {display}: {m}")
        return 1

    print("Pipeline output passes all critical checkpoints on all 5 reference PDFs.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
