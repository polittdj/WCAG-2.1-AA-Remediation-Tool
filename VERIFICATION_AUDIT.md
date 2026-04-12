# VERIFICATION AUDIT — WCAG 2.1 AA PDF Remediation Tool

## Date: 2026-04-12

## PHASE 0A — CODEBASE MAP

### Pipeline Flow
Upload → fix_scanned_ocr → fix_title → fix_language → fix_security →
fix_pdfua_meta → fix_content_streams → fix_ghost_text → fix_untagged_content →
fix_headings → fix_widget_mapper → fix_widget_tu → fix_widget_appearance →
fix_focus_order → fix_link_alt → fix_figure_alt_text → fix_annotations →
fix_bookmarks → fix_artifacts → fix_pdfua_meta (final) → audit_pdf → report → ZIP

### Auditor Structure
47 checkpoints (C-01 through C-47) with statuses: PASS, FAIL, NOT_APPLICABLE, MANUAL_REVIEW, INDETERMINATE

---

## PHASE 0B — EXISTING TEST RESULTS

- **Total tests:** 355 (285 passed, 36 failed, 34 skipped)
- **Root cause of failures:** `pyo3_runtime.PanicException` from cryptography module (environment issue with `_cffi_backend` missing). Affects `ocrmypdf` import path in pipeline, causing cascading failures in tests that run the full pipeline.
- **Skipped tests:** Browser compatibility (5, need playwright), integration tests (22, need TEST_*.pdf fixtures), checkpoint coverage (7, environment-dependent)

---

## PHASE 0C — CHECKPOINT COVERAGE TABLE

### Legend
- **Detection**: Auditor checker actually analyzes PDF structure (not hardcoded)
- **Remediation**: A fix module actually modifies the PDF to address the issue
- **Test w/ Violation**: Existing test uses a PDF with a KNOWN violation for this checkpoint
- **GAP**: Any column is N

| ID   | Has Detection? | Has Remediation? | Test w/ Known Violation? | Test Verifies Detection? | Test Verifies Fix? | GAP? |
|------|---------------|-----------------|-------------------------|--------------------------|-------------------|------|
| C-01 | Y (checks /MarkInfo /Marked) | Y (fix_pdfua_meta) | Y | Y | Y | N |
| C-02 | Y (checks /Title non-empty) | Y (fix_title) | Y | Y | Y | N |
| C-03 | Y (checks title not placeholder) | Y (fix_title) | Y | Y | Y | N |
| C-04 | Y (checks /Lang on catalog) | Y (fix_language) | Y | Y | Y | N |
| C-05 | **SUSPECT** (always PASS — "no changes detected") | N (fix_language has TODO) | N | N | N | **Y** |
| C-06 | Y (checks XMP for pdfuaid) | Y (fix_pdfua_meta) | Y | Y | Y | N |
| C-07 | Y (checks DisplayDocTitle) | Y (fix_pdfua_meta) | Y | Y | Y | N |
| C-08 | Y (checks /P bit 10) | **PARTIAL** (fix_security detect-only) | N | N | N | **Y** |
| C-09 | Y (checks /Suspects flag) | Y (fix_pdfua_meta clears it) | Y | Y | N | **Y** |
| C-10 | Y (checks /Tabs /S on annot pages) | Y (fix_focus_order) | Y | Y | Y | N |
| C-11 | **HARDCODED PASS** | N | N | N | N | **Y** |
| C-12 | Y (checks struct tree node count) | Y (fix_untagged_content) | Y | Y | Y | N |
| C-13 | Y (regex scan for non-standard BDC) | Y (fix_content_streams) | Y | Y | Y | N |
| C-14 | Y (detects Tr 3 rendering mode) | Y (fix_ghost_text) | Y | Y | N | **Y** |
| C-15 | **MANUAL_REVIEW** (no analysis) | N | N | N | N | **Y** |
| C-16 | **HARDCODED NOT_APPLICABLE** | N | N | N | N | **Y** |
| C-17 | **MANUAL_REVIEW** (no analysis) | N | N | N | N | **Y** |
| C-18 | **HARDCODED NOT_APPLICABLE** | N | N | N | N | **Y** |
| C-19 | Y (checks for H1-H6 in struct tree) | Y (fix_headings) | Y | Y | N | **Y** |
| C-20 | Y (checks heading nesting) | **PARTIAL** (fix_headings creates but doesn't validate) | N | N | N | **Y** |
| C-21 | **HARDCODED NOT_APPLICABLE** | N | N | N | N | **Y** |
| C-22 | **HARDCODED NOT_APPLICABLE** | N | N | N | N | **Y** |
| C-23 | Y (checks /Outlines for >20 pages) | Y (fix_bookmarks) | N | N | N | **Y** |
| C-24 | Y (checks /Table has /TR kids) | N | N | N | N | **Y** |
| C-25 | Y (checks /TH has /Scope attr) | N | N | N | N | **Y** |
| C-26 | **HARDCODED NOT_APPLICABLE** | N | N | N | N | **Y** |
| C-27 | **SUSPECT** (always PASS when tables exist) | N | N | N | N | **Y** |
| C-28 | Y (checks /L has /LI children) | N | N | N | N | **Y** |
| C-29 | Y (checks /LI has /Lbl or /LBody) | N | N | N | N | **Y** |
| C-30 | **SUSPECT** (always PASS when lists exist) | N | N | N | N | **Y** |
| C-31 | Y (checks /Figure has /Alt) | Y (fix_figure_alt_text) | Y | Y | Y | N |
| C-32 | **SUSPECT** (always PASS) | N | N | N | N | **Y** |
| C-33 | **SUSPECT** (always PASS) | N | N | N | N | **Y** |
| C-34 | **MANUAL_REVIEW** (no scoring) | N | N | N | N | **Y** |
| C-35 | Y (checks /Form struct elements) | Y (fix_widget_mapper) | Y | Y | Y | N |
| C-36 | Y (checks /TU on widgets) | Y (fix_widget_tu) | Y | Y | Y | N |
| C-37 | **SUSPECT** (always PASS) | N | N | N | N | **Y** |
| C-38 | **MANUAL_REVIEW** (no scoring) | N | N | N | N | **Y** |
| C-39 | Y (checks /StructParent on widgets) | Y (fix_widget_mapper) | Y | Y | Y | N |
| C-40 | Y (resolves ParentTree to /Form) | Y (fix_widget_mapper) | Y | Y | Y | N |
| C-41 | **SUSPECT** (always PASS) | Y (fix_widget_appearance) | N | N | N | **Y** |
| C-42 | Y (checks /Link struct elements) | Y (fix_link_alt creates them) | Y | Y | N | **Y** |
| C-43 | Y (checks /Contents on links) | Y (fix_link_alt) | Y | Y | Y | N |
| C-44 | Y (checks /Dest or /A on links) | N | N | N | N | **Y** |
| C-45 | **SUSPECT** (always PASS for other annots) | Y (fix_annotations) | N | N | N | **Y** |
| C-46 | Y (checks /Nums flat, no /Kids) | Y (fix_widget_mapper) | Y | Y | Y | N |
| C-47 | **SUSPECT** (always PASS for multi-page) | **DETECT-ONLY** (fix_artifacts) | N | N | N | **Y** |

### Summary
- **Checkpoints with NO gaps:** 15 (C-01, C-02, C-03, C-04, C-06, C-07, C-10, C-12, C-13, C-31, C-35, C-36, C-39, C-40, C-46)
- **Checkpoints with GAPS:** 32
- **HARDCODED results (no analysis):** C-11, C-16, C-18, C-21, C-22, C-26 (6 total)
- **SUSPECT (always PASS without real analysis):** C-05, C-27, C-30, C-32, C-33, C-37, C-41, C-45, C-47 (9 total)
- **MANUAL_REVIEW with no numeric score:** C-15, C-17, C-34, C-38 (4 total)

---

## PHASE 0D — SILENT PASSES / N/A ABUSE

### Hardcoded Results (No Analysis)

| File | Line | Checkpoint | What It Does | What It Should Do |
|------|------|-----------|-------------|-------------------|
| wcag_auditor.py | 511 | C-11 | Returns PASS always ("no .notdef detected") | Should scan fonts for .notdef/ToUnicode gaps |
| wcag_auditor.py | 574 | C-16 | Returns NOT_APPLICABLE always | Should detect obvious contrast issues or flag for review |
| wcag_auditor.py | 584 | C-18 | Returns NOT_APPLICABLE always | Should detect images with text-like content |
| wcag_auditor.py | 640 | C-21 | Returns NOT_APPLICABLE always | Should compare heading font sizes vs body |
| wcag_auditor.py | 644 | C-22 | Returns NOT_APPLICABLE always | Should check heading consistency per level |
| wcag_auditor.py | 746 | C-26 | Returns NOT_APPLICABLE always | Should check column count consistency in tables |

### Suspect Passes (Appears to Work But Doesn't)

| File | Line | Checkpoint | What It Does | What It Should Do |
|------|------|-----------|-------------|-------------------|
| wcag_auditor.py | 416 | C-05 | Always returns PASS ("no changes detected" OR "at least one /Lang") | Should FAIL if foreign-language text exists without /Lang |
| wcag_auditor.py | 764 | C-27 | Returns PASS when tables exist (no summary check) | Should check for /Summary attr or /Caption child |
| wcag_auditor.py | 866 | C-30 | Returns PASS when any /L exists (no structure check) | Should verify nested /L is child of /LI not sibling |
| wcag_auditor.py | 907 | C-32 | Returns PASS always ("no duplicated alt text") | Should check parent/child alt text duplication |
| wcag_auditor.py | 914 | C-33 | Returns PASS always ("decorative image check completed") | Should detect decorative images not marked as Artifact |
| wcag_auditor.py | 984 | C-37 | Returns PASS always ("tab order check completed") | Should verify visual-to-tab-order correspondence |
| wcag_auditor.py | 1081 | C-41 | Returns PASS always ("appearance check completed") | Should verify widget AP streams are Artifact-tagged |
| wcag_auditor.py | 1163 | C-45 | Returns PASS for "other annotations" (no tag check) | Should verify annotations have struct elements |
| wcag_auditor.py | 1200 | C-47 | Returns PASS always for multi-page docs | Should detect repeated content not marked as Artifact |

### Manual Reviews Without Numeric Scores

| File | Line | Checkpoint | Issue |
|------|------|-----------|-------|
| wcag_auditor.py | 564 | C-15 | Returns "MANUAL_REVIEW" text, no confidence score |
| wcag_auditor.py | 579 | C-17 | Returns "MANUAL_REVIEW" text, no confidence score |
| wcag_auditor.py | 932 | C-34 | Returns "MANUAL_REVIEW" text, no confidence score |
| wcag_auditor.py | 992 | C-38 | Returns "MANUAL_REVIEW" text, no confidence score |

---

## PHASE 0E — HOUSEKEEPING NEEDS

### Dead/Stale Files
- Multiple `.png` screenshots in repo root (PAC WCAG reports) — should be in docs/
- Multiple `_report.html` files in repo root — generated artifacts, should not be committed
- `test_results_raw.txt` — stale test output
- `verify_auditor.py` — standalone verification script, possibly stale
- `PHASE-COMPLETE-*.md` (9 files) — historical tracking docs, clutter
- `R2_AUDIT_REPORT.md`, `R3_BUILD_REPORT.md` — historical, possibly stale
- `ADVERSARIAL_V4_TEST_REPORT.md`, `TEST_SUITE_REPORT.md` — generated reports
- `GAP-FIX-COMPLETE.md`, `FINAL_SUMMARY.md`, `GROUND_TRUTH.md` — phase docs

### Code Issues
- `fix_artifacts.py`: Detection only, no remediation (reported but doesn't fix)
- `fix_security.py`: Detection only (can't fix encrypted PDFs without owner password)
- `fix_focus_order.py`: Only sets /Tabs on pages WITH annotations (directive says ALL pages)
- Several checkers return results without doing work (see Phase 0D)

### Dependency Concerns
- `cryptography` module conflict in environment (pyo3 panic)
- `ocrmypdf` requires `tesseract` binary (not always available)

### .gitignore Gaps
- Generated HTML reports in repo root should be ignored
- PNG screenshots in repo root should be in docs/ or ignored
- `test_results_raw.txt` should be ignored

---

## CRITICAL FINDINGS SUMMARY

1. **32 of 47 checkpoints have gaps** — either no real detection, no remediation, or no proper test
2. **6 checkpoints are completely hardcoded** — always return the same result regardless of input
3. **9 checkpoints are suspect** — appear to work but don't actually analyze anything
4. **4 manual review checkpoints have no numeric scoring**
5. **fix_focus_order only sets /Tabs on pages with annotations** (should be unconditional per spec)
6. **fix_artifacts is detect-only** — reports header/footer repetition but doesn't mark as Artifact
7. **Pipeline failures cascade** when `ocrmypdf` import fails (cryptography issue)
8. **No verification PDFs exist** with known violations specifically designed to test each checkpoint
