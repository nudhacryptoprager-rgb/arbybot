"""M8 Phase 1 — Honeypot detector skeleton.

This module provides a stub honeypot filter for new-pool events.
Phase 1 implementation: always returns PASS.
Phase 2 will add on-chain simulation (simulate a small buy + sell).

Public API
----------
- ``HoneypotVerdict`` — enum: PASS | FAIL | UNKNOWN
- ``check_token_honeypot(token_addr, chain)`` — returns ``HoneypotVerdict``
- ``KNOWN_SCAM_TOKENS`` — frozenset of known-bad token addresses (lowercase)
- ``KNOWN_LEGIT_TOKENS`` — frozenset of known-good token addresses (lowercase)

Phase 1 behaviour
-----------------
- KNOWN_SCAM_TOKENS → FAIL immediately
- KNOWN_LEGIT_TOKENS → PASS immediately
- Everything else → UNKNOWN (treated as PASS in Phase 1 pipeline)

When to upgrade
---------------
Replace the UNKNOWN branch in ``check_token_honeypot`` with on-chain
simulation in Phase 2.  The public API (enum + function signature) must
remain stable.
"""
from __future__ import annotations

from enum import Enum
from typing import Optional

__all__ = [
    "HoneypotVerdict",
    "check_token_honeypot",
    "probe_transfer_tax_sell_side",
    "positive_gross_counts_as_evidence",
    "KNOWN_SCAM_TOKENS",
    "KNOWN_LEGIT_TOKENS",
]

# ---------------------------------------------------------------------------
# Verdict enum
# ---------------------------------------------------------------------------


class HoneypotVerdict(str, Enum):
    """Result of a honeypot check for a single token."""

    PASS = "PASS"       # token appears tradeable / legit
    FAIL = "FAIL"       # token is a known scam or failed simulation
    UNKNOWN = "UNKNOWN"  # not enough data to decide (Phase 1 default)


# ---------------------------------------------------------------------------
# Known-bad and known-good token fixtures
# ---------------------------------------------------------------------------

# Addresses must be lowercase (no checksum).  These are Base mainnet examples.
KNOWN_SCAM_TOKENS: frozenset = frozenset({
    # Protocol sentinel — burn address (not tradeable); see hardcode_audit_allowlist.
    "0x000000000000000000000000000000000000dead",
})


def _load_known_legit_tokens(chain: str = "base") -> frozenset:
    from core.token_identity import anchor_token_addresses

    return anchor_token_addresses(chain)


KNOWN_LEGIT_TOKENS: frozenset = _load_known_legit_tokens()

# ---------------------------------------------------------------------------
# Public check function
# ---------------------------------------------------------------------------


def check_token_honeypot(
    token_addr: str,
    chain: str = "base",  # noqa: ARG001 — reserved for Phase 2 chain routing
) -> HoneypotVerdict:
    """Return a ``HoneypotVerdict`` for *token_addr*.

    Phase 1 logic:
    1. If token is in ``KNOWN_SCAM_TOKENS``  → FAIL
    2. If token is in ``KNOWN_LEGIT_TOKENS`` → PASS
    3. Otherwise                              → UNKNOWN

    Phase 2 will replace step 3 with on-chain simulation.

    Parameters
    ----------
    token_addr:
        Token contract address (any case; normalised internally to lowercase).
    chain:
        Chain identifier — reserved for Phase 2 routing.  Ignored in Phase 1.

    Returns
    -------
    ``HoneypotVerdict``
    """
    addr = token_addr.lower().strip()
    if addr in KNOWN_SCAM_TOKENS:
        return HoneypotVerdict.FAIL
    if addr in KNOWN_LEGIT_TOKENS:
        return HoneypotVerdict.PASS
    return HoneypotVerdict.UNKNOWN


def probe_transfer_tax_sell_side(
    token_addr: str,
    chain: str = "base",  # noqa: ARG001
    *,
    rpc_url: Optional[str] = None,  # noqa: ARG001
) -> HoneypotVerdict:
    """Sell-side eth_call probe skeleton for transfer-tax / honeypot detection.

  Phase 3b: wire to a minimal router/static-quoter eth_call when RPC is available.
  Until then returns UNKNOWN (does not block pipeline; positive_gross evidence
  still requires PASS or UNKNOWN, never FAIL).
    """
    addr = token_addr.lower().strip()
    if addr in KNOWN_SCAM_TOKENS:
        return HoneypotVerdict.FAIL
    return HoneypotVerdict.UNKNOWN


def positive_gross_counts_as_evidence(
    token_addrs: list[str],
    chain: str = "base",
    *,
    strict: bool = False,
) -> bool:
    """Return True if gross_bps>0 may be counted as existence evidence.

    When *strict* is True (hot-path / profit stage), UNKNOWN honeypot/tax probe
    does not count as evidence — only explicit PASS.
    """
    for addr in token_addrs:
        if not addr:
            continue
        hp = check_token_honeypot(addr, chain)
        tax = probe_transfer_tax_sell_side(addr, chain)
        if hp == HoneypotVerdict.FAIL or tax == HoneypotVerdict.FAIL:
            return False
        if strict:
            if hp != HoneypotVerdict.PASS or tax != HoneypotVerdict.PASS:
                return False
    return True


def is_safe_for_pipeline(verdict: HoneypotVerdict) -> bool:
    """Return True if *verdict* should allow the event through the pipeline.

    Phase 1: PASS and UNKNOWN both allow through.
    Phase 2: only PASS will allow through.
    """
    return verdict in (HoneypotVerdict.PASS, HoneypotVerdict.UNKNOWN)
