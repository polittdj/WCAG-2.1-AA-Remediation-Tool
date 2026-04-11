"""html_generator.py — Render per-file WCAG 2.1 AA compliance reports.

Uses Jinja2 to render report.html.j2 with full audit results,
remediation log, and file metadata.
"""

from __future__ import annotations

import json
import pathlib

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"

PRIVACY_TEXT = (
    "Your file was processed in memory and deleted immediately after "
    "your download was ready. No file content was stored, logged, or "
    "shared. All transfers were encrypted (HTTPS)."
)

PRIVACY_TEXT_AI = (
    "This file was processed locally, EXCEPT for the figure-alt-text "
    "step. With WCAG_ENABLE_AI_ALT_TEXT set, rendered images of "
    "every /Figure were sent to Anthropic's Claude Vision API for "
    "description."
)

MANUAL_REVIEW_ITEMS: list[str] = [
    "Alt text for images requires human verification",
    "Color contrast failures are reported but not auto-corrected",
    "Digital signatures are invalidated by remediation",
    "Reading order should be verified by a human reviewer",
    "Form label accuracy should be verified against visible text",
]


def generate_report(
    *,
    filename: str,
    title: str,
    timestamp: str,
    overall: str,
    checkpoints: list[dict],
    failed_steps: list[str] | None = None,
    auditor_error: str = "",
    ai_used: bool = False,
) -> str:
    """Render a per-file WCAG 2.1 AA compliance report using Jinja2.

    Returns the complete HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("report.html.j2")

    json_data = json.dumps(
        {
            "file": filename,
            "title": title,
            "timestamp": timestamp,
            "overall": overall,
            "checkpoints": checkpoints,
        },
        indent=2,
        default=str,
    )

    privacy_text = PRIVACY_TEXT_AI if ai_used else PRIVACY_TEXT

    return template.render(
        filename=filename,
        title=title,
        timestamp=timestamp,
        overall=overall,
        checkpoints=checkpoints,
        manual_items=MANUAL_REVIEW_ITEMS,
        failed_steps=failed_steps or [],
        auditor_error=auditor_error,
        ai_used=ai_used,
        privacy_text=privacy_text,
        json_data=json_data,
    )
