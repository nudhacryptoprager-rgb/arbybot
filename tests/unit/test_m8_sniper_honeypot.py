"""Unit tests for monitoring/sniper_honeypot.py — M8 Phase 1 honeypot skeleton.

Coverage:
  - KNOWN_SCAM_TOKENS → FAIL
  - KNOWN_LEGIT_TOKENS → PASS
  - Unknown address → UNKNOWN
  - Case-insensitive normalisation
  - is_safe_for_pipeline allows PASS and UNKNOWN, rejects FAIL
  - Fixtures: known_scam_returns_fail, known_legit_returns_pass
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from monitoring.sniper_honeypot import (
    KNOWN_LEGIT_TOKENS,
    KNOWN_SCAM_TOKENS,
    HoneypotVerdict,
    check_token_honeypot,
    is_safe_for_pipeline,
)


# ---------------------------------------------------------------------------
# Fixture constants
# ---------------------------------------------------------------------------

# Pick one from each fixture set for deterministic tests
_SCAM_ADDR = next(iter(KNOWN_SCAM_TOKENS))
_LEGIT_ADDR = next(iter(KNOWN_LEGIT_TOKENS))
_UNKNOWN_ADDR = "0xabcdef1234567890abcdef1234567890abcdef12"


# ---------------------------------------------------------------------------
# HoneypotVerdict enum contract
# ---------------------------------------------------------------------------

class TestHoneypotVerdictEnum:
    def test_has_pass_member(self):
        assert HoneypotVerdict.PASS == "PASS"

    def test_has_fail_member(self):
        assert HoneypotVerdict.FAIL == "FAIL"

    def test_has_unknown_member(self):
        assert HoneypotVerdict.UNKNOWN == "UNKNOWN"

    def test_verdicts_are_strings(self):
        for v in HoneypotVerdict:
            assert isinstance(v.value, str)


# ---------------------------------------------------------------------------
# Fixture: known scam returns FAIL
# ---------------------------------------------------------------------------

class TestKnownScamReturnsFail:
    def test_known_scam_address_returns_fail(self):
        result = check_token_honeypot(_SCAM_ADDR)
        assert result == HoneypotVerdict.FAIL, (
            f"Expected FAIL for known scam {_SCAM_ADDR!r}, got {result!r}"
        )

    def test_known_scam_uppercase_returns_fail(self):
        """Address normalisation: uppercase input should still return FAIL."""
        result = check_token_honeypot(_SCAM_ADDR.upper())
        assert result == HoneypotVerdict.FAIL

    def test_known_scam_mixed_case_returns_fail(self):
        mixed = _SCAM_ADDR[:10].upper() + _SCAM_ADDR[10:]
        result = check_token_honeypot(mixed)
        assert result == HoneypotVerdict.FAIL

    def test_all_scam_tokens_return_fail(self):
        for addr in KNOWN_SCAM_TOKENS:
            assert check_token_honeypot(addr) == HoneypotVerdict.FAIL, (
                f"Expected FAIL for {addr!r}"
            )


# ---------------------------------------------------------------------------
# Fixture: known legit returns PASS
# ---------------------------------------------------------------------------

class TestKnownLegitReturnsPass:
    def test_known_legit_address_returns_pass(self):
        result = check_token_honeypot(_LEGIT_ADDR)
        assert result == HoneypotVerdict.PASS, (
            f"Expected PASS for known legit {_LEGIT_ADDR!r}, got {result!r}"
        )

    def test_known_legit_uppercase_returns_pass(self):
        result = check_token_honeypot(_LEGIT_ADDR.upper())
        assert result == HoneypotVerdict.PASS

    def test_all_legit_tokens_return_pass(self):
        for addr in KNOWN_LEGIT_TOKENS:
            assert check_token_honeypot(addr) == HoneypotVerdict.PASS, (
                f"Expected PASS for {addr!r}"
            )


# ---------------------------------------------------------------------------
# Unknown addresses → UNKNOWN
# ---------------------------------------------------------------------------

class TestUnknownAddressReturnsUnknown:
    def test_random_address_returns_unknown(self):
        result = check_token_honeypot(_UNKNOWN_ADDR)
        assert result == HoneypotVerdict.UNKNOWN

    def test_zero_address_returns_unknown_or_fail(self):
        """Zero address is not in scam list — returns UNKNOWN."""
        zero = "0x0000000000000000000000000000000000000000"
        result = check_token_honeypot(zero)
        # May be UNKNOWN (not in fixtures) — either is acceptable
        assert result in (HoneypotVerdict.UNKNOWN, HoneypotVerdict.FAIL)


# ---------------------------------------------------------------------------
# is_safe_for_pipeline
# ---------------------------------------------------------------------------

class TestIsSafeForPipeline:
    def test_pass_is_safe(self):
        assert is_safe_for_pipeline(HoneypotVerdict.PASS) is True

    def test_unknown_is_safe_in_phase1(self):
        assert is_safe_for_pipeline(HoneypotVerdict.UNKNOWN) is True

    def test_fail_is_not_safe(self):
        assert is_safe_for_pipeline(HoneypotVerdict.FAIL) is False


# ---------------------------------------------------------------------------
# API stability
# ---------------------------------------------------------------------------

class TestPublicAPI:
    def test_check_token_honeypot_importable(self):
        from monitoring.sniper_honeypot import check_token_honeypot as fn
        assert callable(fn)

    def test_known_scam_tokens_is_frozenset(self):
        assert isinstance(KNOWN_SCAM_TOKENS, frozenset)

    def test_known_legit_tokens_is_frozenset(self):
        assert isinstance(KNOWN_LEGIT_TOKENS, frozenset)

    def test_scam_and_legit_dont_overlap(self):
        overlap = KNOWN_SCAM_TOKENS & KNOWN_LEGIT_TOKENS
        assert not overlap, f"Overlap between scam and legit: {overlap}"

    def test_check_accepts_chain_kwarg(self):
        """chain= kwarg must be accepted (Phase 2 routing)."""
        result = check_token_honeypot(_UNKNOWN_ADDR, chain="base")
        assert result in HoneypotVerdict.__members__.values()
