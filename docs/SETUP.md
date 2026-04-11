# Setup Guide — Zero to Deployed

This guide walks you through deploying the WCAG 2.1 AA PDF Conversion & Verification Tool from scratch. No terminal or coding experience required — everything runs in the cloud.

---

## What You Need Before Starting

Create free accounts on these platforms (all have generous free tiers):

1. **GitHub** — [github.com](https://github.com) (you likely already have this)
2. **Render** — [render.com](https://render.com) (hosts the web app and worker)
3. **Upstash** — [upstash.com](https://upstash.com) (Redis for the job queue)
4. **Cloudflare** — [dash.cloudflare.com](https://dash.cloudflare.com) (R2 storage for uploaded files)
5. **UptimeRobot** — [uptimerobot.com](https://uptimerobot.com) (monitors the live site)

---

## Step 1: Fork the Repository

1. Go to [github.com/polittdj/WCAG-2.1-AA-Conversion-and-Verification-Tool-v3](https://github.com/polittdj/WCAG-2.1-AA-Conversion-and-Verification-Tool-v3)
2. Click the **Fork** button in the top-right corner
3. Keep the default settings and click **Create fork**
4. You now have your own copy of the repository

> **If you are the repository owner**, skip this step — you already have the repo.

---

## Step 2: Set Up Upstash Redis

1. Go to [console.upstash.com](https://console.upstash.com) and sign in (you can use your GitHub account)
2. Click **Create Database**
3. Fill in:
   - **Name:** `wcag-pdf-tool`
   - **Region:** Pick the one closest to you (e.g., `US-East-1`)
   - **Type:** Regional
4. Click **Create**
5. On the database details page, find the **Redis connection string** (not the REST URL)
6. Copy the `UPSTASH_REDIS_URL` — it starts with `rediss://` and looks like `rediss://default:abc123@us1-xyz.upstash.io:6379`

> **Important:** Copy the **Redis URL** (starts with `rediss://`), NOT the REST URL (starts with `https://`). The app uses the Redis protocol, not the HTTP REST API.
>
> **Save this URL** — you'll need it in Step 4 as `REDIS_URL`.

### Free Tier Limits
- 10,000 commands/day
- 256 MB storage
- Enough for ~500 PDF processing jobs/day

---

## Step 3: Set Up Cloudflare R2 Storage

1. Go to [dash.cloudflare.com](https://dash.cloudflare.com) and sign in
2. In the left sidebar, expand **Storage and databases** → click **R2 Object Storage** → click **Overview**
3. If R2 hasn't been activated yet, you'll see an activation prompt — click through to activate it (free, no credit card needed)
4. On the R2 Overview page, click **Create bucket**
   - **Bucket name:** `wcag-pdf-tool`
   - Click **Create bucket**
5. Go back to **R2 Overview** → click **Manage R2 API Tokens** (top right)
6. Click **Create API token**
   - **Token name:** `wcag-pdf-tool`
   - **Permissions:** Object Read & Write
   - **Bucket:** Apply to `wcag-pdf-tool` bucket only
   - Click **Create API Token**
7. Copy and save these three values:
   - **Account ID** (shown at the top of the R2 page)
   - **Access Key ID**
   - **Secret Access Key**

> **Important:** The Secret Access Key is only shown once. Save it immediately.

### Free Tier Limits
- 10 GB storage
- 10 million reads/month, 1 million writes/month
- Zero egress fees

---

## Step 4: Set Up Render (Web App + Worker)

### 4a. Create the Web Service

1. Go to [dashboard.render.com](https://dashboard.render.com) and sign in with GitHub
2. Click **New** → **Web Service**
3. Connect your GitHub repository:
   - Select **polittdj/WCAG-2.1-AA-Conversion-and-Verification-Tool-v3** (or your fork)
4. Configure the service:
   - **Name:** `wcag-pdf-tool`
   - **Region:** Same region as your Upstash Redis
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `uvicorn backend.main:app --host 0.0.0.0 --port $PORT`
   - **Instance Type:** Free
5. Click **Advanced** and add these **Environment Variables**:

| Key | Value |
|-----|-------|
| `REDIS_URL` | Your Upstash Redis URL from Step 2 |
| `R2_ACCOUNT_ID` | Your Cloudflare Account ID from Step 3 |
| `R2_ACCESS_KEY_ID` | Your R2 Access Key ID from Step 3 |
| `R2_SECRET_ACCESS_KEY` | Your R2 Secret Access Key from Step 3 |
| `R2_BUCKET_NAME` | `wcag-pdf-tool` |
| `R2_ENDPOINT_URL` | `https://<your-account-id>.r2.cloudflarestorage.com` |
| `ENVIRONMENT` | `production` |

6. Click **Create Web Service**
7. Wait for the deploy to complete (2-5 minutes)
8. Your app is now live at `https://wcag-pdf-tool.onrender.com` (or similar)

### 4b. Create the Background Worker

1. In Render dashboard, click **New** → **Background Worker**
2. Connect the same GitHub repository
3. Configure:
   - **Name:** `wcag-pdf-tool-worker`
   - **Branch:** `main`
   - **Runtime:** Python 3
   - **Build Command:** `pip install -r requirements.txt && apt-get update && apt-get install -y tesseract-ocr`
   - **Start Command:** `celery -A backend.queue worker --loglevel=info --concurrency=4`
   - **Instance Type:** Free
4. Add the **same environment variables** as the web service (Step 4a, item 5)
5. Click **Create Background Worker**

> **Note:** The free tier spins down after 15 minutes of inactivity. The first request after idle takes ~30 seconds to wake up. This is normal.

---

## Step 5: Set Up GitHub Secrets (for CI/CD)

These secrets enable automatic deployment when you merge to `main`.

1. Go to your repository on GitHub
2. Click **Settings** → **Secrets and variables** → **Actions**
3. Click **New repository secret** for each:

| Secret Name | Value | Where to Find It |
|-------------|-------|-------------------|
| `RENDER_DEPLOY_HOOK` | Render deploy hook URL | Render → Web Service → Settings → Deploy Hook |
| `LIVE_URL` | `https://wcag-pdf-tool.onrender.com` | Your Render web service URL |

### How to Get the Render Deploy Hook

1. In Render dashboard, go to your **wcag-pdf-tool** web service
2. Click **Settings**
3. Scroll to **Deploy Hook**
4. Click **Generate Deploy Hook**
5. Copy the URL

---

## Step 6: Set Up Monitoring

1. Go to [uptimerobot.com](https://uptimerobot.com) and create a free account
2. Click **Add New Monitor**
3. Configure:
   - **Monitor Type:** HTTP(s)
   - **Friendly Name:** `WCAG PDF Tool`
   - **URL:** `https://wcag-pdf-tool.onrender.com/health`
   - **Monitoring Interval:** 5 minutes
4. Under **Alert Contacts**, add your email
5. Click **Create Monitor**

You'll receive email alerts if the site goes down for more than 10 minutes (2 consecutive failures).

---

## Step 7: Verify Everything Works

1. Open your live URL: `https://wcag-pdf-tool.onrender.com`
   - First visit may take 30 seconds (free tier waking up)
2. You should see the upload interface with a privacy notice
3. Upload a test PDF file
4. Wait for processing (watch the progress bar)
5. Download the remediated PDF and compliance report
6. Open the compliance report in your browser — it should show a scorecard

### Verify the Health Endpoint

Visit `https://wcag-pdf-tool.onrender.com/health` in your browser. You should see:

```json
{
  "status": "healthy",
  "timestamp": "2026-04-07T00:00:00Z",
  "version": "1.0.0",
  "queue_depth": 0,
  "storage_usage_mb": 0.0
}
```

---

## Troubleshooting

### "Service Unavailable" or page won't load
- **Cause:** Render free tier spins down after 15 minutes of inactivity
- **Fix:** Wait 30-60 seconds for it to wake up. Refresh the page.

### "Failed to queue file for processing"
- **Cause:** Redis connection issue
- **Fix:** Check that `REDIS_URL` is correct in Render environment variables. Go to Upstash dashboard and verify the database is active.

### Upload succeeds but processing never completes
- **Cause:** Background worker not running
- **Fix:** Go to Render dashboard → `wcag-pdf-tool-worker` → check if it's running. Check the logs for errors.

### "Daily processing limit reached"
- **Cause:** Upstash free tier allows 10,000 commands/day (~500 files)
- **Fix:** Wait until midnight UTC for the limit to reset, or upgrade your Upstash plan.

### Health endpoint shows `"status": "degraded"`
- **Cause:** One or more services are down
- **Fix:** Check Render logs, Upstash dashboard, and Cloudflare R2 dashboard for issues.

---

## How Deployment Works After Setup

Once everything is configured:

1. You make changes on a feature branch
2. Open a Pull Request to `main`
3. GitHub Actions automatically runs lint, tests, and security checks
4. After the PR is merged, GitHub Actions triggers a deploy to Render
5. A smoke test runs against the live URL
6. If the smoke test fails, a GitHub issue is created and you'll need to rollback manually via the Render dashboard (see [ROLLBACK.md](ROLLBACK.md))

You never need to manually deploy. Just merge PRs.

---

## Cost Summary

| Service | Plan | Monthly Cost |
|---------|------|-------------|
| Render (web + worker) | Free | $0 |
| Upstash Redis | Free | $0 |
| Cloudflare R2 | Free | $0 |
| UptimeRobot | Free | $0 |
| GitHub Actions | Free (public repo) | $0 |
| **Total** | | **$0/month** |
