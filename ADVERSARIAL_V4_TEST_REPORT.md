# DEEP ADVERSARIAL STRESS TEST REPORT (V4)

## Date: 2026-04-12

## Baseline: 292 tests passing (+ 43 skipped)

## RESULTS SUMMARY

| Category | Tests | Pass | Fail | Fixed | Unfixable |
|----------|-------|------|------|-------|-----------|
| M — Remediation Correctness | 8 | 8 | 0 | 0 | 0 |
| N — Pipeline Logic Bombs | 6 | 5 | 1 | 1 | 0 |
| O — Silent Data Corruption | 7 | 7 | 0 | 0 | 0 |
| P — Report Integrity | 5 | 5 | 0 | 0 | 0 |
| Q — Real-World PDF Hell | 6 | 6 | 0 | 0 | 0 |
| S — Fallback Chain Verification | 4 | 4 | 0 | 0 | 0 |
| T — Thread Safety | 3 | 3 | 0 | 0 | 0 |
| U — Gradio UI Edge Cases | 5 | 5 | 0 | 0 | 0 |
| **TOTAL** | **44** | **44** | **0** | **1** | **0** |

## CRITICAL FINDINGS (Silent Wrong Output)

### N10 — Double Suffix in Output Naming (CRITICAL — FIXED)

**What broke:** When a file already named `report_WGAC_2.1_AA_Compliant.pdf`
was processed, the pipeline produced `report_WGAC_2.1_AA_Compliant_WGAC_2.1_AA_Compliant.pdf`.

**Root cause:** `pipeline.py` line 387 uses `in_path.stem` directly as the
base for output naming, without checking if the stem already contains the
compliant/partial suffix.

**What the user would see:** Output PDFs with progressively longer names
if re-processed. ZIP files with confusing double-suffixed filenames.

**Severity:** CRITICAL — silent wrong output that compounds on re-runs.

**Fix (pipeline.py lines 387-393):**

Before:
```python
stem = in_path.stem
```

After:
```python
stem = in_path.stem
for suffix in ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL",
                "_WCAG_2.1_AA_Compliant", "_WCAG_2.1_AA_PARTIAL"):
    if stem.endswith(suffix):
        stem = stem[: -len(suffix)]
        break
```

## HIGH FINDINGS (Crashes & Misleading Reports)

None found. All crash/error scenarios handled gracefully.

## ALL TESTS PASSED

| Test ID | Category | Description | Result |
|---------|----------|-------------|--------|
| M1 | Remediation | Title remediation writes correct bytes | PASS |
| M2 | Remediation | Language /Catalog/Lang set correctly | PASS |
| M3 | Remediation | Tab order /Tabs=/S on ALL 5 pages | PASS |
| M4 | Remediation | MarkInfo + StructTreeRoot created | PASS |
| M5 | Remediation | Form field /TU tooltips on all widgets | PASS |
| M7 | Remediation | Already-tagged PDF not corrupted | PASS |
| M8 | Remediation | Visual content preserved after fix | PASS |
| M12 | Remediation | Report JSON matches actual output | PASS |
| N1 | Pipeline | Audit survives partial remediation failure | PASS |
| N2 | Pipeline | Exception in one check doesn't skip others | PASS |
| N6 | Pipeline | Empty batch returns cleanly | PASS |
| N8 | Pipeline | Deleted file produces error, not crash | PASS |
| N9 | Pipeline | Worker death → other files still process | PASS |
| N10 | Pipeline | No double suffix on re-processed files | PASS (after fix) |
| O4 | Corruption | Balanced BDC/EMC after remediation | PASS |
| O5 | Corruption | Font resources survive remediation | PASS |
| O6 | Corruption | Image count preserved | PASS |
| O7 | Corruption | Page count preserved (7 pages) | PASS |
| O8 | Corruption | No metadata leak between files | PASS |
| O9 | Corruption | Hyperlink destinations survive | PASS |
| O10 | Corruption | AcroForm field values preserved | PASS |
| P1 | Report | Exactly 47 checkpoints in JSON | PASS |
| P3 | Report | Remediation actions match reality | PASS |
| P4 | Report | Valid HTML5 structure | PASS |
| P5 | Report | Noscript fallback completeness | PASS |
| P8 | Report | No absolute paths in report | PASS |
| Q1 | Real-world | Linearized PDF | PASS |
| Q2 | Real-world | Incremental updates | PASS |
| Q4 | Real-world | Object streams (PDF 1.5+) | PASS |
| Q5 | Real-world | XRef streams (PDF 1.5+) | PASS |
| Q6 | Real-world | Optional Content Groups (layers) | PASS |
| Q8 | Real-world | PDF portfolio / collection | PASS |
| S4 | Fallback | Tesseract unavailable | PASS |
| S5 | Fallback | Jinja2 failure → legacy report | PASS |
| S6 | Fallback | ZipFile write failure | PASS |
| S8 | Fallback | All methods fail for one check | PASS |
| T1 | Threading | No title cross-contamination (5 iterations) | PASS |
| T3 | Threading | Unique temp directories | PASS |
| T5 | Threading | Rate limiter thread safety (10 iterations) | PASS |
| U1 | Gradio | None files → clean message | PASS |
| U2 | Gradio | Empty list → clean message | PASS |
| U3 | Gradio | Double submit → no crash | PASS |
| U5 | Gradio | Privacy notice present | PASS |
| U6 | Gradio | Build UI doesn't crash | PASS |

## UNFIXABLE ISSUES

None. All discovered issues were fixed.

## FINAL TEST SUITE

- Original tests: 292
- V4 adversarial tests: 44
- Total: 336
- 3 consecutive clean runs: **YES** (336 passed, 43 skipped, 0 failed)

## CONFIDENCE ASSESSMENT

After V4 testing: The tool handles remediation correctness, pipeline
resilience, concurrent processing, fallback chains, and real-world
PDF variants without silent data corruption. The one CRITICAL finding
(double suffix) has been fixed and verified.

Remaining attack surface:
- PDF/A conformance preservation (not tested — genuine limitation)
- Color contrast auto-fix (documented as detect-only)
- Complex table/list detection accuracy (heuristic-based)
- Scanned PDF OCR quality (depends on Tesseract + image quality)
