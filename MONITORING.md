# MONITORING.md — WCAG 2.1 AA PDF Tool

## Monitoring Overview

The tool is deployed on Hugging Face Spaces. Monitoring covers
availability, processing health, and CI/CD pipeline status.

## UptimeRobot Setup

Configure UptimeRobot (or equivalent) to monitor the live URL:

- **URL:** `https://polittdj-wcag-2-1-aa-conversion-and-verification-tool-v3.hf.space`
- **Check interval:** 5 minutes
- **Alert method:** Email to repository owner
- **Expected response:** HTTP 200 with body containing "WCAG 2.1 AA"

## Alert Conditions

| Condition | Severity | Response |
|-----------|----------|----------|
| HTTP 5xx from HF Spaces | Critical | Check HF Spaces logs, restart Space |
| No response > 10 min | Critical | Check HF status page, restart Space |
| Gradio UI not rendering | High | Check browser console, redeploy |
| Test failures in CI | High | Do not merge; investigate on feature branch |
| Dependency CVE (critical/high) | High | Upgrade dependency, verify tests, merge fix |
| Dependency CVE (medium/low) | Medium | Assess impact, schedule upgrade |
| Smoke test fails after deploy | High | Follow ROLLBACK.md procedure |
| Cold start > 60s | Low | Expected on free tier after inactivity |
| Worker failure in processing | Medium | Check logs for stack trace; may be corrupt PDF |

## Log Locations

| Source | How to Access |
|--------|---------------|
| HF Spaces runtime logs | Space dashboard → Settings → Logs |
| GitHub Actions CI runs | Repository → Actions tab |
| Deployment logs | Repository → Actions → "Deploy to HF Spaces" workflow |
| Local development | stderr output from `python app.py` |

## Worker Failure Log Format

Processing errors are logged to stderr with this format:
```
ERROR:pipeline:pipeline step {step_name} raised:
Traceback (most recent call last):
  ...
{ExceptionType}: {message}
```

Each failed step is also recorded in the HTML compliance report
under "Pipeline Steps with Issues."

## Health Check Procedure

1. Visit the live URL
2. Verify the privacy notice is displayed
3. Upload a small test PDF (< 1 MB)
4. Verify ZIP download contains remediated PDF + HTML report
5. Open the HTML report and verify 47 checkpoints are listed
6. Alternatively, run: `python scripts/smoke_test.py`

## Response Procedures

### Space is down (HTTP 5xx or no response)

1. Check HF Spaces status: https://status.huggingface.co/
2. Open the Space dashboard and check the Logs tab
3. Try restarting the Space (Settings → Restart)
4. If persistent: redeploy from latest passing commit via GitHub Actions
5. If GitHub Actions is down: follow emergency rollback in ROLLBACK.md

### CI pipeline failing

1. Check the Actions tab for the failing workflow run
2. Read the test output to identify the failing test
3. Fix on a feature branch; do not merge to main until CI passes
4. If a dependency CVE is blocking: upgrade the dependency and re-run

### Processing errors on specific PDFs

1. Check the HTML report for "Pipeline Steps with Issues"
2. The error identifies which fix module failed and why
3. Known limitation: password-protected and severely corrupt PDFs
   will always produce PARTIAL results
4. File a GitHub issue with the error details (do not attach the PDF
   if it contains sensitive data)

## Escalation

1. Check HF Spaces status page
2. Check GitHub Actions for recent failures
3. If persistent: redeploy from latest passing commit
4. If infrastructure issue: follow ROLLBACK.md
5. Notify repository owner (polittdj) via GitHub issue
