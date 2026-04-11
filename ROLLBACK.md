# ROLLBACK.md — WCAG 2.1 AA PDF Tool

## When to Rollback

- Live URL returns errors after deployment
- Smoke test fails after merge to main
- Critical regression discovered in production

## Automatic Rollback

The `deploy.yml` workflow runs `scripts/smoke_test.py` after every
deployment. If the smoke test fails, a GitHub issue is automatically
opened with details and instructions.

## Manual Rollback via GitHub Actions

This is the primary rollback method:

1. **Revert the merge commit on main:**
   ```bash
   git revert HEAD --no-edit
   git push origin main
   ```

2. **GitHub Actions will auto-deploy** the previous version to HF Spaces.

3. **Verify the rollback succeeded:**
   ```bash
   python scripts/smoke_test.py
   ```

4. **Notify the repository owner** (polittdj) via GitHub issue.

## Emergency Manual Rollback

If GitHub Actions is down or the automated pipeline is not working:

1. **Push a known good commit directly to HF Spaces:**
   ```bash
   git checkout <last-known-good-sha>
   pip install huggingface_hub
   huggingface-cli upload \
     polittdj/WCAG-2-1-AA-Conversion-and-Verification-Tool-v3 \
     . . --repo-type space
   ```

2. **Verify the rollback:**
   ```bash
   python scripts/smoke_test.py
   ```

## Post-Rollback Checklist

- [ ] Live URL is accessible
- [ ] Upload/download works
- [ ] HTML report shows 47 checkpoints
- [ ] All 5 production PDFs process successfully
- [ ] Smoke test passes (`python scripts/smoke_test.py`)
- [ ] Repository owner (polittdj) notified via GitHub issue
- [ ] Root cause identified and documented

## Investigate and Fix

1. Check the failing commit's test results in GitHub Actions
2. Identify the root cause
3. Fix on a feature branch
4. Create PR with fix + new test covering the bug
5. Merge only after CI passes
