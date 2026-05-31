"""Unit tests for depth-aware sizing (package #2).

Covers:
  - TestCapSizesToDepth: pure ladder-clamping helper
  - TestCycleMinDepth: GraphCycle.min_effective_depth_usd property
  - TestDynamicDepthAware: quote_cycle_dynamic_sync clamps the ladder by depth
"""
from __future__ import annotations

from m9.graph_arb.models import GraphCycle, GraphEdge
from m9.graph_arb import quoter
from m9.graph_arb.quoter import cap_sizes_to_depth, quote_cycle_dynamic_sync

_QUOTER = "0x" + "1" * 40
_ADDR_A = "0x" + "a" * 40
_ADDR_B = "0x" + "b" * 40
_ADDR_C = "0x" + "c" * 40
_POOL1 = "0x" + "d1" * 20
_POOL2 = "0x" + "d2" * 20
_POOL3 = "0x" + "d3" * 20


def _edge(sym_in, addr_in, sym_out, addr_out, pool, depth=None) -> GraphEdge:
    return GraphEdge(
        token_in_sym=sym_in, token_out_sym=sym_out,
        token_in_addr=addr_in, token_out_addr=addr_out,
        token_in_decimals=18, token_out_decimals=18,
        route_id=f"{sym_in}_{sym_out}_{pool[-4:]}",
        dex_id="uniswap_v3", adapter_type="uniswap_v3",
        fee=500, tick_spacing=10,
        quoter_addr=_QUOTER, pool_address=pool,
        fee_bps=5.0, factory_class="UNKNOWN",
        pair_id=f"{sym_in}_{sym_out}",
        effective_depth_usd=depth,
    )


def _cycle(d1=None, d2=None, d3=None) -> GraphCycle:
    return GraphCycle(edges=(
        _edge("A", _ADDR_A, "B", _ADDR_B, _POOL1, depth=d1),
        _edge("B", _ADDR_B, "C", _ADDR_C, _POOL2, depth=d2),
        _edge("C", _ADDR_C, "A", _ADDR_A, _POOL3, depth=d3),
    ))


# ---------------------------------------------------------------------------
# TestCapSizesToDepth
# ---------------------------------------------------------------------------
class TestCapSizesToDepth:
    def test_none_depth_unchanged(self):
        sizes = (50.0, 100.0, 500.0)
        assert cap_sizes_to_depth(sizes, None) == sizes

    def test_zero_depth_unchanged(self):
        sizes = (50.0, 100.0)
        assert cap_sizes_to_depth(sizes, 0.0) == sizes

    def test_clamps_above_cap(self):
        sizes = (50.0, 100.0, 500.0, 1000.0)
        # fraction 1.0, depth 200 → keep <=200
        assert cap_sizes_to_depth(sizes, 200.0, 1.0) == (50.0, 100.0)

    def test_fraction_applied(self):
        sizes = (50.0, 100.0, 500.0)
        # depth 200, fraction 0.5 → cap 100 → keep <=100
        assert cap_sizes_to_depth(sizes, 200.0, 0.5) == (50.0, 100.0)

    def test_all_above_cap_keeps_smallest(self):
        sizes = (100.0, 500.0, 1000.0)
        # depth 20, fraction 1.0 → cap 20, all exceed → keep smallest
        assert cap_sizes_to_depth(sizes, 20.0, 1.0) == (100.0,)

    def test_all_within_cap_unchanged(self):
        sizes = (10.0, 20.0)
        assert cap_sizes_to_depth(sizes, 1000.0, 1.0) == (10.0, 20.0)


# ---------------------------------------------------------------------------
# TestCycleMinDepth
# ---------------------------------------------------------------------------
class TestCycleMinDepth:
    def test_none_when_no_depth(self):
        assert _cycle().min_effective_depth_usd is None

    def test_min_over_edges(self):
        assert _cycle(d1=500.0, d2=120.0, d3=900.0).min_effective_depth_usd == 120.0

    def test_ignores_none_edges(self):
        # only one edge has depth → that value is the min
        assert _cycle(d1=None, d2=75.0, d3=None).min_effective_depth_usd == 75.0


# ---------------------------------------------------------------------------
# TestDynamicDepthAware
# ---------------------------------------------------------------------------
class TestDynamicDepthAware:
    def _patch_quote(self, monkeypatch):
        """Stub quote_cycle_sync: gross_bps grows with size so 'best' = largest size
        that survives the ladder. Returns the list of sizes actually quoted."""
        quoted_sizes = []

        def _fake(cycle_arg, size_usd, *_a, **_k):
            quoted_sizes.append(size_usd)
            from m9.graph_arb.models import CycleQuoteResult
            return CycleQuoteResult(
                cycle=cycle_arg, size_usd=size_usd,
                amount_in=int(size_usd), amount_out=int(size_usd * 1.01),
                gross_bps=100.0, status="POSITIVE_GROSS", reject_reason=None,
                leg_results=[], elapsed_s=0.01,
            )

        monkeypatch.setattr(quoter, "quote_cycle_sync", _fake)
        return quoted_sizes

    def test_ladder_clamped_by_depth(self, monkeypatch):
        quoted = self._patch_quote(monkeypatch)
        cyc = _cycle(d1=500.0, d2=150.0, d3=800.0)  # bottleneck 150
        res = quote_cycle_dynamic_sync(
            cyc, (50.0, 100.0, 500.0, 1000.0), w3=None,
        )
        # Only sizes <= 150 quoted
        assert quoted == [50.0, 100.0]
        assert res.depth_capped is True
        assert res.cycle_min_depth_usd == 150.0

    def test_no_depth_uses_full_ladder(self, monkeypatch):
        quoted = self._patch_quote(monkeypatch)
        cyc = _cycle()  # no depth
        res = quote_cycle_dynamic_sync(
            cyc, (50.0, 100.0, 500.0), w3=None,
        )
        assert quoted == [50.0, 100.0, 500.0]
        assert res.depth_capped is False
        assert res.cycle_min_depth_usd is None

    def test_depth_aware_disabled(self, monkeypatch):
        quoted = self._patch_quote(monkeypatch)
        cyc = _cycle(d1=150.0, d2=150.0, d3=150.0)
        res = quote_cycle_dynamic_sync(
            cyc, (50.0, 100.0, 500.0), w3=None, depth_aware=False,
        )
        assert quoted == [50.0, 100.0, 500.0]
        assert res.depth_capped is False
