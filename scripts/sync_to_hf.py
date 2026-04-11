"""Upload repo to HF Spaces."""
import os
import sys
from huggingface_hub import HfApi

token = os.environ.get("HF_TOKEN", "")
if not token:
    print("No HF_TOKEN, skipping")
    sys.exit(0)

api = HfApi(token=token)

try:
    info = api.whoami()
    print(f"Authenticated as: {info['name']}")
except Exception as e:
    print(f"Auth failed: {e}")
    sys.exit(1)

api.upload_folder(
    folder_path=".",
    repo_id="polittdj/WCAG-2-1-AA-Conversion-and-Verification-Tool-v3",
    repo_type="space",
    ignore_patterns=[".git/*", "_archive/*", "__pycache__/*", "*.pyc", "test_suite/*.pdf", "tests/fixtures/**/*.pdf"],
)
print("Upload complete!")
