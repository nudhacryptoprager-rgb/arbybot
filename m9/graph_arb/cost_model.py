"""Per-adapter cost model for M9 graph-arb cycles.

Provides a flat cost_bps estimate per adapter family.
Replaces the previous hard-coded 11 bps constant in artifacts.py.

Usage
-----
    from m9.graph_arb.cost_model import adapter_cost_bps, cycle_cost_bps

    # Single-edge cost
    cost = adapter_cost_bps("uniswap_v3")          # → 8.0

    # Full-cycle cost (sum of edge costs)
    total = cycle_cost_bps(["uniswap_v3", "ve33_stable"])  # → 12.0

Design notes
------------
Values are *minimum expected round-trip costs in basis points* assuming:
- Trade size $100–$500 USD (gas dominates for smaller sizes)
- No fallback router; direct pool interaction
- Base L2 gas price ≈ 0.01–0.05 gwei (static cost)
- Slippage = worst-case 50th percentile for the adapter type

These estimates are intentionally *conservative* so that only
cycles with room above the cost bar are flagged as profitable.
Tune values via `config/cost_model.yaml` override (optional future work).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# ---------------------------------------------------------------------------
# Per-adapter cost in basis points (one-way leg cost)
# ---------------------------------------------------------------------------
# The cost for a full arbitrage cycle = sum over all legs.
# For a 3-leg cycle through CLMM→stable→CLMM: 8 + 4 + 8 = 20 bps total cost.
# Positive gross must exceed this for a net-positive trade.
_ADAPTER_COST_BPS: Dict[str, float] = {
    # Standard AMMs
    "uniswap_v2": 12.0,           # 30 bps swap fee dominates; deep but legacy
    "uniswap_v3": 8.0,            # 5–30 bps tier; gas modest; good liquidity
    "uniswap_v4": 10.0,           # no-hook v4; slightly more gas than v3 (singleton overhead)
    "uniswap_v4_nohook": 10.0,    # alias for explicitness in config
    "uniswap_v4_hook": 14.0,      # unknown hook may alter fee/logic; guard upward
    # Solidly ve(3,3) family
    "ve33": 12.0,                  # volatile solidly; treated same as V2 for now
    "ve33_volatile": 12.0,         # explicit volatile alias
    "ve33_stable": 4.0,            # stable x³y+xy³=k; very low slippage near peg
    "aerodrome_v2_stable": 4.0,    # same invariant via bridge_builder dex_id
    # Concentrated-liquidity forks
    "aerodrome_slipstream": 9.0,   # CL tick-based; slightly cheaper than V3 due to low tiers
    "pancakeswap_v3": 8.0,         # V3 fork; same math
    "sushiswap_v3": 8.0,
    "sushiswap_v2": 12.0,
    "baseswap_v2": 12.0,
    "algebra": 9.0,                # dynamic fee Algebra; estimate mid-range
    "iziswap": 9.0,                # CL-based on zkSync/Linea
    "syncswap": 10.0,
    "ambient": 10.0,
    # New adapters (P1–P2)
    "curve_stable": 3.0,           # StableSwap hybrid invariant; minimal slippage on pegs
    "curve_cryptoswap": 7.0,       # CryptoSwap (volatile-asset Curve); higher slippage
    "maverick_v2": 9.0,            # Directional liquidity; mid-range estimate
    "balancer_weighted": 10.0,     # 80/20 or 60/40 weighted pools
    "balancer_stable": 4.0,        # ComposableStable / BoostedPool
    "balancer_vault": 7.0,         # generic Balancer queryBatchSwap (mixed pool types)
    "dodo_pmm": 6.0,               # Oracle PMM; low slippage near oracle price
    "rfq": 2.0,                    # Hashflow / Bebop; off-chain quote, on-chain settle
    "fluid": 8.0,                  # Lending-AMM hybrid
}

# Default when adapter_type is unknown
_DEFAULT_COST_BPS: float = 11.0


def adapter_cost_bps(adapter_type: str) -> float:
    """Return the estimated one-way leg cost in bps for a given adapter type.

    Falls back to ``_DEFAULT_COST_BPS`` for unrecognised adapters so existing
    cycles never lose their cost estimate.
    """
    return _ADAPTER_COST_BPS.get(adapter_type, _DEFAULT_COST_BPS)


def cycle_cost_bps(adapter_types: List[str]) -> float:
    """Return the total estimated cost of a cycle (sum of per-leg costs).

    Parameters
    ----------
    adapter_types:
        Ordered list of adapter_type strings for each leg of the cycle.
    """
    return sum(adapter_cost_bps(a) for a in adapter_types)


def cycle_net_bps(gross_bps: float, adapter_types: List[str]) -> float:
    """Compute cost-adjusted net bps for a cycle.

    Returns ``gross_bps - cycle_cost_bps(adapter_types)``.
    """
    return gross_bps - cycle_cost_bps(adapter_types)


def adapter_family(adapter_type: str) -> str:
    """Return a coarse adapter family for grouping in artifact breakdowns.

    Families: uniswap_v2, uniswap_v3, uniswap_v4, solidly_stable,
              solidly_volatile, curve, balancer, maverick, dodo_pmm, rfq, other.
    """
    _map: Dict[str, str] = {
        "uniswap_v2": "uniswap_v2",
        "sushiswap_v2": "uniswap_v2",
        "baseswap_v2": "uniswap_v2",
        "uniswap_v3": "uniswap_v3",
        "sushiswap_v3": "uniswap_v3",
        "pancakeswap_v3": "uniswap_v3",
        "uniswap_v4": "uniswap_v4",
        "uniswap_v4_nohook": "uniswap_v4",
        "uniswap_v4_hook": "uniswap_v4",
        "ve33": "solidly_volatile",
        "ve33_volatile": "solidly_volatile",
        "ve33_stable": "solidly_stable",
        "aerodrome_v2_stable": "solidly_stable",
        "aerodrome_slipstream": "uniswap_v3",
        "algebra": "uniswap_v3",
        "iziswap": "uniswap_v3",
        "syncswap": "uniswap_v3",
        "ambient": "uniswap_v3",
        "curve_stable": "curve",
        "curve_cryptoswap": "curve",
        "balancer_weighted": "balancer",
        "balancer_stable": "balancer",
        "maverick_v2": "maverick",
        "dodo_pmm": "dodo_pmm",
        "rfq": "rfq",
        "fluid": "other",
    }
    return _map.get(adapter_type, "other")


def build_cost_breakdown(
    cycle_results: "List",
    adapter_type_getter: "Optional[callable]" = None,
) -> Dict[str, Any]:
    """Build `cost_breakdown_by_adapter`, `cycles_by_adapter_family`, and
    `positive_cycles_by_adapter_family` dicts for artifact output.

    Accepts both production CycleQuoteResult objects and plain dicts (for tests).

    Parameters
    ----------
    cycle_results:
        List of ``CycleQuoteResult`` objects **or** plain dicts with keys:
        ``{"gross_spread_bps": float, "legs": [{"adapter_type": str}, ...]}``.
    adapter_type_getter:
        Optional callable ``(edge) -> str`` to extract adapter_type from a
        cycle edge. Defaults to ``edge.adapter_type`` / ``edge.dex_id`` / ``edge["adapter_type"]``.
    """
    from collections import defaultdict

    def _get_adapter_from_edge(edge: Any) -> str:
        if adapter_type_getter:
            return adapter_type_getter(edge)
        if isinstance(edge, dict):
            return edge.get("adapter_type") or edge.get("dex_id") or "other"
        return getattr(edge, "adapter_type", None) or getattr(edge, "dex_id", "other")

    def _gross_bps_from_qr(qr: Any) -> float:
        if isinstance(qr, dict):
            return float(qr.get("gross_spread_bps", qr.get("gross_bps", 0.0)))
        return float(getattr(qr, "gross_bps", 0.0))

    def _edges_from_qr(qr: Any) -> list:
        if isinstance(qr, dict):
            return qr.get("legs", [])
        cycle = getattr(qr, "cycle", None)
        if cycle is None:
            return []
        return getattr(cycle, "edges", [])

    cost_breakdown: Dict[str, Dict[str, Any]] = {}
    cycles_by_family: Dict[str, int] = defaultdict(int)
    positive_by_family: Dict[str, int] = defaultdict(int)

    for qr in cycle_results:
        gross = _gross_bps_from_qr(qr)
        edges = _edges_from_qr(qr)
        # Collect unique adapter types in this cycle
        adapters_in_cycle = list(dict.fromkeys(_get_adapter_from_edge(e) for e in edges))
        if not adapters_in_cycle:
            adapters_in_cycle = ["other"]
        families_in_cycle = list(dict.fromkeys(adapter_family(a) for a in adapters_in_cycle))

        # net_bps = gross - sum(per-leg costs)
        net_bps = cycle_net_bps(gross, adapters_in_cycle)

        for fam in families_in_cycle:
            cycles_by_family[fam] += 1
            if net_bps > 0:
                positive_by_family[fam] += 1

        # Per-adapter cost contribution
        for a_type in adapters_in_cycle:
            if a_type not in cost_breakdown:
                cost_breakdown[a_type] = {
                    "cost_bps_per_leg": adapter_cost_bps(a_type),
                    "cycle_count": 0,
                    "positive_cycle_count": 0,
                }
            cost_breakdown[a_type]["cycle_count"] += 1
            if net_bps > 0:
                cost_breakdown[a_type]["positive_cycle_count"] += 1

    return {
        "cost_breakdown_by_adapter": cost_breakdown,
        "cycles_by_adapter_family": dict(cycles_by_family),
        "positive_cycles_by_adapter_family": dict(positive_by_family),
    }
