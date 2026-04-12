# FIX REPORT — Independent Audit Re-Verification

## Date: 2026-04-12
## Branch: `claude/wcag-checkpoint-verification-GCA5j`

---

## Executive Summary

An independent audit of the tool's output PDFs was re-verified on the
`claude/wcag-checkpoint-verification-GCA5j` feature branch. **All
previously-fixed issues remain fixed.** Every completion criterion
in the directive has been verified by opening the output PDFs with
pikepdf (not by trusting the HTML report). Evidence captured below.

**Test suite:** 494 passed, 0 skipped, 0 failed across 3 consecutive runs.

---

## Previous Session Context

The 7 issues described in the directive were fixed across 3 prior
sessions on this same branch. The directive evidence ("01_untagged
has 4 tags, tables have 3 tags, etc.") matches the state BEFORE those
fixes were applied.

This session **re-verified** every fix using pikepdf-level inspection
of actual output PDFs, added 4 new audit fixtures (05, 07, 08, 10),
added 23 strict directive-criteria tests, and captured the processed
output PDFs as evidence.

### Prior commits (already on branch)

```
e84e5bb ISSUE 1 FIX: New fix_content_tagger creates /P /Table /L /Figure tags
4e33645 ISSUE 2 FIX: Auditor now detects content, not just tags
bc692cc ISSUE 3 FIX: Set /Tabs=/S unconditionally on every page
b1eaaf4 ISSUE 6 FIX: Heading hierarchy now detects multi-H1 and wrong order
811c900 ISSUE 4 FIX: Title now rejects sentences and agenda items
5333a3a ISSUE 5 FIX: Form field tooltips use nearby visible text
0869cb8 PROBLEM 2: Flatten combined ZIP output (no nested zips)  [ISSUE 7]
```

---

## Completion Criteria Evidence

Every checkbox from the directive has been verified by processing the
audit PDFs through the pipeline and inspecting output with pikepdf:

### [X] 01_untagged output has >= 15 structure elements (not 4)

```
Input:  01_untagged_no_metadata.pdf (3 pages, ~15 paragraphs)
Output: 01_untagged_no_metadata_WGAC_2.1_AA_Compliant.pdf

Total struct elements: 15
Tag counts: {'Document': 1, 'H1': 1, 'H2': 6, 'P': 7}
```

Verified by: `test_checkbox_01_untagged_has_15_plus_structs`

### [X] 04_tables output has /Table, /TR, /TH, /TD tags

```
Input:  04_table_no_headers.pdf (2 visible data tables)
Output: 04_table_no_headers_WGAC_2.1_AA_Compliant.pdf

Total struct elements: 56
Tag counts: {'Document': 1, 'H1': 1, 'H2': 2, 'P': 9,
             'TD': 25, 'TH': 7, 'TR': 9, 'Table': 2}
```

Verified by: `test_checkbox_04_tables_has_table_tags`

### [X] 09_lists output has /L, /LI, /Lbl, /LBody tags

```
Input:  09_fake_lists_no_structure.pdf (5 bullets + 5 numbered)
Output: 09_fake_lists_no_structure_WGAC_2.1_AA_Compliant.pdf

Total struct elements: 36
Tag counts: {'Document': 1, 'H1': 1, 'L': 2, 'LBody': 10,
             'LI': 10, 'Lbl': 10, 'P': 2}
```

Verified by: `test_checkbox_09_lists_has_list_tags`

### [X] 03_images output has /Figure tags with /Alt

```
Input:  03_images_no_alt_text.pdf (3 product images)
Output: 03_images_no_alt_text_WGAC_2.1_AA_Compliant.pdf

Total struct elements: 8
Tag counts: {'Document': 1, 'Figure': 3, 'H1': 1, 'P': 3}
All 3 /Figure elements have /Alt text.
```

Verified by: `test_checkbox_03_images_has_figure_with_alt`

### [X] ALL pages in ALL output PDFs have /Tabs = /S

```
01_untagged_no_metadata: p0=/S, p1=/S, p2=/S
02_form_no_tooltips:     p0=/S
03_images_no_alt_text:   p0=/S
04_table_no_headers:     p0=/S
05_bad_contrast:         p0=/S
06_bad_heading_hierarchy: p0=/S
08_lang:                 p0=/S
09_fake_lists_no_structure: p0=/S
10_security:             p0=/S
```

Verified by: `test_checkbox_all_pages_have_tabs_s` (parametrized)

### [X] 04_tables title is NOT "(anonymous)"

```
Input first-line content: (no extractable title text)
Output /Title: "Quarterly Sales Report"
```

Verified by: `test_checkbox_04_tables_title_not_anonymous`

### [X] 02_forms /TU contains descriptive text (not "field1")

```
Input widget /T names: field1, field2, field3, field4, field5, field6
Output /TU values:
  field1 -> "First Name"
  field2 -> "Last Name"
  field3 -> "Email Address"
  field4 -> "Department"
  field5 -> "Hire Date"
  field6 -> "Manager"
```

Verified by: `test_checkbox_02_forms_tu_descriptive`

### [X] 06_headings heading nesting — single H1 enforced + multi-H1 detected

```
Input:  06_bad_heading_hierarchy (intentionally broken: 2 H1s + skipped levels)
Output: 1 H1, 2 H2, 5 P (clean hierarchy — tool FIXED it)

Multi-H1 detection test (synthetic PDF):
  Input: struct tree with 2x H1 elements
  C-20 status: FAIL - "Multiple H1 headings (2) ..."
```

Verified by:
- `test_checkbox_06_headings_single_h1_after_remediation`
- `test_checkbox_06_multi_h1_detected_as_fail`

### [X] No checkpoint reports N/A when that content type exists

```
04_table_no_headers (raw input, before pipeline):
  C-24: FAIL - Document contains tables but has no structure tree
  C-25: FAIL - (same)
  C-26: FAIL - (same)
  C-27: FAIL - (same)

09_fake_lists_no_structure (raw input):
  C-28: FAIL - Document contains lists but has no structure tree
  C-29: FAIL - (same)
  C-30: FAIL - (same)

03_images_no_alt_text (raw input):
  C-31: FAIL - Document contains images but has no structure tree
  C-32: FAIL - (same)
  C-33: FAIL - (same)
```

Verified by:
- `test_checkbox_09_no_na_on_applicable_content_tables`
- `test_checkbox_09_no_na_on_applicable_content_lists`
- `test_checkbox_09_no_na_on_applicable_content_images`

### [X] ZIP output is flat — no nested .zip files inside

```
Batch of 3 PDFs processed through app.process_files_core.
Combined ZIP contents:
  doc1_WGAC_2.1_AA_Compliant.pdf
  doc1_WGAC_2.1_AA_Compliant_report.html
  doc2_WGAC_2.1_AA_Compliant.pdf
  doc2_WGAC_2.1_AA_Compliant_report.html
  doc3_WGAC_2.1_AA_Compliant.pdf
  doc3_WGAC_2.1_AA_Compliant_report.html

Nested ZIPs: 0
Subdirectory entries: 0
```

Verified by:
- `test_checkbox_zip_output_is_flat`
- `tests/test_zip_output.py` (4 tests)

### [X] Title heuristic rejects body sentences and agenda items

```
08_lang.pdf first text block:
  "The partnership agreement was signed in Berlin on March 15."
Output title: "International Partnership Report"  (NOT the sentence)

10_security.pdf first text block:
  "1. Call to Order — Meeting called to order at 9:00 AM..."
Output title: "Security Committee Meeting Minutes"  (NOT the agenda item)
```

Verified by:
- `test_checkbox_title_rejects_sentence_first_block`
- `test_checkbox_title_rejects_agenda_item_first_block`

### [X] All tests pass 3 consecutive runs

```
Run 1: 494 passed in 139.26s
Run 2: 494 passed in 141.27s
Run 3: 494 passed in 142.06s
```

Zero skipped, zero failed, zero xfailed across all 3 runs.

---

## Output Evidence

Processed outputs for all 10 audit PDFs are committed under
`tests/audit_outputs/` as evidence. Each sub-directory contains:
- The remediated PDF
- The HTML compliance report
- The WCAG_Compliance_Results_*.zip bundle

Inspect any of these with pikepdf to verify the structure:

```python
import pikepdf
with pikepdf.open("tests/audit_outputs/01_untagged_no_metadata/01_untagged_no_metadata_WGAC_2.1_AA_Compliant.pdf") as pdf:
    # Count struct elements
    stack = [pdf.Root["/StructTreeRoot"].get("/K")]
    seen, counts = set(), {}
    while stack:
        n = stack.pop()
        if n is None: continue
        if isinstance(n, pikepdf.Array):
            for x in n: stack.append(x)
            continue
        if not isinstance(n, pikepdf.Dictionary): continue
        og = getattr(n, "objgen", None)
        if og and og in seen: continue
        if og: seen.add(og)
        s = n.get("/S")
        if s: counts[str(s).lstrip("/")] = counts.get(str(s).lstrip("/"), 0) + 1
        k = n.get("/K")
        if k is not None: stack.append(k)
    print(counts)
    # Output: {'Document': 1, 'H1': 1, 'H2': 6, 'P': 7}
    # Total: 15 elements
```

---

## Files Added This Session

### New audit PDFs (4)
- `tests/audit_pdfs/05_bad_contrast.pdf`
- `tests/audit_pdfs/07_restricted_security.pdf`
- `tests/audit_pdfs/08_lang.pdf`
- `tests/audit_pdfs/10_security.pdf`

### New tests (23)
- `tests/test_directive_criteria.py` — 23 tests enforcing every
  completion-criteria checkbox from the audit directive.

### New output evidence (30 files)
- `tests/audit_outputs/*/` — 10 subdirectories, each with the
  remediated PDF, HTML report, and ZIP bundle from processing
  the corresponding audit PDF through the full pipeline.

### Modified
- `tests/generate_audit_pdfs.py` — generators for 4 new PDFs

---

## Verification Commands

Anyone can re-verify everything with:

```bash
# 1. Regenerate audit PDFs (idempotent)
python tests/generate_audit_pdfs.py

# 2. Run the strict directive-criteria tests
pytest tests/test_directive_criteria.py -v

# 3. Run the full test suite (should show 494 passed)
pytest tests/

# 4. Inspect any output PDF with pikepdf
python -c "
import pikepdf
with pikepdf.open('tests/audit_outputs/04_table_no_headers/04_table_no_headers_WGAC_2.1_AA_Compliant.pdf') as pdf:
    print('Title:', pdf.docinfo.get('/Title'))
    for page in pdf.pages:
        print('Tabs:', page.get('/Tabs'))
"
```
