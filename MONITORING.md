# MONITORING.md — WCAG 2.1 AA PDF Tool

## Monitoring Overview

### UptimeRobot
- URL: https://huggingface.co/spaces/polittdj/WCAG-2.1-AA-Conversion-and-Verification-Tool-v3
- Check interval: 5 minutes
- Alert: Email on downtime

### Alert Conditions

| Condition | Severity | Response |
|-----------|----------|----------|
| HTTP 5xx from HF Spaces | Critical | Check HF Spaces logs, restart Space |
| No response > 10 min | Critical | Check HF Spaces status page, restart |
| Gradio UI not rendering | High | Check browser console, redeploy |
| Test failures in CI | High | Do not merge, investigate |
| Dependency CVE alert | Medium | Assess impact, pin safe version |
| Cold start > 60s | Low | Expected on free tier after inactivity |

### Log Locations
- HF Spaces logs: Settings > Logs in Space dashboard
- GitHub Actions: Actions tab in repository
- Local: stderr output from `python app.py`

### Health Check Procedure
1. Visit the live URL
2. Upload a small test PDF (< 1 MB)
3. Verify ZIP download contains remediated PDF + HTML report
4. Check HTML report shows 47 checkpoints
5. Verify privacy notice appears before upload

### Escalation
1. Check HF Spaces status: https://status.huggingface.co/
2. Check GitHub Actions for recent failures
3. If persistent: redeploy from latest passing commit
4. If infrastructure issue: follow ROLLBACK.md
