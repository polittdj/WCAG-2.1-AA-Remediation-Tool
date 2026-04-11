# R2 AUDIT REPORT — Pre-Migration Assessment

**Date:** 2026-04-11
**Git SHA:** 7d93330
**Branch:** claude/review-image-error-IzYFq

---

## 1. EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| Total tests | 173 |
| Passed | 173 |
| Failed | 0 |
| Errors | 0 |
| Skipped | 0 |
| Pass rate | **100%** |
| Total PDFs smoke-tested | 19 |
| Pipeline runs executed | 10 |
| Pipeline PASS | 10 |
| Pipeline crashes | 0 |
| pikepdf open success | 19/19 |
| fitz open success | 19/19 |

**Bottom line:** The current codebase is fully operational. All 173 tests pass. Every PDF opens successfully. Every raw input PDF runs through the full pipeline without crashing and produces PASS output. The system is solid.

---

## 2. PASSING TESTS — FULL LIST

### test_wcag_auditor.py (63 tests) — Auditor checkpoint logic
All 10 checkpoints tested with synthetic PDFs for PASS, FAIL, NOT_APPLICABLE, and edge cases:
- TestC01FigureAlt: 8 tests (with alt, without, empty, whitespace, no struct, no figures, partial, nested)
- TestC02WidgetTU: 6 tests (with TU, without, empty, whitespace, no widgets, partial)
- TestC13Title: 4 tests (has title, no title, empty, whitespace)
- TestC16Lang: 4 tests (has lang, no lang, empty, parametrized 5 languages)
- TestC18StructParent: 4 tests (has SP, without, no widgets, partial)
- TestC19StructParentResolvesToForm: 5 tests (resolves to Form, to Span, no struct, no widgets, no SP)
- TestC25MarkInfo: 3 tests (true, missing, false)
- TestC33BDCTags: 6 tests (no BDC, standard, non-standard, artifact, mixed, multi-page)
- TestC34TitleNotPlaceholder: 5+9 parametrized (real, empty, untitled, case-insensitive, all 9 blacklisted)
- TestC35ParentTree: 4 tests (flat Nums, Kids tree, no PT, no struct)
- TestAuditorStructural: 5 tests (all 10 present, summary counts, timestamp, corrupt, fully-compliant)

### test_fix_scanned_ocr.py (24 tests) — OCR detection + integration
- TestDetection: 10 tests (scan/digital/hybrid classification, signals, empty PDF, nonexistent)
- TestFixScannedOcr: 8 tests (noop digital, OCR scan, struct stub, lang, multi-page, force OCR, lang env, graceful)
- TestPipelineIntegration: 4 tests (scan pipeline, title from OCR, digital unchanged, fixtures unaffected)
- 2 tests tagged with skip_no_ocr that run when tesseract is installed

### test_fix_figure_alt_text.py (10 tests) — Figure alt text + hex decode
- extract_text Tj/TJ array, hex 4-byte UTF-16BE, hex 2-byte latin-1, mixed paren+hex
- no-figure noop, placeholder without API key, Claude mock, no-opt-in gate, existing alt preserved, decorative sentinel

### test_fix_link_alt.py (12 tests) — Link annotation descriptions
- URL humanization (slug, extensions, camelCase), URI→name (GSA, mailto, tel, host-only)
- Travel Form link gets contents, existing preserved, struct elem alt, no-links noop, /Dest link

### test_pipeline.py (15 tests) — Pipeline end-to-end + resilience
- All 5 PDFs pass, output naming, bare PDF, original unchanged, ZIP contents, privacy notice
- No AI without opt-in, AI banner with mock, password-protected, corrupt, empty, nonexistent
- Idempotent re-run, result keys, checkpoint completeness

### test_fix_widget_tu.py (8 tests) — Widget accessible names
### test_fix_widget_appearance.py (7 tests) — Widget /AP artifact tagging
### test_fix_untagged_content.py (7 tests) — Untagged content wrapping
### test_fix_widget_mapper.py (6 tests) — Widget→Form struct mapping
### test_fix_content_streams.py (6 tests) — BDC tag normalization
### test_app.py (6 tests) — Gradio UI constants + processing
### test_fix_title.py (5 tests) — Title derivation
### test_fix_focus_order.py (4 tests) — Tab order enforcement

---

## 3. FAILING TESTS — FULL DETAIL

**None.** All 173 tests pass.

---

## 4. CHECKPOINT COVERAGE MAP

| ID | Check Name | Detection Tests | Fix Tests | Status |
|----|-----------|-----------------|-----------|--------|
| C-01 | Figure /Alt text | test_wcag_auditor (8) | test_fix_figure_alt_text (10) | SOLID |
| C-02 | Widget /TU tooltip | test_wcag_auditor (6) | test_fix_widget_tu (8) | SOLID |
| C-13 | DocInfo /Title set | test_wcag_auditor (4) | test_fix_title (5) | SOLID |
| C-16 | Document /Lang | test_wcag_auditor (4) | test_fix_scanned_ocr (2) | SOLID |
| C-18 | Widget /StructParent | test_wcag_auditor (4) | test_fix_widget_mapper (6) | SOLID |
| C-19 | SP resolves to /Form | test_wcag_auditor (5) | test_fix_widget_mapper (6) | SOLID |
| C-25 | /MarkInfo /Marked | test_wcag_auditor (3) | test_fix_scanned_ocr (2) | SOLID |
| C-33 | Standard BDC tags | test_wcag_auditor (6) | test_fix_content_streams (6) | SOLID |
| C-34 | Title not placeholder | test_wcag_auditor (14) | test_fix_title (5) | SOLID |
| C-35 | ParentTree flat /Nums | test_wcag_auditor (4) | test_fix_widget_mapper (6) | SOLID |
| **C-03..C-12** | **Not implemented** | NONE | NONE | NO TEST |
| **C-14..C-15** | **Not implemented** | NONE | NONE | NO TEST |
| **C-17..C-24** | **Not implemented** | NONE | NONE | NO TEST |
| **C-26..C-32** | **Not implemented** | NONE | NONE | NO TEST |
| **C-36..C-47** | **Not implemented** | NONE | NONE | NO TEST |

**Coverage: 10 of 47 checkpoints (21%)**

---

## 5. MODULE HEALTH MAP

| Module | Lines | Tests | Pass/Fail | Health |
|--------|-------|-------|-----------|--------|
| wcag_auditor.py | 646 | 63 | 63/0 | **SOLID** |
| pipeline.py | 458 | 15 | 15/0 | **SOLID** |
| fix_figure_alt_text.py | 842 | 10 | 10/0 | **SOLID** |
| fix_untagged_content.py | 634 | 7 | 7/0 | **SOLID** |
| fix_link_alt.py | 455 | 12 | 12/0 | **SOLID** |
| fix_widget_mapper.py | 431 | 6 | 6/0 | **SOLID** |
| fix_widget_tu.py | 399 | 8 | 8/0 | **SOLID** |
| app.py | 390 | 6 | 6/0 | **SOLID** |
| fix_widget_appearance.py | 382 | 7 | 7/0 | **SOLID** |
| fix_scanned_ocr.py | 373 | 24 | 24/0 | **SOLID** |
| fix_title.py | 333 | 5 | 5/0 | **SOLID** |
| fix_content_streams.py | 296 | 6 | 6/0 | **SOLID** |
| verify_auditor.py | 144 | 0 | — | UNTESTED (helper) |
| fix_focus_order.py | 109 | 4 | 4/0 | **SOLID** |

**Total: 5,892 lines across 14 modules. 13 of 14 SOLID.**

---

## 6. SAMPLE PDF SMOKE TEST RESULTS

### Per-File Results Table

| File | Pg | Size | Tagged | Forms | pikepdf | fitz | Audit | Pipeline |
|------|----|------|--------|-------|---------|------|-------|----------|
| 12.0_updated.pdf | 3 | 186K | Y | N | OK | OK | 10/10 | PASS |
| 12.0_updated - converted from MS Word.pdf | 3 | 186K | Y | N | OK | OK | 8/10 | PASS |
| 12.0_updated_editable.pdf | 3 | 338K | Y | Y | OK | OK | 7/10 | PASS |
| 12.0_updated_editable_ADA.pdf | 3 | 217K | Y | Y | OK | OK | 7/10 | PASS |
| CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte.pdf | 2 | 2.0M | Y | Y | OK | OK | 5/10 | PASS |
| tests/fixtures/r2/12.0_updated.pdf | 3 | 186K | Y | N | OK | OK | 10/10 | PASS |
| tests/fixtures/r2/12.0_updated_word.pdf | 3 | 186K | Y | N | OK | OK | 8/10 | PASS |
| tests/fixtures/r2/12.0_updated_editable.pdf | 3 | 338K | Y | Y | OK | OK | 7/10 | PASS |
| tests/fixtures/r2/12.0_updated_editable_ADA.pdf | 3 | 217K | Y | Y | OK | OK | 7/10 | PASS |
| tests/fixtures/r2/cpsspc_travel_form.pdf | 2 | 2.0M | Y | Y | OK | OK | 5/10 | PASS |

**All 10 pipeline runs: PASS. Zero crashes. Zero errors.**

### Pre-remediation checkpoint breakdown (raw inputs):

| File | C-01 | C-02 | C-13 | C-16 | C-18 | C-19 | C-25 | C-33 | C-34 | C-35 |
|------|------|------|------|------|------|------|------|------|------|------|
| 12.0_updated | N/A | N/A | PASS | PASS | N/A | N/A | PASS | PASS | PASS | PASS |
| Word converted | N/A | N/A | FAIL | PASS | N/A | N/A | PASS | PASS | FAIL | PASS |
| Editable | N/A | FAIL | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
| Editable ADA | N/A | FAIL | PASS | PASS | PASS | PASS | PASS | FAIL | PASS | FAIL |
| Travel Form | FAIL | FAIL | FAIL | PASS | FAIL | N/A | PASS | PASS | FAIL | PASS |

**After pipeline: ALL become PASS on all 10 checkpoints.**

---

## 7. WORKING MODULES — SAFE TO KEEP

Every module is safe to keep. All 13 modules with tests pass 100%:

1. **wcag_auditor.py** — 63 tests, all pass, synthetic PDF coverage for every checkpoint
2. **pipeline.py** — 15 tests, resilience tested (corrupt, encrypted, empty, re-run)
3. **fix_scanned_ocr.py** — 24 tests, OCR detection + pipeline integration verified
4. **fix_figure_alt_text.py** — 10 tests, hex decode, bbox coords, decorative retag
5. **fix_link_alt.py** — 12 tests, URI/Dest/rect fallback, struct alt
6. **fix_widget_mapper.py** — 6 tests, idempotent, ParentTree flattening
7. **fix_widget_tu.py** — 8 tests, inherited /FT, non-terminal fields
8. **fix_widget_appearance.py** — 7 tests, shared XObject safety
9. **fix_untagged_content.py** — 7 tests, operand capture, BDC/EMC delta
10. **fix_content_streams.py** — 6 tests, RoleMap cleanup
11. **fix_title.py** — 5 tests, content/filename/date derivation
12. **fix_focus_order.py** — 4 tests, /Tabs /S enforcement
13. **app.py** — 6 tests, Gradio UI, derived columns

---

## 8. BROKEN OR INCOMPLETE MODULES

**None broken.** All modules operational.

**Incomplete (by v6 spec):**
- Missing 37 of 47 auditor checkpoints
- Missing 11 of 21 fix modules
- No synthetic TEST_01..TEST_26 PDF files
- No PDF/UA XMP identifier (pdfuaid:part=1)
- No ViewerPreferences.DisplayDocTitle
- No heading detection/hierarchy
- No table detection/TH Scope
- No list structure detection
- No bookmark generation
- No contrast detection
- No ghost text cleanup
- No annotation tagging (non-Widget/Link)
- No header/footer artifacting

---

## 9. TEST FIXTURE INVENTORY

### Linked Fixtures (6 PDFs used by tests)
| File | Size | Pages | Tests using it | Status |
|------|------|-------|----------------|--------|
| 12.0_updated - WCAG 2.1 AA Compliant.pdf | 248K | 3 | 12 test files | LINKED |
| 12.0_updated - converted... Compliant.pdf | 248K | 3 | 8 test files | LINKED |
| 12.0_updated_editable - ... Compliant.pdf | 268K | 3 | 8 test files | LINKED |
| 12.0_updated_editable_ADA -... Compliant.pdf | 218K | 3 | 8 test files | LINKED |
| CPSSPPC_TRAVEL_FORM... Compliant.pdf | 2.0M | 2 | 11 test files | LINKED |
| CPSSPPC_TRAVEL_FORM... Politte.pdf | 2.0M | 2 | 2 test files | LINKED |

### Orphaned Fixtures (20 PDFs not referenced by any test)
- 7 PAC report PDFs (*.PAC_*.pdf) — review artifacts, safe to archive
- 5 duplicate raw PDFs in tests/fixtures/r2/ — copies of test_suite/ originals
- 5 raw unremediated PDFs — useful for pipeline but not directly referenced
- 3 intermediate remediation outputs — from earlier sessions

---

## 10. ARCHITECTURE OBSERVATIONS

### Pipeline orchestration
- Single `pipeline.py` file with `run_pipeline()` function
- 10 sequential fix steps, each reads input → writes output
- Step failures logged but don't halt pipeline (graceful degradation)
- Auditor runs after all fixes, determines PASS/PARTIAL
- Self-healing retry: NOT implemented (v6 spec requires it)

### Checkpoint numbering
- Current: C-01, C-02, C-13, C-16, C-18, C-19, C-25, C-33, C-34, C-35 (sparse numbering)
- v6 target: C-01 through C-47 (dense numbering with different meanings for some IDs)
- **ID conflict**: Current C-16 = /Lang, v6 C-16 = Text contrast. Current C-18 = StructParent, v6 C-18 = Images of text.

### Current vs target checkpoint count
- Current: 10 checkpoints
- v6 target: 47 checkpoints
- Gap: 37 checkpoints (79% not yet implemented)
- Of the 37 missing: ~8 auto-PASS, ~5 manual-review, ~12 trivial, ~8 moderate, ~4 complex

### No architectural blockers
- Modular design allows adding fix modules without changing existing ones
- Pipeline step list is a simple array — easy to extend
- Auditor checker list is a simple array — easy to add new functions
- No circular dependencies detected
- All imports clean (verified in Step 2)

---

## 11. RECOMMENDATIONS FOR R3 MIGRATION

### Modules to KEEP as-is (all tests pass, smoke test clean):
All 14 current modules. No rebuild needed.

### Modules to ADD (11 new fix modules per v6 spec):
1. fix_pdfua_meta.py (C-35, C-37, C-38) — **highest priority, PAC compliance**
2. fix_language.py (C-28, C-29) — trivial
3. fix_suspects.py (C-43) — trivial
4. fix_headings.py (C-09, C-40-42) — moderate
5. fix_annotations.py (C-03, C-45) — moderate
6. fix_bookmarks.py (C-23) — moderate
7. fix_artifacts.py (C-46) — moderate
8. fix_tag_tree.py (C-05, C-06) — complex
9. fix_ghost_text.py (C-10) — moderate
10. fix_tables.py (C-07, C-39) — complex
11. fix_lists.py (C-08) — moderate
12. fix_reading_order.py (C-11) — complex
13. fix_contrast.py (C-16, C-20) — complex

### Auditor expansion:
- Add 37 new `_check_cNN` functions to wcag_auditor.py
- Renumber existing checkpoints to match v6 ID scheme
- Update CRITICAL_CHECKPOINTS in pipeline.py

### Test fixtures needed:
- 0 synthetic TEST_*.pdf files exist (v6 wants 26)
- Current approach (inline pikepdf generation in tests) is viable and avoids fixture bloat
- Recommend: keep inline approach, add more test classes per new checkpoint

### Estimated gap to full v6 compliance:
- ~3,500 lines of new code (auditor + fix modules)
- ~800 lines of new tests
- 4-6 focused sessions to complete
- Highest ROI first: fix_pdfua_meta → fix_language → fix_suspects → fix_headings
