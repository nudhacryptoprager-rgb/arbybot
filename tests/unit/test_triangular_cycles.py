# PATH: tests/unit/test_triangular_cycles.py
"""
Unit tests for engine/triangular_cycles.py (M7.A).

Covers:
- TriangularCycle construction and validation
- 3-hop cycle finder (find_3hop_cycles)
- Dedup / canonicalization of rotated cycles
- No-repeated-pool enforcement
- Fee-only scoring
- Ranking and filtering utilities
- CycleScore artifact serialization
- Same-state classification correctness
"""

import pytest

from engine.triangular_graph import PoolEdge, PoolGraph
from engine.triangular_cycles import (
    CycleScore,
    SAME_STATE_AMBIGUOUS,
    SAME_STATE_PROVEN,
    SAME_STATE_VIOLATED,
    TriangularCycle,
    _fee_tier_to_bps,
    filter_viable_fee_structures,
    find_3hop_cycles,
    rank_cycles_by_net,
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


def _triangle_graph():
    """WETH <-> USDC <-> ARB <-> WETH, each on a distinct pool."""
    graph = PoolGraph(chain="arbitrum_one")
    graph.add_pool(_edge("WETH", "USDC", pool="0xp1", fee=500))
    graph.add_pool(_edge("USDC", "ARB", pool="0xp2", fee=3000))
    graph.add_pool(_edge("ARB", "WETH", pool="0xp3", fee=3000))
    return graph


def _make_cycle() -> TriangularCycle:
    return TriangularCycle(
        leg1=_edge("ARB", "USDC", pool="0xp2", fee=3000),
        leg2=_edge("USDC", "WETH", pool="0xp1", fee=500),
        leg3=_edge("WETH", "ARB", pool="0xp3", fee=3000),
    )


# ---------------------------------------------------------------------------
# TriangularCycle construction
# ---------------------------------------------------------------------------

class TestTriangularCycle:
    def test_valid_cycle(self):
        c = _make_cycle()
        assert c.tokens == ("ARB", "USDC", "WETH")
        assert c.leg3.token_out == "ARB"

    def test_invalid_leg12_mismatch(self):
        with pytest.raises(ValueError, match="Leg1 token_out"):
            TriangularCycle(
                leg1=_edge("WETH", "USDC", pool="0x1"),
                leg2=_edge("ARB", "WETH", pool="0x2"),  # token_in=ARB != USDC
                leg3=_edge("WETH", "WETH", pool="0x3"),
            )

    def test_invalid_leg23_mismatch(self):
        with pytest.raises(ValueError, match="Leg2 token_out"):
            TriangularCycle(
                leg1=_edge("WETH", "USDC", pool="0x1"),
                leg2=_edge("USDC", "ARB", pool="0x2"),
                leg3=_edge("WETH", "WETH", pool="0x3"),  # token_in=WETH != ARB
            )

    def test_invalid_not_closed(self):
        with pytest.raises(ValueError, match="Leg3 token_out"):
            TriangularCycle(
                leg1=_edge("WETH", "USDC", pool="0x1"),
                leg2=_edge("USDC", "ARB", pool="0x2"),
                leg3=_edge("ARB", "LINK", pool="0x3"),  # LINK != WETH
            )

    def test_token_set(self):
        c = _make_cycle()
        assert c.token_set == frozenset({"ARB", "USDC", "WETH"})

    def test_has_repeated_pool_positive(self):
        c = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0xSAME"),
            leg2=_edge("USDC", "WETH", pool="0xSAME"),  # same pool!
            leg3=_edge("WETH", "ARB", pool="0xp3"),
        )
        assert c.has_repeated_pool() is True

    def test_has_repeated_pool_negative(self):
        c = _make_cycle()
        assert c.has_repeated_pool() is False

    def test_route_display(self):
        c = _make_cycle()
        assert "ARB->USDC->WETH->ARB" in c.route_display

    def test_cycle_key_deterministic(self):
        c1 = _make_cycle()
        c2 = _make_cycle()
        assert c1.cycle_key == c2.cycle_key

    def test_frozen(self):
        c = _make_cycle()
        with pytest.raises(AttributeError):
            c.leg1 = None


# ---------------------------------------------------------------------------
# find_3hop_cycles
# ---------------------------------------------------------------------------

class TestFind3HopCycles:
    def test_triangle_graph_finds_both_directions(self):
        g = _triangle_graph()
        cycles = find_3hop_cycles(g)
        # 3 tokens => 2 directional cycles (A->B->C->A and A->C->B->A)
        # because pool direction matters for pricing
        assert len(cycles) == 2
        for c in cycles:
            assert c.tokens[0] == "ARB"  # canonical start

    def test_no_self_loops(self):
        g = PoolGraph(chain="arb")
        g.add_pool(_edge("WETH", "WETH", pool="0x1"))
        g.add_pool(_edge("WETH", "USDC", pool="0x2"))
        g.add_pool(_edge("USDC", "ARB", pool="0x3"))
        g.add_pool(_edge("ARB", "WETH", pool="0x4"))
        cycles = find_3hop_cycles(g)
        # No cycle should use a self-loop edge
        for c in cycles:
            for leg in c.legs():
                assert leg.token_in != leg.token_out

    def test_no_repeated_pool(self):
        """If two legs must use the same pool, that cycle is rejected."""
        g = PoolGraph(chain="arb")
        # WETH <-> USDC on pool 0x1
        g.add_pool(_edge("WETH", "USDC", pool="0x1"))
        # USDC <-> ARB on pool 0x1 (SAME pool!)
        g.add_pool(_edge("USDC", "ARB", pool="0x1"))
        # ARB <-> WETH on pool 0x2
        g.add_pool(_edge("ARB", "WETH", pool="0x2"))

        cycles = find_3hop_cycles(g)
        # The cycle must use 3 distinct pools, and leg1+leg2 both have 0x1
        # so no valid cycle exists
        assert all(not c.has_repeated_pool() for c in cycles)

    def test_no_repeated_tokens(self):
        g = _triangle_graph()
        cycles = find_3hop_cycles(g)
        for c in cycles:
            # All 3 tokens must be distinct
            assert len(set(c.tokens)) == 3

    def test_max_cycles_cap(self):
        g = _triangle_graph()
        cycles = find_3hop_cycles(g, max_cycles=0)
        assert len(cycles) == 0

    def test_start_tokens_filter(self):
        g = _triangle_graph()
        # Only cycles starting from WETH — since canonical is min, and
        # ARB < USDC < WETH, cycles canonically start from ARB.
        # So filtering to start_tokens={"WETH"} should find nothing.
        cycles = find_3hop_cycles(g, start_tokens={"WETH"})
        assert len(cycles) == 0

    def test_start_tokens_includes_canonical(self):
        g = _triangle_graph()
        cycles = find_3hop_cycles(g, start_tokens={"ARB"})
        assert len(cycles) == 2  # both directions from ARB

    def test_empty_graph(self):
        g = PoolGraph(chain="arb")
        assert find_3hop_cycles(g) == []

    def test_two_node_graph_no_cycles(self):
        g = PoolGraph(chain="arb")
        g.add_pool(_edge("WETH", "USDC", pool="0x1"))
        assert find_3hop_cycles(g) == []

    def test_multi_dex_same_pair(self):
        """Multiple DEXes for the same pair should yield more cycles."""
        g = PoolGraph(chain="arb")
        # WETH/USDC on 2 dexes
        g.add_pool(_edge("WETH", "USDC", pool="0x1", dex="uni"))
        g.add_pool(_edge("WETH", "USDC", pool="0x4", dex="sushi"))
        # USDC/ARB
        g.add_pool(_edge("USDC", "ARB", pool="0x2"))
        # ARB/WETH
        g.add_pool(_edge("ARB", "WETH", pool="0x3"))
        cycles = find_3hop_cycles(g)
        # 2 pools for WETH/USDC * 2 directions = 4 distinct cycles
        assert len(cycles) == 4
        keys = {c.cycle_key for c in cycles}
        assert len(keys) == 4

    def test_four_tokens_multiple_triangles(self):
        """WETH, USDC, ARB, WBTC — fully connected => multiple triangles."""
        g = PoolGraph(chain="arb")
        tokens = ["ARB", "USDC", "WBTC", "WETH"]
        pool_id = 0
        for i, t1 in enumerate(tokens):
            for t2 in tokens[i+1:]:
                pool_id += 1
                g.add_pool(_edge(t1, t2, pool=f"0x{pool_id:04x}"))
        cycles = find_3hop_cycles(g)
        # C(4,3) = 4 token triples, each generates 2 directional cycles = 8
        assert len(cycles) == 8


# ---------------------------------------------------------------------------
# Fee-only scoring
# ---------------------------------------------------------------------------

class TestScoreCycleFeesOnly:
    def test_fee_calculation(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c, gas_cost_usd=0.50, notional_usd=100.0)
        # leg1: 3000 fee -> 30 bps, leg2: 500 -> 5 bps, leg3: 3000 -> 30 bps
        assert s.fee_leg1_bps == 30.0
        assert s.fee_leg2_bps == 5.0
        assert s.fee_leg3_bps == 30.0
        assert s.total_fee_bps == 65.0
        # gas: 0.50 / 100 * 10000 = 50 bps
        assert s.gas_bps == 50.0
        # net: -(65 + 50) = -115
        assert s.final_net_bps == -115.0

    def test_no_live_quote_data(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c)
        assert s.gross_bps == 0.0
        assert s.provenance_summary == "fee_structure_only"

    def test_same_state_default_ambiguous(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c)
        assert s.same_state_class == SAME_STATE_AMBIGUOUS

    def test_zero_notional(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c, notional_usd=0.0)
        assert s.gas_bps == 0.0


class TestFeeConversion:
    def test_v3_tiers(self):
        assert _fee_tier_to_bps(100) == 1.0
        assert _fee_tier_to_bps(500) == 5.0
        assert _fee_tier_to_bps(3000) == 30.0
        assert _fee_tier_to_bps(10000) == 100.0
        assert _fee_tier_to_bps(2500) == 25.0  # PancakeSwap

    def test_v2_none(self):
        assert _fee_tier_to_bps(None) == 30.0


# ---------------------------------------------------------------------------
# Ranking and filtering
# ---------------------------------------------------------------------------

class TestRanking:
    def test_rank_descending(self):
        c = _make_cycle()
        s1 = CycleScore(cycle=c, final_net_bps=10.0)
        s2 = CycleScore(cycle=c, final_net_bps=-5.0)
        s3 = CycleScore(cycle=c, final_net_bps=50.0)
        ranked = rank_cycles_by_net([s1, s2, s3])
        assert [s.final_net_bps for s in ranked] == [50.0, 10.0, -5.0]

    def test_rank_min_net_filter(self):
        c = _make_cycle()
        s1 = CycleScore(cycle=c, final_net_bps=10.0)
        s2 = CycleScore(cycle=c, final_net_bps=-5.0)
        ranked = rank_cycles_by_net([s1, s2], min_net_bps=0.0)
        assert len(ranked) == 1
        assert ranked[0].final_net_bps == 10.0

    def test_rank_promoted_only(self):
        c = _make_cycle()
        s1 = CycleScore(
            cycle=c, final_net_bps=10.0,
            same_state_class=SAME_STATE_PROVEN,
            route_viable=True, reject_reason=None,
        )
        s2 = CycleScore(
            cycle=c, final_net_bps=20.0,
            same_state_class=SAME_STATE_AMBIGUOUS,
        )
        ranked = rank_cycles_by_net([s1, s2], promoted_only=True)
        assert len(ranked) == 1
        assert ranked[0].final_net_bps == 10.0


class TestFilterViableFeeStructures:
    def test_high_fee_filtered(self):
        # 3 legs * 100 bps = 300 bps total
        c_high = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x1", fee=10000),
            leg2=_edge("USDC", "WETH", pool="0x2", fee=10000),
            leg3=_edge("WETH", "ARB", pool="0x3", fee=10000),
        )
        # 3 legs * 1 bps = 3 bps total
        c_low = TriangularCycle(
            leg1=_edge("ARB", "USDC", pool="0x4", fee=100),
            leg2=_edge("USDC", "WETH", pool="0x5", fee=100),
            leg3=_edge("WETH", "ARB", pool="0x6", fee=100),
        )
        result = filter_viable_fee_structures([c_high, c_low], max_total_fee_bps=50.0)
        assert len(result) == 1
        assert result[0] is c_low


# ---------------------------------------------------------------------------
# CycleScore serialization
# ---------------------------------------------------------------------------

class TestCycleScoreSerialization:
    def test_to_dict_has_all_required_fields(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c)
        d = s.to_dict()
        # Required by step_M7.md
        required = [
            "gross_bps", "fee_leg1_bps", "fee_leg2_bps", "fee_leg3_bps",
            "slippage_leg1_bps", "slippage_leg2_bps", "slippage_leg3_bps",
            "gas_bps", "final_net_bps", "best_size_usd", "block_tag",
            "provenance_summary",
        ]
        for key in required:
            assert key in d, f"Missing required field: {key}"

    def test_to_dict_has_per_leg_identity(self):
        c = _make_cycle()
        s = score_cycle_fees_only(c)
        d = s.to_dict()
        for leg_key in ("leg1", "leg2", "leg3"):
            assert leg_key in d
            leg = d[leg_key]
            assert "dex" in leg
            assert "pool" in leg
            assert "fee" in leg
            assert "adapter_type" in leg

    def test_to_dict_same_state_class(self):
        c = _make_cycle()
        s = CycleScore(cycle=c, same_state_class=SAME_STATE_VIOLATED)
        d = s.to_dict()
        assert d["same_state_class"] == "same_state_violated"


# ---------------------------------------------------------------------------
# CycleScore.is_promoted semantics
# ---------------------------------------------------------------------------

class TestPromotion:
    def test_promoted_requires_all_conditions(self):
        c = _make_cycle()
        s = CycleScore(
            cycle=c,
            final_net_bps=5.0,
            same_state_class=SAME_STATE_PROVEN,
            route_viable=True,
            reject_reason=None,
        )
        assert s.is_promoted() is True

    def test_not_promoted_if_ambiguous(self):
        c = _make_cycle()
        s = CycleScore(
            cycle=c,
            final_net_bps=5.0,
            same_state_class=SAME_STATE_AMBIGUOUS,
            route_viable=True,
            reject_reason=None,
        )
        assert s.is_promoted() is False

    def test_not_promoted_if_negative_net(self):
        c = _make_cycle()
        s = CycleScore(
            cycle=c,
            final_net_bps=-1.0,
            same_state_class=SAME_STATE_PROVEN,
            route_viable=True,
            reject_reason=None,
        )
        assert s.is_promoted() is False

    def test_not_promoted_if_not_viable(self):
        c = _make_cycle()
        s = CycleScore(
            cycle=c,
            final_net_bps=5.0,
            same_state_class=SAME_STATE_PROVEN,
            route_viable=False,
            reject_reason=None,
        )
        assert s.is_promoted() is False

    def test_not_promoted_if_reject_reason(self):
        c = _make_cycle()
        s = CycleScore(
            cycle=c,
            final_net_bps=5.0,
            same_state_class=SAME_STATE_PROVEN,
            route_viable=True,
            reject_reason="SLIPPAGE_TOO_HIGH",
        )
        assert s.is_promoted() is False
