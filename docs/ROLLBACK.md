# Rollback Procedure

## Automatic Rollback

Rollback triggers automatically when:
- The post-deployment smoke test fails (checks `/health` endpoint within 60s of deploy)
- GitHub Actions `rollback.yml` workflow is dispatched

**What happens:**
1. A GitHub issue is created documenting the failure
2. An alert is sent via the configured notification channel
3. The previous Render deployment remains active (Render keeps deploy history)

## Manual Rollback

### Via GitHub Actions
1. Go to the repository's **Actions** tab
2. Click **Rollback** in the left sidebar
3. Click **Run workflow**
4. Select the `main` branch
5. Click **Run workflow**

### Via Render Dashboard
1. Go to [Render Dashboard](https://dashboard.render.com)
2. Select the **wcag-pdf-tool** web service
3. Click **Events** tab
4. Find the last successful deploy
5. Click **Rollback to this deploy**

### Via Render CLI
```bash
# List recent deploys
render deploys list --service srv-xxxxx

# Rollback to a specific deploy
render deploys rollback --service srv-xxxxx --deploy dep-xxxxx
```

## Verification

After rollback, verify the service is healthy:

```bash
curl https://your-app.onrender.com/health
```

Expected response: `{"status": "healthy", ...}`

## Escalation

If rollback also fails:
1. Check Render service logs for errors
2. Verify Redis (Upstash) is operational
3. Verify R2 storage is accessible
4. If infrastructure issue: check platform status pages
5. Contact repository maintainer
