"""Per-adapter cost and pricing-model taxonomy for M9 graph-arb cycles.

The runtime needs two distinct groupings:

* adapter family: operational grouping used for dashboards and readiness
* pricing model: curve topology used for strategy coverage analysis

The second grouping is what lets M9 verify that it is expanding beyond
CPMM/CLMM into Solidly stable curves, Curve StableSwap, PMM, RFQ, directional
liquidity, and hook-driven pools.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Per-adapter cost in basis points for one leg.  Cycle cost is the sum over
# every leg, not the set of unique adapters in the cycle.
_ADAPTER_COST_BPS: Dict[str, float] = {
    # Standard AMMs
    "uniswap_v2": 12.0,
    "sushiswap_v2": 12.0,
    "baseswap_v2": 12.0,
    "uniswap_v3": 8.0,
    "pancakeswap_v3": 8.0,
    "sushiswap_v3": 8.0,
    "uniswap_v4": 10.0,
    "uniswap_v4_nohook": 10.0,
    "uniswap_v4_hook": 14.0,
    "uniswap_v4_with_hooks": 14.0,
    # Solidly ve(3,3)
    "ve33": 12.0,
    "ve33_volatile": 12.0,
    "solidly_volatile": 12.0,
    "ve33_stable": 4.0,
    "solidly_stable": 4.0,
    "aerodrome_stable": 4.0,
    "aerodrome_v2_stable": 4.0,
    # Concentrated-liquidity forks
    "aerodrome_slipstream": 9.0,
    "algebra": 9.0,
    "iziswap": 9.0,
    "syncswap": 10.0,
    "ambient": 10.0,
    # Orthogonal pricing models from CURRENT_STRATEGY.md
    "curve_stable": 3.0,
    "curve_stableswap": 3.0,
    "curve_cryptoswap": 7.0,
    "maverick_v2": 9.0,
    "balancer_weighted": 10.0,
    "balancer_stable": 4.0,
    "balancer_vault": 7.0,
    "dodo_pmm": 6.0,
    "dodo_pmm_v2": 6.0,
    "rfq": 2.0,
    "hashflow_rfq": 2.0,
    "bebop_rfq": 2.0,
    "native_rfq": 2.0,
    "fluid": 8.0,
}

_DEFAULT_COST_BPS: float = 11.0


def adapter_cost_bps(adapter_type: str) -> float:
    """Return the estimated one-way leg cost in bps for an adapter type."""
    return _ADAPTER_COST_BPS.get(adapter_type, _DEFAULT_COST_BPS)


def cycle_cost_bps(adapter_types: List[str]) -> float:
    """Return the total estimated cost of a cycle, summed per leg."""
    return sum(adapter_cost_bps(a) for a in adapter_types)


def cycle_net_bps(gross_bps: float, adapter_types: List[str]) -> float:
    """Return gross spread minus per-leg cycle cost."""
    return gross_bps - cycle_cost_bps(adapter_types)


def adapter_family(adapter_type: str) -> str:
    """Return a coarse operational adapter family."""
    _map: Dict[str, str] = {
        "uniswap_v2": "uniswap_v2",
        "sushiswap_v2": "uniswap_v2",
        "baseswap_v2": "uniswap_v2",
        "uniswap_v3": "uniswap_v3",
        "sushiswap_v3": "uniswap_v3",
        "pancakeswap_v3": "uniswap_v3",
        "aerodrome_slipstream": "uniswap_v3",
        "algebra": "uniswap_v3",
        "iziswap": "uniswap_v3",
        "syncswap": "uniswap_v3",
        "ambient": "uniswap_v3",
        "uniswap_v4": "uniswap_v4",
        "uniswap_v4_nohook": "uniswap_v4",
        "uniswap_v4_hook": "uniswap_v4",
        "uniswap_v4_with_hooks": "uniswap_v4",
        "ve33": "solidly_volatile",
        "ve33_volatile": "solidly_volatile",
        "solidly_volatile": "solidly_volatile",
        "ve33_stable": "solidly_stable",
        "solidly_stable": "solidly_stable",
        "aerodrome_stable": "solidly_stable",
        "aerodrome_v2_stable": "solidly_stable",
        "curve_stable": "curve",
        "curve_stableswap": "curve",
        "curve_cryptoswap": "curve",
        "balancer_weighted": "balancer",
        "balancer_stable": "balancer",
        "balancer_vault": "balancer",
        "maverick_v2": "maverick",
        "dodo_pmm": "dodo_pmm",
        "dodo_pmm_v2": "dodo_pmm",
        "rfq": "rfq",
        "hashflow_rfq": "rfq",
        "bebop_rfq": "rfq",
        "native_rfq": "rfq",
        "fluid": "other",
    }
    return _map.get(adapter_type, "other")


def adapter_pricing_model(adapter_type: str) -> str:
    """Return the pricing topology used by an adapter type.

    This is intentionally separate from ``adapter_family``.  Two adapters can
    belong to different brands/families while sharing the same curve, and the
    strategy needs explicit visibility into orthogonal pricing models.
    """
    _map: Dict[str, str] = {
        "uniswap_v2": "cpmm_xyk",
        "sushiswap_v2": "cpmm_xyk",
        "baseswap_v2": "cpmm_xyk",
        "uniswap_v3": "clmm_ticks",
        "sushiswap_v3": "clmm_ticks",
        "pancakeswap_v3": "clmm_ticks",
        "aerodrome_slipstream": "clmm_ticks",
        "algebra": "clmm_dynamic_fee",
        "iziswap": "clmm_ticks",
        "syncswap": "hybrid_pool",
        "ambient": "ambient_concentrated",
        "uniswap_v4": "v4_nohook_clmm",
        "uniswap_v4_nohook": "v4_nohook_clmm",
        "uniswap_v4_hook": "v4_hook_dynamic_fee",
        "uniswap_v4_with_hooks": "v4_hook_dynamic_fee",
        "ve33": "solidly_volatile_xyk",
        "ve33_volatile": "solidly_volatile_xyk",
        "solidly_volatile": "solidly_volatile_xyk",
        "ve33_stable": "solidly_stable_curve",
        "solidly_stable": "solidly_stable_curve",
        "aerodrome_stable": "solidly_stable_curve",
        "aerodrome_v2_stable": "solidly_stable_curve",
        "curve_stable": "curve_stableswap",
        "curve_stableswap": "curve_stableswap",
        "curve_cryptoswap": "curve_cryptoswap",
        "balancer_weighted": "balancer_weighted",
        "balancer_stable": "balancer_stable",
        "balancer_vault": "balancer_vault_mixed",
        "maverick_v2": "maverick_directional",
        "dodo_pmm": "pmm_oracle",
        "dodo_pmm_v2": "pmm_oracle",
        "rfq": "rfq_offchain",
        "hashflow_rfq": "rfq_offchain",
        "bebop_rfq": "rfq_offchain",
        "native_rfq": "rfq_offchain",
        "fluid": "lending_amm_hybrid",
    }
    return _map.get(adapter_type, "unknown")


def build_cost_breakdown(
    cycle_results: "List",
    adapter_type_getter: "Optional[callable]" = None,
) -> Dict[str, Any]:
    """Build cost and topology breakdowns for artifact output.

    Accepts production ``CycleQuoteResult`` objects and plain dicts with:
    ``{"gross_spread_bps": float, "legs": [{"adapter_type": str}, ...]}``.
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
    cycles_by_pricing_model: Dict[str, int] = defaultdict(int)
    positive_by_pricing_model: Dict[str, int] = defaultdict(int)

    for qr in cycle_results:
        gross = _gross_bps_from_qr(qr)
        edges = _edges_from_qr(qr)
        adapters_by_leg = [_get_adapter_from_edge(e) for e in edges]
        if not adapters_by_leg:
            adapters_by_leg = ["other"]

        adapters_in_cycle = list(dict.fromkeys(adapters_by_leg))
        families_in_cycle = list(dict.fromkeys(adapter_family(a) for a in adapters_in_cycle))
        pricing_models_in_cycle = list(
            dict.fromkeys(adapter_pricing_model(a) for a in adapters_in_cycle)
        )

        net_bps = cycle_net_bps(gross, adapters_by_leg)

        for fam in families_in_cycle:
            cycles_by_family[fam] += 1
            if net_bps > 0:
                positive_by_family[fam] += 1
        for model in pricing_models_in_cycle:
            cycles_by_pricing_model[model] += 1
            if net_bps > 0:
                positive_by_pricing_model[model] += 1

        for a_type in adapters_in_cycle:
            if a_type not in cost_breakdown:
                cost_breakdown[a_type] = {
                    "cost_bps_per_leg": adapter_cost_bps(a_type),
                    "pricing_model": adapter_pricing_model(a_type),
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
        "cycles_by_pricing_model": dict(cycles_by_pricing_model),
        "positive_cycles_by_pricing_model": dict(positive_by_pricing_model),
    }
