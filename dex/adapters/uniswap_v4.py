"""Uniswap V4 hooks registry and safety whitelist.

V4 pools have a ``hooks`` address that determines custom behavior.
An unknown hook can:
  - modify fee amounts after the swap
  - revert for non-whitelisted callers
  - perform token transfers in unexpected order (re-entrancy risk)

Policy
------
The bridge admits a V4 pool only when its ``hooks`` address is:
  1. Zero address (vanilla pool — no hooks), OR
  2. Present in ``_KNOWN_SAFE_HOOKS`` (audited, deterministic behavior).

Unknown hooks are quarantined with reason ``UNKNOWN_V4_HOOK`` and listed
in ``m8_pending_routes`` so they can be manually reviewed.

Adding a hook to the whitelist
-------------------------------
1. Verify the hook contract source on Basescan.
2. Confirm it does NOT modify amounts (only adds fees in a fixed ratio) OR
   that it is a well-known permissionless hook from Uniswap Foundation.
3. Add to ``_KNOWN_SAFE_HOOKS`` and document the hook type below.
4. Add a test in ``tests/unit/test_v4_hooks_whitelist.py``.

Quoting infrastructure
-----------------------
V4 quoting is implemented inline in ``m8_1/stable_anchor/quote_probe.py``
(``_encode_v4_call`` / ``_decode_v4_response``) rather than as a
traditional adapter class because V4 uses a singleton PoolManager
rather than per-pool contracts.

This module provides only the hooks-policy layer.
"""
from __future__ import annotations

from typing import Optional

# ---------------------------------------------------------------------------
# Zero address constant (vanilla pool = no hooks)
# ---------------------------------------------------------------------------
_V4_ZERO_HOOKS: str = "0x" + "0" * 40

# ---------------------------------------------------------------------------
# Known safe hooks on Base mainnet (address → hook_type label)
# ---------------------------------------------------------------------------
# Rules for inclusion:
#   - Source verified on Basescan (etherscan.io/address/<addr>)
#   - Does NOT conditionally revert for arbitrary callers
#   - Does NOT charge variable/unknown fees beyond pool fee
#   - Behaviour is deterministic and amount-preserving
#   - getHookPermissions().afterSwapReturnDelta == False
#   - getHookPermissions().beforeSwapReturnDelta == False
#
# Leave empty until specific hooks are audited. The empty whitelist
# maintains current bridge behavior (only zero-address admitted).
_KNOWN_HOOK_TYPES: dict[str, str] = {
    # Example (currently commented — add only after on-chain verification):
    # "0x000000000019d2ee56f594feef0abe7e1f3f45fe": "uniswap_protocol_fee_hook",
}

# ---------------------------------------------------------------------------
# Known UNSAFE hooks (verified on-chain — DO NOT WHITELIST)
# ---------------------------------------------------------------------------
# These addresses have been audited and confirmed to modify swap amounts via
# afterSwapReturnDelta or beforeSwapReturnDelta hook permissions.
# Quoting them with a standard V4 Quoter produces incorrect output amounts.
#
# Audit date: 2026-05-26 | Basescan source verification | Base mainnet
# ---------------------------------------------------------------------------
_KNOWN_UNSAFE_HOOKS: dict[str, str] = {
    # DopplerHookInitializer — Doppler/Airlock token launchpad bonding curve
    # Basescan: https://basescan.org/address/0xbdf938149ac6a781f94faa0ed45e6a0e984c6544#code
    # afterSwapReturnDelta=True, updateDynamicLPFee(), collectFees() — modifies amounts
    # Pool count (Base, 2026-05-26): ~131 pools
    "0xbdf938149ac6a781f94faa0ed45e6a0e984c6544": "doppler_hook_initializer",
    # ZoraV4CoinHook — Zora creator coin launchpad with creator rewards
    # Basescan: https://basescan.org/address/0x0469a4bd3724dc86c9542f4694c976da13c450c0#code
    # afterSwapReturnDelta=True, beforeSwapReturnDelta=True — steals delta for creator fees
    # Pool count (Base, 2026-05-26): ~95 pools
    "0x0469a4bd3724dc86c9542f4694c976da13c450c0": "zora_v4_coin_hook",
    # PositionManager (Flaunch) — memecoin fair launch with fee distribution hooks
    # Basescan: https://basescan.org/address/0x23321f11a6d44fd1ab790044fdfde5758c902fdc#code
    # afterSwapReturnDelta=True, beforeSwapReturnDelta=True — modifies amounts for fee splits
    # Pool count (Base, 2026-05-26): ~70 pools
    "0x23321f11a6d44fd1ab790044fdfde5758c902fdc": "flaunch_position_manager",
}

# Lowercase set for O(1) lookup
_KNOWN_SAFE_HOOKS: frozenset[str] = frozenset(
    addr.lower() for addr in _KNOWN_HOOK_TYPES
)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def is_safe_v4_hook(hooks: Optional[str]) -> bool:
    """Return True when a V4 pool's hooks address is safe to quote.

    A hook is safe when it is:
    - None or empty string (treat as zero address)
    - The zero address (no hooks)
    - Present in the audited ``_KNOWN_SAFE_HOOKS`` whitelist

    Parameters
    ----------
    hooks:
        The ``hooks`` address from the V4 PoolInitialized event, or None.
    """
    if not hooks:
        return True  # None / "" → treat as zero address
    h = hooks.lower()
    return h == _V4_ZERO_HOOKS.lower() or h in _KNOWN_SAFE_HOOKS


def quarantine_reason_for_hook(hooks: Optional[str]) -> Optional[str]:
    """Return the quarantine reason for an unsafe hook, or None if safe.

    Parameters
    ----------
    hooks:
        The ``hooks`` address from the V4 PoolInitialized event, or None.
    """
    if is_safe_v4_hook(hooks):
        return None
    return "UNKNOWN_V4_HOOK"


def hook_type_label(hooks: Optional[str]) -> str:
    """Return the human-readable label for a known hook, or 'zero_hooks' / 'unknown_hook'."""
    if not hooks or hooks.lower() == _V4_ZERO_HOOKS.lower():
        return "zero_hooks"
    label = _KNOWN_HOOK_TYPES.get(hooks.lower())
    if label:
        return label
    return "unknown_hook"
