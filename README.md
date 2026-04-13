---
title: WCAG 2.1 AA PDF Tool
emoji: ♿
colorFrom: blue
colorTo: green
sdk: gradio
sdk_version: 5.50.0
app_file: app.py
pinned: false
license: mit
---

# WCAG 2.1 AA PDF Conversion & Verification Tool (v3)

This tool automatically remediates PDF files for WCAG 2.1 AA accessibility
compliance. It applies a 19-step remediation pipeline covering 47 checkpoints,
then generates a detailed compliance report for each file.

## Live URL

**[Open the tool on Hugging Face Spaces](https://huggingface.co/spaces/polittdj/WCAG-2-1-AA-Conversion-and-Verification-Tool-v3)**

## How to Use It

1. **Open the tool** — Visit the live URL above. The tool runs in your
   browser; no installation is needed.

2. **Read the privacy notice** — A privacy notice is displayed at the top
   of the page. Your files are processed in memory and deleted immediately
   after download.

3. **Upload your PDFs** — Click the "Upload PDF files" area and select one
   or more PDF files from your computer. You can upload multiple files at once.

4. **Click "Process Files"** — The tool will process each PDF through the
   19-step remediation pipeline. Progress is shown in the status box.

5. **Wait for processing** — Processing typically takes 2-5 seconds per file
   for PDFs under 10 MB. Larger or scanned PDFs may take longer due to OCR.

6. **Download results** — When processing completes, a download link appears.
   Click it to download a ZIP file containing your results.

7. **Review the output** — The ZIP contains a remediated PDF and an HTML
   compliance report for each uploaded file.

## What's in the Output

Each processed file produces two outputs inside the ZIP:

- **Remediated PDF** (`filename_WGAC_2.1_AA_Compliant.pdf`) — The original
  PDF with accessibility fixes applied automatically: tagged structure,
  document title, language, alt text placeholders, form field descriptions,
  reading order, bookmarks, and more.

- **HTML Compliance Report** (`filename_WGAC_2.1_AA_Compliant_report.html`) —
  A standalone report showing per-checkpoint pass/fail status, confidence
  scores, actions taken, and items requiring human review. Readable with
  or without JavaScript.

## Known Limitations

1. Alt text for images requires human review after processing — the tool
   inserts placeholders only.
2. Color contrast failures are reported but not auto-corrected.
3. Password-protected PDFs cannot be processed. PDFs encrypted with a
   user-password (including R=3 legacy RC4 and R=6 AES-256) are rejected
   with a clear message. PDFs encrypted with an owner-only password — i.e.
   an empty user password — are processed normally.
4. Digital signatures become invalid after processing.
5. Complex multi-column layouts may have imperfect reading order.
6. Full tag creation for untagged PDFs is best-effort heuristic.
7. OCR for scanned PDFs is best-effort (Tesseract).
8. PDF/UA full conformance is not guaranteed — manual review is recommended
   for legally-regulated contexts.
9. TTS pause behavior varies by screen reader.
10. Cold start may take 30-60 seconds after inactivity on the free tier.
11. Max file size: 50 MB per file, 500 MB per batch.
12. Rate limit: 10 processing jobs per hour.
13. Broken links (empty URI action) and JavaScript actions in annotations are
    flagged as warnings requiring manual review rather than auto-corrected.
14. File-attachment and embedded-file contents (`/EmbeddedFiles`, `/FileAttachment`
    annotations) are left untouched — the tool remediates the parent document
    only and never cracks open attachment payloads.
15. `/Author`, `/Producer`, and other DocInfo metadata fields beyond `/Title`
    are not included in the HTML compliance report. This is intentional:
    it keeps the report safe to share without leaking potential PII.
16. Memory-pressure pause/resume (via `rate_limiter.check_memory_pressure`)
    requires the optional `psutil` dependency. Without it the guard is a
    no-op and the pipeline continues to accept jobs regardless of system
    memory utilisation.
17. Round-trip remediation is stable: re-processing an already-remediated
    PDF yields the same checkpoint verdicts and adds at most a trivial
    number of struct-tree elements. It does not recover from an initial
    partial remediation by retrying.

## Privacy

Your file is processed in memory and deleted immediately after your
download is ready. No file content is stored, logged, or shared. All
transfers are encrypted (HTTPS).

See also: the privacy confirmation in each HTML compliance report.

## Technical Details

- **Tech stack:** Python, Gradio, pikepdf, PyMuPDF (fitz), Tesseract OCR,
  Jinja2, reportlab
- **Checkpoints:** 47 WCAG 2.1 AA checkpoints audited
  (30 auto-fix, 10 detect-only, 4 manual review, 3 N/A)
- **Pipeline:** 19-step remediation pipeline
- **Tests:** 551 automated tests at 100% pass rate (includes 86 edge-case
  tests across 12 hardening categories — annotations, batch, content,
  fonts, forms, images, malformed PDFs, output validation, performance,
  privacy, tags, and unusual filenames)
- **Reports:** Standalone HTML with dark mode, print styles, responsive
  layout, noscript fallback, and embedded JSON data

## Repository Structure

| Path | Description |
|------|-------------|
| `app.py` | Gradio web UI — file upload, processing, download |
| `pipeline.py` | 19-step remediation pipeline orchestrator |
| `wcag_auditor.py` | 47-checkpoint accessibility auditor |
| `fix_*.py` | Individual fix modules (18 total) |
| `rate_limiter.py` | Request validation and rate limiting |
| `reporting/` | Jinja2 HTML report generator and templates |
| `tests/` | Automated test suite |
| `scripts/` | Deployment and utility scripts |
| `.github/workflows/` | CI/CD pipeline (test + deploy) |

## CI/CD

Pushes to `main` auto-deploy to Hugging Face Spaces via GitHub Actions.
Pull requests run the full test suite and CVE audit before merge.

## Rollback

See [ROLLBACK.md](ROLLBACK.md) for emergency rollback procedures.

## Monitoring

See [MONITORING.md](MONITORING.md) for alert conditions and response procedures.
