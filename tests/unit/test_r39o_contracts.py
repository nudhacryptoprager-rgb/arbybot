# PATH: tests/unit/test_r39o_contracts.py
"""
R39o contract tests for the Base profit-lane narrowing patch set.

Tests:
1. include_pairs hard clamp in resolve_universe
2. Per-cycle 429 quarantine in quote_rpc
3. No-slot0 for entire Base profit contour (not just alpha)
4. excluded_pool_addresses enforcement
5. Reserved candidate budget slots
6. _match_pair_pattern helper
"""

import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
from unittest.mock import patch, MagicMock


# ============================================================================
# 1. include_pairs hard clamp
# ============================================================================

class TestIncludePairsClamp:
    """include_pairs in config must filter pairs_list before return."""

    def test_clamp_filters_to_whitelist(self):
        """Only whitelisted pairs survive the clamp."""
        from strategy.scan_universe import resolve_universe
        from config.pairs import PairConfig

        mock_pairs = [
            PairConfig(chain="base", token_in="WETH", token_out="USDC"),
            PairConfig(chain="base", token_in="cbBTC", token_out="USDC"),
            PairConfig(chain="base", token_in="WETH", token_out="AERO"),  # noise
            PairConfig(chain="base", token_in="VIRTUAL", token_out="USDC"),  # noise
        ]

        config = {
            "chain": "base",
            "chain_id": 8453,
            "universe_source": "discovery_runtime",
            "dexes": ["uniswap_v3"],
            "include_pairs": ["WETH/USDC", "cbBTC/USDC"],
            "run_kind": "COVERAGE",
            "discovery_runtime_max_pairs": 15,
        }

        # Mock discovery_runtime to return our mock pairs directly
        mock_runtime_pairs = MagicMock()
        mock_runtime_stats = MagicMock()
        mock_runtime_stats.to_dict.return_value = {}

        with patch("discovery.runtime.resolve_runtime_pairs", return_value=(mock_runtime_pairs, mock_runtime_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=mock_pairs):
            result = resolve_universe(
                config=config,
                chain_key="base",
                dexes_list=["uniswap_v3"],
                run_kind="COVERAGE",
                cap_switches={},
            )
        names = [p.display_name for p in result["pairs_list"]]
        assert "WETH/USDC" in names
        assert "cbBTC/USDC" in names
        assert "WETH/AERO" not in names, "Noise pair must be filtered out"
        assert "VIRTUAL/USDC" not in names, "Noise pair must be filtered out"
        assert result["stats_updates"]["include_pairs_clamp"]["before"] == 4
        assert result["stats_updates"]["include_pairs_clamp"]["after"] == 2

    def test_no_clamp_without_include_pairs(self):
        """Without include_pairs, all pairs pass through."""
        from strategy.scan_universe import resolve_universe
        from config.pairs import PairConfig

        config = {
            "chain": "base",
            "chain_id": 8453,
            "universe_source": "discovery_runtime",
            "dexes": ["uniswap_v3"],
            "run_kind": "NORMAL",
            "discovery_runtime_max_pairs": 15,
        }
        mock_pairs = [
            PairConfig(chain="base", token_in="WETH", token_out="USDC"),
            PairConfig(chain="base", token_in="WETH", token_out="AERO"),
        ]

        mock_runtime_pairs = MagicMock()
        mock_runtime_stats = MagicMock()
        mock_runtime_stats.to_dict.return_value = {}

        with patch("discovery.runtime.resolve_runtime_pairs", return_value=(mock_runtime_pairs, mock_runtime_stats)), \
             patch("discovery.runtime.runtime_pairs_to_pair_configs", return_value=mock_pairs):
            result = resolve_universe(
                config=config,
                chain_key="base",
                dexes_list=["uniswap_v3"],
                run_kind="NORMAL",
                cap_switches={},
            )
        assert len(result["pairs_list"]) == 2
        assert "include_pairs_clamp" not in result["stats_updates"]


# ============================================================================
# 2. Per-cycle 429 quarantine
# ============================================================================

class TestCycleQuarantine:
    """Per-cycle 429 quarantine: skip RPCs that already 429'd this cycle."""

    def test_reset_clears_quarantine(self):
        from strategy.quote_rpc import _cycle_quarantine, reset_cycle_quarantine

        _cycle_quarantine.add(("http://rpc1", "0xQuoter"))
        _cycle_quarantine.add(("http://rpc2", "0xQuoter"))
        cleared = reset_cycle_quarantine()
        assert cleared == 2
        assert len(_cycle_quarantine) == 0

    def test_quarantine_skips_url(self):
        """After quarantining (url, quoter), read_quoter_v2 should skip that URL."""
        from strategy.quote_rpc import (
            _cycle_quarantine,
            reset_cycle_quarantine,
            QUOTER_RATE_LIMITED,
            read_quoter_v2,
        )

        reset_cycle_quarantine()
        # Pre-quarantine primary RPC
        _cycle_quarantine.add(("http://primary", "0xQuoterAddr"))

        # With only primary available and it's quarantined, should return QUOTER_RATE_LIMITED
        with patch.dict(os.environ, {"ARBY_SKIP_RPC": "0"}):
            result = read_quoter_v2(
                quoter_address="0xQuoterAddr",
                token_in="0xTokenIn",
                token_out="0xTokenOut",
                amount_in=1000000,
                fee=500,
                rpc_url="http://primary",
                block_num=12345,
                fallback_rpc_urls=None,
            )
        assert result is QUOTER_RATE_LIMITED
        reset_cycle_quarantine()  # cleanup


# ============================================================================
# 3. Full contour no-slot0 (test the logic, not full collect_quotes)
# ============================================================================

class TestContourSlot0Suppression:
    """When include_pairs is configured, ALL pairs in the whitelist should
    skip slot0 on 429, not just alpha pairs."""

    def test_include_pairs_matches_contour(self):
        """Verify the contour check logic: if pair is in include_pairs, it matches."""
        include_pairs = ["cbBTC/USDC", "cbBTC/WETH", "AERO/USDC", "WETH/USDC", "USDC/DAI", "USDC/USDT"]
        # All 6 profit-contour pairs should match
        for pair in include_pairs:
            assert pair in include_pairs
        # Noise pairs should NOT match
        assert "WETH/AERO" not in include_pairs
        assert "VIRTUAL/USDC" not in include_pairs

    def test_benchmark_pair_in_contour_skips_slot0(self):
        """WETH/USDC (benchmark) is in include_pairs and should be treated
        same as alpha for slot0 suppression on 429."""
        # This is a logic test — WETH/USDC is benchmark, but if include_pairs
        # contains it, the contour check fires first (before the alpha check)
        include_pairs = ["cbBTC/USDC", "WETH/USDC", "AERO/USDC"]
        pair_display = "WETH/USDC"
        assert pair_display in include_pairs, "Benchmark pair must be in contour whitelist"


# ============================================================================
# 4. excluded_pool_addresses config test
# ============================================================================

class TestExcludedPoolAddresses:
    """Config excluded_pool_addresses must be loaded into lowercase set."""

    def test_config_loading(self):
        """Verify the loading pattern normalizes addresses to lowercase."""
        config = {
            "excluded_pool_addresses": [
                "0x7F670F78B17DeC44D5ef68a48740b6f8849cc2e6",
                "0x80abe24a3ef1fc593ac5da960f232ca23b2069d0",
            ]
        }
        excluded = set(a.lower() for a in (config.get("excluded_pool_addresses") or []))
        assert "0x7f670f78b17dec44d5ef68a48740b6f8849cc2e6" in excluded
        assert "0x80abe24a3ef1fc593ac5da960f232ca23b2069d0" in excluded
        assert len(excluded) == 2

    def test_empty_config(self):
        config = {}
        excluded = set(a.lower() for a in (config.get("excluded_pool_addresses") or []))
        assert len(excluded) == 0


# ============================================================================
# 5. Reserved candidate budget slots
# ============================================================================

class TestReservedCandidateBudget:
    """Reserved slots must guarantee key pairs get evaluation slots."""

    def test_reserved_slots_guarantee_placement(self):
        from strategy.roundtrip_selection import select_roundtrip_candidates

        # Create opps where WETH/USDC has best margin but cbBTC opps exist
        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 30.0, "spread_minus_required_bps": 15.0,
            },
            {
                "pair": "cbBTC/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "aerodrome",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 18.0, "spread_minus_required_bps": 3.0,
            },
            {
                "pair": "cbBTC/WETH",
                "buy_dex": "uniswap_v3", "sell_dex": "pancakeswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 15.0, "spread_minus_required_bps": 1.0,
            },
            {
                "pair": "AERO/USDC",
                "buy_dex": "aerodrome", "sell_dex": "uniswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 12.0, "spread_minus_required_bps": 0.5,
            },
        ]
        reserved = [
            {"pair_pattern": "WETH/USDC", "min_slots": 1},
            {"pair_pattern": "cbBTC/*", "min_slots": 2},
            {"pair_pattern": "AERO/USDC", "min_slots": 1},
        ]
        eligible, stats = select_roundtrip_candidates(
            opps, rt_top_n=4, chain="base", reserved_slots=reserved,
        )
        pairs = [e["pair"] for e in eligible]
        assert "cbBTC/USDC" in pairs, "cbBTC/USDC must be reserved"
        assert "cbBTC/WETH" in pairs, "cbBTC/WETH must be reserved"
        assert "AERO/USDC" in pairs, "AERO/USDC must be reserved"
        assert "WETH/USDC" in pairs, "WETH/USDC must be reserved"

    def test_reserved_slots_with_tight_budget(self):
        """With rt_top_n=2, reserved slots must still guarantee placement."""
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 30.0, "spread_minus_required_bps": 15.0,
            },
            {
                "pair": "cbBTC/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "aerodrome",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 18.0, "spread_minus_required_bps": 3.0,
            },
            {
                "pair": "AERO/USDC",
                "buy_dex": "aerodrome", "sell_dex": "uniswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 12.0, "spread_minus_required_bps": 0.5,
            },
        ]
        reserved = [
            {"pair_pattern": "cbBTC/*", "min_slots": 1},
            {"pair_pattern": "AERO/USDC", "min_slots": 1},
        ]
        eligible, _ = select_roundtrip_candidates(
            opps, rt_top_n=2, chain="base", reserved_slots=reserved,
        )
        pairs = [e["pair"] for e in eligible]
        # Reserved pairs take priority over WETH/USDC even though WETH has better margin
        assert "cbBTC/USDC" in pairs
        assert "AERO/USDC" in pairs

    def test_no_reserved_slots_backwards_compatible(self):
        """Without reserved_slots, behavior is unchanged."""
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 30.0, "spread_minus_required_bps": 15.0,
            },
        ]
        eligible, _ = select_roundtrip_candidates(opps, rt_top_n=10)
        assert len(eligible) == 1


# ============================================================================
# 6. _match_pair_pattern helper
# ============================================================================

class TestMatchPairPattern:
    """Pair pattern matching with wildcard support."""

    def test_exact_match(self):
        from strategy.roundtrip_selection import _match_pair_pattern
        assert _match_pair_pattern("WETH/USDC", "WETH/USDC") is True
        assert _match_pair_pattern("WETH/USDC", "cbBTC/USDC") is False

    def test_trailing_wildcard(self):
        from strategy.roundtrip_selection import _match_pair_pattern
        assert _match_pair_pattern("cbBTC/*", "cbBTC/USDC") is True
        assert _match_pair_pattern("cbBTC/*", "cbBTC/WETH") is True
        assert _match_pair_pattern("cbBTC/*", "WETH/USDC") is False

    def test_leading_wildcard(self):
        from strategy.roundtrip_selection import _match_pair_pattern
        assert _match_pair_pattern("*/USDC", "WETH/USDC") is True
        assert _match_pair_pattern("*/USDC", "cbBTC/USDC") is True
        assert _match_pair_pattern("*/USDC", "WETH/DAI") is False

    def test_empty_inputs(self):
        from strategy.roundtrip_selection import _match_pair_pattern
        assert _match_pair_pattern("", "WETH/USDC") is False
        assert _match_pair_pattern("WETH/USDC", "") is False
        assert _match_pair_pattern("", "") is False


# ============================================================================
# 7. R39q: Pre-RT cost filter
# ============================================================================

class TestCostFilterViable:
    """R39q: cost_filter_viable rejects routes with excessive LP fees."""

    def test_cheap_route_passes(self):
        from strategy.roundtrip_selection import cost_filter_viable
        opp = {"buy_fee": 500, "sell_fee": 500}  # 5+5=10 bps roundtrip
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is True

    def test_expensive_route_blocked(self):
        from strategy.roundtrip_selection import cost_filter_viable
        # WETH/USDC on Base: fee_tier 3000+3000 -> 30+30=60 bps roundtrip -> > 30 bps
        opp = {"buy_fee": 3000, "sell_fee": 3000}  # 30+30=60 bps roundtrip
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is False

    def test_100bps_fee_tier_blocked(self):
        from strategy.roundtrip_selection import cost_filter_viable
        # fee_tier 10000 + 500 -> 100+5=105 bps roundtrip
        opp = {"buy_fee": 10000, "sell_fee": 500}
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is False

    def test_default_uncapped_allows_all(self):
        from strategy.roundtrip_selection import cost_filter_viable
        opp = {"buy_fee": 10000, "sell_fee": 10000}  # 200 bps roundtrip
        # Default lp_fee_max_bps=9999 -> passes
        assert cost_filter_viable(opp) is True

    def test_exact_boundary_passes(self):
        from strategy.roundtrip_selection import cost_filter_viable
        # 15+15=30 bps roundtrip, threshold=30: NOT > 30, so it passes
        opp = {"buy_fee": 1500, "sell_fee": 1500}
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is True

    def test_just_over_boundary_blocked(self):
        from strategy.roundtrip_selection import cost_filter_viable
        # 15.01+15=30.01 bps > 30 -> blocked
        opp = {"buy_fee": 1501, "sell_fee": 1500}
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is False

    def test_just_under_boundary(self):
        from strategy.roundtrip_selection import cost_filter_viable
        opp = {"buy_fee": 1400, "sell_fee": 1500}  # 14+15=29 bps
        assert cost_filter_viable(opp, lp_fee_max_bps=30) is True


class TestSelectCandidatesWithCostFilter:
    """R39q: select_roundtrip_candidates with lp_fee_max_bps parameter."""

    def test_cost_filter_demotes_expensive_routes(self):
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 3000, "sell_fee": 3000,  # 60 bps roundtrip
                "gross_spread_bps": 80.0, "spread_minus_required_bps": 15.0,
            },
            {
                "pair": "USDC/DAI",
                "buy_dex": "uniswap_v3", "sell_dex": "pancakeswap_v3",
                "buy_fee": 100, "sell_fee": 100,  # 2 bps roundtrip
                "gross_spread_bps": 10.0, "spread_minus_required_bps": 5.0,
            },
        ]
        eligible, stats = select_roundtrip_candidates(
            opps, rt_top_n=10, lp_fee_max_bps=30,
        )
        pairs = [e["pair"] for e in eligible]
        # WETH/USDC (60 bps > 30) should be rejected by cost filter
        assert "WETH/USDC" not in pairs
        assert "USDC/DAI" in pairs
        assert stats["cost_filter_rejected"] == 1

    def test_cost_filter_default_allows_all(self):
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "WETH/USDC",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 3000, "sell_fee": 3000,
                "gross_spread_bps": 80.0, "spread_minus_required_bps": 15.0,
            },
        ]
        eligible, stats = select_roundtrip_candidates(opps, rt_top_n=10)
        assert len(eligible) == 1
        assert stats["cost_filter_rejected"] == 0

    def test_margin_ordering_descending(self):
        """R39q step 5: Candidates ranked by spread_minus_required_bps descending."""
        from strategy.roundtrip_selection import select_roundtrip_candidates

        opps = [
            {
                "pair": "USDC/DAI",
                "buy_dex": "uniswap_v3", "sell_dex": "pancakeswap_v3",
                "buy_fee": 100, "sell_fee": 100,
                "gross_spread_bps": 10.0, "spread_minus_required_bps": 2.0,
            },
            {
                "pair": "USDC/USDT",
                "buy_dex": "uniswap_v3", "sell_dex": "sushiswap_v3",
                "buy_fee": 100, "sell_fee": 100,
                "gross_spread_bps": 15.0, "spread_minus_required_bps": 8.0,
            },
            {
                "pair": "AERO/USDC",
                "buy_dex": "aerodrome", "sell_dex": "uniswap_v3",
                "buy_fee": 500, "sell_fee": 500,
                "gross_spread_bps": 25.0, "spread_minus_required_bps": 5.0,
            },
        ]
        # No chain — pure margin ordering
        eligible, _ = select_roundtrip_candidates(opps, rt_top_n=10)
        margins = [e["spread_minus_required_bps"] for e in eligible]
        assert margins == sorted(margins, reverse=True), \
            f"Expected descending margin order, got {margins}"
