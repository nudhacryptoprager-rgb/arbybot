"""Depth-first economics gate: skip cycle HTTP when min size exceeds pool depth."""
from __future__ import annotations

from typing import Any, List, Sequence, Tuple

from m9.graph_arb.models import CycleQuoteResult, GraphCycle

MIN_ECONOMICS_SIZE_USD = 0.25
STATUS_DEPTH_BELOW_LIVENESS = "DEPTH_BELOW_LIVENESS_FLOOR"
REJECT_DEPTH_BELOW_LIVENESS = "DEPTH_BELOW_LIVENESS_FLOOR"


def min_quote_size_usd(sizes_usd: Sequence[float]) -> float:
    vals = [float(s) for s in sizes_usd if float(s) > 0]
    return min(vals) if vals else MIN_ECONOMICS_SIZE_USD


def cycle_fails_depth_first_gate(cycle: GraphCycle, min_size_usd: float) -> bool:
    """True when measured bottleneck depth cannot support the liveness floor."""
    depth = getattr(cycle, "min_effective_depth_usd", None)
    if depth is None:
        return False
    try:
        return float(depth) < float(min_size_usd)
    except (TypeError, ValueError):
        return False


def synthetic_depth_gate_result(
    cycle: GraphCycle,
    *,
    size_usd: float,
    min_size_usd: float,
) -> CycleQuoteResult:
    depth = getattr(cycle, "min_effective_depth_usd", None)
    return CycleQuoteResult(
        cycle=cycle,
        size_usd=float(size_usd),
        amount_in=0,
        amount_out=0,
        gross_bps=0.0,
        status=STATUS_DEPTH_BELOW_LIVENESS,
        reject_reason=REJECT_DEPTH_BELOW_LIVENESS,
        leg_results=[],
        elapsed_s=0.0,
        cycle_min_depth_usd=depth,
    )


def apply_depth_first_gate(
    cycles: List[GraphCycle],
    sizes_usd: Sequence[float],
) -> Tuple[List[GraphCycle], List[CycleQuoteResult]]:
    """Partition cycles: quoteable batch vs depth-gated synthetic rejects."""
    floor = min_quote_size_usd(sizes_usd)
    quote_batch: List[GraphCycle] = []
    skipped: List[CycleQuoteResult] = []
    for cycle in cycles:
        if cycle_fails_depth_first_gate(cycle, floor):
            skipped.append(
                synthetic_depth_gate_result(
                    cycle, size_usd=floor, min_size_usd=floor
                )
            )
        else:
            quote_batch.append(cycle)
    return quote_batch, skipped
