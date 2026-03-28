# PATH: tests/unit/test_triangular_graph.py
"""
Unit tests for engine/triangular_graph.py (M7.A).

Covers:
- PoolEdge creation and reversal
- PoolGraph add/dedup/neighbor semantics
- Graph builder from pool_dicts
- Graph summary serialization
"""

import pytest

from engine.triangular_graph import PoolEdge, PoolGraph, build_graph_from_pool_dicts


# ---------------------------------------------------------------------------
# Fixtures
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


def _arb_graph_minimal():
    """Builds a small arb graph: WETH <-> USDC, USDC <-> ARB, ARB <-> WETH."""
    graph = PoolGraph(chain="arbitrum_one")
    graph.add_pool(_edge("WETH", "USDC", pool="0xpool1", fee=500))
    graph.add_pool(_edge("USDC", "ARB", pool="0xpool2", fee=3000))
    graph.add_pool(_edge("ARB", "WETH", pool="0xpool3", fee=3000))
    return graph


# ---------------------------------------------------------------------------
# PoolEdge tests
# ---------------------------------------------------------------------------

class TestPoolEdge:
    def test_edge_key_deterministic(self):
        e = _edge("WETH", "USDC", pool="0xAbcdef1234")
        assert "WETH->USDC" in e.edge_key
        assert "0xAbcdef1234" in e.edge_key  # full address

    def test_edge_key_no_collision_on_prefix(self):
        """Two pools sharing a 10-char prefix must produce distinct edge_keys."""
        e1 = _edge("WETH", "USDC", pool="0xAbcdef1234_pool_alpha")
        e2 = _edge("WETH", "USDC", pool="0xAbcdef1234_pool_beta")
        assert e1.edge_key != e2.edge_key

    def test_edge_key_v2_fee_none(self):
        e = _edge("WETH", "USDC", fee=None)
        assert "v2" in e.edge_key

    def test_reverse(self):
        e = _edge("WETH", "USDC", dex="sushiswap_v3", fee=500,
                  pool="0x123")
        r = e.reverse()
        assert r.token_in == "USDC"
        assert r.token_out == "WETH"
        assert r.pool_address == "0x123"
        assert r.dex == "sushiswap_v3"
        assert r.fee == 500

    def test_reverse_swaps_decimals(self):
        e = PoolEdge(
            token_in="USDC", token_out="WETH", pool_address="0x1",
            dex="v3", adapter_type="v3", fee=500, chain="arb",
            decimals_in=6, decimals_out=18,
        )
        r = e.reverse()
        assert r.decimals_in == 18
        assert r.decimals_out == 6

    def test_frozen_immutable(self):
        e = _edge("WETH", "USDC")
        with pytest.raises(AttributeError):
            e.token_in = "ARB"

    def test_edge_hashable(self):
        e1 = _edge("WETH", "USDC", pool="0x1")
        e2 = _edge("WETH", "USDC", pool="0x1")
        assert e1 == e2
        assert {e1, e2} == {e1}


# ---------------------------------------------------------------------------
# PoolGraph tests
# ---------------------------------------------------------------------------

class TestPoolGraph:
    def test_empty_graph(self):
        g = PoolGraph(chain="arbitrum_one")
        assert g.node_count == 0
        assert g.edge_count == 0

    def test_add_edge_single(self):
        g = PoolGraph(chain="arbitrum_one")
        e = _edge("WETH", "USDC")
        assert g.add_edge(e) is True
        assert g.edge_count == 1
        assert g.node_count == 2

    def test_add_edge_dedup(self):
        g = PoolGraph(chain="arbitrum_one")
        e = _edge("WETH", "USDC")
        g.add_edge(e)
        assert g.add_edge(e) is False
        assert g.edge_count == 1

    def test_add_pool_adds_both_directions(self):
        g = PoolGraph(chain="arbitrum_one")
        e = _edge("WETH", "USDC")
        added = g.add_pool(e)
        assert added == 2
        assert g.edge_count == 2

    def test_neighbors(self):
        g = _arb_graph_minimal()
        neighbors = g.neighbors("WETH")
        token_outs = {e.token_out for e in neighbors}
        assert "USDC" in token_outs
        assert "ARB" in token_outs  # from ARB->WETH reverse

    def test_neighbor_tokens(self):
        g = _arb_graph_minimal()
        assert g.neighbor_tokens("USDC") == {"WETH", "ARB"}

    def test_all_tokens(self):
        g = _arb_graph_minimal()
        assert g.all_tokens() == {"WETH", "USDC", "ARB"}

    def test_summary_shape(self):
        g = _arb_graph_minimal()
        s = g.to_summary()
        assert s["chain"] == "arbitrum_one"
        assert s["node_count"] == 3
        assert s["edge_count"] == 6  # 3 pools * 2 directions
        assert "WETH" in s["tokens"]


# ---------------------------------------------------------------------------
# build_graph_from_pool_dicts
# ---------------------------------------------------------------------------

class TestBuildFromPoolDicts:
    def test_basic_build(self):
        dicts = [
            {"token_in": "WETH", "token_out": "USDC", "dex": "uni_v3",
             "pool_address": "0x1", "fee": 500},
            {"token_in": "USDC", "token_out": "ARB", "dex": "sushi_v3",
             "pool_address": "0x2", "fee": 3000},
        ]
        g = build_graph_from_pool_dicts("arbitrum_one", dicts)
        assert g.node_count == 3
        assert g.edge_count == 4  # 2 pools * 2 dir

    def test_skips_missing_fields(self):
        dicts = [
            {"token_in": "WETH"},  # no token_out, no address
            {"token_in": "WETH", "token_out": "USDC", "dex": "x",
             "pool_address": "0x1"},
        ]
        g = build_graph_from_pool_dicts("arb", dicts)
        assert g.edge_count == 2  # only the valid pool

    def test_empty_input(self):
        g = build_graph_from_pool_dicts("arb", [])
        assert g.node_count == 0
        assert g.edge_count == 0

    def test_alternate_field_names(self):
        dicts = [
            {"token0_symbol": "WETH", "token1_symbol": "USDC", "dex": "x",
             "address": "0x1", "fee_tier": 500},
        ]
        g = build_graph_from_pool_dicts("arb", dicts)
        assert g.edge_count == 2
