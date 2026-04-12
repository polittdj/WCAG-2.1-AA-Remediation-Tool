"""app.py — Gradio UI wrapping pipeline.run_pipeline.

Users upload one or more PDFs through the browser, the pipeline runs on
each file (concurrently, with a per-file timeout), and a single combined
ZIP is offered for download.
"""

from __future__ import annotations

import datetime as _dt
import logging
import os
import pathlib
import shutil
import tempfile
import traceback
import zipfile
from concurrent.futures import (
    ThreadPoolExecutor,
    TimeoutError as FuturesTimeoutError,
    as_completed,
)
from typing import Any

import gradio as gr

from pipeline import run_pipeline, CRITICAL_CHECKPOINTS
from rate_limiter import (
    validate_file,
    validate_batch,
    check_rate_limit,
    check_queue_depth,
    record_job,
)

logger = logging.getLogger(__name__)

PRIVACY_NOTICE_MD = """## Privacy Notice
Uploaded files are processed locally in this environment.
No file contents are transmitted to any external server.
All uploaded and processed files are deleted automatically
after your session ends."""

KNOWN_LIMITATIONS_MD = """1. Alt text for images requires human review after processing.
2. Color contrast failures are reported but not auto-corrected.
3. Password-protected PDFs cannot be processed.
4. Digital signatures become invalid after processing.
5. Complex multi-column layouts may have imperfect reading order."""

PER_FILE_TIMEOUT_SEC = 300
MAX_WORKERS = 4
RESULT_HEADERS = ["Filename", "Result", *CRITICAL_CHECKPOINTS]


def _process_one(input_path: str, out_dir: str) -> dict:
    try:
        return run_pipeline(input_path, out_dir)
    except Exception as e:
        return {
            "result": "ERROR",
            "checkpoints": [],
            "errors": [f"{type(e).__name__}: {e}"],
            "output_pdf": "",
            "report_html": "",
            "zip_path": "",
        }


def _row_for(filename: str, res: dict) -> list[str]:
    statuses = {c["id"]: c["status"] for c in res.get("checkpoints", [])}
    def cell(cid: str) -> str:
        s = statuses.get(cid)
        return s if s else "\u2014"
    return [filename, res.get("result", "ERROR"), *(cell(cid) for cid in CRITICAL_CHECKPOINTS)]


def _file_input_to_path(item: Any) -> str:
    if item is None:
        return ""
    if isinstance(item, (str, pathlib.Path)):
        return str(item)
    name = getattr(item, "name", None)
    if name:
        return str(name)
    if isinstance(item, dict) and "path" in item:
        return str(item["path"])
    return str(item)


def _unique_arcname(name: str, used: set[str]) -> str:
    """Return a ZIP-safe arcname that doesn't collide with existing entries.

    If `name` is already in `used`, append `(1)`, `(2)`, etc. to the stem.
    """
    if name not in used:
        used.add(name)
        return name
    stem, ext = os.path.splitext(name)
    counter = 1
    while True:
        candidate = f"{stem}({counter}){ext}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        counter += 1


def process_files_core(
    file_paths: list[str],
    work_root: pathlib.Path | None = None,
) -> tuple[list[list[str]], str | None, list[str]]:
    rows: list[list[str]] = []
    err_log: list[str] = []
    # Collect (pdf_path, html_path) from each successful pipeline run.
    # We write these directly — flat — into the combined ZIP so the user
    # unzips once and sees their files immediately. No nested ZIPs.
    per_file_outputs: list[tuple[str, str]] = []  # (pdf_path, html_path)
    if not file_paths:
        return rows, None, err_log
    work_dir = pathlib.Path(work_root if work_root is not None else tempfile.mkdtemp(prefix="wcag_app_"))
    work_dir.mkdir(parents=True, exist_ok=True)
    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            future_to_meta: dict[Any, tuple[int, str]] = {}
            for idx, path in enumerate(file_paths):
                file_out = work_dir / f"job_{idx}"
                file_out.mkdir(parents=True, exist_ok=True)
                fut = ex.submit(_process_one, path, str(file_out))
                future_to_meta[fut] = (idx, path)
            for done in as_completed(future_to_meta):
                idx, in_path = future_to_meta[done]
                fname = pathlib.Path(in_path).name
                try:
                    res = done.result(timeout=PER_FILE_TIMEOUT_SEC)
                except FuturesTimeoutError:
                    err_log.append(f"{fname}: timeout")
                    res = {"result": "ERROR", "checkpoints": [], "errors": ["timeout"], "zip_path": "", "output_pdf": "", "report_html": ""}
                except Exception as e:
                    err_log.append(f"{fname}: {type(e).__name__}: {e}")
                    res = {"result": "ERROR", "checkpoints": [], "errors": [str(e)], "zip_path": "", "output_pdf": "", "report_html": ""}
                rows.append(_row_for(fname, res))
                out_pdf = res.get("output_pdf", "")
                out_html = res.get("report_html", "")
                if out_pdf and pathlib.Path(out_pdf).exists():
                    per_file_outputs.append((out_pdf, out_html))
                else:
                    err_log.append(f"{fname}: no output PDF")
        combined_path: str | None = None
        if per_file_outputs:
            persistent_dir = pathlib.Path(tempfile.mkdtemp(prefix="wcag_out_"))
            stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            combined = persistent_dir / f"WCAG_Compliance_Results_{stamp}.zip"
            used_names: set[str] = set()
            with zipfile.ZipFile(str(combined), "w", zipfile.ZIP_DEFLATED) as zf:
                for out_pdf, out_html in per_file_outputs:
                    # Write each output file as a FLAT entry. Use
                    # os.path.basename so the arcname contains no
                    # directory prefix. If two batches produced the
                    # same basename (rare but possible with renames),
                    # disambiguate with (1), (2), etc.
                    pdf_arc = _unique_arcname(os.path.basename(out_pdf), used_names)
                    zf.write(out_pdf, arcname=pdf_arc)
                    if out_html and pathlib.Path(out_html).exists():
                        html_arc = _unique_arcname(os.path.basename(out_html), used_names)
                        zf.write(out_html, arcname=html_arc)
            combined_path = str(combined)
        return rows, combined_path, err_log
    finally:
        try:
            shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass


def process_files(files: list[Any], request: gr.Request | None = None) -> tuple[str, list[list[str]], Any]:
    if not files:
        return "No files uploaded.", [], gr.update(value=None, visible=False)
    paths = [_file_input_to_path(f) for f in files]

    # --- Rate limiting checks (before any processing) ---
    ip = "unknown"
    if request is not None:
        ip = getattr(request, "client", {})
        if isinstance(ip, dict):
            ip = ip.get("host", "unknown")
        elif hasattr(ip, "host"):
            ip = ip.host
        else:
            ip = str(ip) if ip else "unknown"

    # Per-IP rate limit
    rate_err = check_rate_limit(ip)
    if rate_err:
        return rate_err, [], gr.update(value=None, visible=False)

    # Queue depth
    queue_err = check_queue_depth()
    if queue_err:
        return queue_err, [], gr.update(value=None, visible=False)

    # Per-file validation (size + MIME)
    for p in paths:
        file_err = validate_file(p)
        if file_err:
            return file_err, [], gr.update(value=None, visible=False)

    # Batch size validation
    batch_err = validate_batch(paths)
    if batch_err:
        return batch_err, [], gr.update(value=None, visible=False)

    # Record the job for rate limiting
    record_job(ip)

    n = len(paths)
    rows, combined_zip, err_log = process_files_core(paths)
    status = f"Done. Processed {n} file(s)."
    if err_log:
        status += "\n\nErrors:\n" + "\n".join(err_log)
    return (
        status,
        list(rows),
        gr.update(value=combined_zip, visible=combined_zip is not None),
    )


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="WCAG 2.1 AA PDF Remediation") as demo:
        gr.Markdown(PRIVACY_NOTICE_MD)
        upload = gr.File(
            label="Upload PDF files for WCAG 2.1 AA remediation",
            file_count="multiple",
            file_types=[".pdf"],
        )
        process_btn = gr.Button("Process Files", variant="primary")
        status = gr.Textbox(label="Processing Status", interactive=False, lines=6, max_lines=20)
        results = gr.Dataframe(
            label="Results",
            headers=RESULT_HEADERS,
            datatype=["str"] * len(RESULT_HEADERS),
            interactive=False,
            wrap=True,
        )
        download = gr.File(label="Download Results (ZIP)", interactive=False, visible=False)
        with gr.Accordion("Known Limitations", open=False):
            gr.Markdown(KNOWN_LIMITATIONS_MD)
        process_btn.click(
            fn=process_files,
            inputs=[upload],
            outputs=[status, results, download],
        )
    return demo


demo = build_ui()

def main() -> int:
    demo.launch(server_name="0.0.0.0", server_port=7860, share=False, show_error=True)
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
