# ROLLBACK.md — WCAG 2.1 AA PDF Tool

## When to Rollback
- Live URL returns errors after deployment
- Smoke test fails after merge to main
- Critical regression discovered in production

## Automatic Rollback
The deploy.yml workflow includes a smoke test after deployment.
If the smoke test fails, the deployment is automatically rolled back
to the previous working version.

## Manual Rollback Procedure

### Step 1: Identify the last working commit
```bash
git log --oneline main
# Find the last commit where CI passed
```

### Step 2: Revert to last working state
```bash
git revert HEAD --no-edit
git push origin main
```

### Step 3: Verify rollback
1. Wait for HF Spaces to redeploy (1-2 minutes)
2. Visit the live URL
3. Upload a test PDF
4. Verify the tool works correctly

### Step 4: Investigate
1. Check the failing commit's test results
2. Identify the root cause
3. Fix on a feature branch
4. Create PR with fix + new test covering the bug
5. Merge only after CI passes

## Emergency: Force Rollback
If `git revert` doesn't work:
```bash
git reset --hard <last-known-good-sha>
git push --force origin main
```
**WARNING**: Force push destroys commit history. Use only as last resort.

## Post-Rollback Checklist
- [ ] Live URL is accessible
- [ ] Upload/download works
- [ ] HTML report shows 47 checkpoints
- [ ] All 5 production PDFs process successfully
- [ ] UptimeRobot shows green
- [ ] Team notified of rollback and root cause
