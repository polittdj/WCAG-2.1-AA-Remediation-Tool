# CVE Audit Report — WCAG 2.1 AA PDF Tool

## Date: 2026-04-11

## Tool: pip-audit 2.10.0

## Dependency Versions (all pinned)

| Package | Pinned Version | Notes |
|---------|---------------|-------|
| pikepdf | 10.5.1 | PDF manipulation |
| PyMuPDF | 1.27.2.2 | PDF rendering / text extraction |
| reportlab | 4.4.10 | PDF generation |
| Pillow | 12.2.0 | Image processing |
| pdfminer.six | 20260107 | PDF text extraction |
| jinja2 | 3.1.6 | HTML template rendering |
| pytesseract | 0.3.13 | OCR interface |
| ocrmypdf | 17.4.1 | OCR pipeline |
| python-dotenv | 1.2.2 | Environment variable loading |

## Audit Results

```
$ pip-audit -r requirements.txt
No known vulnerabilities found
```

**Critical CVEs found: 0**
**High CVEs found: 0**
**Medium CVEs found: 0**
**Low CVEs found: 0**

## Resolution

No upgrades needed. All dependencies are at current stable versions
with no known vulnerabilities.

## Tests After Audit

All tests pass after pinning versions. No behavioral changes.

## CI Integration

pip-audit is included in `.github/workflows/ci.yml` and runs on every
pull request to main. The security job will flag any future CVEs.
