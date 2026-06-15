"""Universal cycle quote sanity gates (leg continuity, stable peg ratios)."""
from __future__ import annotations

from typing import List, Optional, Tuple

from m8_1.stable_anchor.quote_probe import QuoteResult
from m9.graph_arb.models import GraphCycle, GraphEdge

STABLE_PEG_SYMBOLS = frozenset(
    {"USDC", "USDT", "DAI", "USDbC", "USDBC", "EURC", "crvUSD", "FRAX", "LUSD"}
)

# Pegged stables should not deviate more than this factor in a single hop.
STABLE_VALUE_RATIO_MIN = 0.5
STABLE_VALUE_RATIO_MAX = 2.0

# Skip stable-peg ratio gate below this normalized token_in (micro-probe rounding).
MIN_STABLE_SANITY_NORM_IN_USD = 1.0

REJECT_AMOUNT_CONTINUITY_VIOLATION = "AMOUNT_CONTINUITY_VIOLATION"
REJECT_STABLE_VALUE_RATIO_OUTLIER = "STABLE_VALUE_RATIO_OUTLIER"


def is_stable_peg_symbol(sym: str) -> bool:
    return (sym or "").strip().upper() in STABLE_PEG_SYMBOLS


def leg_norm_value_ratio(edge: GraphEdge, leg: QuoteResult) -> Optional[float]:
    """Normalized out/in for one leg when both amounts are present."""
    raw_in = getattr(leg, "amount_in", None)
    raw_out = getattr(leg, "amount_out", None)
    if raw_in is None or raw_out is None or int(raw_in) <= 0 or int(raw_out) <= 0:
        return None
    dec_in = edge.token_in_decimals
    dec_out = edge.token_out_decimals
    if dec_in is None or dec_out is None:
        return None
    norm_in = int(raw_in) / (10 ** int(dec_in))
    norm_out = int(raw_out) / (10 ** int(dec_out))
    if norm_in <= 0:
        return None
    return norm_out / norm_in


def leg_norm_amount_in(edge: GraphEdge, leg: QuoteResult) -> Optional[float]:
    """Human-readable token_in amount for one leg (None when unknown)."""
    raw_in = getattr(leg, "amount_in", None)
    if raw_in is None or int(raw_in) <= 0:
        return None
    dec_in = edge.token_in_decimals
    if dec_in is None:
        return None
    return int(raw_in) / (10 ** int(dec_in))


def stable_value_ratio_outlier(edge: GraphEdge, leg: QuoteResult) -> bool:
    ratio = leg_norm_value_ratio(edge, leg)
    if ratio is None:
        return False
    if not (is_stable_peg_symbol(edge.token_in_sym) and is_stable_peg_symbol(edge.token_out_sym)):
        return False
    norm_in = leg_norm_amount_in(edge, leg)
    if norm_in is not None and norm_in < MIN_STABLE_SANITY_NORM_IN_USD:
        return False
    return ratio < STABLE_VALUE_RATIO_MIN or ratio > STABLE_VALUE_RATIO_MAX


def check_cycle_leg_sanity(
    cycle: GraphCycle,
    leg_results: List[QuoteResult],
) -> Optional[str]:
    """Return reject reason when continuity or stable-ratio sanity fails."""
    prev_out: Optional[int] = None
    for i, edge in enumerate(cycle.edges):
        if i >= len(leg_results):
            break
        leg = leg_results[i]
        if not leg.ok:
            continue
        raw_in = getattr(leg, "amount_in", None)
        if i > 0 and prev_out is not None and raw_in is not None:
            if int(raw_in) != int(prev_out):
                return REJECT_AMOUNT_CONTINUITY_VIOLATION
        if stable_value_ratio_outlier(edge, leg):
            return REJECT_STABLE_VALUE_RATIO_OUTLIER
        raw_out = getattr(leg, "amount_out", None)
        if raw_out is not None:
            prev_out = int(raw_out)
    return None


def leg_continuity_pairs(
    cycle: GraphCycle,
    leg_results: List[QuoteResult],
) -> List[Tuple[int, bool, Optional[int], Optional[int]]]:
    """(leg_index, ok, prev_out, current_in) for RCA telemetry."""
    rows: List[Tuple[int, bool, Optional[int], Optional[int]]] = []
    prev_out: Optional[int] = None
    for i, edge in enumerate(cycle.edges):
        if i >= len(leg_results):
            break
        leg = leg_results[i]
        raw_in = getattr(leg, "amount_in", None)
        ok = (
            i == 0
            or prev_out is None
            or raw_in is None
            or int(raw_in) == int(prev_out)
        )
        rows.append((i, ok, prev_out, int(raw_in) if raw_in is not None else None))
        if leg.ok and getattr(leg, "amount_out", None) is not None:
            prev_out = int(leg.amount_out)
    return rows
