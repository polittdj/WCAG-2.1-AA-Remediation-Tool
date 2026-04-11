"""Acceptance tests for fix_figure_alt_text.py.

The Claude Vision call is mocked — we never hit the network from a
test. Coverage verifies:

 * Files with no /Figure elements are a no-op.
 * A /Figure that already has /Alt is left alone.
 * A /Figure without /Alt gets a placeholder when no API key and no
   fallback text is available, AND is listed in needs_manual_review.
 * A /Figure without /Alt gets the mocked Claude description when
   ANTHROPIC_API_KEY is set and the SDK is patched.
 * The label-cleaning text-fallback extracts strings from MCID BDC
   blocks correctly.
"""

from __future__ import annotations

import pathlib
import sys

import pikepdf
import pytest

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import fix_figure_alt_text  # noqa: E402
from fix_figure_alt_text import _extract_text_for_mcids  # noqa: E402
from fix_figure_alt_text import fix_figure_alt_text as fix_alt  # noqa: E402
from wcag_auditor import audit_pdf  # noqa: E402

TEST_SUITE = ROOT / "test_suite"
TRAVEL = TEST_SUITE / "CPSSPPC_TRAVEL_FORM_1.9_CGI - Politte - WCAG 2.1 AA Compliant.pdf"
GOOD = TEST_SUITE / "12.0_updated - WCAG 2.1 AA Compliant.pdf"


def _figure_alts(path: pathlib.Path) -> list[str]:
    out: list[str] = []
    with pikepdf.open(str(path)) as pdf:
        sr = pdf.Root.get("/StructTreeRoot")
        if sr is None:
            return out
        stack: list = []
        k = sr.get("/K")
        if isinstance(k, pikepdf.Array):
            stack.extend(list(k))
        elif isinstance(k, pikepdf.Dictionary):
            stack.append(k)
        seen: set = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            og = getattr(node, "objgen", None)
            if og in seen:
                continue
            if og:
                seen.add(og)
            if str(node.get("/S", "")) == "/Figure":
                out.append(str(node.get("/Alt", "") or ""))
            sub = node.get("/K")
            if sub is None:
                continue
            if isinstance(sub, pikepdf.Array):
                stack.extend(list(sub))
            elif isinstance(sub, pikepdf.Dictionary):
                stack.append(sub)
    return out


# ---------------------------------------------------------------------------
# Text extraction unit test
# ---------------------------------------------------------------------------


def test_extract_text_for_mcids_handles_tj_and_tj_array() -> None:
    data = b"/MCID 5 >>BDC\nBT\n(Hello ) Tj\n[(wor)-3 (ld)] TJ\nET\nEMC\n/MCID 7 >>BDC\nBT\n(Ignored) Tj\nET\nEMC\n"
    text = _extract_text_for_mcids(data, {5})
    assert text == "Hello world"


def test_extract_text_hex_4byte_utf16be() -> None:
    """<00480069> should decode as UTF-16BE 'Hi'."""
    data = b"/MCID 0 >> BDC\nBT <00480069> Tj ET\nEMC\n"
    text = _extract_text_for_mcids(data, {0})
    assert "Hi" in text, f"expected 'Hi' from 4-byte hex, got {text!r}"


def test_extract_text_hex_2byte_latin1() -> None:
    """<4142> should decode as latin-1 'AB', not UTF-16BE CJK."""
    data = b"/MCID 0 >> BDC\nBT <4142> Tj ET\nEMC\n"
    text = _extract_text_for_mcids(data, {0})
    assert "AB" in text, f"expected 'AB' from 2-byte hex, got {text!r}"


def test_extract_text_mixed_paren_and_hex() -> None:
    data = b"/MCID 0 >> BDC\nBT (Word1) Tj <00480069> Tj ET\nEMC\n"
    text = _extract_text_for_mcids(data, {0})
    assert "Word1" in text and "Hi" in text, f"expected both 'Word1' and 'Hi', got {text!r}"


# ---------------------------------------------------------------------------
# No-figure files are a clean no-op
# ---------------------------------------------------------------------------


def test_file_without_figures_is_noop(tmp_path: pathlib.Path) -> None:
    out = tmp_path / "out.pdf"
    res = fix_alt(str(GOOD), str(out))
    assert res["errors"] == []
    # GOOD doesn't happen to contain Figure structure elements, so
    # the counts should all be zero.
    assert res["figures_total"] == 0
    assert res["figures_filled_by_claude"] == 0
    assert res["needs_manual_review"] == []
    assert out.exists()


# ---------------------------------------------------------------------------
# Travel Form with no API key: placeholder + manual review
# ---------------------------------------------------------------------------


def test_travel_form_placeholder_without_api_key(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("WCAG_ENABLE_AI_ALT_TEXT", raising=False)
    out = tmp_path / "out.pdf"
    res = fix_alt(str(TRAVEL), str(out))
    assert res["errors"] == []
    # Travel Form has exactly one logo Figure.
    assert res["figures_total"] == 1
    assert res["figures_filled_by_claude"] == 0
    # Without AI, the figure is retagged as /Artifact and flagged for
    # manual review. No placeholder /Alt is written — screen readers
    # skip Artifacts, which is better than reading a fake description.
    assert res["figures_retagged_artifact"] == 1
    assert len(res["needs_manual_review"]) == 1
    # The /Figure element was retagged to /Artifact — no Figure should remain.
    alts = _figure_alts(out)
    assert alts == []


# ---------------------------------------------------------------------------
# Travel Form with mocked Claude: description written
# ---------------------------------------------------------------------------


def test_travel_form_uses_claude_when_opt_in_and_api_key_set(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("WCAG_ENABLE_AI_ALT_TEXT", "1")
    # Patch the internal vision call to return a known string so we
    # don't hit the network.
    monkeypatch.setattr(
        fix_figure_alt_text,
        "_claude_describe",
        lambda png, timeout_s=45.0: "Blue and red CGI company logo",
    )
    out = tmp_path / "out.pdf"
    res = fix_alt(str(TRAVEL), str(out))
    assert res["errors"] == []
    assert res["ai_opt_in"] is True
    assert res["ai_used"] is True
    assert res["figures_filled_by_claude"] == 1
    assert res["needs_manual_review"] == []
    alts = _figure_alts(out)
    assert alts == ["Blue and red CGI company logo"]
    # C-01 should now be a real PASS.
    report = audit_pdf(out)
    by_id = {c["id"]: c for c in report["checkpoints"]}
    assert by_id["C-01"]["status"] == "PASS"


def test_api_key_without_opt_in_does_not_call_claude(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Setting ANTHROPIC_API_KEY alone must NOT trigger an external call.
    The caller also has to set WCAG_ENABLE_AI_ALT_TEXT to consent to the
    outbound transfer."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.delenv("WCAG_ENABLE_AI_ALT_TEXT", raising=False)
    # If the gate is broken, the mock would be consulted; if it's working,
    # the mock should never fire. Raise loudly on an unexpected call.

    def _must_not_call(png: bytes, timeout_s: float = 45.0) -> str | None:
        raise AssertionError("_claude_describe was called without opt-in")

    monkeypatch.setattr(fix_figure_alt_text, "_claude_describe", _must_not_call)

    out = tmp_path / "out.pdf"
    res = fix_alt(str(TRAVEL), str(out))
    assert res["errors"] == []
    assert res["ai_opt_in"] is False
    assert res["ai_used"] is False
    assert res["figures_filled_by_claude"] == 0
    # Falls through to the placeholder path.
    assert len(res["needs_manual_review"]) == 1


# ---------------------------------------------------------------------------
# A Figure that already has /Alt is left alone
# ---------------------------------------------------------------------------


def test_existing_alt_not_overwritten(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    # Seed by running once with a mocked description.
    seeded = tmp_path / "seeded.pdf"
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("WCAG_ENABLE_AI_ALT_TEXT", "1")
    monkeypatch.setattr(
        fix_figure_alt_text,
        "_claude_describe",
        lambda png, timeout_s=45.0: "Seed alt text",
    )
    fix_alt(str(TRAVEL), str(seeded))

    # Re-run; the mock now returns a different string — but because
    # /Alt is already populated we should skip the call entirely.
    monkeypatch.setattr(
        fix_figure_alt_text,
        "_claude_describe",
        lambda png, timeout_s=45.0: "Different alt text",
    )
    second = tmp_path / "second.pdf"
    res = fix_alt(str(seeded), str(second))
    assert res["figures_already_had_alt"] == 1
    assert res["figures_filled_by_claude"] == 0
    alts = _figure_alts(second)
    assert alts == ["Seed alt text"]


# ---------------------------------------------------------------------------
# DECORATIVE sentinel → "Decorative graphic"
# ---------------------------------------------------------------------------


def test_decorative_sentinel_mapped(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("WCAG_ENABLE_AI_ALT_TEXT", "1")
    monkeypatch.setattr(
        fix_figure_alt_text,
        "_claude_describe",
        lambda png, timeout_s=45.0: "DECORATIVE",
    )
    out = tmp_path / "out.pdf"
    res = fix_alt(str(TRAVEL), str(out))
    assert res["figures_decorative"] == 1
    assert res["figures_filled_by_claude"] == 0
    # DECORATIVE response → Figure retagged as /Artifact, /Alt removed.
    # _figure_alts only looks for /Figure elements, so should be empty.
    alts = _figure_alts(out)
    assert alts == []
    # Verify the element was actually retagged.
    with pikepdf.open(str(out)) as pdf:
        sr = pdf.Root.get("/StructTreeRoot")
        found_artifact = False
        stack: list = []
        k = sr.get("/K")
        if isinstance(k, pikepdf.Array):
            stack.extend(list(k))
        elif isinstance(k, pikepdf.Dictionary):
            stack.append(k)
        seen: set = set()
        while stack:
            node = stack.pop()
            if not isinstance(node, pikepdf.Dictionary):
                continue
            og = getattr(node, "objgen", None)
            if og in seen:
                continue
            if og:
                seen.add(og)
            if str(node.get("/S", "")) == "/Artifact":
                found_artifact = True
                # Should have no /Alt
                assert node.get("/Alt") is None
                break
            sub = node.get("/K")
            if sub is None:
                continue
            if isinstance(sub, pikepdf.Array):
                stack.extend(list(sub))
            elif isinstance(sub, pikepdf.Dictionary):
                stack.append(sub)
    assert found_artifact, "Expected a retagged /Artifact element in the struct tree"
