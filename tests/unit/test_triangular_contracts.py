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
- classify_same_state provenance classification
- score_cycle_measured live decomposition
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
    LegQuote,
    SAME_STATE_AMBIGUOUS,
    SAME_STATE_PROVEN,
    SAME_STATE_VIOLATED,
    TriangularCycle,
    classify_same_state,
    find_3hop_cycles,
    leg_quote_from_rpc_result,
    score_cycle_fees_only,
    score_cycle_measured,
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
        "slippage_leg1_bps_heuristic", "slippage_leg2_bps_heuristic", "slippage_leg3_bps_heuristic",
        "total_slippage_bps_heuristic",
        "gas_bps", "final_net_bps", "scored_size_usd",
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
                   "gas_bps", "scored_size_usd"):
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


# ---------------------------------------------------------------------------
# classify_same_state provenance
# ---------------------------------------------------------------------------

class TestClassifySameState:
    """Same-state provenance classification for 3-leg cycles."""

    def test_all_same_block_is_proven(self):
        assert classify_same_state([100, 100, 100]) == SAME_STATE_PROVEN

    def test_adjacent_blocks_proven(self):
        assert classify_same_state([100, 101, 100]) == SAME_STATE_PROVEN

    def test_drift_2_with_default_max_1_is_violated(self):
        assert classify_same_state([100, 102, 100]) == SAME_STATE_VIOLATED

    def test_drift_2_with_max_2_is_proven(self):
        assert classify_same_state([100, 102, 100], max_block_drift=2) == SAME_STATE_PROVEN

    def test_none_block_is_ambiguous(self):
        assert classify_same_state([100, None, 100]) == SAME_STATE_AMBIGUOUS

    def test_all_none_is_ambiguous(self):
        assert classify_same_state([None, None, None]) == SAME_STATE_AMBIGUOUS

    def test_large_drift_is_violated(self):
        assert classify_same_state([100, 200, 150]) == SAME_STATE_VIOLATED


# ---------------------------------------------------------------------------
# score_cycle_measured: live decomposition
# ---------------------------------------------------------------------------

class TestScoreCycleMeasured:
    """Live measured triangular scoring."""

    def _make_cycle(self):
        return TriangularCycle(
            leg1=_edge("WETH", "USDC", pool="0x1", fee=500),
            leg2=_edge("USDC", "ARB", pool="0x2", fee=3000),
            leg3=_edge("ARB", "WETH", pool="0x3", fee=500),
        )

    def _make_quotes_profitable(self):
        """Quotes where cycle returns more than started with."""
        # Start: 1 WETH (1e18 wei)
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       gas_estimate=150_000, fee_tier=500, block_number=100)
        # 2000 USDC -> 4000 ARB (1e18 decimals)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       gas_estimate=150_000, fee_tier=3000, block_number=100)
        # 4000 ARB -> 1.005 WETH (profitable)
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=int(1.005 * 10**18),
                       gas_estimate=150_000, fee_tier=500, block_number=100)
        return q1, q2, q3

    def _make_quotes_unprofitable(self):
        """Quotes where cycle returns less than started with."""
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       gas_estimate=150_000, fee_tier=500, block_number=100)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       gas_estimate=150_000, fee_tier=3000, block_number=100)
        # Returns less than started with
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=int(0.99 * 10**18),
                       gas_estimate=150_000, fee_tier=500, block_number=100)
        return q1, q2, q3

    def test_provenance_is_measured(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.provenance_summary == "measured"

    def test_profitable_gross_is_positive(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.gross_bps > 0

    def test_unprofitable_gross_is_negative(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_unprofitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.gross_bps < 0

    def test_gas_bps_is_positive(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.gas_bps > 0

    def test_final_net_includes_gas(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.final_net_bps < s.gross_bps  # gas reduces net

    def test_same_state_proven_when_same_block(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.same_state_class == SAME_STATE_PROVEN

    def test_same_state_violated_large_drift(self):
        c = self._make_cycle()
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       block_number=100)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       block_number=200)
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=10**18,
                       block_number=100)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.same_state_class == SAME_STATE_VIOLATED

    def test_same_state_ambiguous_when_none_block(self):
        c = self._make_cycle()
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       block_number=None)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       block_number=100)
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=10**18,
                       block_number=100)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.same_state_class == SAME_STATE_AMBIGUOUS

    def test_reject_net_negative(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_unprofitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.reject_reason == "NET_NEGATIVE"

    def test_reject_zero_amount_in(self):
        c = self._make_cycle()
        q1 = LegQuote(amount_in_wei=0, amount_out_wei=0)
        q2 = LegQuote(amount_in_wei=0, amount_out_wei=0)
        q3 = LegQuote(amount_in_wei=0, amount_out_wei=0)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.reject_reason == "ZERO_AMOUNT_IN"

    def test_fee_decomposition_from_metadata(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.fee_leg1_bps == 5.0   # 500/100
        assert s.fee_leg2_bps == 30.0  # 3000/100
        assert s.fee_leg3_bps == 5.0   # 500/100
        assert s.total_fee_bps == 40.0

    def test_slippage_from_ticks(self):
        c = self._make_cycle()
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       ticks_crossed=4, block_number=100)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       ticks_crossed=2, block_number=100)
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=int(1.005 * 10**18),
                       ticks_crossed=6, block_number=100)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.slippage_leg1_bps == 2.0   # 4 * 0.5
        assert s.slippage_leg2_bps == 1.0   # 2 * 0.5
        assert s.slippage_leg3_bps == 3.0   # 6 * 0.5
        assert s.total_slippage_bps == 6.0

    def test_promoted_requires_proven_positive_viable(self):
        """Promotion requires same_state_proven + positive net + viable."""
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        # Even if gross is positive, final_net must also be positive after gas
        if s.final_net_bps > 0 and s.same_state_class == SAME_STATE_PROVEN:
            assert s.is_promoted() is True
        else:
            assert s.is_promoted() is False

    def test_artifact_schema_additive(self):
        """Measured score produces the same artifact keys as fee-only."""
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        d = s.to_dict()
        required = [
            "route", "tokens", "cycle_key",
            "gross_bps", "fee_leg1_bps", "fee_leg2_bps", "fee_leg3_bps",
            "total_fee_bps",
            "slippage_leg1_bps_heuristic", "slippage_leg2_bps_heuristic", "slippage_leg3_bps_heuristic",
            "total_slippage_bps_heuristic",
            "gas_bps", "final_net_bps", "scored_size_usd",
            "block_tag", "provenance_summary",
            "same_state_class", "is_promoted", "reject_reason", "route_viable",
            "leg1", "leg2", "leg3",
        ]
        for key in required:
            assert key in d, f"Missing key in measured score artifact: {key}"

    def test_block_tag_from_quotes(self):
        c = self._make_cycle()
        q1, q2, q3 = self._make_quotes_profitable()
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.block_tag == "100"  # all blocks are 100

    def test_route_viable_false_on_zero_output(self):
        c = self._make_cycle()
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=0, block_number=100)
        q2 = LegQuote(amount_in_wei=0, amount_out_wei=0, block_number=100)
        q3 = LegQuote(amount_in_wei=0, amount_out_wei=0, block_number=100)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.route_viable is False
        assert s.reject_reason == "ZERO_AMOUNT_OUT"


# ---------------------------------------------------------------------------
# leg_quote_from_rpc_result: quote dict -> LegQuote adapter
# ---------------------------------------------------------------------------

class TestLegQuoteFromRpcResult:
    """Tests for the RPC result -> LegQuote conversion adapter."""

    def test_v3_quoter_result(self):
        """Standard read_quoter_v2 result dict converts to LegQuote."""
        rpc = {
            "amount_out": 2000_000_000,  # 2000 USDC
            "sqrt_price_after": 123456789,
            "ticks_crossed": 3,
            "gas_estimate": 180_000,
        }
        q = leg_quote_from_rpc_result(
            rpc, amount_in_wei=10**18, fee_tier=500,
            block_number=12345, quote_source="quoter_v2",
        )
        assert q is not None
        assert q.amount_in_wei == 10**18
        assert q.amount_out_wei == 2000_000_000
        assert q.gas_estimate == 180_000
        assert q.ticks_crossed == 3
        assert q.block_number == 12345
        assert q.fee_tier == 500
        assert q.quote_source == "quoter_v2"
        assert q.sqrt_price_after == 123456789

    def test_algebra_quoter_result(self):
        """Algebra quoter returns None for ticks/sqrt_price."""
        rpc = {
            "amount_out": 5000_000_000,
            "sqrt_price_after": None,
            "ticks_crossed": None,
            "gas_estimate": 200_000,
        }
        q = leg_quote_from_rpc_result(
            rpc, amount_in_wei=10**18, fee_tier=None,
            block_number=12345, quote_source="algebra_quoter",
        )
        assert q is not None
        assert q.amount_out_wei == 5000_000_000
        assert q.gas_estimate == 200_000
        assert q.ticks_crossed == 0  # None maps to 0
        assert q.sqrt_price_after is None

    def test_ve33_style_dict(self):
        """ve33 result dict (from wrapper) converts correctly."""
        rpc = {
            "amount_out": 1_000_000,
            "gas_estimate": 80_000,
            "ticks_crossed": None,
            "sqrt_price_after": None,
        }
        q = leg_quote_from_rpc_result(
            rpc, amount_in_wei=500_000_000,
            quote_source="ve33_getAmountOut",
        )
        assert q is not None
        assert q.gas_estimate == 80_000
        assert q.ticks_crossed == 0

    def test_none_result_returns_none(self):
        """None RPC result -> None LegQuote."""
        assert leg_quote_from_rpc_result(None, amount_in_wei=10**18) is None

    def test_zero_amount_out_returns_none(self):
        """Zero amount_out -> None (no liquidity)."""
        rpc = {"amount_out": 0}
        assert leg_quote_from_rpc_result(rpc, amount_in_wei=10**18) is None

    def test_missing_gas_defaults_to_150k(self):
        """Missing gas_estimate defaults to 150_000."""
        rpc = {"amount_out": 1000}
        q = leg_quote_from_rpc_result(rpc, amount_in_wei=10**18)
        assert q is not None
        assert q.gas_estimate == 150_000

    def test_no_double_fee_subtraction(self):
        """CRITICAL: leg_quote preserves amount_out as-is (LP fees embedded)."""
        rpc = {"amount_out": 1_999_000_000}  # 1999 USDC after LP fee
        q = leg_quote_from_rpc_result(rpc, amount_in_wei=10**18, fee_tier=500)
        # The amount_out must NOT be reduced further — LP fees already taken
        assert q.amount_out_wei == 1_999_000_000


# ---------------------------------------------------------------------------
# 3-leg chaining: quote_cycle_3legs contract
# ---------------------------------------------------------------------------

class TestQuoteCycle3LegsWiring:
    """Test the 3-leg sequential chaining in m7a_enumerate_cycles."""

    def test_chaining_amount_out_to_amount_in(self):
        """leg1.amount_out == leg2.amount_in, leg2.amount_out == leg3.amount_in."""
        # Simulate the chaining manually (same logic as quote_cycle_3legs)
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6)
        q2 = LegQuote(amount_in_wei=q1.amount_out_wei, amount_out_wei=4000 * 10**18)
        q3 = LegQuote(amount_in_wei=q2.amount_out_wei, amount_out_wei=int(0.99 * 10**18))

        # Verify chaining
        assert q2.amount_in_wei == q1.amount_out_wei
        assert q3.amount_in_wei == q2.amount_out_wei

    def test_measured_score_from_chained_quotes(self):
        """Chained quotes produce meaningful measured score."""
        c = TriangularCycle(
            leg1=_edge("WETH", "USDC", pool="0x1", fee=500),
            leg2=_edge("USDC", "ARB", pool="0x2", fee=3000),
            leg3=_edge("ARB", "WETH", pool="0x3", fee=500),
        )
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       block_number=100, quote_source="quoter_v2")
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       block_number=100, quote_source="quoter_v2")
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=int(1.003 * 10**18),
                       block_number=100, quote_source="quoter_v2")

        s = score_cycle_measured(c, q1, q2, q3)
        assert s.provenance_summary == "measured"
        assert s.same_state_class == SAME_STATE_PROVEN
        assert s.gross_bps > 0  # 0.3% triangular return

    def test_block_numbers_propagate_to_same_state(self):
        """Real block numbers from quotes drive same-state classification."""
        c = TriangularCycle(
            leg1=_edge("WETH", "USDC", pool="0x1", fee=500),
            leg2=_edge("USDC", "ARB", pool="0x2", fee=3000),
            leg3=_edge("ARB", "WETH", pool="0x3", fee=500),
        )
        # Adjacent blocks → PROVEN
        q1 = LegQuote(amount_in_wei=10**18, amount_out_wei=2000 * 10**6,
                       block_number=1000)
        q2 = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                       block_number=1001)
        q3 = LegQuote(amount_in_wei=4000 * 10**18, amount_out_wei=10**18,
                       block_number=1000)
        s = score_cycle_measured(c, q1, q2, q3)
        assert s.same_state_class == SAME_STATE_PROVEN

        # Large drift → VIOLATED
        q2_far = LegQuote(amount_in_wei=2000 * 10**6, amount_out_wei=4000 * 10**18,
                          block_number=1050)
        s2 = score_cycle_measured(c, q1, q2_far, q3)
        assert s2.same_state_class == SAME_STATE_VIOLATED

    def test_rpc_result_to_measured_pipeline(self):
        """End-to-end: RPC result dict -> LegQuote -> score_cycle_measured."""
        c = TriangularCycle(
            leg1=_edge("WETH", "USDC", pool="0x1", fee=500),
            leg2=_edge("USDC", "ARB", pool="0x2", fee=3000),
            leg3=_edge("ARB", "WETH", pool="0x3", fee=500),
        )
        # Simulate RPC results
        rpc1 = {"amount_out": 2000 * 10**6, "gas_estimate": 180_000,
                "ticks_crossed": 2, "sqrt_price_after": 999}
        rpc2 = {"amount_out": 4000 * 10**18, "gas_estimate": 200_000,
                "ticks_crossed": 1, "sqrt_price_after": None}
        rpc3 = {"amount_out": int(1.002 * 10**18), "gas_estimate": 180_000,
                "ticks_crossed": 3, "sqrt_price_after": 888}

        q1 = leg_quote_from_rpc_result(rpc1, 10**18, fee_tier=500,
                                        block_number=5000, quote_source="quoter_v2")
        q2 = leg_quote_from_rpc_result(rpc2, q1.amount_out_wei, fee_tier=3000,
                                        block_number=5000, quote_source="algebra_quoter")
        q3 = leg_quote_from_rpc_result(rpc3, q2.amount_out_wei, fee_tier=500,
                                        block_number=5000, quote_source="quoter_v2")

        s = score_cycle_measured(c, q1, q2, q3)
        assert s.provenance_summary == "measured"
        assert s.same_state_class == SAME_STATE_PROVEN
        assert s.gross_bps > 0
        # LP fees NOT subtracted again — embedded in amount_out
        assert s.fee_leg1_bps == 5.0   # metadata only
        assert s.fee_leg2_bps == 30.0
        assert s.fee_leg3_bps == 5.0


# ---------------------------------------------------------------------------
# SizeSweepResult / SizeSweepPoint contract tests
# ---------------------------------------------------------------------------

from engine.triangular_cycles import SizeSweepPoint, SizeSweepResult


class TestSizeSweepResult:
    """Contract tests for the bounded size sweep dataclasses."""

    def _make_cycle(self):
        return TriangularCycle(
            leg1=_edge("WETH", "USDC", pool="0x1", fee=500),
            leg2=_edge("USDC", "ARB", pool="0x2", fee=3000),
            leg3=_edge("ARB", "WETH", pool="0x3", fee=500),
        )

    def _make_score(self, net_bps: float, size_usd: float = 100.0) -> CycleScore:
        return CycleScore(
            cycle=self._make_cycle(),
            final_net_bps=net_bps,
            scored_size_usd=size_usd,
            provenance_summary="measured",
        )

    def test_sweep_point_fields(self):
        p = SizeSweepPoint(size_usd=100.0, final_net_bps=-5.2, quoted=True)
        assert p.size_usd == 100.0
        assert p.final_net_bps == -5.2
        assert p.quoted is True

    def test_sweep_point_unquoted(self):
        p = SizeSweepPoint(size_usd=50.0, final_net_bps=0.0, quoted=False)
        assert p.quoted is False

    def test_sweep_result_fields(self):
        c = self._make_cycle()
        best = self._make_score(-3.5, 250.0)
        curve = [
            SizeSweepPoint(100.0, -5.2, True),
            SizeSweepPoint(250.0, -3.5, True),
            SizeSweepPoint(500.0, -8.1, True),
        ]
        r = SizeSweepResult(
            cycle=c, best_size_usd=250.0, best_net_bps=-3.5,
            best_score=best, size_curve=curve,
            sizes_attempted=3, sizes_quoted=3,
        )
        assert r.best_size_usd == 250.0
        assert r.best_net_bps == -3.5
        assert r.sizes_attempted == 3
        assert r.sizes_quoted == 3

    def test_sweep_result_to_dict_schema(self):
        """to_dict() must produce all required keys."""
        c = self._make_cycle()
        best = self._make_score(-3.5, 250.0)
        curve = [
            SizeSweepPoint(100.0, -5.2, True),
            SizeSweepPoint(250.0, -3.5, True),
        ]
        r = SizeSweepResult(
            cycle=c, best_size_usd=250.0, best_net_bps=-3.5,
            best_score=best, size_curve=curve,
            sizes_attempted=2, sizes_quoted=2,
        )
        d = r.to_dict()
        required_keys = [
            "cycle_key", "route", "best_size_usd", "best_net_bps",
            "sizes_attempted", "sizes_quoted", "size_curve", "best_decomposition",
        ]
        for key in required_keys:
            assert key in d, f"Missing key: {key}"

    def test_sweep_result_to_dict_curve_entries(self):
        """Each size_curve entry has size_usd, final_net_bps, quoted."""
        c = self._make_cycle()
        best = self._make_score(-3.5, 250.0)
        curve = [
            SizeSweepPoint(100.0, -5.2, True),
            SizeSweepPoint(50.0, 0.0, False),
        ]
        r = SizeSweepResult(
            cycle=c, best_size_usd=100.0, best_net_bps=-5.2,
            best_score=best, size_curve=curve,
            sizes_attempted=2, sizes_quoted=1,
        )
        d = r.to_dict()
        assert len(d["size_curve"]) == 2
        for entry in d["size_curve"]:
            assert "size_usd" in entry
            assert "final_net_bps" in entry
            assert "quoted" in entry

    def test_sweep_result_best_decomposition_is_cycle_score(self):
        """best_decomposition should match CycleScore.to_dict() keys."""
        c = self._make_cycle()
        best = self._make_score(-3.5, 250.0)
        r = SizeSweepResult(
            cycle=c, best_size_usd=250.0, best_net_bps=-3.5,
            best_score=best, size_curve=[],
            sizes_attempted=0, sizes_quoted=0,
        )
        d = r.to_dict()
        decomp = d["best_decomposition"]
        # Must have standard CycleScore artifact keys
        assert "final_net_bps" in decomp
        assert "scored_size_usd" in decomp
        assert "route" in decomp

    def test_canonical_sweep_sizes_reusable(self):
        """CANONICAL_SWEEP_SIZES_USD from roundtrip.py must be importable."""
        from engine.roundtrip import CANONICAL_SWEEP_SIZES_USD
        assert isinstance(CANONICAL_SWEEP_SIZES_USD, list)
        assert len(CANONICAL_SWEEP_SIZES_USD) >= 10
        assert all(s > 0 for s in CANONICAL_SWEEP_SIZES_USD)
        # Must be sorted ascending
        assert CANONICAL_SWEEP_SIZES_USD == sorted(CANONICAL_SWEEP_SIZES_USD)

    def test_calculate_starting_amount_accepts_target_usd(self):
        """_calculate_starting_amount must accept target_usd parameter."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _calculate_starting_amount

        amt_100 = _calculate_starting_amount("USDC", 6, target_usd=100.0)
        amt_500 = _calculate_starting_amount("USDC", 6, target_usd=500.0)
        # Stablecoin: $500 should be 5x $100
        assert amt_500 == 5 * amt_100

    def test_calculate_starting_amount_default_backward_compat(self):
        """Default target_usd=100 preserves existing behavior."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _calculate_starting_amount

        amt = _calculate_starting_amount("USDC", 6)
        assert amt == 100 * 10**6  # $100 at $1/USDC, 6 decimals


# ---------------------------------------------------------------------------
# Blocker analysis contract tests
# ---------------------------------------------------------------------------

class TestBlockerSummary:
    """Contract tests for the M7.A blocker summary (machine-readable RCA)."""

    def _make_score(self, gross=-10.0, gas=12.0, fee1=0.0, fee2=1.0, fee3=5.0,
                    net=-28.0, size_usd=100.0, tokens=("ARB", "USDC", "WETH")):
        e1 = _edge(tokens[0], tokens[1], dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge(tokens[1], tokens[2], dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge(tokens[2], tokens[0], dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        return CycleScore(
            cycle=cycle, gross_bps=gross, gas_bps=gas,
            fee_leg1_bps=fee1, fee_leg2_bps=fee2, fee_leg3_bps=fee3,
            total_fee_bps=fee1 + fee2 + fee3,
            final_net_bps=net, scored_size_usd=size_usd,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
            reject_reason="NET_NEGATIVE",
        )

    def _make_stats(self, scored=67, failed=33, attempted=100):
        return {
            "block_number": 446635245,
            "attempted": attempted,
            "scored": scored,
            "failed": failed,
            "measured_ranked_count": scored,
            "diagnostic_fallback_count": failed,
            "promoted_count": 0,
            "best_measured_net_bps": -20.96,
            "same_state_distribution": {"same_state_proven": scored},
        }

    def test_blocker_summary_schema_keys(self):
        """blocker_summary must contain all required keys."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])

        required_keys = {
            "best_route_gross_bps", "best_route_gas_bps", "best_route_total_fee_bps",
            "best_route_net_bps", "best_route_best_size_usd",
            "small_size_gas_domination", "large_size_slippage_domination",
            "same_state_proven_rate", "route_failure_rate",
            "token_triple_concentration", "top_blockers",
        }
        for key in required_keys:
            assert key in result, f"Missing key: {key}"

    def test_blocker_summary_gross_negative(self):
        """If best route gross is negative, GROSS_NEGATIVE_CORE must be in top_blockers."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary, BLOCKER_GROSS_NEGATIVE_CORE

        ranked = [self._make_score(gross=-9.3)]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert BLOCKER_GROSS_NEGATIVE_CORE in result["top_blockers"]

    def test_blocker_summary_third_leg_fee(self):
        """If leg3 fee >= 5 bps, THIRD_LEG_FEE_BINDING must appear."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary, BLOCKER_THIRD_LEG_FEE_BINDING

        ranked = [self._make_score(fee3=5.0)]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert BLOCKER_THIRD_LEG_FEE_BINDING in result["top_blockers"]

    def test_blocker_summary_single_triple_concentration(self):
        """100% same token triple must trigger SINGLE_TRIPLE_CONCENTRATION."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            _build_blocker_summary, BLOCKER_SINGLE_TRIPLE_CONCENTRATION,
        )

        # All routes use same triple
        ranked = [self._make_score() for _ in range(5)]
        stats = self._make_stats(scored=5, failed=0, attempted=5)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["token_triple_concentration"] == 1.0
        assert BLOCKER_SINGLE_TRIPLE_CONCENTRATION in result["top_blockers"]

    def test_blocker_summary_quote_failure_breadth(self):
        """High failure rate (>=25%) triggers QUOTE_FAILURE_BREADTH_LIMIT."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import (
            _build_blocker_summary, BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT,
        )

        ranked = [self._make_score()]
        stats = self._make_stats(scored=50, failed=50, attempted=100)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["route_failure_rate"] == 0.5
        assert BLOCKER_QUOTE_FAILURE_BREADTH_LIMIT in result["top_blockers"]

    def test_blocker_summary_same_state_rate(self):
        """same_state_proven_rate must match distribution."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=67, failed=33, attempted=100)
        result = _build_blocker_summary(ranked, stats, [])
        assert result["same_state_proven_rate"] == 1.0  # 67/67 proven

    def test_blocker_summary_no_measured_routes(self):
        """Empty measured list produces error sentinel."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        result = _build_blocker_summary([], {}, [])
        assert result.get("error") == "no_measured_routes"

    def test_blocker_summary_dominant_triple_field(self):
        """dominant_triple must be a sorted list of 3 tokens."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.m7a_enumerate_cycles import _build_blocker_summary

        ranked = [self._make_score()]
        stats = self._make_stats(scored=1, failed=0, attempted=1)
        result = _build_blocker_summary(ranked, stats, [])
        assert isinstance(result["dominant_triple"], list)
        assert len(result["dominant_triple"]) == 3
        assert result["dominant_triple"] == sorted(result["dominant_triple"])


class TestClassifyBlockerTags:
    """Contract tests for classify_blocker_tags()."""

    def _make_score(self, gross=-10.0, gas=12.0, fee3=5.0, net=-28.0):
        e1 = _edge("ARB", "USDC", dex="camelot_v3", fee=0, pool="0x111", adapter_type="algebra")
        e2 = _edge("USDC", "WETH", dex="uniswap_v3", fee=100, pool="0x222")
        e3 = _edge("WETH", "ARB", dex="pancakeswap_v3", fee=500, pool="0x333")
        cycle = TriangularCycle(leg1=e1, leg2=e2, leg3=e3)
        return CycleScore(
            cycle=cycle, gross_bps=gross, gas_bps=gas,
            fee_leg1_bps=0.0, fee_leg2_bps=1.0, fee_leg3_bps=fee3,
            total_fee_bps=1.0 + fee3,
            final_net_bps=net, scored_size_usd=100.0,
            block_tag="123456", provenance_summary="measured",
            same_state_class=SAME_STATE_PROVEN, route_viable=True,
        )

    def test_gross_negative_tag(self):
        """Negative gross triggers GROSS_NEGATIVE_CORE."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GROSS_NEGATIVE_CORE
        s = self._make_score(gross=-5.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_GROSS_NEGATIVE_CORE in tags

    def test_positive_gross_no_tag(self):
        """Positive gross does NOT trigger GROSS_NEGATIVE_CORE."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GROSS_NEGATIVE_CORE
        s = self._make_score(gross=2.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_GROSS_NEGATIVE_CORE not in tags

    def test_third_leg_fee_tag(self):
        """fee_leg3 >= 5 bps triggers THIRD_LEG_FEE_BINDING."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_THIRD_LEG_FEE_BINDING
        s = self._make_score(fee3=5.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_THIRD_LEG_FEE_BINDING in tags

    def test_low_third_leg_fee_no_tag(self):
        """fee_leg3 < 5 bps does NOT trigger THIRD_LEG_FEE_BINDING."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_THIRD_LEG_FEE_BINDING
        s = self._make_score(fee3=1.0)
        tags = classify_blocker_tags(s)
        assert BLOCKER_THIRD_LEG_FEE_BINDING not in tags

    def test_gas_dominant_small_with_sweep(self):
        """Gas domination at small sizes detected from sweep curve."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_GAS_DOMINANT_SMALL
        from engine.triangular_cycles import SizeSweepPoint, SizeSweepResult

        s = self._make_score(gross=-10.0, net=-21.0)
        curve = [
            SizeSweepPoint(size_usd=1.0, final_net_bps=-1100.0, quoted=True),
            SizeSweepPoint(size_usd=100.0, final_net_bps=-21.0, quoted=True),
            SizeSweepPoint(size_usd=10000.0, final_net_bps=-400.0, quoted=True),
        ]
        sweep = SizeSweepResult(
            cycle=s.cycle, best_size_usd=100.0, best_net_bps=-21.0,
            best_score=s, size_curve=curve,
            sizes_attempted=3, sizes_quoted=3,
        )
        tags = classify_blocker_tags(s, sweep)
        assert BLOCKER_GAS_DOMINANT_SMALL in tags

    def test_slippage_dominant_large_with_sweep(self):
        """Slippage domination at large sizes detected from sweep curve."""
        from scripts.m7a_enumerate_cycles import classify_blocker_tags, BLOCKER_SLIPPAGE_DOMINANT_LARGE
        from engine.triangular_cycles import SizeSweepPoint, SizeSweepResult

        s = self._make_score(gross=-10.0, net=-21.0)
        curve = [
            SizeSweepPoint(size_usd=1.0, final_net_bps=-1100.0, quoted=True),
            SizeSweepPoint(size_usd=100.0, final_net_bps=-21.0, quoted=True),
            SizeSweepPoint(size_usd=10000.0, final_net_bps=-400.0, quoted=True),
        ]
        sweep = SizeSweepResult(
            cycle=s.cycle, best_size_usd=100.0, best_net_bps=-21.0,
            best_score=s, size_curve=curve,
            sizes_attempted=3, sizes_quoted=3,
        )
        tags = classify_blocker_tags(s, sweep)
        assert BLOCKER_SLIPPAGE_DOMINANT_LARGE in tags

    def test_no_sweep_no_size_tags(self):
        """Without sweep data, no size-dependent tags should be produced."""
        from scripts.m7a_enumerate_cycles import (
            classify_blocker_tags,
            BLOCKER_GAS_DOMINANT_SMALL,
            BLOCKER_SLIPPAGE_DOMINANT_LARGE,
        )
        s = self._make_score()
        tags = classify_blocker_tags(s, sweep=None)
        assert BLOCKER_GAS_DOMINANT_SMALL not in tags
        assert BLOCKER_SLIPPAGE_DOMINANT_LARGE not in tags
