"""app.py — Gradio UI wrapping pipeline.run_pipeline.

Users upload one or more PDFs through the browser, the pipeline runs on
each file (concurrently, with a per-file timeout), and a single combined
ZIP is offered for download. No remediation logic lives here — every
fix is delegated to pipeline.run_pipeline().
"""

from __future__ import annotations

import datetime as _dt
import logging
import pathlib
import shutil
import sys
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

from pipeline import run_pipeline

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

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

from pipeline import CRITICAL_CHECKPOINTS

RESULT_HEADERS = ["Filename", "Result", *CRITICAL_CHECKPOINTS]


# ---------------------------------------------------------------------------
# Workers
# ---------------------------------------------------------------------------


def _process_one(input_path: str, out_dir: str) -> dict:
    """Worker thread: run the full pipeline on one file. Never raises."""
    try:
        return run_pipeline(input_path, out_dir)
    except Exception as e:
        return {
            "result": "ERROR",
            "checkpoints": [],
            "errors": [f"{type(e).__name__}: {e}\n{traceback.format_exc()}"],
            "output_pdf": "",
            "report_html": "",
            "zip_path": "",
        }


def _row_for(filename: str, res: dict) -> list[str]:
    """Build a Dataframe row for one processed file."""
    statuses = {c["id"]: c["status"] for c in res.get("checkpoints", [])}

    def cell(cid: str) -> str:
        s = statuses.get(cid)
        return s if s else "—"

    return [
        filename,
        res.get("result", "ERROR"),
        *(cell(cid) for cid in CRITICAL_CHECKPOINTS),
    ]


def _file_input_to_path(item: Any) -> str:
    """Coerce a Gradio file upload object into a filesystem path."""
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


# ---------------------------------------------------------------------------
# Public processing function (also called by tests)
# ---------------------------------------------------------------------------


def process_files_core(
    file_paths: list[str],
    work_root: pathlib.Path | None = None,
) -> tuple[list[list[str]], str | None, list[str]]:
    """Run the pipeline on every file_path. Returns (rows, combined_zip, errors).

    The combined ZIP path (if produced) lives in a directory that is NOT
    cleaned up by this function — the caller is responsible for handing
    it to the user and eventually disposing of it.
    """
    rows: list[list[str]] = []
    err_log: list[str] = []
    # (source_filename, per_file_zip_path) — source filename is used to
    # build a collision-proof arcname when two files complete in the
    # same second and would otherwise share a per-file zip name.
    per_file_zips: list[tuple[str, str]] = []

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
                    msg = f"{fname}: timeout after {PER_FILE_TIMEOUT_SEC}s"
                    logger.error(msg)
                    err_log.append(msg)
                    res = {
                        "result": "ERROR",
                        "checkpoints": [],
                        "errors": ["timeout"],
                        "zip_path": "",
                    }
                except Exception as e:
                    msg = f"{fname}: {type(e).__name__}: {e}"
                    logger.error(msg)
                    err_log.append(msg)
                    res = {
                        "result": "ERROR",
                        "checkpoints": [],
                        "errors": [str(e)],
                        "zip_path": "",
                    }

                rows.append(_row_for(fname, res))
                if res.get("zip_path"):
                    per_file_zips.append((fname, res["zip_path"]))
                else:
                    err_log.append(f"{fname}: no output ZIP — {res.get('errors')}")

        # Combined ZIP — written into a *separate* persistent directory
        # so the work_dir cleanup below does not remove it.
        combined_path: str | None = None
        if per_file_zips:
            persistent_dir = pathlib.Path(tempfile.mkdtemp(prefix="wcag_out_"))
            stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            combined = persistent_dir / f"WCAG_Compliance_Results_{stamp}.zip"
            with zipfile.ZipFile(str(combined), "w", zipfile.ZIP_DEFLATED) as zf:
                for src_name, zp in per_file_zips:
                    arcname = f"{pathlib.Path(src_name).stem}.zip"
                    zf.write(zp, arcname=arcname)
            combined_path = str(combined)

        return rows, combined_path, err_log

    finally:
        try:
            shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Gradio handler (generator — yields incremental status updates)
# ---------------------------------------------------------------------------


def process_files(files: list[Any], progress: Any = None):
    """Gradio click handler. Yields (status, rows, file_update) tuples."""
    if progress is None:
        progress = gr.Progress()

    if not files:
        yield (
            "No files uploaded.",
            [],
            gr.update(value=None, visible=False),
        )
        return

    paths = [_file_input_to_path(f) for f in files]
    n = len(paths)

    rows: list[list[str]] = []
    err_log: list[str] = []
    per_file_zips: list[tuple[str, str]] = []
    work_dir = pathlib.Path(tempfile.mkdtemp(prefix="wcag_app_"))

    status_lines: list[str] = [f"Submitted {n} file(s) for processing."]
    yield (
        "\n".join(status_lines),
        list(rows),
        gr.update(value=None, visible=False),
    )

    try:
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as ex:
            future_to_meta: dict[Any, tuple[int, str]] = {}
            for idx, path in enumerate(paths):
                file_out = work_dir / f"job_{idx}"
                file_out.mkdir(parents=True, exist_ok=True)
                fut = ex.submit(_process_one, path, str(file_out))
                future_to_meta[fut] = (idx, path)

            processed = 0
            for done in as_completed(future_to_meta):
                idx, in_path = future_to_meta[done]
                fname = pathlib.Path(in_path).name
                processed += 1

                try:
                    res = done.result(timeout=PER_FILE_TIMEOUT_SEC)
                except FuturesTimeoutError:
                    res = {
                        "result": "ERROR",
                        "checkpoints": [],
                        "errors": [f"timeout after {PER_FILE_TIMEOUT_SEC}s"],
                        "zip_path": "",
                    }
                    err_log.append(f"{fname}: timeout")
                except Exception as e:
                    res = {
                        "result": "ERROR",
                        "checkpoints": [],
                        "errors": [str(e)],
                        "zip_path": "",
                    }
                    err_log.append(f"{fname}: {type(e).__name__}: {e}")

                rows.append(_row_for(fname, res))
                if res.get("zip_path"):
                    per_file_zips.append((fname, res["zip_path"]))

                try:
                    progress(
                        processed / n,
                        desc=f"Processing file {processed} of {n}: {fname}",
                    )
                except Exception:
                    pass

                status_lines.append(f"Processing file {processed} of {n}: {fname}")
                yield (
                    "\n".join(status_lines),
                    list(rows),
                    gr.update(value=None, visible=False),
                )

        # Build the combined ZIP in a persistent dir so we can hand its
        # path to the gr.File output without it being cleaned up.
        combined_out: str | None = None
        if per_file_zips:
            persistent_dir = pathlib.Path(tempfile.mkdtemp(prefix="wcag_out_"))
            stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
            combined = persistent_dir / f"WCAG_Compliance_Results_{stamp}.zip"
            with zipfile.ZipFile(str(combined), "w", zipfile.ZIP_DEFLATED) as zf:
                for src_name, zp in per_file_zips:
                    arcname = f"{pathlib.Path(src_name).stem}.zip"
                    zf.write(zp, arcname=arcname)
            combined_out = str(combined)

        # Final yield — make the download visible.
        final_status = "\n".join(
            status_lines + ["", f"Done. Processed {n} file(s)."] + ([""] + ["Errors:"] + err_log if err_log else [])
        )
        yield (
            final_status,
            list(rows),
            gr.update(
                value=combined_out,
                visible=combined_out is not None,
            ),
        )

    finally:
        try:
            shutil.rmtree(str(work_dir), ignore_errors=True)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# UI
# ---------------------------------------------------------------------------


def build_ui() -> gr.Blocks:
    with gr.Blocks(title="WCAG 2.1 AA PDF Remediation") as demo:
        gr.Markdown(PRIVACY_NOTICE_MD)

        upload = gr.File(
            label="Upload PDF files for WCAG 2.1 AA remediation",
            file_count="multiple",
            file_types=[".pdf"],
        )

        process_btn = gr.Button("Process Files", variant="primary")

        status = gr.Textbox(
            label="Processing Status",
            interactive=False,
            lines=6,
            max_lines=20,
        )

        results = gr.Dataframe(
            label="Results",
            headers=RESULT_HEADERS,
            datatype=["str"] * len(RESULT_HEADERS),
            interactive=False,
            wrap=True,
        )

        download = gr.File(
            label="Download Results (ZIP)",
            interactive=False,
            visible=False,
        )

        with gr.Accordion("Known Limitations", open=False):
            gr.Markdown(KNOWN_LIMITATIONS_MD)

        process_btn.click(
            fn=process_files,
            inputs=[upload],
            outputs=[status, results, download],
        )

    return demo


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main() -> int:
    demo = build_ui()
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        share=False,
        show_error=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
