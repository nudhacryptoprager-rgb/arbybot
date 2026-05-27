"""Unit tests for V4 hooks whitelist policy (dex/adapters/uniswap_v4.py).

Verifies:
  - is_safe_v4_hook(None) == True  (no hooks)
  - is_safe_v4_hook("") == True  (empty string)
  - is_safe_v4_hook(ZERO_ADDRESS) == True  (zero address)
  - is_safe_v4_hook("0xabc...") == False for unknown address
  - quarantine_reason_for_hook() returns a non-empty string for unknown hooks
  - quarantine_reason_for_hook() returns None for safe hooks
  - hook_type_label() returns a string for any input
"""
from __future__ import annotations

import pytest

from dex.adapters.uniswap_v4 import (
    is_safe_v4_hook,
    quarantine_reason_for_hook,
    hook_type_label,
    _KNOWN_SAFE_HOOKS,
)

ZERO_ADDRESS = "0x" + "0" * 40
UNKNOWN_HOOK = "0xDeadBeefDeadBeefDeadBeefDeadBeefDeadBeef"


class TestIsSafeV4Hook:
    """is_safe_v4_hook() must allow None/empty/zero and block unknowns."""

    def test_none_is_safe(self):
        assert is_safe_v4_hook(None) is True

    def test_empty_string_is_safe(self):
        assert is_safe_v4_hook("") is True

    def test_zero_address_is_safe(self):
        assert is_safe_v4_hook(ZERO_ADDRESS) is True

    def test_zero_address_checksummed_is_safe(self):
        assert is_safe_v4_hook("0x0000000000000000000000000000000000000000") is True

    def test_unknown_hook_is_not_safe(self):
        assert is_safe_v4_hook(UNKNOWN_HOOK) is False

    def test_unknown_lowercase_is_not_safe(self):
        assert is_safe_v4_hook(UNKNOWN_HOOK.lower()) is False

    def test_random_hex_is_not_safe(self):
        addr = "0x" + "ab" * 20
        assert is_safe_v4_hook(addr) is False


class TestQuarantineReasonForHook:
    """quarantine_reason_for_hook() must return None for safe hooks, string for unsafe."""

    def test_none_hook_returns_none(self):
        assert quarantine_reason_for_hook(None) is None

    def test_zero_address_returns_none(self):
        assert quarantine_reason_for_hook(ZERO_ADDRESS) is None

    def test_empty_string_returns_none(self):
        assert quarantine_reason_for_hook("") is None

    def test_unknown_hook_returns_reason_string(self):
        reason = quarantine_reason_for_hook(UNKNOWN_HOOK)
        assert reason is not None
        assert isinstance(reason, str)
        assert len(reason) > 0

    def test_quarantine_reason_contains_useful_info(self):
        """The reason string should contain something meaningful."""
        reason = quarantine_reason_for_hook(UNKNOWN_HOOK)
        assert reason is not None
        # Should mention "hook" or "HOOK" or "unknown" etc.
        assert any(kw in reason.upper() for kw in ("HOOK", "UNKNOWN", "UNSAFE", "V4")), (
            f"Quarantine reason does not mention hooks: {reason!r}"
        )


class TestHookTypeLabel:
    """hook_type_label() should always return a non-empty string."""

    def test_none_gives_string(self):
        label = hook_type_label(None)
        assert isinstance(label, str)

    def test_empty_gives_string(self):
        label = hook_type_label("")
        assert isinstance(label, str)

    def test_zero_address_gives_string(self):
        label = hook_type_label(ZERO_ADDRESS)
        assert isinstance(label, str)

    def test_unknown_hook_gives_string(self):
        label = hook_type_label(UNKNOWN_HOOK)
        assert isinstance(label, str)
        assert len(label) > 0


class TestKnownSafeHooksSet:
    """_KNOWN_SAFE_HOOKS is an audited whitelist; zero address is handled by is_safe_v4_hook separately."""

    def test_is_safe_hook_handles_zero_via_function(self):
        """Zero address is safe even if not in _KNOWN_SAFE_HOOKS (handled by explicit check)."""
        # The is_safe_v4_hook() function checks zero address separately from _KNOWN_SAFE_HOOKS
        assert is_safe_v4_hook(ZERO_ADDRESS) is True

    def test_known_safe_hooks_is_frozenset(self):
        assert isinstance(_KNOWN_SAFE_HOOKS, frozenset)
