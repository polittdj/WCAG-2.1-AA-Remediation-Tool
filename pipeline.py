"""pipeline.py — R3 remediation pipeline with 47-checkpoint auditing.

Chains all fix modules in dependency order, audits the result against
all 47 checkpoints, and emits a ZIP containing the remediated PDF and
an HTML compliance report.

Order is non-negotiable:
  0.  fix_scanned_ocr        (detect scans -> OCR -> struct tree stub)
  1.  fix_title              (metadata only)
  2.  fix_content_streams    (sanitize non-standard BDC tags)
  3.  fix_untagged_content   (wrap untagged BT/ET and paths)
  4.  fix_widget_mapper      (widget /Form nesting + flat /Nums ParentTree)
  5.  fix_widget_tu          (populate missing /TU accessible names)
  6.  fix_widget_appearance  (retag widget /AP content as /Artifact)
  7.  fix_focus_order        (force /Tabs /S on pages with annotations)
  8.  fix_link_alt           (populate /Contents on /Link annotations)
  9.  fix_figure_alt_text    (AI-assisted alt text for /Figure elements)
 10.  wcag_auditor           (verify the result - 47 checkpoints)

The original input file is never modified or deleted.  All intermediate
files are written into a temp directory and removed in a finally block.
"""

from __future__ import annotations

import datetime as _dt
import json
import logging
import pathlib
import shutil
import sys
import tempfile
import traceback
import zipfile
from html import escape
from typing import Any

import pikepdf

from fix_annotations import fix_annotations
from fix_artifacts import fix_artifacts
from fix_bookmarks import fix_bookmarks
from fix_content_streams import fix_content_streams
from fix_content_tagger import fix_content_tagger
from fix_figure_alt_text import fix_figure_alt_text
from fix_focus_order import fix_focus_order
from fix_ghost_text import fix_ghost_text
from fix_headings import fix_headings
from fix_language import fix_language
from fix_link_alt import fix_link_alt
from fix_pdfua_meta import fix_pdfua_meta
from fix_scanned_ocr import fix_scanned_ocr
from fix_security import fix_security
from fix_title import fix_title
from fix_untagged_content import fix_untagged_content
from fix_widget_appearance import fix_widget_appearance
from fix_widget_mapper import fix_widget_mapper
from fix_widget_tu import fix_widget_tu
from wcag_auditor import audit_pdf

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Critical checkpoints that determine PASS vs PARTIAL.
# These use the NEW R3 dense IDs (C-01 through C-47).
CRITICAL_CHECKPOINTS: tuple[str, ...] = (
    "C-01",  # Tagged PDF (/MarkInfo /Marked)
    "C-02",  # Document Title
    "C-03",  # Title not placeholder
    "C-04",  # Document /Lang
    "C-10",  # Tab order (/Tabs /S)
    "C-13",  # Standard BDC tags
    "C-31",  # Figures have Alt text
    "C-36",  # Field descriptions (/TU)
    "C-39",  # Widget StructParent
    "C-40",  # SP resolves to /Form
    "C-46",  # ParentTree flat /Nums
)

# Checkpoints where NOT_APPLICABLE is an acceptable "success" state.
_NA_ACCEPTABLE: frozenset[str] = frozenset(
    {
        "C-31",  # Figures - N/A when no figures
        "C-36",  # Widget TU - N/A when no widgets
        "C-39",  # Widget StructParent - N/A when no widgets
        "C-40",  # SP resolves to /Form - N/A when no widgets
    }
)

MANUAL_REVIEW_ITEMS: list[str] = [
    "Alt text for images requires human verification",
    "Color contrast failures are reported but not auto-corrected",
    "Digital signatures are invalidated by remediation",
    "Reading order should be verified by a human reviewer",
    "Form label accuracy should be verified against visible text",
]

PRIVACY_NOTICE_LOCAL = "This file was processed locally.\nNo data was transmitted to any external server."

PRIVACY_NOTICE_AI = (
    "This file was processed locally, EXCEPT for the figure-alt-text "
    "step.\nWith WCAG_ENABLE_AI_ALT_TEXT set, rendered images of "
    "every /Figure were\nsent to Anthropic's Claude Vision API for "
    "description."
)

# Preserved for backwards-compatible imports (tests, third-party code).
PRIVACY_NOTICE = PRIVACY_NOTICE_LOCAL


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _is_pass(checkpoints: list[dict]) -> bool:
    """Return True iff every critical checkpoint is PASS (or N/A when
    the checkpoint appears in `_NA_ACCEPTABLE`)."""
    statuses = {c["id"]: c["status"] for c in checkpoints}
    for cid in CRITICAL_CHECKPOINTS:
        st = statuses.get(cid)
        if st == "PASS":
            continue
        if st == "NOT_APPLICABLE" and cid in _NA_ACCEPTABLE:
            continue
        return False
    return True


def _read_title(pdf_path: pathlib.Path) -> str:
    """Read DocInfo /Title from a PDF; return '' on failure."""
    try:
        with pikepdf.open(str(pdf_path)) as pdf:
            t = pdf.docinfo.get("/Title")
            return str(t).strip() if t is not None else ""
    except Exception:
        return ""


def _build_html_report_legacy(
    *,
    filename: str,
    title: str,
    timestamp: str,
    overall: str,
    checkpoints: list[dict],
    failed_steps: list[str],
    auditor_error: str,
    ai_used: bool = False,
) -> str:
    """Render the standalone HTML compliance report."""
    status_class = {
        "PASS": "ok",
        "FAIL": "fail",
        "WARN": "warn",
        "NOT_APPLICABLE": "na",
        "INDETERMINATE": "warn",
        "MANUAL_REVIEW": "review",
    }
    rows = []
    for c in checkpoints:
        cls = status_class.get(c.get("status", ""), "")
        rows.append(
            "  <tr class='{cls}'><td>{id}</td><td>{desc}</td><td>{status}</td><td>{detail}</td></tr>".format(
                cls=cls,
                id=escape(c.get("id", "")),
                desc=escape(c.get("description", "")),
                status=escape(c.get("status", "")),
                detail=escape(c.get("detail", "")),
            )
        )
    table = "\n".join(rows) if rows else ("  <tr><td colspan='4'><em>No checkpoint results.</em></td></tr>")

    review_lis = "\n".join(f"  <li>{escape(item)}</li>" for item in MANUAL_REVIEW_ITEMS)

    failed_section = ""
    if failed_steps:
        failed_section += (
            "<h2>Failed pipeline steps</h2>\n<ul>\n"
            + "\n".join(f"  <li>{escape(s)}</li>" for s in failed_steps)
            + "\n</ul>\n"
        )
    if auditor_error:
        failed_section += f"<h2>Auditor error</h2>\n<pre>{escape(auditor_error)}</pre>\n"

    title_html = escape(title) if title else "<em>(no title)</em>"

    if ai_used:
        privacy_text = PRIVACY_NOTICE_AI
        ai_banner = (
            "<h2>External data transfer notice</h2>\n"
            "<p style='background:#fff3cd;border:1px solid #ffeeba;"
            "padding:0.5em 0.8em;border-radius:4px;'>\n"
            "This document contains figure elements whose alt text "
            "was generated\n"
            "by Anthropic's Claude Vision API. Rendered images of "
            "those figures\n"
            "were transmitted to Anthropic for description. All other "
            "pipeline\n"
            "steps ran locally.\n"
            "</p>\n"
        )
    else:
        privacy_text = PRIVACY_NOTICE_LOCAL
        ai_banner = ""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>WCAG 2.1 AA Compliance Report &mdash; {escape(filename)}</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
       max-width: 960px; margin: 2em auto; padding: 0 1em; color: #222; }}
h1 {{ border-bottom: 2px solid #333; padding-bottom: 0.2em; }}
h2 {{ margin-top: 1.5em; }}
table {{ border-collapse: collapse; width: 100%; margin: 1em 0; }}
th, td {{ border: 1px solid #ccc; padding: 0.4em 0.6em; text-align: left;
         vertical-align: top; }}
th {{ background: #f0f0f0; }}
tr.ok td {{ background: #e6f4ea; }}
tr.fail td {{ background: #fce8e6; }}
tr.warn td {{ background: #fef7e0; }}
tr.na td {{ background: #f0f0f0; color: #666; }}
tr.review td {{ background: #e8eaf6; color: #333; }}
.overall {{ font-size: 1.4em; font-weight: bold; padding: 0.25em 0.6em;
           border-radius: 4px; display: inline-block; }}
.overall.pass {{ background: #e6f4ea; color: #1e8e3e; }}
.overall.partial {{ background: #fef7e0; color: #b06000; }}
footer {{ border-top: 1px solid #ccc; margin-top: 2em; padding-top: 1em;
         color: #666; font-size: 0.9em; white-space: pre-line; }}
</style>
</head>
<body>
<h1>WCAG 2.1 AA Compliance Report</h1>
<p><strong>Document:</strong> {escape(filename)}</p>
<p><strong>Title:</strong> {title_html}</p>
<p><strong>Processed:</strong> {escape(timestamp)}</p>
<p><strong>Overall result:</strong>
  <span class="overall {overall.lower()}">{escape(overall)}</span>
</p>

<h2>Checkpoint results</h2>
<table>
<thead><tr><th>ID</th><th>Description</th><th>Status</th><th>Detail</th></tr></thead>
<tbody>
{table}
</tbody>
</table>

{failed_section}<h2>Manual review items</h2>
<ul>
{review_lis}
</ul>

{ai_banner}<footer>{escape(privacy_text)}</footer>
</body>
</html>
"""


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def run_pipeline(input_path: str, output_dir: str) -> dict:
    """Run the full remediation pipeline on `input_path`.

    Writes outputs into `output_dir`.  Returns a dict with keys:
      output_pdf, report_html, zip_path, result, checkpoints, errors
    """
    in_path = pathlib.Path(input_path).resolve()
    out_dir = pathlib.Path(output_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)

    result: dict[str, Any] = {
        "output_pdf": "",
        "report_html": "",
        "zip_path": "",
        "result": "PARTIAL",
        "checkpoints": [],
        "errors": [],
    }

    failed_steps: list[str] = []
    auditor_error = ""
    tmpdir: pathlib.Path | None = None
    ai_used = False

    # Preflight: reject password-protected PDFs early with a clear message.
    try:
        with pikepdf.open(str(in_path)):
            pass
    except pikepdf.PasswordError:
        result["errors"].append(
            "The PDF is password-protected and cannot be processed. Remove the password before uploading."
        )
        result["result"] = "PARTIAL"
        return result
    except Exception:
        pass  # other open failures will be caught by the first fix step

    try:
        tmpdir = pathlib.Path(tempfile.mkdtemp(prefix="wcag_pipe_"))

        # last_good = path of the most recent successful intermediate.
        last_good: pathlib.Path = in_path

        steps: list[tuple[str, Any]] = [
            ("fix_scanned_ocr", fix_scanned_ocr),
            ("fix_title", fix_title),
            ("fix_language", fix_language),
            ("fix_security", fix_security),
            ("fix_pdfua_meta", fix_pdfua_meta),  # early: MarkInfo + StructTreeRoot
            ("fix_content_streams", fix_content_streams),
            ("fix_ghost_text", fix_ghost_text),
            ("fix_untagged_content", fix_untagged_content),
            ("fix_headings", fix_headings),
            ("fix_content_tagger", fix_content_tagger),  # /P, /Table, /L, /Figure
            ("fix_widget_mapper", fix_widget_mapper),
            ("fix_widget_tu", fix_widget_tu),
            ("fix_widget_appearance", fix_widget_appearance),
            ("fix_focus_order", fix_focus_order),
            ("fix_link_alt", fix_link_alt),
            ("fix_figure_alt_text", fix_figure_alt_text),
            ("fix_annotations", fix_annotations),
            ("fix_bookmarks", fix_bookmarks),
            ("fix_artifacts", fix_artifacts),
            ("fix_pdfua_meta", fix_pdfua_meta),  # final: re-ensure XMP after all changes
        ]

        for step_name, fn in steps:
            tmp_out = tmpdir / f"{step_name}.pdf"
            try:
                step_result = fn(str(last_good), str(tmp_out))
                inner_errs = step_result.get("errors") or []
                if isinstance(inner_errs, str):
                    inner_errs = [inner_errs] if inner_errs else []
                if inner_errs:
                    logger.warning(
                        "step %s reported internal issues: %s",
                        step_name,
                        inner_errs,
                    )
                    for ie in inner_errs:
                        result["errors"].append(f"{step_name} (warning): {ie}")
                if step_result.get("ai_used"):
                    ai_used = True
                if not tmp_out.exists():
                    raise RuntimeError(f"{step_name} did not produce {tmp_out}")
                last_good = tmp_out
            except Exception as e:
                tb = traceback.format_exc()
                logger.error(
                    "pipeline step %s raised:\n%s",
                    step_name,
                    tb,
                )
                result["errors"].append(f"{step_name}: {type(e).__name__}: {e}")
                failed_steps.append(step_name)

        # Audit with all 47 checkpoints
        report: dict = {"checkpoints": [], "summary": {}, "file": last_good.name}
        try:
            report = audit_pdf(last_good)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("auditor raised:\n%s", tb)
            auditor_error = f"{type(e).__name__}: {e}"
            result["errors"].append(f"audit: {auditor_error}")

        result["checkpoints"] = report.get("checkpoints", [])

        # Decide PASS / PARTIAL based on critical checkpoints only.
        if failed_steps or auditor_error:
            overall = "PARTIAL"
        elif _is_pass(result["checkpoints"]):
            overall = "PASS"
        else:
            overall = "PARTIAL"
        result["result"] = overall

        # Output filenames — strip existing suffix to avoid doubling
        stem = in_path.stem
        for suffix in ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL",
                        "_WCAG_2.1_AA_Compliant", "_WCAG_2.1_AA_PARTIAL"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        if overall == "PASS":
            out_pdf_name = f"{stem}_WGAC_2.1_AA_Compliant.pdf"
            report_name = f"{stem}_WGAC_2.1_AA_Compliant_report.html"
        else:
            out_pdf_name = f"{stem}_WGAC_2.1_AA_PARTIAL.pdf"
            report_name = f"{stem}_WGAC_2.1_AA_PARTIAL_report.html"

        out_pdf_path = out_dir / out_pdf_name
        shutil.copy2(str(last_good), str(out_pdf_path))

        # Build HTML report (Jinja2 with legacy fallback)
        title = _read_title(out_pdf_path)
        timestamp = _dt.datetime.now().isoformat(sep=" ", timespec="seconds")
        try:
            from reporting.html_generator import generate_report

            html = generate_report(
                filename=in_path.name,
                title=title,
                timestamp=timestamp,
                overall=overall,
                checkpoints=result["checkpoints"],
                failed_steps=failed_steps,
                auditor_error=auditor_error,
                ai_used=ai_used,
            )
        except Exception as jinja_err:
            logger.warning("Jinja2 report failed, using legacy: %s", jinja_err)
            html = _build_html_report_legacy(
                filename=in_path.name,
                title=title,
                timestamp=timestamp,
                overall=overall,
                checkpoints=result["checkpoints"],
                failed_steps=failed_steps,
                auditor_error=auditor_error,
                ai_used=ai_used,
            )
        result["ai_used"] = ai_used
        report_path = out_dir / report_name
        report_path.write_text(html, encoding="utf-8")

        # ZIP
        zip_stamp = _dt.datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        zip_name = f"WCAG_Compliance_Results_{zip_stamp}.zip"
        zip_path = out_dir / zip_name
        with zipfile.ZipFile(str(zip_path), "w", zipfile.ZIP_DEFLATED) as zf:
            zf.write(str(out_pdf_path), arcname=out_pdf_name)
            zf.write(str(report_path), arcname=report_name)

        result["output_pdf"] = str(out_pdf_path)
        result["report_html"] = str(report_path)
        result["zip_path"] = str(zip_path)
        return result

    except Exception as e:
        tb = traceback.format_exc()
        logger.exception("pipeline catastrophic failure")
        result["errors"].append(f"pipeline: {type(e).__name__}: {e}\n{tb}")
        result["result"] = "PARTIAL"
        return result

    finally:
        if tmpdir is not None and tmpdir.exists():
            try:
                shutil.rmtree(str(tmpdir), ignore_errors=True)
            except Exception:
                pass


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def _main(argv: list[str]) -> int:
    if len(argv) < 3:
        print("usage: python pipeline.py <input.pdf> <output_dir>")
        return 2
    res = run_pipeline(argv[1], argv[2])
    summary = {k: v for k, v in res.items() if k != "checkpoints"}
    print(json.dumps(summary, indent=2))
    return 0 if res["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(_main(sys.argv))
