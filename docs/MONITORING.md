# Monitoring Guide

## Active Monitors

| Monitor | Tool | Endpoint | Interval | Alert |
|---------|------|----------|----------|-------|
| Site Health | UptimeRobot | `GET /health` | 5 min | Email on 2 consecutive failures |
| Deploy Health | GitHub Actions | Smoke test | Every merge to main | Auto-rollback + GitHub issue |

## Alert Definitions

### Site Down
- **Trigger:** UptimeRobot reports 2 consecutive /health failures
- **Meaning:** Web service is unreachable or unhealthy
- **Response:**
  1. Check Render dashboard for service status
  2. If service is sleeping (free tier): it will auto-wake on next request; wait 60s
  3. If service crashed: check Render logs, restart service
  4. If deploy broken: trigger rollback (see ROLLBACK.md)

### Deploy Failed
- **Trigger:** GitHub Actions smoke test fails after deployment
- **Meaning:** New code deployed but the service is not working correctly
- **Response:**
  1. Automatic rollback triggers via rollback.yml
  2. Check the GitHub issue created by the rollback workflow
  3. Verify the live URL is operational after rollback
  4. Investigate the failed commit

### Worker Stalled
- **Trigger:** /health shows queue_depth > 0 and no jobs completed in 5+ minutes
- **Meaning:** Background worker is hung or crashed
- **Response:**
  1. Check Render worker logs
  2. Restart worker service on Render
  3. If OOM: reduce worker concurrency
  4. If task error: check Celery task logs

### Storage Near Limit
- **Trigger:** /health shows storage_usage_mb > 8000 (8GB of 10GB)
- **Meaning:** Approaching Cloudflare R2 free tier storage limit
- **Response:**
  1. Verify cleanup job is running (check Celery beat logs)
  2. Manually trigger cleanup: POST /api/admin/cleanup (if available)
  3. Delete old files directly via Cloudflare R2 dashboard

### Redis Limit Approaching
- **Trigger:** Rate limiter detects >9000 Redis commands used today
- **Meaning:** Approaching Upstash 10,000 daily command limit
- **Response:**
  1. New jobs will be rejected with "Daily processing limit reached" message
  2. Limit resets at midnight UTC
  3. If persistent: optimize Redis usage or upgrade plan

## Health Endpoint Response

```json
{
  "status": "healthy",
  "timestamp": "2026-04-06T14:30:22Z",
  "version": "1.0.0",
  "queue_depth": 3,
  "worker_status": "active",
  "storage_usage_mb": 1240.5,
  "redis_commands_today": 4521
}
```

## Setting Up UptimeRobot

1. Create account at https://uptimerobot.com (free)
2. Add new monitor: HTTP(s), URL = your live URL + /health
3. Interval: 5 minutes
4. Alert contacts: your email
5. Save
