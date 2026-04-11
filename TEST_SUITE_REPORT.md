# SYNTHETIC TEST SUITE REPORT — 26 TEST PDFs + 5 Production PDFs

**Date:** 2026-04-11  
**Git SHA:** 7d93330  
**Branch:** claude/review-image-error-IzYFq

---

## EXECUTIVE SUMMARY

| Metric | Value |
|--------|-------|
| Total synthetic test PDFs | 26 |
| Production test PDFs | 5 |
| **Total PDFs tested** | **31** |
| Pipeline PASS | 21 (68%) |
| Pipeline PARTIAL | 9 (29%) |
| Pipeline CRASH | 0 (0%) |
| Encrypted (handled gracefully) | 1 (3%) |
| Total checkpoints fixed by pipeline | 61 |
| Existing unit/integration tests | 173 (all passing) |

---

## PER-FILE RESULTS — 26 SYNTHETIC TEST PDFs

| # | File | Scenario | Pre-Audit | Pipeline | Post-Audit | Fixed |
|---|------|----------|-----------|----------|------------|-------|
| 01 | TEST_01_completely_untagged | No struct tree, no tags | 6/10 | **PARTIAL** | 8/10 | +2 |
| 02 | TEST_02_scanned_no_text | Image-only scan | 6/10 | **PASS** | 10/10 | +4 |
| 03 | TEST_03_forms_no_tooltips | Widgets without /TU | 3/10 | **PASS** | 10/10 | +7 |
| 04 | TEST_04_images_no_alt | Figures without /Alt | 6/10 | **PASS** | 9/10 | +3 |
| 05 | TEST_05_low_contrast | Low contrast text | 6/10 | **PARTIAL** | 8/10 | +2 |
| 06 | TEST_06_tables_no_headers | Table without TH | 7/10 | **PASS** | 9/10 | +2 |
| 07 | TEST_07_links_no_description | Links without /Contents | 6/10 | **PASS** | 10/10 | +4 |
| 08 | TEST_08_multipage_no_bookmarks | 5 pages, no outlines | 9/10 | **PASS** | 10/10 | +1 |
| 09 | TEST_09_no_language | No /Lang set | 9/10 | **PARTIAL** | 9/10 | 0 |
| 10 | TEST_10_nonstandard_bdc_tags | ExtraCharSpan/ParagraphSpan | 6/10 | **PASS** | 9/10 | +3 |
| 11 | TEST_11_javascript_actions | JS in /OpenAction | 6/10 | **PASS** | 10/10 | +4 |
| 12 | TEST_12_broken_struct_tree | /K is a string (invalid) | 6/10 | **PARTIAL** | 8/10 | +2 |
| 13 | TEST_13_already_compliant | Everything correct | 10/10 | **PASS** | 10/10 | 0 |
| 14 | TEST_14_everything_wrong | Max issues combined | 3/10 | **PARTIAL** | 6/10 | +3 |
| 15 | TEST_15_landscape | Landscape orientation | 8/10 | **PASS** | 10/10 | +2 |
| 16 | TEST_16_with_attachment | Embedded attachment | 8/10 | **PASS** | 10/10 | +2 |
| 17 | TEST_17_encrypted | Password-protected | 0/10 | **PARTIAL** | N/A | 0 |
| 18 | TEST_18_ghost_text | Invisible Tr 3 text | 6/10 | **PARTIAL** | 8/10 | +2 |
| 19 | TEST_19_multilingual | English + Spanish | 9/10 | **PARTIAL** | 9/10 | 0 |
| 20 | TEST_20_no_pdfua_id | No pdfuaid:part in XMP | 10/10 | **PASS** | 10/10 | 0 |
| 21 | TEST_21_wrong_tabs_order | /Tabs = /R (wrong) | 3/10 | **PARTIAL** | 9/10 | +6 |
| 22 | TEST_22_th_no_scope | TH without Scope attr | 7/10 | **PASS** | 9/10 | +2 |
| 23 | TEST_23_heading_hierarchy_wrong | H3 before H1 | 7/10 | **PASS** | 9/10 | +2 |
| 24 | TEST_24_suspects_true | /Suspects = true | 7/10 | **PASS** | 9/10 | +2 |
| 25 | TEST_25_fonts_not_embedded | Non-embedded Type1 | 6/10 | **PARTIAL** | 8/10 | +2 |
| 26 | TEST_26_annotations_no_contents | /Text annot, no /Contents | 6/10 | **PASS** | 10/10 | +4 |

---

## PER-FILE RESULTS — 5 PRODUCTION PDFs

| File | Pre-Audit | Pipeline | Post-Audit | Fixed |
|------|-----------|----------|------------|-------|
| 12.0_updated.pdf | 10/10 | **PASS** | 10/10 | 0 |
| 12.0_updated - converted from MS Word.pdf | 8/10 | **PASS** | 10/10 | +2 |
| 12.0_updated_editable.pdf | 7/10 | **PASS** | 10/10 | +3 |
| 12.0_updated_editable_ADA.pdf | 7/10 | **PASS** | 10/10 | +3 |
| CPSSPPC_TRAVEL_FORM (Politte).pdf | 5/10 | **PASS** | 10/10 | +5 |

**All 5 production PDFs: PASS with 10/10 checkpoints after remediation.**

---

## WHAT THE PIPELINE FIXES SUCCESSFULLY

| Checkpoint | What it fixes | Test PDFs that demonstrate it |
|-----------|---------------|-------------------------------|
| C-01 Figure /Alt | Retags undescribable figures as /Artifact | TEST_04 |
| C-02 Widget /TU | Derives accessible names from /T, parent chain | TEST_03, TEST_14, TEST_21 |
| C-13 Title present | Sets DocInfo /Title from content/filename/date | TEST_01-12, TEST_14-26 |
| C-16 /Lang set | Sets from OCR language or defaults to "en" | TEST_02, TEST_07, TEST_15-16, TEST_26 |
| C-18 Widget StructParent | Creates /StructParent on every widget | TEST_03 |
| C-19 SP→Form | Creates /Form struct elements for widgets | TEST_03 |
| C-25 MarkInfo /Marked | Sets /Marked = true | TEST_02, TEST_07-08, TEST_15-16, TEST_26 |
| C-33 Standard BDC tags | Replaces ExtraCharSpan → Span, etc. | TEST_10, TEST_14 |
| C-34 Title not placeholder | Replaces "Untitled Document" etc. | All files with bad/missing titles |
| C-35 Flat ParentTree | Flattens /Kids→/Nums, creates stub if absent | TEST_02, TEST_07-08, TEST_15-16, TEST_26 |

---

## WHAT THE PIPELINE DOES NOT FIX YET (PARTIAL results)

| Test | Issue | Missing fix module | v6 checkpoint |
|------|-------|--------------------|---------------|
| TEST_01 | No struct tree (untagged) | fix_tag_tree.py | C-05, C-06 |
| TEST_05 | Low contrast text | fix_contrast.py | C-16 (v6) |
| TEST_09 | /Lang not set on tagged doc | fix_language.py | C-28 |
| TEST_12 | Broken struct tree (/K = string) | fix_tag_tree.py | C-06, C-32 |
| TEST_14 | No struct tree + multiple issues | fix_tag_tree.py | C-05, C-06 |
| TEST_17 | Encrypted (password-protected) | N/A (design limit) | — |
| TEST_18 | Ghost text (Tr 3, 6pt) | fix_ghost_text.py | C-10 |
| TEST_19 | Missing passage-level /Lang | fix_language.py | C-29 |
| TEST_21 | Widgets on page but no struct tree | fix_tag_tree.py | C-33 |
| TEST_25 | Non-embedded fonts | fix_fonts.py | C-44 |

---

## CHECKPOINTS NOT YET IMPLEMENTED (37 of 47)

These are the checkpoints from the v6 specification that do NOT have auditor functions or fix modules:

### Auto-PASS (4) — always pass for PDF
C-04 (Media N/A), C-13 (Orientation), C-17 (Text resize), C-19 (Reflow)

### Manual-Review (5) — flag for human judgment
C-12 (Color-only info), C-15 (Color mechanism), C-22 (Keyboard traps), C-30 (Context changes), C-31 (Error handling)

### Trivial to implement (12) — simple property checks
C-03, C-05, C-24, C-28, C-29, C-35, C-36, C-37, C-38, C-43, C-44, C-47

### Moderate complexity (10) — struct tree walking
C-06, C-07, C-08, C-09, C-10, C-11, C-14, C-21, C-32, C-33 (v6), C-34 (v6)

### Complex (6) — advanced analysis
C-16 (contrast), C-18 (images of text), C-20 (non-text contrast), C-39-42, C-45-46

---

## KEY FINDINGS

1. **Zero crashes on any input** — encrypted PDFs are handled gracefully with a clean error message
2. **OCR works end-to-end** — TEST_02 (scanned PDF) goes from 6/10 → 10/10 PASS
3. **Form remediation is comprehensive** — TEST_03 fixes 7 checkpoints in one pass
4. **Already-compliant documents pass through unchanged** — TEST_13 has 0 modifications
5. **The pipeline is idempotent** — running twice produces the same result
6. **16 of 26 synthetic tests reach PASS** — the tool handles most common scenarios
7. **10 PARTIAL results identify exactly which fix modules need to be built** for v6

---

## RECOMMENDATIONS

### Priority 1 — Fix the remaining PARTIAL cases:
1. **fix_tag_tree.py** — would fix TEST_01, TEST_12, TEST_14, TEST_21 (4 files)
2. **fix_language.py** — would fix TEST_09, TEST_19 (2 files)
3. **fix_ghost_text.py** — would fix TEST_18 (1 file)
4. **fix_pdfua_meta.py** — needed for full PAC compliance

### Priority 2 — Add missing checkpoints:
- 12 trivial checkpoints (simple property checks, 5-15 lines each)
- 5 manual-review flags
- 4 auto-PASS returns

### Priority 3 — Complex modules:
- fix_contrast.py, fix_tables.py, fix_headings.py, fix_lists.py
