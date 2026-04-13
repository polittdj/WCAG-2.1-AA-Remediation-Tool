"""src.constants — Shared constants for the WCAG remediation tool.

Re-exports key constants from pipeline.py so they can also be imported
from a stable src.constants path.
"""
from pipeline import CRITICAL_CHECKPOINTS, _NA_ACCEPTABLE  # noqa: F401

__all__ = ["CRITICAL_CHECKPOINTS", "_NA_ACCEPTABLE"]
