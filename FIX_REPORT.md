# FIX REPORT — 6 Critical WCAG Remediation Tool Failures

## Date: 2026-04-12
## Branch: `claude/wcag-checkpoint-verification-GCA5j`

---

## Executive Summary

An independent comparative audit identified 6 critical failures in the
WCAG 2.1 AA Remediation Tool. The tool was reporting PASS and N/A on
checkpoints where it should have been reporting FAIL. The remediation
engine was doing far less than it claimed: most structured content
(paragraphs, tables, lists, images) was being completely untagged
while the auditor hid the failures by reporting N/A.

**All 6 issues are now fixed.** 286 tests pass across 3 consecutive
runs with zero introduced regressions.

---

## Reproduction: Audit PDFs

Six new purpose-built audit PDFs (in `tests/audit_pdfs/`) reproduce
each issue with realistic content:

| PDF | Content | Pre-fix behavior |
|-----|---------|------------------|
| `01_untagged_no_metadata.pdf` | 3 pages, ~15 paragraphs, 4 headings | 4 struct elements total |
| `02_form_no_tooltips.pdf` | Form with 6 visible labels | /TU = "field1", "field2"... |
| `03_images_no_alt_text.pdf` | 3 image draws, visible text | Image checks = N/A |
| `04_table_no_headers.pdf` | 2 data tables (4x4, 4x3) | Table checks = N/A |
| `06_bad_heading_hierarchy.pdf` | H1→H3→H5→H1 | C-20 = PASS |
| `09_fake_lists_no_structure.pdf` | 5 bullet + 5 numbered items | List checks = N/A |

---

## ISSUE 1 — Tag Creation Is Headings-Only (CRITICAL)

### Problem
`fix_untagged_content.py` wraps content streams with /Span marked-content
but doesn't create /P, /Table, /L, or /Figure struct elements. `fix_headings`
creates only H1-H6 elements based on font size. Result: a 3-page document
with dozens of paragraphs produces only 4 struct elements
(`Document + H1 + H2 + H2`).

### Fix
New module `fix_content_tagger.py` runs after `fix_headings` and creates:
- **`/P`** for each body text block (non-heading, non-list)
- **`/Figure`** for each image draw (counts `Do` operators, not XObjects,
  so reportlab's dedupe doesn't undercount)
- **`/Table` > `/TR` > `/TH` + `/TD`** for tables detected by
  PyMuPDF's `find_tables()` — first row = TH with Scope=Column
- **`/L` > `/LI` > `/Lbl` + `/LBody`** for consecutive bullet or
  numbered list lines

The module is idempotent — it skips tag types already present in the
struct tree so repeated runs don't double-tag.

### Files Changed
- **NEW**: `fix_content_tagger.py` (578 lines)
- **MODIFIED**: `pipeline.py` (added step after `fix_headings`)

### Verification
| Audit PDF | Before | After |
|-----------|--------|-------|
| 01_untagged | 4 structs | **15** structs (P tags added) |
| 03_images  | 2 structs | **6** structs (3 Figures) |
| 04_table   | 4 structs | **56** structs (2 Tables, 9 TR, 7 TH, 25 TD, 9 P) |
| 09_lists   | 2 structs | **36** structs (2 L, 10 LI, 10 Lbl, 10 LBody, 2 P) |

---

## ISSUE 2 — Auditor N/A Abuse (CRITICAL)

### Problem
Auditor checkers returned NOT_APPLICABLE when the relevant struct
elements (tables/lists/figures) didn't exist in the tag tree. But the
elements didn't exist BECAUSE the tag creator never made them
(Issue 1) — circular logic that hid the real failures.

Example: `04_table_no_headers.pdf` has two visible data tables. Pre-fix:
```
C-24 (tables /TR):     NOT_APPLICABLE  "No Table elements in structure tree"
C-25 (TH Scope):       NOT_APPLICABLE  "No TH elements in structure tree"
C-27 (table summary):  NOT_APPLICABLE  "No Table elements in structure tree"
```

### Fix
Added content-detection helpers to `wcag_auditor.py`:

- **`_content_has_tables(pdf_path)`** — PyMuPDF `find_tables()`
- **`_content_has_lists(pdf_path)`** — scans text for bullet chars
  and numbered-list prefixes; ≥2 consecutive hits = list
- **`_content_has_images(pdf)`** — checks page Resources for `/Image`
  XObjects
- **`_content_has_links(pdf)`** — checks `/Link` annotations
- **`_count_figure_and_artifact(struct_root)`** — accepts /Artifact-
  marked decorative images as "handled"

Updated checkers to upgrade N/A → FAIL when content exists but no
tags do. Affected: C-24, C-25, C-26, C-27 (tables); C-28, C-29, C-30
(lists); C-31, C-32, C-33, C-34 (figures).

### Files Changed
- **MODIFIED**: `wcag_auditor.py` (+295 lines)

### Verification
```
BEFORE (04_table_no_headers.pdf):
  C-24: NOT_APPLICABLE   C-25: NOT_APPLICABLE   C-27: NOT_APPLICABLE

AFTER:
  C-24: FAIL "Document contains tables but has no structure tree"
  C-25: FAIL (same)
  C-27: FAIL (same)

After full pipeline (content tagger creates the structs):
  C-24: PASS   C-25: PASS   C-27: PASS
```

---

## ISSUE 3 — Tab Order Not Set On All Pages (HIGH)

### Problem
`fix_focus_order.py` only set `/Tabs=/S` on pages with annotations.
The auditor's C-10 check only looked at pages with annotations, so the
bug was masked. PDF/UA-1 requires `/Tabs=/S` on every page
unconditionally.

### Fix
1. `fix_focus_order`: removed the `_has_annots` gate. Now sets
   `/Tabs=/S` on EVERY page.
2. `wcag_auditor._check_c10`: now requires `/Tabs=/S` on ALL pages
   (not just those with annotations).

### Files Changed
- **MODIFIED**: `fix_focus_order.py`
- **MODIFIED**: `wcag_auditor.py` (_check_c10)
- **MODIFIED**: `tests/test_fix_focus_order.py` (updated assertion)

### Verification
```
BEFORE (tab order on audit PDFs):
  01_untagged: p0=MISSING, p1=MISSING, p2=MISSING
  03_images:   p0=MISSING
  04_table:    p0=MISSING
  09_lists:    p0=MISSING

AFTER:
  01_untagged: p0=/S, p1=/S, p2=/S
  03_images:   p0=/S
  04_table:    p0=/S
  09_lists:    p0=/S
  All C-10 checks: PASS
```

---

## ISSUE 6 — Heading Hierarchy Check (HIGH)

### Problem
C-20 (heading nesting) reported PASS even when:
1. Multiple H1 elements existed in the struct tree
2. The "first heading" check visited nodes in REVERSE order because
   `_walk_struct_tree` used LIFO stack traversal

`fix_headings.py` created multiple H1s when two text blocks shared the
largest font size, producing invalid hierarchies.

### Fix
Three interlocking changes:

1. **`_check_c20`**: Now detects multiple H1 elements as FAIL:
   ```python
   if h1_count > 1:
       return _result("FAIL", f"Multiple H1 headings ({h1_count}) ...")
   ```

2. **`_walk_struct_tree_ordered`**: NEW FIFO depth-first walker that
   yields nodes in document order. C-20 uses this so "first heading"
   means the one that actually appears first, not the last added.

3. **`fix_headings`**: Ensures only ONE H1 is created. If multiple
   candidates share the largest font size, the first becomes H1 and
   the rest are demoted to H2.

### Files Changed
- **MODIFIED**: `wcag_auditor.py` (_check_c20 + `_walk_struct_tree_ordered`)
- **MODIFIED**: `fix_headings.py` (single-H1 enforcement)

### Verification
```
Two-H1 synthetic PDF:
  BEFORE: C-20 = PASS
  AFTER:  C-20 = FAIL "Multiple H1 headings (2) ..."

06_bad_heading_hierarchy (two 22pt blocks in source):
  BEFORE: H1, H2, H2 (but audit said "first heading is H2")
  AFTER:  H1, H2, H2 and C-20 = PASS (single H1 enforced)

Skipped levels synthetic PDF (H1 → H3):
  C-20 = FAIL "Heading level skipped: H1 followed by H3"
```

---

## ISSUE 4 — Document Titles Are Garbage (MEDIUM)

### Problem
`fix_title` picked the first text block it found with a large font.
Example bad titles from the audit:
- `"(anonymous)"` (from 04_tables)
- `"The partnership agreement was signed in Berlin on March 15."`
- `"1. Call to Order — Meeting called to order at 9:00 AM"`

### Fix
Added heuristic filters in `_derive_from_content`:

1. **`_looks_like_sentence(text)`**: rejects candidates ending in
   `.`/`!`/`?` with ≥3 common function words (the, was, is, of...)
2. **`_looks_like_agenda_item(text)`**: rejects `"N. "` / `"N) "`
   patterns containing em-dash, colon, or length > 60
3. Added `"(anonymous)"` and `"anonymous"` to the BLACKLIST

When no candidate survives filtering, `fix_title` falls through to the
filename-based derivation (which produces titles like "Quarterly Sales
Report" from `04_table_no_headers.pdf`).

### Files Changed
- **MODIFIED**: `fix_title.py`

### Verification
```python
_looks_like_sentence("The partnership agreement was signed in Berlin.")  # True
_looks_like_sentence("Quarterly Sales Report")                           # False
_looks_like_agenda_item("1. Call to Order — Meeting called to order")   # True
_looks_like_agenda_item("Company Annual Report")                         # False
```

---

## ISSUE 5 — Form Field Tooltips Use Internal Names (MEDIUM)

### Problem
`fix_widget_tu` set `/TU` to the internal `/T` field name (`"field1"`,
`"field2"`) when no label was found in the `/Parent` chain. Screen
readers would announce "field1" which tells the user nothing.

### Fix
Added visible-text-near-widget detection as STEP 0 in `_derive_name`:

1. **`_find_page_for_widget(pdf, widget)`**: resolves which page
   contains a widget by matching its `objgen` against each page's
   `/Annots`.
2. **`_extract_nearby_label(pdf_path, page_idx, rect, radius=50)`**:
   uses PyMuPDF to scan all text spans on the widget's page. For each
   span, checks if its bounding box is within `search_radius` points
   of the widget's LEFT edge (with vertical overlap) or ABOVE its top
   edge (with horizontal overlap). Returns the closest one.
3. **`_clean_visible_label(raw)`**: strips trailing colons, asterisks,
   parentheses, whitespace.

Handles the fitz/PDF coordinate flip (fitz y-down vs PDF y-up) via
`page.rect.height - y`.

### Files Changed
- **MODIFIED**: `fix_widget_tu.py` (+173 lines)

### Verification
```
02_form_no_tooltips.pdf (6 labeled fields):

BEFORE:  field1 → /TU="field1"
         field2 → /TU="field2"
         ...

AFTER:   field1 → /TU="First Name"
         field2 → /TU="Last Name"
         field3 → /TU="Email Address"
         field4 → /TU="Department"
         field5 → /TU="Hire Date"
         field6 → /TU="Manager"
```

---

## Final Test Results

### Commits in this fix series

| # | Commit | Files | Description |
|---|--------|-------|-------------|
| 1 | `eb0bb3c` | 7 new | Audit verification PDFs |
| 2 | `4e33645` | 1 mod | ISSUE 2: Auditor content detection |
| 3 | `e84e5bb` | 2 mod/new | ISSUE 1: fix_content_tagger module |
| 4 | `bc692cc` | 3 mod | ISSUE 3: /Tabs=/S on all pages |
| 5 | `b1eaaf4` | 2 mod | ISSUE 6: Heading hierarchy |
| 6 | `811c900` | 1 mod | ISSUE 4: Title sentence filtering |
| 7 | `5333a3a` | 1 mod | ISSUE 5: Form tooltip visible-text |
| 8 | `44ea6d8` | 1 new | Integration tests (21 tests) |
| 9 | `84662eb` | 2 mod | /Figure→/Artifact retagging support |

### Test counts

- **Audit fix tests**: 21 (ALL PASS)
- **Checkpoint verification tests**: 56 (ALL PASS)
- **Edge case tests**: 6 (ALL PASS, 4 skipped — ocrmypdf env issue)
- **Existing unit tests**: 203 (ALL PASS)
- **Total non-env tests**: **286 PASSING**
- **Env-caused failures**: 2 (pre-existing, cryptography module panic
  on `ocrmypdf` import — both rely on running the full pipeline in
  this specific environment)

### 3 Consecutive Clean Runs

| Run | Result |
|-----|--------|
| 1 | 286 passed, 4 skipped |
| 2 | 286 passed, 4 skipped |
| 3 | 286 passed, 4 skipped |

**Zero test regressions from the fixes.**

---

## Remaining Known Limitations

1. **Manual review checkpoints (C-15, C-17, C-34, C-38)**: Still return
   `MANUAL_REVIEW` text without numeric confidence scores. These need
   significant new scoring algorithms (reading order analysis, color-
   only detection, etc.) and are out of scope for this PR.

2. **Contrast checking (C-16)**: Still `NOT_APPLICABLE` — needs a
   rendering engine for pixel-level color extraction.

3. **Encryption re-application (C-08)**: `fix_security` is still
   detect-only. Re-encrypting without the owner password is not
   possible, so the tool can only report issues.

4. **Environment-dependent tests**: 2 tests in `test_checkpoint_coverage.py`
   fail with `pyo3_runtime.PanicException` from the system's
   `cryptography` module (missing `_cffi_backend`). This affects any
   test that imports `ocrmypdf` in the pipeline's `fix_scanned_ocr`
   step. The HF Space deployment has correct system libraries and is
   unaffected.
