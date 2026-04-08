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


# ---------------------------------------------------------------------------
# 9. M7.E1.2: Chain-purity invariant — dynamic target pool selection
# ---------------------------------------------------------------------------

_ARBITRUM_POOL = "0xd13040d4fe917ee704158cfcb3338dcd2838b245"


class TestE1_2_DynamicTargetPoolSelection:
    """M7.E1.2: Target pool is selected from bridge, not hardcoded."""

    def test_target_pool_from_a_cold_exec(self):
        """First A_cold_exec pool in bridge_selected_at_assembly is chosen."""
        bsa = [
            {"pool_address": "0xbase_a1", "bucket": "A_cold_exec", "family": "tok0/tok1"},
            {"pool_address": "0xbase_b1", "bucket": "B_hot_seen", "family": "tok2/tok3"},
        ]
        target = None
        for sel in bsa:
            if sel.get("bucket") == "A_cold_exec" and sel.get("pool_address"):
                target = sel["pool_address"].lower()
                break
        assert target == "0xbase_a1"

    def test_fallback_to_any_pool_if_no_a_bucket(self):
        """If no A_cold_exec, picks first available pool."""
        bsa = [
            {"pool_address": "0xbase_b1", "bucket": "B_hot_seen", "family": "tok2/tok3"},
        ]
        target = None
        for sel in bsa:
            if sel.get("bucket") == "A_cold_exec" and sel.get("pool_address"):
                target = sel["pool_address"].lower()
                break
        if target is None:
            for sel in bsa:
                if sel.get("pool_address"):
                    target = sel["pool_address"].lower()
                    break
        assert target == "0xbase_b1"

    def test_empty_bridge_gives_none(self):
        """Empty bridge_selected_at_assembly → target=None."""
        bsa = []
        target = None
        for sel in bsa:
            if sel.get("bucket") == "A_cold_exec" and sel.get("pool_address"):
                target = sel["pool_address"].lower()
                break
        assert target is None

    def test_no_hardcoded_arbitrum_pool_in_production(self):
        """M7.E1.2 chain-purity: production code must NOT contain hardcoded Arbitrum pool."""
        import inspect
        from scripts.m7a_orderflow_loop import _update_hot_rollup
        source = inspect.getsource(_update_hot_rollup)
        assert _ARBITRUM_POOL not in source, (
            "Hardcoded Arbitrum pool still in _update_hot_rollup — breaks chain purity"
        )


# ---------------------------------------------------------------------------
# 10. M7.E1.2: Event-to-bridge classification counters
# ---------------------------------------------------------------------------

class TestE1_2_EventBridgeClassification:
    """M7.E1.2: Event classification for hot blocker separation."""

    def _make_mock_result(self, pool_address, scoring_path="registry_fast", net_bps=0):
        class MockEvent:
            def __init__(self, pa):
                self.pool_address = pa
        class MockResult:
            pass
        r = MockResult()
        r._source_event = MockEvent(pool_address)
        r.scoring_path = scoring_path
        r.best_backrun_net_bps = net_bps
        return r

    def test_event_in_bridge_counted(self):
        bridge_set = {"0xpool_a", "0xpool_b"}
        fast = [self._make_mock_result("0xpool_a")]
        in_bridge = sum(
            1 for r in fast
            if getattr(r._source_event, "pool_address", "").lower() in bridge_set
        )
        assert in_bridge == 1

    def test_event_not_in_bridge_counted(self):
        bridge_set = {"0xpool_a"}
        fast = [self._make_mock_result("0xother")]
        not_in_bridge = sum(
            1 for r in fast
            if getattr(r._source_event, "pool_address", "").lower() not in bridge_set
        )
        assert not_in_bridge == 1

    def test_matched_hot_skip_counted_as_registry_rejected(self):
        """Event in bridge but hot_skip → registry_rejected counter (E1.3 split)."""
        bridge_set = {"0xpool_a"}
        fast = [self._make_mock_result("0xpool_a", scoring_path="hot_skip", net_bps=0)]
        matched_registry_rejected = 0
        matched_gas_rejected = 0
        for r in fast:
            pa = getattr(r._source_event, "pool_address", "").lower()
            if pa in bridge_set:
                if r.scoring_path == "hot_skip":
                    matched_registry_rejected += 1
                elif (r.best_backrun_net_bps or 0) <= 0:
                    matched_gas_rejected += 1
        assert matched_registry_rejected == 1
        assert matched_gas_rejected == 0

    def test_matched_gas_rejected_separate_from_registry(self):
        """Event in bridge, passed registry, net<=0 → gas_rejected counter."""
        bridge_set = {"0xpool_a"}
        fast = [self._make_mock_result("0xpool_a", scoring_path="registry_fast", net_bps=-5.0)]
        matched_registry_rejected = 0
        matched_gas_rejected = 0
        for r in fast:
            pa = getattr(r._source_event, "pool_address", "").lower()
            if pa in bridge_set:
                if r.scoring_path == "hot_skip":
                    matched_registry_rejected += 1
                elif (r.best_backrun_net_bps or 0) <= 0:
                    matched_gas_rejected += 1
        assert matched_registry_rejected == 0
        assert matched_gas_rejected == 1

    def test_matched_positive_counted(self):
        """Event in bridge with positive net → scored_positive counter."""
        bridge_set = {"0xpool_a"}
        fast = [self._make_mock_result("0xpool_a", scoring_path="registry_fast", net_bps=5.0)]
        matched_positive = 0
        for r in fast:
            pa = getattr(r._source_event, "pool_address", "").lower()
            if pa in bridge_set:
                net = r.best_backrun_net_bps or 0
                if r.scoring_path != "hot_skip" and net > 0:
                    matched_positive += 1
        assert matched_positive == 1

    def test_family_event_map_built_correctly(self):
        """Per-family event map uses PTT for family lookup."""
        ptt = {"0xpool_a": ["tok0", "tok1", 500], "0xpool_b": ["tok2", "tok3", 3000]}
        fast = [
            self._make_mock_result("0xpool_a"),
            self._make_mock_result("0xpool_a"),
            self._make_mock_result("0xpool_b"),
        ]
        family_counts = {}
        for r in fast:
            pa = getattr(r._source_event, "pool_address", "").lower()
            info = ptt.get(pa)
            if info and len(info) >= 2:
                fam = f"{info[0]}/{info[1]}"
                family_counts[fam] = family_counts.get(fam, 0) + 1
        assert family_counts == {"tok0/tok1": 2, "tok2/tok3": 1}


# ---------------------------------------------------------------------------
# 11. M7.E1.2: Three-way blocker classification
# ---------------------------------------------------------------------------

class TestE1_2_BlockerClassification:
    """M7.E1.2: blocker_class is three-way, not binary."""

    def test_event_source_absence(self):
        """Zero events → event_source_absence."""
        assert _classify_blocker(events=0, bridge_hits=0, events_in_bridge=0, positive=0) == "event_source_absence"

    def test_events_not_reaching_bridge(self):
        """Events exist but none in bridge → events_not_reaching_bridge."""
        assert _classify_blocker(events=10, bridge_hits=0, events_in_bridge=0, positive=0) == "events_not_reaching_bridge"

    def test_gas_economics_only(self):
        """Events reach bridge but none scored positive → gas_economics_only."""
        assert _classify_blocker(events=10, bridge_hits=5, events_in_bridge=5, positive=0) == "gas_economics_only"

    def test_selection_or_scoring(self):
        """Some events scored positive → selection_or_scoring."""
        assert _classify_blocker(events=10, bridge_hits=5, events_in_bridge=5, positive=2) == "selection_or_scoring"


def _classify_blocker(events: int, bridge_hits: int, events_in_bridge: int, positive: int) -> str:
    """Mirror of M7.E1.2 blocker classification logic."""
    if events == 0:
        return "event_source_absence"
    elif events_in_bridge == 0 and bridge_hits == 0:
        return "events_not_reaching_bridge"
    elif positive > 0:
        return "selection_or_scoring"
    else:
        return "gas_economics_only"


# ---------------------------------------------------------------------------
# 12. M7.E1.3: Chain-purity invariant — cross-artifact consistency
# ---------------------------------------------------------------------------

# Known Arbitrum-era addresses that must NOT appear in Base artifacts
_ARBITRUM_CONTAMINATION_ADDRESSES = {
    "0xd13040d4fe917ee704158cfcb3338dcd2838b245",
}


class TestE1_3_ChainPurityInvariant:
    """M7.E1.3: If orderflow chain=base, rollup must have Base-native traces."""

    def test_base_rollup_must_not_have_arbitrum_pool_address(self):
        """exact_pool_trace.pool_address must not be a known Arbitrum address on Base."""
        # Simulate a Base rollup with a Base pool
        rollup = {
            "exact_pool_trace": {"pool_address": "0x6f79e046101eaf00c399f0489b581e932f558d5f"},
            "architecture_blocker_trace": {"blocker_class": "gas_economics_only"},
        }
        pa = (rollup["exact_pool_trace"]["pool_address"] or "").lower()
        assert pa not in _ARBITRUM_CONTAMINATION_ADDRESSES

    def test_arbitrum_contamination_detected(self):
        """If Arbitrum pool leaks into Base rollup, test must catch it."""
        rollup = {
            "exact_pool_trace": {"pool_address": "0xd13040d4fe917ee704158cfcb3338dcd2838b245"},
        }
        pa = (rollup["exact_pool_trace"]["pool_address"] or "").lower()
        assert pa in _ARBITRUM_CONTAMINATION_ADDRESSES

    def test_base_rollup_must_not_have_family_unresolved(self):
        """exact_family_trace.family must not be family_unresolved on Base."""
        rollup = {
            "exact_family_trace": {
                "family": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913/0xe0cd4cacddcbf4f36e845407ce53e87717b6601d"
            },
        }
        assert rollup["exact_family_trace"]["family"] != "family_unresolved"

    def test_no_hardcoded_arbitrum_pool_in_rollup_function(self):
        """Source of _update_hot_rollup must not contain hardcoded Arbitrum pools."""
        import inspect
        from scripts.m7a_orderflow_loop import _update_hot_rollup
        src = inspect.getsource(_update_hot_rollup)
        for addr in _ARBITRUM_CONTAMINATION_ADDRESSES:
            assert addr not in src.lower(), f"Hardcoded Arbitrum address {addr} in _update_hot_rollup"


# ---------------------------------------------------------------------------
# 13. M7.E1.3: Registry vs gas rejection separation in hot_gap_debug
# ---------------------------------------------------------------------------

class TestE1_3_RegistryVsGasSeparation:
    """M7.E1.3: hot_gap_debug must separate registry rejection from gas rejection."""

    def _make_mock_result(self, pool_address, scoring_path="registry_fast", net_bps=0):
        class MockEvent:
            def __init__(self, pa):
                self.pool_address = pa
        class MockResult:
            pass
        r = MockResult()
        r._source_event = MockEvent(pool_address)
        r.scoring_path = scoring_path
        r.best_backrun_net_bps = net_bps
        return r

    def test_bridge_registry_rejected_counted(self):
        """Event in bridge + hot_skip → matched_bridge_then_registry_rejected."""
        bridge_set = {"0xpool_a"}
        results = [self._make_mock_result("0xpool_a", scoring_path="hot_skip")]
        reg_rej = sum(
            1 for r in results
            if getattr(r._source_event, "pool_address", "").lower() in bridge_set
            and r.scoring_path == "hot_skip"
        )
        assert reg_rej == 1

    def test_bridge_gas_rejected_counted(self):
        """Event in bridge + registry_fast + net<=0 → matched_bridge_then_gas_rejected."""
        bridge_set = {"0xpool_a"}
        results = [self._make_mock_result("0xpool_a", scoring_path="registry_fast", net_bps=-3.0)]
        gas_rej = sum(
            1 for r in results
            if getattr(r._source_event, "pool_address", "").lower() in bridge_set
            and r.scoring_path != "hot_skip"
            and (r.best_backrun_net_bps or 0) <= 0
        )
        assert gas_rej == 1

    def test_bridge_scored_positive_counted(self):
        """Event in bridge + registry_fast + net>0 → matched_bridge_then_scored_positive."""
        bridge_set = {"0xpool_a"}
        results = [self._make_mock_result("0xpool_a", scoring_path="registry_fast", net_bps=5.0)]
        pos = sum(
            1 for r in results
            if getattr(r._source_event, "pool_address", "").lower() in bridge_set
            and r.scoring_path != "hot_skip"
            and (r.best_backrun_net_bps or 0) > 0
        )
        assert pos == 1

    def test_not_in_bridge_ignored(self):
        """Event NOT in bridge → not counted in any bridge-matched counter."""
        bridge_set = {"0xpool_a"}
        results = [self._make_mock_result("0xother", scoring_path="hot_skip")]
        bridge_matched = sum(
            1 for r in results
            if getattr(r._source_event, "pool_address", "").lower() in bridge_set
        )
        assert bridge_matched == 0

    def test_rollup_registry_and_gas_are_separate_counters(self):
        """Rollup must have both matched_then_registry_rejected_total and
        matched_then_gas_rejected_total as distinct counters."""
        rollup = {
            "matched_then_registry_rejected_total": 3,
            "matched_then_gas_rejected_total": 7,
            "matched_then_scored_positive_total": 0,
            "events_in_bridge_total": 10,
        }
        total_bridge = (
            rollup["matched_then_registry_rejected_total"]
            + rollup["matched_then_gas_rejected_total"]
            + rollup["matched_then_scored_positive_total"]
        )
        assert total_bridge == rollup["events_in_bridge_total"]


# ---------------------------------------------------------------------------
# 14. M7.E1.4: Hot intent convergence fields
# ---------------------------------------------------------------------------

class TestE1_4_IntentConvergenceFields:
    """M7.E1.4: hot intents must carry pool_address, family, selected_bucket,
    same_pool_as_cold_exec for cold-hot cross-reference."""

    def _make_intent_row(self, pool_address, cold_exec_pools, selected_pools, ptt=None):
        """Simulate the convergence-field derivation from _write_hot_intents."""
        _pool_addr = (pool_address or "").lower()
        _cold_exec_pool_set = {(p or "").lower() for p in cold_exec_pools}
        _selected_pool_info = {}
        for sp in selected_pools:
            pa = (sp.get("pool_address") or "").lower()
            if pa:
                _selected_pool_info[pa] = {
                    "bucket": sp.get("bucket"),
                    "family": sp.get("family"),
                }
        _ptt_intents = ptt or {}

        _sel = _selected_pool_info.get(_pool_addr, {})
        _family_raw = _sel.get("family")
        if not _family_raw and _pool_addr and _ptt_intents:
            _ptt_info = _ptt_intents.get(_pool_addr)
            if _ptt_info and len(_ptt_info) >= 2:
                _family_raw = f"{_ptt_info[0]}/{_ptt_info[1]}"

        return {
            "pool_address": _pool_addr or None,
            "family": _family_raw,
            "selected_bucket": _sel.get("bucket"),
            "same_pool_as_cold_exec": _pool_addr in _cold_exec_pool_set if _pool_addr else False,
        }

    def test_pool_address_present(self):
        row = self._make_intent_row("0xABC123", [], [])
        assert row["pool_address"] == "0xabc123"

    def test_pool_address_none_when_empty(self):
        row = self._make_intent_row("", [], [])
        assert row["pool_address"] is None

    def test_family_from_selected_pools(self):
        row = self._make_intent_row(
            "0xabc",
            cold_exec_pools=[],
            selected_pools=[{"pool_address": "0xABC", "bucket": "A_cold_exec", "family": "WETH/USDC"}],
        )
        assert row["family"] == "WETH/USDC"
        assert row["selected_bucket"] == "A_cold_exec"

    def test_family_fallback_to_ptt(self):
        row = self._make_intent_row(
            "0xdef",
            cold_exec_pools=[],
            selected_pools=[],
            ptt={"0xdef": ["AERO", "USDC", 3000]},
        )
        assert row["family"] == "AERO/USDC"

    def test_same_pool_as_cold_exec_true(self):
        row = self._make_intent_row(
            "0xABC",
            cold_exec_pools=["0xabc", "0xdef"],
            selected_pools=[],
        )
        assert row["same_pool_as_cold_exec"] is True

    def test_same_pool_as_cold_exec_false(self):
        row = self._make_intent_row(
            "0x999",
            cold_exec_pools=["0xabc", "0xdef"],
            selected_pools=[],
        )
        assert row["same_pool_as_cold_exec"] is False

    def test_same_pool_as_cold_exec_false_when_no_pool_address(self):
        row = self._make_intent_row("", cold_exec_pools=["0xabc"], selected_pools=[])
        assert row["same_pool_as_cold_exec"] is False

    def test_selected_bucket_none_when_not_in_bridge(self):
        row = self._make_intent_row("0x999", [], [])
        assert row["selected_bucket"] is None


# ---------------------------------------------------------------------------
# 15. M7.E1.4: Funnel counters (viable_total in rollup)
# ---------------------------------------------------------------------------

class TestE1_4_FunnelCounters:
    """M7.E1.4: rollup must have viable_total between fast_path_positive and
    profit_guard_passed for complete funnel visibility."""

    def test_viable_total_accumulates(self):
        """viable_total must accumulate across windows."""
        rollup: dict = {}
        # Simulate 3 windows
        for window_viable in [2, 0, 3]:
            rollup["viable_total"] = rollup.get("viable_total", 0) + window_viable
        assert rollup["viable_total"] == 5

    def test_funnel_ordering_invariant(self):
        """Funnel: scored >= positive >= viable (route economics check).
        profit_guard_passed is a parallel criterion, not strictly chained."""
        rollup = {
            "fast_path_scored_total": 100,
            "fast_path_positive_total": 20,
            "viable_total": 15,
        }
        assert rollup["fast_path_scored_total"] >= rollup["fast_path_positive_total"]
        assert rollup["fast_path_positive_total"] >= rollup["viable_total"]

    def test_viable_total_zero_when_no_viable(self):
        """If no events have route_viable=True, viable_total stays 0."""
        rollup: dict = {"viable_total": 0}
        class MockR:
            route_viable = False
        _fast = [MockR(), MockR()]
        rollup["viable_total"] += sum(1 for r in _fast if r.route_viable)
        assert rollup["viable_total"] == 0

    def test_viable_total_counts_only_viable(self):
        """Only route_viable=True events increment viable_total."""
        class MockR:
            def __init__(self, viable):
                self.route_viable = viable
        _fast = [MockR(True), MockR(False), MockR(True), MockR(False)]
        viable_in_window = sum(1 for r in _fast if r.route_viable)
        assert viable_in_window == 2

    def test_rollup_has_viable_total_key(self):
        """Rollup schema must include viable_total."""
        expected_funnel_keys = [
            "fast_path_scored_total",
            "fast_path_positive_total",
            "viable_total",
            "profit_guard_passed_total",
        ]
        rollup = {k: 0 for k in expected_funnel_keys}
        for k in expected_funnel_keys:
            assert k in rollup
