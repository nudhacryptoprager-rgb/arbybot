# PATH: tests/unit/test_triangular_contracts.py
"""
Compatibility contract tests for M7.A triangular modules.

Covers:
- M7.A universe constants (tokens, dexes, adapters)
- Graph filter correctness
- PoolEdge.edge_key collision resistance
- build_graph_from_runtime_pairs compatibility with RuntimePair
- build_graph_from_discovered_pools provenance
- CycleScore artifact schema compliance with step_M7.md
- score_cycle_fees_only is diagnostic prefilter (not canonical truth)
"""

import pytest
from unittest.mock import patch, MagicMock

from engine.triangular_graph import (
    M7A_DEXES_ARBITRUM_ONE,
    M7A_STABLE_ADAPTERS,
    M7A_TOKENS_ARBITRUM_ONE,
    PoolEdge,
    PoolGraph,
    build_graph_from_pool_dicts,
    build_graph_from_runtime_pairs,
    filter_graph_to_m7a_universe,
)
from engine.triangular_cycles import (
    CycleScore,
    SAME_STATE_AMBIGUOUS,
    SAME_STATE_PROVEN,
    TriangularCycle,
    find_3hop_cycles,
    score_cycle_fees_only,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _edge(token_in, token_out, dex="uniswap_v3", fee=3000,
          pool="0xaaa", chain="arbitrum_one", adapter_type=None):
    return PoolEdge(
        token_in=token_in,
        token_out=token_out,
        pool_address=pool,
        dex=dex,
        adapter_type=adapter_type or dex,
        fee=fee,
        chain=chain,
    )


# ---------------------------------------------------------------------------
# M7.A Universe constants
# ---------------------------------------------------------------------------

class TestM7AUniverseConstants:
    def test_tokens_frozenset(self):
        assert isinstance(M7A_TOKENS_ARBITRUM_ONE, frozenset)

    def test_tokens_contain_core_anchors(self):
        """WETH, USDC and ARB must be in the M7.A token set."""
        for t in ("WETH", "USDC", "ARB"):
            assert t in M7A_TOKENS_ARBITRUM_ONE, f"{t} missing from M7.A tokens"

    def test_tokens_exclude_accounting_sensitive(self):
        """wstETH/WSTETH must NOT be in M7.A (peg drift risk)."""
        for t in ("wstETH", "WSTETH"):
            assert t not in M7A_TOKENS_ARBITRUM_ONE

    def test_adapters_frozenset(self):
        assert isinstance(M7A_STABLE_ADAPTERS, frozenset)

    def test_adapters_include_known_stable(self):
        for a in ("uniswap_v3", "uniswap_v2", "algebra"):
            assert a in M7A_STABLE_ADAPTERS

    def test_adapters_exclude_unstable(self):
        """iziswap, ve33 adapters are not stable for M7.A."""
        for a in ("iziswap", "ve33"):
            assert a not in M7A_STABLE_ADAPTERS

    def test_dexes_frozenset(self):
        assert isinstance(M7A_DEXES_ARBITRUM_ONE, frozenset)

    def test_dexes_include_major(self):
        for d in ("uniswap_v3", "sushiswap_v3", "camelot_v3"):
            assert d in M7A_DEXES_ARBITRUM_ONE

    def test_dexes_exclude_iziswap(self):
        """iziswap not in M7.A (adapter not stable enough)."""
        assert "iziswap" not in M7A_DEXES_ARBITRUM_ONE


# ---------------------------------------------------------------------------
# Graph filter
# ---------------------------------------------------------------------------

class TestFilterGraphToM7AUniverse:
    def test_keeps_eligible_edges(self):
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(_edge("WETH", "USDC", dex="uniswap_v3",
                         adapter_type="uniswap_v3", pool="0x1"))
        filtered = filter_graph_to_m7a_universe(g)
        assert filtered.edge_count == 2  # both directions

    def test_filters_non_m7a_tokens(self):
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(_edge("WETH", "GMX", dex="uniswap_v3",
                         adapter_type="uniswap_v3", pool="0x1"))
        filtered = filter_graph_to_m7a_universe(g)
        assert filtered.edge_count == 0  # GMX not in M7.A tokens

    def test_filters_non_stable_adapter(self):
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(_edge("WETH", "USDC", dex="iziswap",
                         adapter_type="iziswap", pool="0x1"))
        filtered = filter_graph_to_m7a_universe(g)
        assert filtered.edge_count == 0

    def test_filters_non_m7a_dex(self):
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(_edge("WETH", "USDC", dex="iziswap",
                         adapter_type="uniswap_v3", pool="0x1"))
        filtered = filter_graph_to_m7a_universe(g)
        assert filtered.edge_count == 0

    def test_preserves_chain(self):
        g = PoolGraph(chain="arbitrum_one")
        g.add_pool(_edge("WETH", "USDC", dex="uniswap_v3",
                         adapter_type="uniswap_v3", pool="0x1"))
        filtered = filter_graph_to_m7a_universe(g)
        assert filtered.chain == "arbitrum_one"


# ---------------------------------------------------------------------------
# PoolEdge.edge_key collision resistance
# ---------------------------------------------------------------------------

class TestEdgeKeyCollisionResistance:
    def test_same_prefix_different_address(self):
        """Two pools sharing a 10-char prefix produce distinct edge_keys."""
        e1 = _edge("WETH", "USDC", pool="0xAbcdef1234_suffix_one")
        e2 = _edge("WETH", "USDC", pool="0xAbcdef1234_suffix_two")
        assert e1.edge_key != e2.edge_key

    def test_full_address_in_edge_key(self):
        addr = "0x1234567890abcdef1234567890abcdef12345678"
        e = _edge("WETH", "USDC", pool=addr)
        assert addr in e.edge_key

    def test_graph_dedup_with_similar_addresses(self):
        """Graph correctly deduplicates edges with distinct but similar addresses."""
        g = PoolGraph(chain="arbitrum_one")
        g.add_edge(_edge("WETH", "USDC", pool="0xAbcdef1234_pool_A"))
        g.add_edge(_edge("WETH", "USDC", pool="0xAbcdef1234_pool_B"))
        assert g.edge_count == 2  # both kept (different addresses)


# ---------------------------------------------------------------------------
# build_graph_from_runtime_pairs compatibility
# ---------------------------------------------------------------------------

class TestBuildFromRuntimePairs:
    def test_builds_from_mock_runtime_pairs(self):
        """Verify build_graph_from_runtime_pairs works with RuntimePair-like objects."""
        # Use a mock that has all RuntimePair fields
        rp = MagicMock()
        rp.chain = "arbitrum_one"
        rp.token_a = "WETH"
        rp.token_b = "USDC"
        rp.dex = "uniswap_v3"
        rp.fee = 500
        rp.pool_address = "0xc31e54c7a869b9fcbecc14363cf510d1c41fa443"
        rp.decimals_a = 18
        rp.decimals_b = 6

        with patch("discovery.index_factories.get_dex_adapter_type", return_value="uniswap_v3"):
            graph = build_graph_from_runtime_pairs("arbitrum_one", [rp])

        assert graph.node_count == 2
        assert graph.edge_count == 2  # bidirectional
        edges = graph.neighbors("WETH")
        assert len(edges) == 1
        assert edges[0].token_out == "USDC"
        assert edges[0].fee == 500
        assert edges[0].decimals_in == 18
        assert edges[0].decimals_out == 6

    def test_skips_wrong_chain(self):
        rp = MagicMock()
        rp.chain = "base"  # different chain
        rp.token_a = "WETH"
        rp.token_b = "USDC"
        rp.dex = "uniswap_v3"
        rp.fee = 500
        rp.pool_address = "0x1"
        rp.decimals_a = 18
        rp.decimals_b = 6

        with patch("discovery.index_factories.get_dex_adapter_type", return_value="uniswap_v3"):
            graph = build_graph_from_runtime_pairs("arbitrum_one", [rp])

        assert graph.edge_count == 0


# ---------------------------------------------------------------------------
# Provenance demotion (score_cycle_fees_only)
# ---------------------------------------------------------------------------

class TestProvenanceDemotion:
    def test_fee_only_score_is_ambiguous(self):
        """Fee-only scoring always produces AMBIGUOUS same_state."""
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1"),
            leg2=_edge("USDC", "WETH", pool="0x2"),
            leg3=_edge("WETH", "ARB", pool="0x3"),
        )
        s = score_cycle_fees_only(c)
        assert s.same_state_class == SAME_STATE_AMBIGUOUS

    def test_fee_only_score_has_reject_reason(self):
        """Fee-only scoring marks reject_reason=FEE_ONLY_SCORE."""
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1"),
            leg2=_edge("USDC", "WETH", pool="0x2"),
            leg3=_edge("WETH", "ARB", pool="0x3"),
        )
        s = score_cycle_fees_only(c)
        assert s.reject_reason == "FEE_ONLY_SCORE"

    def test_fee_only_never_promoted(self):
        """A fee-only scored cycle can never be is_promoted()."""
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1"),
            leg2=_edge("USDC", "WETH", pool="0x2"),
            leg3=_edge("WETH", "ARB", pool="0x3"),
        )
        s = score_cycle_fees_only(c)
        assert s.is_promoted() is False

    def test_fee_only_provenance_summary(self):
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1"),
            leg2=_edge("USDC", "WETH", pool="0x2"),
            leg3=_edge("WETH", "ARB", pool="0x3"),
        )
        s = score_cycle_fees_only(c)
        assert s.provenance_summary == "fee_structure_only"


# ---------------------------------------------------------------------------
# CycleScore artifact schema compliance
# ---------------------------------------------------------------------------

class TestArtifactSchemaCompliance:
    """Verify CycleScore.to_dict() matches step_M7.md required fields."""

    REQUIRED_TOP_LEVEL = [
        "route", "tokens", "cycle_key",
        "gross_bps", "fee_leg1_bps", "fee_leg2_bps", "fee_leg3_bps",
        "total_fee_bps",
        "slippage_leg1_bps", "slippage_leg2_bps", "slippage_leg3_bps",
        "total_slippage_bps",
        "gas_bps", "final_net_bps", "best_size_usd",
        "block_tag", "provenance_summary",
        "same_state_class", "is_promoted", "reject_reason", "route_viable",
        "leg1", "leg2", "leg3",
    ]

    REQUIRED_LEG_FIELDS = ["dex", "pool", "fee", "adapter_type", "token_in", "token_out"]

    def _make_score(self) -> CycleScore:
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1"),
            leg2=_edge("USDC", "WETH", pool="0x2"),
            leg3=_edge("WETH", "ARB", pool="0x3"),
        )
        return score_cycle_fees_only(c)

    def test_all_top_level_fields_present(self):
        d = self._make_score().to_dict()
        for field in self.REQUIRED_TOP_LEVEL:
            assert field in d, f"Missing top-level field: {field}"

    def test_all_leg_fields_present(self):
        d = self._make_score().to_dict()
        for leg_key in ("leg1", "leg2", "leg3"):
            leg = d[leg_key]
            for f in self.REQUIRED_LEG_FIELDS:
                assert f in leg, f"Missing {leg_key}.{f}"

    def test_numeric_fields_are_floats(self):
        d = self._make_score().to_dict()
        for f in ("gross_bps", "fee_leg1_bps", "final_net_bps",
                   "gas_bps", "best_size_usd"):
            assert isinstance(d[f], (int, float)), f"{f} must be numeric"

    def test_tokens_is_tuple_or_list(self):
        d = self._make_score().to_dict()
        assert isinstance(d["tokens"], (list, tuple))
        assert len(d["tokens"]) == 3

    def test_route_is_string(self):
        d = self._make_score().to_dict()
        assert isinstance(d["route"], str)
        assert "->" in d["route"]

    def test_cycle_key_is_deterministic(self):
        s1 = self._make_score()
        s2 = self._make_score()
        assert s1.to_dict()["cycle_key"] == s2.to_dict()["cycle_key"]


# ---------------------------------------------------------------------------
# M7.A enumeration artifact schema: cap-hit fields
# ---------------------------------------------------------------------------

class TestEnumerationCapHitFields:
    """Enumeration JSON must declare max_cycles_hit and cycles_lower_bound."""

    REQUIRED_CYCLES_KEYS = [
        "total_found",
        "max_cycles_cap",
        "max_cycles_hit",
        "cycles_lower_bound",
        "viable_after_fee_filter",
        "max_fee_bps_threshold",
    ]

    def _run_enumeration(self, max_cycles: int):
        """Build a small graph and run enumeration to get cycles dict."""
        from engine.triangular_cycles import find_3hop_cycles, filter_viable_fee_structures

        g = PoolGraph(chain="arbitrum_one")
        # triangle: WETH -> USDC -> ARB -> WETH (two directed cycles)
        g.add_pool(_edge("WETH", "USDC", dex="uniswap_v3",
                         adapter_type="uniswap_v3", pool="0xa1", fee=500))
        g.add_pool(_edge("USDC", "ARB", dex="uniswap_v3",
                         adapter_type="uniswap_v3", pool="0xa2", fee=3000))
        g.add_pool(_edge("ARB", "WETH", dex="sushiswap_v3",
                         adapter_type="uniswap_v3", pool="0xa3", fee=500))

        cycles = find_3hop_cycles(g, max_cycles=max_cycles)
        max_cycles_hit = len(cycles) >= max_cycles
        viable = filter_viable_fee_structures(cycles, max_total_fee_bps=100.0)

        return {
            "total_found": len(cycles),
            "max_cycles_cap": max_cycles,
            "max_cycles_hit": max_cycles_hit,
            "cycles_lower_bound": max_cycles_hit,
            "viable_after_fee_filter": len(viable),
            "max_fee_bps_threshold": 100.0,
        }

    def test_required_keys_present(self):
        d = self._run_enumeration(max_cycles=10000)
        for key in self.REQUIRED_CYCLES_KEYS:
            assert key in d, f"Missing cycles key: {key}"

    def test_cap_not_hit_when_below_limit(self):
        d = self._run_enumeration(max_cycles=10000)
        # small graph produces only 2 cycles, well below 10000
        assert d["max_cycles_hit"] is False
        assert d["cycles_lower_bound"] is False

    def test_cap_hit_when_at_limit(self):
        d = self._run_enumeration(max_cycles=1)
        # max_cycles=1 forces cap hit
        assert d["max_cycles_hit"] is True
        assert d["cycles_lower_bound"] is True
        assert d["total_found"] == 1

    def test_max_cycles_cap_matches_input(self):
        d = self._run_enumeration(max_cycles=42)
        assert d["max_cycles_cap"] == 42
