"""
M7.E1 — Tests for chain-aware infrastructure (Base Flashblocks event-source pilot).

Validates:
1. Chain-aware constants: prewarm pairs, gas floor, Chainlink feeds per chain
2. Flashblocks WS preference for Base in mode_ws_live
3. Backward compatibility: Arbitrum defaults unchanged
"""
from __future__ import annotations

import pytest

from m7.shared.constants import (
    CHAINLINK_FEEDS_ARBITRUM,
    CHAINLINK_FEEDS_BASE,
    GAS_FLOOR_BPS_ARBITRUM,
    GAS_FLOOR_BPS_BASE,
    PREWARM_PAIRS_ARBITRUM,
    PREWARM_PAIRS_BASE,
    get_chainlink_feeds,
    get_gas_floor_bps,
    get_prewarm_pairs,
)


# ---------------------------------------------------------------------------
# 1. Chain-aware prewarm pairs
# ---------------------------------------------------------------------------

class TestPrewarmPairs:
    def test_arbitrum_prewarm_pairs_default(self):
        pairs = get_prewarm_pairs("arbitrum_one")
        assert len(pairs) >= 3
        assert ("WETH", "USDC") in pairs

    def test_base_prewarm_pairs_narrow_contour(self):
        pairs = get_prewarm_pairs("base")
        assert ("USDC", "DAI") in pairs
        assert ("USDC", "USDT") in pairs
        assert ("WETH", "USDC") in pairs

    def test_base_prewarm_no_arb_token(self):
        """Base prewarm should not contain ARB (Arbitrum-specific token)."""
        pairs = get_prewarm_pairs("base")
        for a, b in pairs:
            assert a != "ARB" and b != "ARB"

    def test_unknown_chain_falls_back_to_arbitrum(self):
        pairs = get_prewarm_pairs("some_unknown_chain")
        assert pairs == PREWARM_PAIRS_ARBITRUM

    def test_prewarm_pairs_are_tuples_of_two(self):
        for chain in ("arbitrum_one", "base"):
            for pair in get_prewarm_pairs(chain):
                assert isinstance(pair, tuple)
                assert len(pair) == 2


# ---------------------------------------------------------------------------
# 2. Chain-aware Chainlink feeds
# ---------------------------------------------------------------------------

class TestChainlinkFeeds:
    def test_arbitrum_feeds_have_canonical_tokens(self):
        feeds = get_chainlink_feeds("arbitrum_one")
        assert "WETH" in feeds
        assert "USDC" in feeds
        assert "ARB" in feeds

    def test_base_feeds_have_base_tokens(self):
        feeds = get_chainlink_feeds("base")
        assert "WETH" in feeds
        assert "USDC" in feeds
        assert "DAI" in feeds
        assert "cbBTC" in feeds

    def test_base_feeds_no_arb(self):
        feeds = get_chainlink_feeds("base")
        assert "ARB" not in feeds

    def test_unknown_chain_falls_back_to_arbitrum(self):
        feeds = get_chainlink_feeds("unknown")
        assert feeds is CHAINLINK_FEEDS_ARBITRUM

    def test_feed_addresses_are_hex_strings(self):
        for chain in ("arbitrum_one", "base"):
            for token, addr in get_chainlink_feeds(chain).items():
                assert addr.startswith("0x"), f"{chain}/{token}: {addr}"
                assert len(addr) == 42, f"{chain}/{token}: {addr}"


# ---------------------------------------------------------------------------
# 3. Chain-aware gas floor
# ---------------------------------------------------------------------------

class TestGasFloor:
    def test_arbitrum_gas_floor_is_2(self):
        assert get_gas_floor_bps("arbitrum_one") == 2.0

    def test_base_gas_floor_is_lower(self):
        base_floor = get_gas_floor_bps("base")
        arb_floor = get_gas_floor_bps("arbitrum_one")
        assert base_floor < arb_floor
        assert base_floor == 0.5

    def test_unknown_chain_falls_back_to_arbitrum(self):
        assert get_gas_floor_bps("unknown") == GAS_FLOOR_BPS_ARBITRUM


# ---------------------------------------------------------------------------
# 4. Constants backward compatibility
# ---------------------------------------------------------------------------

class TestBackwardCompatibility:
    def test_gas_floor_bps_arbitrum_unchanged(self):
        assert GAS_FLOOR_BPS_ARBITRUM == 2.0

    def test_chainlink_feeds_arbitrum_has_10_tokens(self):
        assert len(CHAINLINK_FEEDS_ARBITRUM) == 10

    def test_prewarm_pairs_arbitrum_has_6(self):
        assert len(PREWARM_PAIRS_ARBITRUM) == 6

    def test_gas_floor_bps_base_exists(self):
        assert GAS_FLOOR_BPS_BASE == 0.5


# ---------------------------------------------------------------------------
# 5. Flashblocks WS preference for Base
# ---------------------------------------------------------------------------

class TestFlashblocksWSPreference:
    def test_flashblocks_ws_url_resolution(self):
        from chains.flashblocks import get_flashblocks_ws_url
        url = get_flashblocks_ws_url(None)
        assert url.startswith("wss://")
        assert "flashblocks" in url

    def test_flashblocks_ws_url_config_override(self):
        from chains.flashblocks import get_flashblocks_ws_url
        custom = "wss://custom.flashblocks.example.com/ws"
        url = get_flashblocks_ws_url(custom)
        assert url == custom

    def test_flashblocks_ws_url_env_override(self, monkeypatch):
        from chains.flashblocks import get_flashblocks_ws_url
        env_url = "wss://env.flashblocks.example.com/ws"
        monkeypatch.setenv("ARBY_FLASHBLOCKS_WS", env_url)
        url = get_flashblocks_ws_url("wss://config.example.com/ws")
        assert url == env_url

    def test_chains_yaml_has_base_flashblocks(self):
        from config import load_chains
        chains = load_chains()
        base = chains.get("base", {})
        assert "flashblocks_ws_endpoint" in base
        assert base["flashblocks_ws_endpoint"].startswith("wss://")

    def test_chains_yaml_has_base_flashblocks_http(self):
        from config import load_chains
        chains = load_chains()
        base = chains.get("base", {})
        assert "flashblocks_http_endpoint" in base
        assert base["flashblocks_http_endpoint"].startswith("https://")


# ---------------------------------------------------------------------------
# M7.E1.1: Gas breakdown fields in compact candidate rows
# ---------------------------------------------------------------------------
class TestE1_1_GasBreakdownInCompactCandidates:
    """
    M7.E1.1: _compact_candidate emits l1_data_gas_bps, l2_exec_gas_bps,
    total_gas_bps, gap_to_zero_bps for actionable per-candidate gas diagnostics.
    """

    def test_gas_fields_present_when_populated(self):
        from m7.orderflow.artifacts import build_replay_summary
        from tests.unit.conftest import _make_event, _make_result
        from m7.shared.constants import REJECT_GAS_EXCEEDS_GROSS

        e = _make_event()
        r = _make_result(
            event_id="g1",
            best_backrun_net_bps=-8.5,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
            event_block=100,
            event_detected_at_block=100,
            l2_gas_bps=2.5,
            l1_data_bps=10.0,
            total_gas_bps=12.5,
        )
        art = build_replay_summary([e], [r], mode="test", chain="base")
        near = art["near_executable_candidates"]
        assert len(near) == 1
        c = near[0]
        assert c["l1_data_gas_bps"] == 10.0
        assert c["l2_exec_gas_bps"] == 2.5
        assert c["total_gas_bps"] == 12.5
        assert c["gap_to_zero_bps"] == -8.5

    def test_gas_fields_none_when_not_set(self):
        from m7.orderflow.artifacts import build_replay_summary
        from tests.unit.conftest import _make_event, _make_result
        from m7.shared.constants import REJECT_GAS_EXCEEDS_GROSS

        e = _make_event()
        r = _make_result(
            event_id="g2",
            best_backrun_net_bps=-5.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
            event_block=200,
            event_detected_at_block=200,
        )
        art = build_replay_summary([e], [r], mode="test", chain="base")
        near = art["near_executable_candidates"]
        assert len(near) == 1
        c = near[0]
        assert c["l1_data_gas_bps"] is None
        assert c["l2_exec_gas_bps"] is None
        assert c["total_gas_bps"] is None
        assert c["gap_to_zero_bps"] == -5.0

    def test_gas_fields_in_top_executable_candidates(self):
        from m7.orderflow.artifacts import build_replay_summary
        from tests.unit.conftest import _make_event, _make_result

        e = _make_event()
        r = _make_result(
            event_id="exec1",
            best_backrun_net_bps=3.0,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=None,
            route_viable=True,
            size_valid_for_token=True,
            scoring_path="registry_direct",
            event_block=100,
            event_detected_at_block=100,
            l2_gas_bps=1.0,
            l1_data_bps=4.0,
            total_gas_bps=5.0,
        )
        art = build_replay_summary([e], [r], mode="test", chain="base")
        top = art["top_executable_candidates"]
        assert len(top) >= 1
        c = top[0]
        assert c["l1_data_gas_bps"] == 4.0
        assert c["l2_exec_gas_bps"] == 1.0
        assert c["total_gas_bps"] == 5.0
        assert c["gap_to_zero_bps"] == 3.0

    def test_gap_to_zero_matches_net_bps(self):
        """gap_to_zero_bps == net_bps by definition (distance from breakeven)."""
        from m7.orderflow.artifacts import build_replay_summary
        from tests.unit.conftest import _make_event, _make_result
        from m7.shared.constants import REJECT_GAS_EXCEEDS_GROSS

        e = _make_event()
        r = _make_result(
            event_id="gap1",
            best_backrun_net_bps=-2.28,
            block_lag=0,
            same_state_class="same_block",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            route_viable=False,
            size_valid_for_token=True,
            scoring_path="registry_direct",
            event_block=100,
            event_detected_at_block=100,
            total_gas_bps=10.0,
        )
        art = build_replay_summary([e], [r], mode="test", chain="base")
        near = art["near_executable_candidates"]
        assert len(near) == 1
        assert near[0]["gap_to_zero_bps"] == near[0]["net_bps"]


# ---------------------------------------------------------------------------
# 6. start_nonstop_runtime chain passthrough
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# 7. build_replay_summary chain parameter
# ---------------------------------------------------------------------------

class TestBuildReplaySummaryChain:
    def test_default_chain_is_arbitrum(self):
        from m7.orderflow.artifacts import build_replay_summary
        art = build_replay_summary([], [], mode="test")
        assert art["chain"] == "arbitrum_one"

    def test_chain_param_base(self):
        from m7.orderflow.artifacts import build_replay_summary
        art = build_replay_summary([], [], mode="test", chain="base")
        assert art["chain"] == "base"

    def test_chain_param_none_defaults_to_arbitrum(self):
        from m7.orderflow.artifacts import build_replay_summary
        art = build_replay_summary([], [], mode="test", chain=None)
        assert art["chain"] == "arbitrum_one"


# ---------------------------------------------------------------------------
# 8. start_nonstop_runtime chain passthrough
# ---------------------------------------------------------------------------

class TestNonstopRuntimeChain:
    def test_parse_args_default_chain(self):
        """start_nonstop_runtime default chain is arbitrum_one."""
        import sys
        sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent.parent))
        from scripts.start_nonstop_runtime import parse_args
        import unittest.mock as mock
        with mock.patch("sys.argv", ["prog", "--hours", "0.01"]):
            args = parse_args()
        assert args.chain == "arbitrum_one"

    def test_parse_args_base_chain(self):
        from scripts.start_nonstop_runtime import parse_args
        import unittest.mock as mock
        with mock.patch("sys.argv", ["prog", "--hours", "0.01", "--chain", "base"]):
            args = parse_args()
        assert args.chain == "base"
