# FIX REPORT — Round 2 (4 Remaining Audit Issues)

## Date: 2026-04-12
## Branch: `claude/fix-4-remaining-issues`

---

## Executive Summary

A follow-up audit of the deployed tool found 4 regressions on real-world
input PDFs that pass through the content tagger. The original fixes
worked on clean reportlab-generated PDFs but broke down on PDFs whose
text is drawn as separate `Tj` operators with widely-separated X
coordinates — the kind of layout produced by InDesign, older MS Word
exports, and many commercial authoring tools.

**All 4 issues are now fixed.** 503 tests pass (was 494) across 3
consecutive runs, zero regressions.

---

## The 4 Reported Issues

### Issue 1 — 09_fake_lists_no_structure.pdf: ZERO list tags + /Tabs missing

**User report**: *"ZERO list tags created (/L, /LI, /Lbl, /LBody). Also
/Tabs=/S is MISSING on this file. The list detection is not finding
bullet patterns (•, -, \\*) or numbered patterns (1., 2., 3.)."*

**Root cause**: When real-world PDF authoring tools draw a list item,
they often emit two separate `Tj` operators: one for the bullet glyph
(e.g. `•` at x=86pt) and one for the item text (at x=100pt, 14 points
to the right). PyMuPDF's `page.get_text("text")` treats two text spans
with the same Y but widely-separated X as being on separate LINES. So
the text output looks like:

```
•
User authentication with OAuth 2.0
•
Real-time notifications via WebSocket
...
```

The old `_add_lists` scanned line-by-line looking for lines that start
with a bullet char AND have item text after. A line containing only
`•` didn't match (no body), and the next line starting with "User" was
flushed as a non-list line. **Zero list items got emitted.**

**Fix** (`fix_content_tagger.py`):

1. Added lookahead pairing in `_add_lists`:
   - If a line is ONLY a bullet character, peek at the next non-empty
     line. If that line is NOT itself a list prefix, use it as the
     body for the bullet.
   - Same logic for numbered prefixes on their own line (`1.`, `2.`).
2. Added `_add_lists_from_spans` as a fallback — span-level detection
   that groups spans by Y coordinate into rows, then checks if the
   leftmost span of each row is a list prefix. This catches cases
   where the line-level text extractor doesn't even put bullets and
   item text on "lines" that can be meaningfully joined.
3. The main entry point calls `_add_lists` first; if it produces 0
   lists, it falls back to `_add_lists_from_spans`.

**For /Tabs=/S**: Added a belt-and-suspenders pass in `pipeline.py`
after all fix modules complete and the output PDF is written. Directly
opens the output PDF and forces `/Tabs=/S` on every page. Even if
`fix_focus_order` is skipped or silently fails on some code path,
this final pass guarantees C-10 compliance.

**Evidence**: v2 + v3 adversarial PDFs (where bullets and numbers are
drawn as separate Tj with 0.2–0.5 inch gaps) now produce:

```
Tags: {'Document': 1, 'H1': 1, 'L': 2, 'LBody': 10, 'LI': 10, 'Lbl': 10, 'P': 2}
Tabs: ['/S']
```

### Issue 2 — 04_table_no_headers.pdf: /TH without /Table/TR/TD containers

**User report**: *"Has /TH tags but no /Table or /TR or /TD container
structure. Tables need the full hierarchy."*

**Root cause**: The old `_add_tables` had a branch that created an
empty `/Table` element if `extract()` returned no rows. That empty
`/Table` (without `/TR` or `/TD` children) still counted as "a table
exists" downstream but had no semantic value. On image-heavy pages,
PyMuPDF's `find_tables()` could return a 1-row "table" whose
`extract()` returned rows with empty cells — the old code created
a `/Table > /TR > /TH` that consisted of header cells with no
corresponding data rows, producing orphan-looking /TH.

**Fix** (`_add_tables` in `fix_content_tagger.py`):

1. **Require at least 2 rows AND at least one row with ≥2 cells**
   before creating a `/Table` element. This rejects:
   - Empty tables (`extract()` returned `None` or `[]`)
   - 1-row tables (can't have both header and data)
   - 1-column "tables" (probably image captions or single paragraphs)
2. Build the whole hierarchy atomically — wrap the entire `/Table >
   /TR > /TH + /TD` construction in a try/except. If anything fails
   mid-build, nothing gets appended to the parent. **No orphan /TH
   can ever be produced.**

**Evidence**: 04_table_no_headers still produces the full hierarchy
(Table=2, TR=9, TH=7, TD=25) while 03_images_no_alt_text now produces
ZERO /Table, /TR, and /TH tags (the false-positive table detection is
filtered out).

### Issue 3 — 03_images_no_alt_text.pdf: /TH and /TR tags, ZERO /Figure

**User report**: *"Has /TH and /TR tags (wrong — this is not a table
document) but ZERO /Figure tags. This document has 3 product images.
Each image XObject must get a /Figure tag with /Alt."*

**Root cause**: Two independent problems:

1. `_add_tables` was mis-detecting image-caption text columns as a
   table (see Issue 2).
2. `_add_figures` was gated on `"Figure" not in existing_types` — a
   check done BEFORE any tagging. If an earlier module somehow left a
   /Figure in the struct tree (e.g. a partial tag from
   `fix_untagged_content`), `_add_figures` would skip and the user's
   3 images would never get tagged.

**Fix** (`fix_content_tagger.py`):

1. Issue 2 fix (filter spurious tables) stops /TH from being created
   on image PDFs.
2. Made `_add_figures` **unconditional**. Instead of skipping when
   "Figure" is in `existing_types`, it:
   - Counts existing `/Figure` elements with `_count_existing_figures`
   - Counts total image draws with `_count_images_per_page`
   - Adds new `/Figure` tags only if `existing < total_images`
   - **Guarantees**: every image draw has a matching /Figure
     struct element in the final output.

**Evidence**: 03_images_no_alt_text.pdf now produces:

```
Tags: {'Document': 1, 'Figure': 3, 'H1': 1, 'P': 3}
```

Zero spurious /TH or /TR tags, all 3 Figures present with `/Alt` text.

### Issue 4 — ZIP output flat verification

**User report**: *"Verify the ZIP is flat (no nested .zip files inside).
Process 3+ files and check the download."*

**Root cause**: None — this was already fixed in Round 1. The user
asked for verification.

**Verification**: Processed 3-file and 5-file batches through
`app.process_files_core`. Combined ZIP is flat:

```
Combined ZIP: WCAG_Compliance_Results_2026-04-12_06-41-28.zip
Entries (6):
  alpha_WGAC_2.1_AA_Compliant.pdf
  alpha_WGAC_2.1_AA_Compliant_report.html
  beta_WGAC_2.1_AA_Compliant.pdf
  beta_WGAC_2.1_AA_Compliant_report.html
  gamma_WGAC_2.1_AA_Compliant.pdf
  gamma_WGAC_2.1_AA_Compliant_report.html
```

Zero nested .zip entries, zero subdirectory entries. Added two new
regression tests that specifically process 3 and 5 files and assert
flat structure.

---

## Files Changed

### Modified
- **`fix_content_tagger.py`** — hardening fixes for Issues 1, 2, 3
  - New helpers: `_count_existing_figures`, `_is_bullet_line`,
    `_is_numbered_line`, `_add_lists_from_spans`
  - Rewrote `_add_lists` with lookahead pairing for bullets/numbers
    on separate lines
  - Rewrote `_add_tables` to reject sub-2-row detections and build
    atomically (no orphan /TH)
  - Made `_add_figures` call unconditional, gated only by
    `existing_figures < total_images`
- **`pipeline.py`** — belt-and-suspenders /Tabs=/S pass after save

### Added
- **`tests/test_round2_fixes.py`** — 9 regression tests covering
  the 4 reported issues across v2 and v3 adversarial PDFs
- **`tests/generate_audit_pdfs_v2.py`** — adversarial PDF generator
  (bullets on separate lines from items)
- **`tests/generate_audit_pdfs_v3.py`** — even more adversarial
  (every list prefix on its own line, widest X gaps)

### Regenerated
- **`tests/audit_outputs/`** — fresh outputs from running the
  hardened pipeline on all 10 audit PDFs, committed as evidence

---

## Test Results

### Round 2 Regression Tests (9 new)

```
tests/test_round2_fixes.py::TestIssue1Lists::test_v2_bullets_and_numbered_both_detected PASSED
tests/test_round2_fixes.py::TestIssue1Lists::test_v3_every_glyph_separate_detected PASSED
tests/test_round2_fixes.py::TestIssue1Lists::test_v2_tabs_s_on_every_page PASSED
tests/test_round2_fixes.py::TestIssue1Lists::test_v3_tabs_s_on_every_page PASSED
tests/test_round2_fixes.py::TestIssue2TableHierarchy::test_04_tables_has_full_hierarchy PASSED
tests/test_round2_fixes.py::TestIssue2TableHierarchy::test_tables_never_create_orphan_th PASSED
tests/test_round2_fixes.py::TestIssue3Figures::test_03_images_has_3_figures PASSED
tests/test_round2_fixes.py::TestIssue4FlatZip::test_three_files_flat_zip PASSED
tests/test_round2_fixes.py::TestIssue4FlatZip::test_five_files_flat_zip PASSED

9 passed
```

### Full Suite (3 consecutive runs)

| Run | Result |
|---|---|
| 1 | **503 passed**, 0 skipped, 0 failed (140.48s) |
| 2 | **503 passed**, 0 skipped, 0 failed (133.05s) |
| 3 | **503 passed**, 0 skipped, 0 failed (134.51s) |

**Net test count**: 494 → 503 (+9 new regression tests). Zero test
regressions introduced by the hardening.

---

## Completion Criteria Checklist

- [X] Issue 1: v2 adversarial 09_lists produces ≥2 /L, ≥10 /LI, /Lbl, /LBody
- [X] Issue 1: v3 adversarial 09_lists (every glyph separate) also works
- [X] Issue 1: /Tabs=/S on every page of 09_lists (belt-and-suspenders)
- [X] Issue 2: 04_tables produces full /Table > /TR > /TH + /TD hierarchy
- [X] Issue 2: Image-heavy PDFs produce NO orphan /TH, /TR, /Table tags
- [X] Issue 3: 03_images produces 3 /Figure tags, each with /Alt
- [X] Issue 3: _add_figures is unconditional (guaranteed to run)
- [X] Issue 4: 3-file batch produces flat ZIP (no nested .zip)
- [X] Issue 4: 5-file batch produces flat ZIP
- [X] All tests pass 3 consecutive runs (503 each time)
- [X] Zero regressions vs. previous 494 passing tests
- [X] Feature branch, never directly on main
