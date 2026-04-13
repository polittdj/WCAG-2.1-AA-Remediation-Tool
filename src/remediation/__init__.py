"""src.remediation — PDF accessibility fixer modules.

Each submodule wraps a root-level fix_*.py implementation.
The pipeline entry point is also exposed here.
"""
from pipeline import run_pipeline, compute_overall, CRITICAL_CHECKPOINTS, _NA_ACCEPTABLE  # noqa: F401

__all__ = ["run_pipeline", "compute_overall", "CRITICAL_CHECKPOINTS", "_NA_ACCEPTABLE"]
