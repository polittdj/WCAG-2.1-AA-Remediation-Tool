"""src.models — Shared data models for the WCAG remediation tool.

Defines TypedDict and dataclass types used across audit and remediation
modules to ensure consistent data contracts.
"""
from __future__ import annotations

from typing import Any, TypedDict


class CheckpointResult(TypedDict):
    """Single checkpoint result as returned by audit_pdf."""

    id: str
    description: str
    status: str  # PASS | FAIL | NOT_APPLICABLE | MANUAL_REVIEW | INDETERMINATE
    detail: str


class FixResult(TypedDict, total=False):
    """Standard return type for fix_*.py functions."""

    errors: list[str]
    changes: list[str]


class PipelineResult(TypedDict, total=False):
    """Result dict returned by run_pipeline."""

    output_pdf: str
    report_html: str
    zip_path: str
    result: str  # PASS | PARTIAL
    checkpoints: list[CheckpointResult]
    errors: list[str]
    ai_used: bool
    failed_steps: list[str]
