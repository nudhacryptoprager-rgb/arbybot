"""Per-DEX sizing helpers."""
from __future__ import annotations

from m9.graph_arb.models import GraphEdge
from m9.graph_arb.per_dex_sizing import productive_cycle_size_usd_cap


def _edge(adapter: str, pool_char: str = "a") -> GraphEdge:
    pool = "0x" + pool_char * 40
    return GraphEdge(
        token_in_sym="A",
        token_out_sym="B",
        token_in_addr="0x" + "1" * 40,
        token_out_addr="0x" + "2" * 40,
        token_in_decimals=18,
        token_out_decimals=18,
        route_id=f"{adapter}:{pool}@0",
        dex_id=adapter,
        adapter_type=adapter,
        fee=0,
        tick_spacing=None,
        quoter_addr=pool,
        pool_address=pool,
        fee_bps=1.0,
        factory_class="EFFICIENT_BASELINE",
        pair_id="A_B",
    )


def test_productive_cycle_size_usd_cap_distinct_without_depth():
    class _Cycle:
        min_effective_depth_usd = None
        edges = (_edge("maverick_v2"), _edge("uniswap_v3", "b"))

    assert productive_cycle_size_usd_cap(_Cycle(), 1.0, {}) == 0.05


def test_productive_cycle_size_usd_cap_no_micro_when_measured_depth():
    class _Cycle:
        min_effective_depth_usd = 5000.0
        edges = (_edge("maverick_v2"), _edge("uniswap_v3", "b"))

    assert productive_cycle_size_usd_cap(_Cycle(), 50.0, {}) == 50.0


def test_productive_cycle_size_usd_floor_for_sane_measured_depth():
    class _Edge:
        def __init__(self, adapter: str, pool_char: str, depth: float) -> None:
            base = _edge(adapter, pool_char)
            self.dex_id = base.dex_id
            self.adapter_type = base.adapter_type
            self.effective_depth_usd = depth
            self.depth_probe_status = "MEASURED_CAPACITY"

    class _Cycle:
        min_effective_depth_usd = 5000.0
        edges = (_Edge("maverick_v2", "a", 5000.0), _Edge("uniswap_v3", "b", 8000.0))

    assert productive_cycle_size_usd_cap(_Cycle(), 1.0, {}) == 25.0
