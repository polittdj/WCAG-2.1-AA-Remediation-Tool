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
from src.utils.structure_validator import (
    validate_structure_tree,
    validate_and_rebuild_parent_tree,
)
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
    "C-20",  # Heading hierarchy (no multiple H1, no skipped levels)
    "C-24",  # Tables have /TR row structure
    "C-25",  # Table headers (/TH) have Scope attribute
    "C-28",  # Lists use /L containing /LI
    "C-31",  # Figures have Alt text
    "C-36",  # Field descriptions (/TU)
    "C-39",  # Widget StructParent
    "C-40",  # SP resolves to /Form
    "C-46",  # ParentTree flat /Nums
)

# Checkpoints where NOT_APPLICABLE is an acceptable "success" state.
_NA_ACCEPTABLE: frozenset[str] = frozenset(
    {
        "C-20",  # Heading hierarchy - N/A when document has no headings
        "C-24",  # Table /TR structure - N/A when no tables
        "C-25",  # TH Scope - N/A when no TH elements
        "C-28",  # List /LI - N/A when no lists
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


def compute_overall(checkpoints: list[dict]) -> str:
    """Compute overall compliance status from a list of checkpoint results.

    Rules (IRS-01 Fix 1):
    * FAIL on **any** checkpoint → "PARTIAL"
    * MANUAL_REVIEW and NOT_APPLICABLE are acceptable — they do not block PASS
    * Everything else PASS → "PASS"

    This replaces the previous CRITICAL_CHECKPOINTS whitelist approach, which
    was allowing documents with non-critical FAILs to be falsely labelled PASS.
    """
    has_fail = any(c.get("status") == "FAIL" for c in checkpoints)
    return "PARTIAL" if has_fail else "PASS"


def _is_pass(checkpoints: list[dict]) -> bool:
    """Deprecated wrapper kept for backwards-compatible imports.

    Delegates to :func:`compute_overall`.  New code should call
    ``compute_overall`` directly and compare the returned string.
    """
    return compute_overall(checkpoints) == "PASS"


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
    result: dict[str, Any] = {
        "output_pdf": "",
        "report_html": "",
        "zip_path": "",
        "result": "PARTIAL",
        "checkpoints": [],
        "errors": [],
    }

    # Path coercion can raise (e.g. embedded null byte in the input path).
    # Catch that up front so the function always returns a dict instead of
    # propagating a ValueError to the caller.
    try:
        in_path = pathlib.Path(input_path).resolve()
        out_dir = pathlib.Path(output_dir).resolve()
        out_dir.mkdir(parents=True, exist_ok=True)
    except (ValueError, OSError) as e:
        result["errors"].append(
            f"Invalid input or output path: {type(e).__name__}: {e}"
        )
        return result

    failed_steps: list[str] = []
    auditor_error = ""
    tmpdir: pathlib.Path | None = None
    ai_used = False

    # Intake preflight: catch obviously-malformed files before spending
    # time running all 20 fix steps. Covers empty files, wrong file
    # signatures (non-PDF content with a .pdf extension), and truncated
    # downloads that are missing the %%EOF marker. Failing here surfaces
    # a single clean user-facing error instead of 20 step failures.
    try:
        _size = in_path.stat().st_size
    except OSError as e:
        result["errors"].append(f"Unable to read the input file: {e}")
        result["result"] = "PARTIAL"
        return result
    if _size == 0:
        result["errors"].append(
            "The file is empty (0 bytes) and cannot be processed as a PDF."
        )
        result["result"] = "PARTIAL"
        return result
    try:
        with open(str(in_path), "rb") as _fh:
            _head = _fh.read(8)
            _fh.seek(max(0, _size - 1024))
            _tail = _fh.read(1024)
    except OSError as e:
        result["errors"].append(f"Unable to read the input file: {e}")
        result["result"] = "PARTIAL"
        return result
    if not _head.startswith(b"%PDF-"):
        result["errors"].append(
            "The file is not a PDF (missing %PDF- header). "
            "Please upload a valid PDF document."
        )
        result["result"] = "PARTIAL"
        return result
    if b"%%EOF" not in _tail:
        result["errors"].append(
            "The PDF appears to be truncated (missing %%EOF marker). "
            "Please re-export or re-download the file."
        )
        result["result"] = "PARTIAL"
        return result

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

        # Belt-and-suspenders: force /Tabs = /S on every page of the
        # remediated PDF before running the final audit.  fix_focus_order
        # runs earlier in the pipeline and should already have done this,
        # but on some code paths the struct tree gets mutated by later
        # steps and /Tabs can end up unset.  Doing this pass BEFORE the
        # audit guarantees the audit sees the final, correct state
        # (BUG-07: audit must run on the final output, not on an earlier
        # intermediate).
        final_candidate = tmpdir / "final_candidate.pdf"
        shutil.copy2(str(last_good), str(final_candidate))
        try:
            with pikepdf.open(str(final_candidate), allow_overwriting_input=True) as _pdf:
                _modified = False
                for _page in _pdf.pages:
                    _existing = _page.get("/Tabs")
                    if str(_existing) != "/S":
                        _page["/Tabs"] = pikepdf.Name("/S")
                        _modified = True
                if _modified:
                    _pdf.save(str(final_candidate))
        except Exception as _tab_err:
            logger.warning(
                "pipeline: belt-and-suspenders /Tabs=/S failed: %s",
                _tab_err,
            )

        # IRS-03 / BUG-02: Validate structure-tree integrity and, if broken,
        # rebuild the ParentTree from scratch before the audit runs.
        # Orphaned MCIDs in the struct tree cause PAC "4.1 Compatible"
        # failures even when the auditor reports PASS.  We fix first, then
        # report any remaining structural warnings from a fresh validation.
        try:
            with pikepdf.open(str(final_candidate), allow_overwriting_input=True) as _val_pdf:
                _pt_valid, _pt_fixes = validate_and_rebuild_parent_tree(_val_pdf)
                if not _pt_valid:
                    _val_pdf.save(str(final_candidate))
                    logger.info(
                        "pipeline: ParentTree rebuilt (%d orphaned MCID(s) resolved)",
                        _pt_fixes,
                    )
                # Run the diagnostic validator AFTER any rebuild so the
                # issues list reflects the post-repair state.
                struct_issues = validate_structure_tree(_val_pdf)
            if struct_issues:
                for _issue in struct_issues:
                    logger.warning("structure_validator: %s", _issue)
                    result["errors"].append(f"structure_validator (warning): {_issue}")
        except Exception as _val_err:
            logger.warning("structure_validator raised: %s", _val_err)

        # Audit with all 47 checkpoints — run on the final candidate so
        # the report reflects what the user actually receives (BUG-07).
        report: dict = {"checkpoints": [], "summary": {}, "file": final_candidate.name}
        try:
            report = audit_pdf(final_candidate)
        except Exception as e:
            tb = traceback.format_exc()
            logger.error("auditor raised:\n%s", tb)
            auditor_error = f"{type(e).__name__}: {e}"
            result["errors"].append(f"audit: {auditor_error}")

        result["checkpoints"] = report.get("checkpoints", [])

        # Decide PASS / PARTIAL.
        # Any FAIL on any checkpoint → PARTIAL (IRS-01 Fix 1).
        # Pipeline failures or auditor errors also force PARTIAL.
        if failed_steps or auditor_error:
            overall = "PARTIAL"
        else:
            overall = compute_overall(result["checkpoints"])
        result["result"] = overall

        # Output filenames — strip existing suffix to avoid doubling
        stem = in_path.stem
        for suffix in ("_WGAC_2.1_AA_Compliant", "_WGAC_2.1_AA_PARTIAL",
                        "_WCAG_2.1_AA_Compliant", "_WCAG_2.1_AA_PARTIAL"):
            if stem.endswith(suffix):
                stem = stem[: -len(suffix)]
                break
        # Truncate the stem so the final filename stays within the 255-byte
        # POSIX limit even after the compliance suffix and _report.html
        # extension are appended. The worst-case appended string is
        # "_WGAC_2.1_AA_Compliant_report.html" (34 bytes), so we leave
        # 255 - 34 = 221 bytes of headroom for the stem.
        _MAX_STEM_BYTES = 221
        stem_bytes = stem.encode("utf-8")
        if len(stem_bytes) > _MAX_STEM_BYTES:
            # .decode(errors="ignore") drops any half-cut multibyte sequence
            # at the truncation boundary.
            stem = stem_bytes[:_MAX_STEM_BYTES].decode("utf-8", errors="ignore")
        if overall == "PASS":
            out_pdf_name = f"{stem}_WGAC_2.1_AA_Compliant.pdf"
            report_name = f"{stem}_WGAC_2.1_AA_Compliant_report.html"
        else:
            out_pdf_name = f"{stem}_WGAC_2.1_AA_PARTIAL.pdf"
            report_name = f"{stem}_WGAC_2.1_AA_PARTIAL_report.html"

        out_pdf_path = out_dir / out_pdf_name
        shutil.copy2(str(final_candidate), str(out_pdf_path))

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
        # Full traceback goes to the logger; the user-facing error list
        # gets a clean single-line message so no stack dump leaks to UI.
        logger.exception("pipeline catastrophic failure")
        result["errors"].append(f"pipeline: {type(e).__name__}: {e}")
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
