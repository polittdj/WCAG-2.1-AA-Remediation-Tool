# IRS Critical Bug Fixes — Phase Complete

Branch: `fix/irs-critical-bugs`
Date: 2026-04-13
Final test count: **160 passed, 2 skipped** (skipped = reference PDFs not present in CI)

## Bugs Fixed

| Bug | Checkpoint | Description | Status |
|-----|-----------|-------------|--------|
| BUG-01 | — | False compliance determination — any FAIL → PARTIAL | **FIXED** |
| BUG-02 | — | Introducing 4.1 Compatible failures — ParentTree rebuild | **FIXED** |
| BUG-04 | C-20 | Multiple H1 headings never remediated | **FIXED** |
| BUG-05 | C-25 | TH Scope attribute never added | **FIXED** |
| BUG-06 | C-13 | Non-standard BDC tags not mapped in RoleMap | **FIXED** |
| BUG-07 | — | No post-remediation re-audit (report described pre-fix state) | **FIXED** |
| BUG-10 | — | HTML report status icons double-encoded as `&amp;#x2713;` | **FIXED** |
| BUG-11 | — | Compliance % included N/A checkpoints in denominator | **FIXED** |

## IRS Phase Summary

### IRS-01 — Compliance Determination + Re-audit
- `pipeline.py`: `compute_overall()` replaces CRITICAL_CHECKPOINTS whitelist
- `pipeline.py`: Belt-and-suspenders /Tabs=/S fix runs BEFORE audit (BUG-07)
- `fix_pdfua_meta.py`: Repair existing empty StructTreeRoot /K arrays
- `fix_link_alt.py`: Create /Link struct elements for bare link annotations
- Tests: `tests/test_compliance_determination.py`, `tests/test_post_audit.py`

### IRS-02 — C-20, C-25, C-13 Remediations
- `fix_headings.py`: `_demote_extra_h1s()` keeps first H1, promotes rest to H2
- `fix_content_tagger.py`: `_fix_existing_th_scope()` adds /Scope=/Column to bare TH elements
- `fix_content_streams.py`: Added `/Normal → P` to NON_STANDARD_TO_STANDARD
- Tests: `tests/test_fix_headings.py`, `tests/test_irs02_fixes.py`

### IRS-03 — ParentTree Validation + Rebuild
- `src/utils/structure_validator.py`: `validate_and_rebuild_parent_tree()` detects
  orphaned MCIDs and rebuilds the ParentTree from scratch using only MCIDs present
  in both the struct tree AND content streams
- `pipeline.py`: Rebuild runs before audit on `final_candidate`
- Tests: `tests/test_parent_tree_rebuild.py`

### IRS-04 — HTML Report + Pipeline Wiring
- `reporting/templates/report.html.j2`: Unicode icons (✓ ✗ ⚠) — no HTML entities
- `reporting/templates/report.html.j2`: `applicable = total - na_count` denominator
- `pipeline.py`: All IRS-02/03 fixers confirmed wired
- Tests: `tests/test_html_report.py` (added 14 new tests)

## Next Steps (Manual)

1. Re-run all 9 IRS form PDFs (f461, f56f, f656b, f172, etc.) through the
   updated tool
2. Run PAC (PDF Accessibility Checker) on outputs
3. Verify "4.1 Compatible" failure counts are reduced vs pre-fix baseline:
   - f461: was 201 new failures → target: 0
   - f56f: was 118 new failures → target: 0
   - f656b: was 6 new failures → target: 0
   - f172: was 3 new failures → target: 0
