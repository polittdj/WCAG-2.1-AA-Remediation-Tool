"""src.audit — PDF accessibility audit modules.

Re-exports the primary audit API from the root-level wcag_auditor module.
"""
from wcag_auditor import audit_pdf  # noqa: F401

__all__ = ["audit_pdf"]
