"""Canonical mirror anchor policy: generic stable/WETH plus launchpad-specific anchors."""
from __future__ import annotations

from typing import FrozenSet

GENERIC_ANCHOR_SYMS: FrozenSet[str] = frozenset(
    {"USDC", "EURC", "WETH", "WETH_BASE", "cbBTC", "DAI", "USDT", "USDbC"}
)
LAUNCHPAD_ANCHOR_SYMS: FrozenSet[str] = frozenset({"VIRTUAL"})
ALL_MIRROR_ANCHOR_SYMS: FrozenSet[str] = GENERIC_ANCHOR_SYMS | LAUNCHPAD_ANCHOR_SYMS

# On-chain factory scan uses generic + launchpad anchors when enabled.
P0_FACTORY_ANCHOR_SYMS: tuple[str, ...] = (
    "USDC",
    "WETH",
    "cbBTC",
    "EURC",
    "USDbC",
    "DAI",
    "VIRTUAL",
)


def approved_anchor_syms(*, launchpad_lane: bool = True) -> FrozenSet[str]:
    if launchpad_lane:
        return ALL_MIRROR_ANCHOR_SYMS
    return GENERIC_ANCHOR_SYMS


def is_approved_anchor_symbol(sym: str, *, launchpad_lane: bool = True) -> bool:
    return str(sym or "").upper() in approved_anchor_syms(launchpad_lane=launchpad_lane)
