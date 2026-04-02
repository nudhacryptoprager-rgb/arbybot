"""
Blocker tags, debug rows, pool truth, and coverage tests for M7 orderflow.

Locks:
- Low-lag debug rows (M7.A.5.15)
- Coverage truth metrics for low-lag subset (M7.A.5.15)
- 4 synthetic low-lag paths (M7.A.5.15)
- Pool-class truth, dex family histogram (M7.A.5.16)
- Pool code empty path (M7.A.5.16)
- Dex family guess categories (M7.A.5.16)
- V2 low-lag metrics, pool_state_read_path in debug rows (M7.A.5.17)
- Blocker tags artifact (M7.A.5.18)
- Quote-fail provenance (M7.A.5.19)
- Low-lag watchlist (M7.A.5.18)
"""
from __future__ import annotations

from m7.orderflow.artifacts import build_replay_summary
from m7.shared.constants import (
    ADMISSION_CANONICAL,
    ADMISSION_ONCHAIN_ENRICHED,
    ALL_BLOCKER_TAGS,
    BLOCKER_GAS_L1_DATA_DOMINANT,
    BLOCKER_LOW_LAG_INACTIVE_POOL,
    BLOCKER_LOW_LAG_NONE_THIS_WINDOW,
    BLOCKER_LOW_LAG_NO_COUNTER_POOL,
    BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY,
    BLOCKER_LOW_LAG_V2_UNSUPPORTED,
    BLOCKER_SUBGRAPH_API_KEY_REQUIRED,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_NO_COUNTER_POOL,
    REJECT_RPC_QUOTE_FAIL,
    REJECT_STALE_POSITIVE,
    REJECT_TOKEN_PAIR_UNRESOLVED,
)

from tests.unit.conftest import _make_event, _make_result


# ===========================================================================
# M7.A.5.15: Low-Lag Debug Rows
# ===========================================================================


class TestM7A515LowLagDebugRows:
    """M7.A.5.15: build_replay_summary emits low_lag_debug_rows."""

    def test_low_lag_debug_rows_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_debug_rows" in art
        assert art["low_lag_debug_rows"] == []

    def test_low_lag_debug_rows_present_with_results(self):
        r = _make_result(
            event_id="debug_row_1", block_lag=1,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="pool_read_failed",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "debug_row_1"
        assert rows[0]["reject_reason"] == REJECT_TOKEN_PAIR_UNRESOLVED

    def test_low_lag_debug_rows_only_low_lag(self):
        low = _make_result(
            event_id="low_lag", block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL, pair_resolved=True,
            actual_pair="LINK/UNI", event_block=100, event_detected_at_block=100,
        )
        stale = _make_result(
            event_id="stale", block_lag=10,
            reject_reason=REJECT_NO_COUNTER_POOL, pair_resolved=True,
            actual_pair="LINK/UNI",
        )
        art = build_replay_summary([], [low, stale], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert rows[0]["event_id"] == "low_lag"

    def test_low_lag_debug_row_keys(self):
        r = _make_result(
            event_id="key_check", block_lag=2,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="X/Y",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=3, event_block=100, event_detected_at_block=102,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        expected_keys = {
            "event_id", "block_lag", "reject_reason", "pair_resolved",
            "actual_pair", "pair_unresolved_detail", "token_admitted",
            "admission_source", "known_pools", "active_pools",
            "counter_venue_count", "pool_contract_truth",
            "pool_state_read_path",
            "quote_fail_stage", "quote_fail_venue",
            "quote_fail_exception_short",
        }
        assert set(row.keys()) == expected_keys


class TestM7A515LowLagCoverageTruth:
    """M7.A.5.15: Coverage truth metrics for low-lag subset."""

    def test_coverage_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_coverage_truth" in art
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 0
        assert ct["no_counter_pool_rate"] is None

    def test_coverage_truth_rates_with_results(self):
        results = [
            _make_result(
                event_id="cov_1", block_lag=0, reject_reason=REJECT_NO_COUNTER_POOL,
                pair_resolved=True, event_block=100, event_detected_at_block=100,
            ),
            _make_result(
                event_id="cov_2", block_lag=1, reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
                pair_resolved=True, event_block=100, event_detected_at_block=101,
                coverage_result={"known_pools_total": 3, "active_pools_total": 0,
                                 "active_buy_venues": 0, "active_sell_venues": 0},
            ),
            _make_result(
                event_id="cov_3", block_lag=2, best_backrun_net_bps=-1.5,
                route_viable=False, pair_resolved=True,
                event_block=100, event_detected_at_block=102,
                coverage_result={"known_pools_total": 5, "active_pools_total": 2,
                                 "active_buy_venues": 1, "active_sell_venues": 1},
            ),
        ]
        art = build_replay_summary([], results, mode="ws_live")
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 8
        assert ct["active_pools_total"] == 2


class TestM7A515FourLowLagPaths:
    """M7.A.5.15: 4 synthetic low-lag paths."""

    def test_path_unresolved_pair(self):
        r = _make_result(
            event_id="path_unresolved", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="pool_read_failed",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
        assert art["events_scored_low_lag"] == 0
        assert art["low_lag_pair_resolution_rate"] == 0.0

    def test_path_no_counter_pool(self):
        r = _make_result(
            event_id="path_no_counter", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0x3212dc0f/WETH",
            token_admitted=True, admission_source=ADMISSION_ONCHAIN_ENRICHED,
            counter_venue_count=0, event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["low_lag_pair_resolution_rate"] == 1.0
        assert art["low_lag_counter_coverage_rate"] == 0.0

    def test_path_inactive_counter_pool(self):
        r = _make_result(
            event_id="path_inactive", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
            counter_venue_count=2, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        ct = art["low_lag_coverage_truth"]
        assert ct["known_pools_total"] == 2
        assert ct["active_pools_total"] == 0

    def test_path_active_reaches_scoring(self):
        r = _make_result(
            event_id="path_scored", block_lag=0, pair_resolved=True,
            actual_pair="WETH/USDC", token_admitted=True,
            admission_source=ADMISSION_CANONICAL,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
            counter_venue_count=4, best_backrun_net_bps=-1.5,
            route_viable=False, event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["events_scored_low_lag"] == 1
        assert art["low_lag_scored_results_rate"] == 1.0


# ===========================================================================
# M7.A.5.16: Pool-Class Truth
# ===========================================================================


class TestM7A516DebugRowPoolTruth:
    """M7.A.5.16: low_lag_debug_rows includes pool_contract_truth."""

    def test_debug_row_has_pool_contract_truth_key(self):
        r = _make_result(
            event_id="row_pct", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_TOKEN0_REVERT",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xabc", "code_present": True,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        rows = art["low_lag_debug_rows"]
        assert len(rows) == 1
        assert "pool_contract_truth" in rows[0]
        assert rows[0]["pool_contract_truth"]["code_present"] is True

    def test_debug_row_pool_truth_none_when_resolved(self):
        r = _make_result(
            event_id="row_resolved", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="WETH/USDC",
            pool_contract_truth=None, event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        assert art["low_lag_debug_rows"][0]["pool_contract_truth"] is None


class TestM7A516ThreeLowLagClasses:
    """M7.A.5.16: pool_class_truth rates and dex_family_histogram."""

    def _make_class_results(self):
        results = []
        results.append(_make_result(
            event_id="c1_unsupported", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_TOKEN0_REVERT",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xaaa", "code_present": True,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "unknown",
            },
        ))
        results.append(_make_result(
            event_id="c2_no_counter", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="0xabc/WETH",
            counter_venue_count=0, event_block=100, event_detected_at_block=101,
        ))
        results.append(_make_result(
            event_id="c3_inactive", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="LINK/UNI",
            counter_venue_count=2, event_block=100, event_detected_at_block=100,
            coverage_result={"known_pools_total": 2, "active_pools_total": 0,
                             "active_buy_venues": 0, "active_sell_venues": 0},
        ))
        results.append(_make_result(
            event_id="c4_scored", block_lag=0,
            pair_resolved=True, actual_pair="WETH/USDC",
            best_backrun_net_bps=-1.5, route_viable=False,
            event_block=100, event_detected_at_block=100,
            coverage_result={"known_pools_total": 4, "active_pools_total": 2,
                             "active_buy_venues": 1, "active_sell_venues": 1},
        ))
        return results

    def test_pool_class_truth_present(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert "low_lag_pool_class_truth" in art

    def test_unsupported_pool_rate(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pool_class_truth"]["unsupported_pool_rate"] == 0.25

    def test_dex_family_histogram(self):
        events = [_make_event(eid=f"ev_{i}") for i in range(4)]
        results = self._make_class_results()
        art = build_replay_summary(events, results, mode="test")
        assert art["low_lag_pool_class_truth"]["dex_family_histogram"] == {"unknown": 1}

    def test_pool_class_truth_all_none_when_no_low_lag(self):
        results = [_make_result(
            event_id="stale_only", block_lag=10,
            reject_reason=REJECT_STALE_POSITIVE,
        )]
        art = build_replay_summary([_make_event()], results, mode="test")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] is None
        assert pct["dex_family_histogram"] == {}


class TestM7A516PoolCodeEmpty:
    """M7.A.5.16: POOL_CODE_EMPTY path."""

    def test_pool_code_empty_detail(self):
        r = _make_result(
            event_id="code_empty", block_lag=0,
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_resolved=False, pair_unresolved_detail="POOL_CODE_EMPTY",
            event_block=100, event_detected_at_block=100,
            pool_contract_truth={
                "pool_address": "0xdead", "code_present": False,
                "token0_ok": False, "token1_ok": False,
                "slot0_ok": False, "liquidity_ok": False,
                "dex_family_guess": "no_code",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        pct = art["low_lag_pool_class_truth"]
        assert pct["unsupported_pool_rate"] == 1.0
        assert pct["dex_family_histogram"] == {"no_code": 1}


class TestM7A516DexFamilyGuessValues:
    """M7.A.5.16: dex_family_guess covers all expected categories."""

    def test_all_family_guesses(self):
        families = [
            "uniswap_v3_like", "uniswap_v2_like",
            "partial_erc20_pool", "unknown", "no_code",
        ]
        for fam in families:
            truth = {
                "pool_address": "0x123", "code_present": fam != "no_code",
                "token0_ok": fam in ("uniswap_v3_like", "uniswap_v2_like", "partial_erc20_pool"),
                "token1_ok": fam in ("uniswap_v3_like", "uniswap_v2_like"),
                "slot0_ok": fam == "uniswap_v3_like",
                "liquidity_ok": fam == "uniswap_v3_like",
                "dex_family_guess": fam,
            }
            r = _make_result(
                event_id=f"fam_{fam}", block_lag=0,
                reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                pool_contract_truth=truth,
                event_block=100, event_detected_at_block=100,
            )
            art = build_replay_summary([], [r], mode="ws_live")
            assert art["low_lag_pool_class_truth"]["dex_family_histogram"] == {fam: 1}


# ===========================================================================
# M7.A.5.17: V2 Low-Lag Metrics, Debug Row Read Path
# ===========================================================================


class TestM7A517DebugRowReadPath:
    """M7.A.5.17: pool_state_read_path appears in low_lag_debug_rows."""

    def test_debug_row_contains_read_path(self):
        r = _make_result(
            event_id="dr_rp", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="X/Y",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=0, pool_state_read_path="v2_getReserves",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["pool_state_read_path"] == "v2_getReserves"

    def test_debug_row_key_count_16(self):
        r = _make_result(
            event_id="dr_kc", block_lag=1,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="A/B",
            token_admitted=True, admission_source=ADMISSION_CANONICAL,
            counter_venue_count=2, pool_state_read_path="v3_multicall",
            event_block=100, event_detected_at_block=101,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert len(row) == 16


class TestM7A517V2LowLagMetrics:
    """M7.A.5.17: low_lag_v2_truth block in build_replay_summary."""

    def test_v2_truth_present_empty(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_v2_truth" in art
        v2t = art["low_lag_v2_truth"]
        expected_keys = {
            "low_lag_v2_supported_rate", "low_lag_v2_scored_results_rate",
            "low_lag_v2_no_counter_pool_rate", "low_lag_v2_inactive_pool_rate",
            "v2_resolved_count", "v2_scored_count",
        }
        assert set(v2t.keys()) == expected_keys

    def test_v2_rates_none_when_no_low_lag(self):
        art = build_replay_summary([], [], mode="test")
        v2t = art["low_lag_v2_truth"]
        assert v2t["low_lag_v2_supported_rate"] is None
        assert v2t["v2_resolved_count"] == 0

    def test_v2_resolved_counted(self):
        v2_result = _make_result(
            event_id="v2_cnt", block_lag=1,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="A/B",
            pool_state_read_path="v2_getReserves",
            event_block=100, event_detected_at_block=101,
        )
        v3_result = _make_result(
            event_id="v3_cnt", block_lag=0,
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            pair_resolved=True, actual_pair="C/D",
            pool_state_read_path="v3_multicall",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [v2_result, v3_result], mode="ws_live")
        v2t = art["low_lag_v2_truth"]
        assert v2t["v2_resolved_count"] == 1


# ===========================================================================
# M7.A.5.18: Blocker Tags
# ===========================================================================


class TestM7A518BlockerTagsArtifact:
    """M7.A.5.18: blocker_tags block in replay summary."""

    def test_blocker_tags_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "blocker_tags" in art

    def test_blocker_tags_structure(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert "active_tags" in bt
        assert "active_count" in bt
        assert "all_canonical_tags" in bt

    def test_blocker_tags_all_canonical_sorted(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert bt["all_canonical_tags"] == sorted(ALL_BLOCKER_TAGS)

    def test_blocker_tags_no_events_gets_none_this_window(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_LOW_LAG_NONE_THIS_WINDOW in bt["active_tags"]

    def test_blocker_tags_subgraph_always_present(self):
        art = build_replay_summary([], [], mode="test")
        bt = art["blocker_tags"]
        assert BLOCKER_SUBGRAPH_API_KEY_REQUIRED in bt["active_tags"]

    def test_blocker_tags_with_gas_dominant(self):
        ev = _make_event(eid="gas_dom")
        r = _make_result(
            event_id="gas_dom", best_backrun_net_bps=-5.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block", event_detected_at_block=100,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_GAS_L1_DATA_DOMINANT in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_no_counter_pool_on_low_lag(self):
        ev = _make_event(eid="ncp_ll")
        r = _make_result(
            event_id="ncp_ll", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_NO_COUNTER_POOL in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_inactive_pool_on_low_lag(self):
        ev = _make_event(eid="inactive_ll")
        r = _make_result(
            event_id="inactive_ll", reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_INACTIVE_POOL in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_unsupported_v2_on_low_lag(self):
        ev = _make_event(eid="v2_unsup_ll")
        r = _make_result(
            event_id="v2_unsup_ll", reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            pair_unresolved_detail="POOL_SLOT0_REVERT",
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_V2_UNSUPPORTED in art["blocker_tags"]["active_tags"]

    def test_blocker_tags_remote_quoter_latency_when_scored_zero(self):
        ev = _make_event(eid="latency_ll")
        r = _make_result(
            event_id="latency_ll", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY not in art["blocker_tags"]["active_tags"]


# ===========================================================================
# M7.A.5.19: Quote-Fail Provenance
# ===========================================================================


class TestM7A519QuoteFailProvenance:
    """M7.A.5.19: quote_fail provenance in low-lag debug rows."""

    def test_provenance_populated_for_rpc_quote_fail(self):
        r = _make_result(
            event_id="qfp_1", block_lag=1,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True, actual_pair="WETH/USDC",
            event_block=100, event_detected_at_block=101,
            pipeline_stage_latency_ms={
                "stage_a_ms": 10.0, "stage_b_ms": 20.0,
                "quote_fail_stage": "buy", "quote_fail_venue": "uniswap_v3",
                "quote_fail_exception_short": "ContractLogicError",
            },
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] == "buy"
        assert row["quote_fail_venue"] == "uniswap_v3"
        assert row["quote_fail_exception_short"] == "ContractLogicError"

    def test_provenance_none_for_non_rpc_fail(self):
        r = _make_result(
            event_id="qfp_2", block_lag=0,
            reject_reason=REJECT_NO_COUNTER_POOL,
            pair_resolved=True, actual_pair="WETH/ARB",
            event_block=100, event_detected_at_block=100,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None

    def test_provenance_none_when_no_pipeline_latency(self):
        r = _make_result(
            event_id="qfp_3", block_lag=2,
            reject_reason=REJECT_RPC_QUOTE_FAIL,
            pair_resolved=True, actual_pair="WETH/USDT",
            event_block=100, event_detected_at_block=102,
        )
        art = build_replay_summary([], [r], mode="ws_live")
        row = art["low_lag_debug_rows"][0]
        assert row["quote_fail_stage"] is None


# ===========================================================================
# M7.A.5.18: Low-Lag Watchlist
# ===========================================================================


class TestM7A518LowLagWatchlist:
    """M7.A.5.18: low_lag_watchlist artifact block."""

    def test_watchlist_present_in_empty_artifact(self):
        art = build_replay_summary([], [], mode="test")
        assert "low_lag_watchlist" in art
        assert art["low_lag_watchlist"] == []

    def test_watchlist_entry_fields(self):
        ev = _make_event(eid="wl_1")
        r = _make_result(
            event_id="wl_1", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block", pair_resolved=True,
            actual_pair="WETH/USDC",
            pool_contract_truth={"pool_address": "0xabc123"},
            pool_state_read_path="v3_multicall",
            event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        expected_keys = {
            "pair", "pool_address", "first_seen_block", "last_seen_block",
            "seen_count", "reject_reason", "pair_unresolved_detail",
            "pool_state_read_path", "known_pools", "active_pools",
        }
        assert set(wl[0].keys()) == expected_keys

    def test_watchlist_deduplication_by_pool(self):
        ev1 = _make_event(eid="wl_dup1")
        ev2 = _make_event(eid="wl_dup2")
        r1 = _make_result(
            event_id="wl_dup1", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
            event_detected_at_block=101,
        )
        r2 = _make_result(
            event_id="wl_dup2", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=105, quote_block=106, block_lag=1,
            same_state_class="next_block",
            pool_contract_truth={"pool_address": "0xsamepool"},
            event_detected_at_block=106,
        )
        art = build_replay_summary([ev1, ev2], [r1, r2], mode="test")
        wl = art["low_lag_watchlist"]
        assert len(wl) == 1
        assert wl[0]["seen_count"] == 2

    def test_watchlist_no_stale_events(self):
        ev = _make_event(eid="wl_stale")
        r = _make_result(
            event_id="wl_stale", reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=200, block_lag=100,
            same_state_class="stale",
            pool_contract_truth={"pool_address": "0xstalepool"},
        )
        art = build_replay_summary([ev], [r], mode="test")
        assert art["low_lag_watchlist"] == []

    def test_watchlist_coverage_truth_propagation(self):
        ev = _make_event(eid="wl_cov")
        r = _make_result(
            event_id="wl_cov", reject_reason=REJECT_NO_COUNTER_POOL,
            event_block=100, quote_block=101, block_lag=1,
            same_state_class="next_block",
            coverage_result={
                "known_pools_total": 3, "active_pools_total": 1,
                "candidate_pools": [{"address": "0xpool1"}],
            },
            event_detected_at_block=101,
        )
        art = build_replay_summary([ev], [r], mode="test")
        wl = art["low_lag_watchlist"]
        assert wl[0]["known_pools"] == 3
        assert wl[0]["active_pools"] == 1
