"""Post-quote guards for stable-stable and anchor-priced leg economics."""
from __future__ import annotations

from typing import Optional

from m9.graph_arb.cycle_sanity import (
    STABLE_VALUE_RATIO_MAX,
    STABLE_VALUE_RATIO_MIN,
    is_stable_peg_symbol,
    leg_norm_amount_in,
    leg_norm_value_ratio,
    stable_value_ratio_outlier,
)
from m9.graph_arb.models import GraphEdge
from m8_1.stable_anchor.quote_probe import QuoteResult

REJECT_TOXIC_STABLE_POOL = "TOXIC_STABLE_POOL"

ANCHOR_PEG_SYMBOLS = frozenset(
    {"WETH", "USDC", "USDT", "DAI", "USDbC", "USDBC", "cbETH", "cbBTC", "WETH_BASE"}
)
ANCHOR_VALUE_RATIO_WARN_MIN = 0.2
ANCHOR_VALUE_RATIO_WARN_MAX = 5.0


def reject_toxic_stable_quote(
    *,
    amount_in: int,
    amount_out: int,
    token_in_decimals: Optional[int],
    token_out_decimals: Optional[int],
    token_in_sym: str,
    token_out_sym: str,
    min_norm_in_usd: float = 1.0,
) -> Optional[str]:
    """Return TOXIC_STABLE_POOL when a stable-stable hop has an implausible peg ratio."""
    if amount_in <= 0 or amount_out <= 0:
        return None
    if token_in_decimals is None or token_out_decimals is None:
        return None
    if not (
        is_stable_peg_symbol(token_in_sym) and is_stable_peg_symbol(token_out_sym)
    ):
        return None
    norm_in = amount_in / (10 ** int(token_in_decimals))
    if norm_in < min_norm_in_usd:
        return None
    norm_out = amount_out / (10 ** int(token_out_decimals))
    if norm_in <= 0:
        return None
    ratio = norm_out / norm_in
    if ratio < STABLE_VALUE_RATIO_MIN or ratio > STABLE_VALUE_RATIO_MAX:
        return REJECT_TOXIC_STABLE_POOL
    return None


def anchor_value_ratio_warning(edge: GraphEdge, leg: QuoteResult) -> bool:
    """True when an anchor-priced leg has a suspicious (non-stable) value ratio."""
    sym_in = (edge.token_in_sym or "").strip().upper()
    sym_out = (edge.token_out_sym or "").strip().upper()
    if sym_in in {"USDC", "USDT", "USDbC", "USDBC", "DAI"} and sym_out in {
        "USDC",
        "USDT",
        "USDbC",
        "USDBC",
        "DAI",
    }:
        return False
    if not (
        sym_in in ANCHOR_PEG_SYMBOLS or sym_out in ANCHOR_PEG_SYMBOLS
    ):
        return False
    ratio = leg_norm_value_ratio(edge, leg)
    if ratio is None:
        return False
    norm_in = leg_norm_amount_in(edge, leg)
    if norm_in is not None and norm_in < 1.0:
        return False
    return ratio < ANCHOR_VALUE_RATIO_WARN_MIN or ratio > ANCHOR_VALUE_RATIO_WARN_MAX


def stable_value_ratio_outlier_for_leg(edge: GraphEdge, leg: QuoteResult) -> bool:
    """Reuse cycle sanity stable peg gate for RCA telemetry."""
    return stable_value_ratio_outlier(edge, leg)
