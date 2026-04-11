"""summary_generator.py — Render batch summary reports.

Uses Jinja2 to render summary.html.j2 with aggregate results
across all processed files.
"""

from __future__ import annotations

import json
import pathlib
from typing import Any

from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = pathlib.Path(__file__).parent / "templates"


def generate_summary(
    *,
    file_results: list[dict[str, Any]],
    timestamp: str,
) -> str:
    """Render a batch summary report using Jinja2.

    Each item in file_results should have:
      filename, result, checkpoints, report_name (optional)

    Returns the complete HTML string.
    """
    env = Environment(
        loader=FileSystemLoader(str(_TEMPLATE_DIR)),
        autoescape=True,
    )
    template = env.get_template("summary.html.j2")

    files = []
    pass_count = 0
    partial_count = 0
    for fr in file_results:
        cps = fr.get("checkpoints", [])
        pc = sum(1 for c in cps if c.get("status") in ("PASS", "NOT_APPLICABLE"))
        fc = sum(1 for c in cps if c.get("status") == "FAIL")
        rc = sum(1 for c in cps if c.get("status") == "MANUAL_REVIEW")
        result = fr.get("result", "PARTIAL")
        if result == "PASS":
            pass_count += 1
        else:
            partial_count += 1
        files.append(
            {
                "filename": fr.get("filename", "unknown"),
                "result": result,
                "pass_count": pc,
                "fail_count": fc,
                "review_count": rc,
                "report_name": fr.get("report_name", ""),
            }
        )

    json_data = json.dumps(
        {
            "timestamp": timestamp,
            "total_files": len(files),
            "pass_count": pass_count,
            "partial_count": partial_count,
            "files": files,
        },
        indent=2,
        default=str,
    )

    return template.render(
        timestamp=timestamp,
        files=files,
        pass_count=pass_count,
        partial_count=partial_count,
        json_data=json_data,
    )
