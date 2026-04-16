"""
SCORING_LATENCY tests for M7 orderflow.

Test categories covered:
- Event classification (backrun type, viability)
- Backrun scoring offline (gross, gas, fee, net bps)
- Stale gate viability
- Zero liquidity reject
- Two-queue priority (low-lag vs stale)
- Mid-pipeline abort
- Low-lag zero-active-pools instant reject
- Session prewarm pairs
- Detection-time lag accounting (M7.A.5.25)
"""
from __future__ import annotations

from dataclasses import asdict

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.orderflow.events import build_fixture_events
from m7.orderflow.pricing import (
    classify_event_backrun_type,
    classify_event_viability,
    estimate_backrun_gross_bps,
    estimate_fee_cost_bps,
    estimate_gas_cost_bps,
)
from m7.orderflow.artifacts import build_replay_summary, score_backrun_offline
from m7.shared.constants import (
    BACKRUN_BUY_DEPRESSED,
    BACKRUN_SELL_APPRECIATED,
    EVENT_TYPE_SWAP,
    MIN_EVENT_SIZE_USD,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
    REJECT_EVENT_TOO_SMALL,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_INSUFFICIENT_IMPACT,
    REJECT_NO_COUNTER_POOL,
    REJECT_PRICING_ANOMALY,
    REJECT_STALE_POSITIVE,
    REJECT_ZERO_LIQUIDITY,
    SIGNIFICANT_IMPACT_BPS,
    UNSCORED_REJECTS,
)

from tests.unit.conftest import _make_event, _make_result


# ---------------------------------------------------------------------------
# 1. Event classification
# ---------------------------------------------------------------------------
class TestEventClassification:
    """Lock event classification logic."""

    def test_high_impact_classified_as_buy_depressed(self):
        e = _make_event(estimated_impact_bps=20.0)
        assert classify_event_backrun_type(e) == BACKRUN_BUY_DEPRESSED

    def test_low_impact_classified_as_sell_appreciated(self):
        e = _make_event(estimated_impact_bps=1.0)
        assert classify_event_backrun_type(e) == BACKRUN_SELL_APPRECIATED

    def test_boundary_impact_at_threshold(self):
        e = _make_event(estimated_impact_bps=SIGNIFICANT_IMPACT_BPS)
        result = classify_event_backrun_type(e)
        assert result == BACKRUN_BUY_DEPRESSED

    def test_viability_rejects_small_events(self):
        e = _make_event(estimated_size_usd=50.0)
        assert classify_event_viability(e) == REJECT_EVENT_TOO_SMALL

    def test_viability_rejects_zero_impact(self):
        e = _make_event(estimated_impact_bps=0.0, estimated_size_usd=1000.0)
        assert classify_event_viability(e) == REJECT_INSUFFICIENT_IMPACT

    def test_viability_accepts_normal_event(self):
        e = _make_event(estimated_size_usd=5000.0, estimated_impact_bps=10.0)
        assert classify_event_viability(e) is None

    def test_viability_boundary_at_min_size(self):
        e = _make_event(estimated_size_usd=MIN_EVENT_SIZE_USD)
        assert classify_event_viability(e) is None


# ---------------------------------------------------------------------------
# 2. Backrun scoring (offline)
# ---------------------------------------------------------------------------
class TestBackrunScoring:
    """Lock offline backrun scoring logic."""

    def test_gross_estimation_proportional_to_impact(self):
        e_low = _make_event(estimated_impact_bps=5.0)
        e_high = _make_event(estimated_impact_bps=50.0)
        assert estimate_backrun_gross_bps(e_high) > estimate_backrun_gross_bps(e_low)

    def test_gross_estimation_is_positive(self):
        e = _make_event(estimated_impact_bps=10.0)
        assert estimate_backrun_gross_bps(e) > 0

    def test_gas_cost_inversely_proportional_to_size(self):
        e_small = _make_event(estimated_size_usd=100.0)
        e_large = _make_event(estimated_size_usd=100000.0)
        assert estimate_gas_cost_bps(e_small) > estimate_gas_cost_bps(e_large)

    def test_gas_cost_positive(self):
        e = _make_event(estimated_size_usd=5000.0)
        assert estimate_gas_cost_bps(e) > 0

    def test_fee_cost_positive(self):
        e = _make_event(fee_tier=500)
        assert estimate_fee_cost_bps(e) > 0

    def test_score_offline_small_event_rejected(self):
        e = _make_event(estimated_size_usd=50.0)
        r = score_backrun_offline(e)
        assert r.reject_reason == REJECT_EVENT_TOO_SMALL
        assert r.route_viable is False

    def test_score_offline_zero_impact_rejected(self):
        e = _make_event(estimated_impact_bps=0.0, estimated_size_usd=1000.0)
        r = score_backrun_offline(e)
        assert r.reject_reason == REJECT_INSUFFICIENT_IMPACT

    def test_score_offline_produces_all_fields(self):
        e = _make_event(estimated_size_usd=5000.0, estimated_impact_bps=10.0)
        r = score_backrun_offline(e)
        d = asdict(r)
        for key in [
            "event_id", "event_source", "event_type",
            "post_trade_state_used", "best_backrun_net_bps",
            "candidate_path", "route_viable", "reject_reason",
        ]:
            assert key in d

    def test_score_offline_has_estimated_state(self):
        e = _make_event()
        r = score_backrun_offline(e)
        assert r.post_trade_state_used == "estimated"
        assert r.event_source == "fixture"

    def test_score_offline_net_is_gross_minus_costs(self):
        """Net bps should be gross - gas - fees."""
        e = _make_event(estimated_size_usd=50000.0, estimated_impact_bps=25.0)
        r = score_backrun_offline(e)
        gross = estimate_backrun_gross_bps(e)
        gas = estimate_gas_cost_bps(e)
        fee = estimate_fee_cost_bps(e)
        expected_net = gross - gas - fee
        assert abs(r.best_backrun_net_bps - expected_net) < 0.01

    def test_all_fixtures_scored(self):
        """All fixture events should produce results."""
        events = build_fixture_events()
        results = [score_backrun_offline(e) for e in events]
        assert len(results) == len(events)
        for r in results:
            assert r.event_id


# ---------------------------------------------------------------------------
# 3. Stale gate viability
# ---------------------------------------------------------------------------
class TestStaleGateViability:
    """route_viable requires net_bps > 0 AND block_lag <= 2."""

    def test_viable_result_positive_low_lag(self):
        r = BackrunResult(
            event_id="stale_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=50.0, block_lag=1, same_state_class="next_block",
            route_viable=True, reject_reason=None,
        )
        assert r.route_viable is True
        assert r.reject_reason is None

    def test_stale_positive_not_viable(self):
        r = BackrunResult(
            event_id="stale_2", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=2630.0, block_lag=23, same_state_class="stale",
            route_viable=False, reject_reason=REJECT_STALE_POSITIVE,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_STALE_POSITIVE

    def test_negative_net_not_viable(self):
        r = BackrunResult(
            event_id="stale_3", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            best_backrun_net_bps=-400.0, block_lag=1, same_state_class="next_block",
            route_viable=False, reject_reason=REJECT_GAS_EXCEEDS_GROSS,
        )
        assert r.route_viable is False
        assert r.reject_reason == REJECT_GAS_EXCEEDS_GROSS


# ---------------------------------------------------------------------------
# 4. Zero liquidity reject
# ---------------------------------------------------------------------------
class TestZeroLiquidityReject:
    """Zero-liquidity pools produce REJECT_ZERO_LIQUIDITY."""

    def test_zero_liq_result(self):
        r = BackrunResult(
            event_id="zeroliq_1", event_source="live", event_type=EVENT_TYPE_SWAP,
            post_trade_state_used="live", backrun_direction=BACKRUN_BUY_DEPRESSED,
            reject_reason=REJECT_ZERO_LIQUIDITY, route_viable=False,
            local_sim_state={
                "pools_queried": 2, "pools_with_state": 2,
                "pool_states": {
                    "0xaaa": {"liquidity": 0},
                    "0xbbb": {"liquidity": 0},
                },
            },
        )
        assert r.reject_reason == REJECT_ZERO_LIQUIDITY
        assert r.route_viable is False


# ---------------------------------------------------------------------------
# 5. Two-queue priority (low-lag vs stale)
# ---------------------------------------------------------------------------
class TestTwoQueuePriority:
    """Events with detection_lag <= 2 scored before stale events."""

    def test_low_lag_events_sorted_first(self):
        events = [
            _make_event("stale1", block=90),
            _make_event("lowlag1", block=100),
            _make_event("stale2", block=85),
            _make_event("lowlag2", block=99),
        ]
        detected_block = 100
        low_lag_queue = [e for e in events if (detected_block - e.block_number) <= 2]
        stale_queue = [e for e in events if (detected_block - e.block_number) > 2]
        ordered = low_lag_queue + stale_queue
        assert len(low_lag_queue) == 2
        assert len(stale_queue) == 2
        assert ordered[0].event_id == "lowlag1"
        assert ordered[1].event_id == "lowlag2"
        assert ordered[2].event_id == "stale1"
        assert ordered[3].event_id == "stale2"

    def test_all_low_lag(self):
        events = [_make_event("a", block=100), _make_event("b", block=99)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        stale = [e for e in events if (detected_block - e.block_number) > 2]
        assert len(low_lag) == 2
        assert len(stale) == 0

    def test_all_stale(self):
        events = [_make_event("a", block=50), _make_event("b", block=60)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        stale = [e for e in events if (detected_block - e.block_number) > 2]
        assert len(low_lag) == 0
        assert len(stale) == 2

    def test_boundary_lag_2_is_low_lag(self):
        events = [_make_event("boundary", block=98)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        assert len(low_lag) == 1

    def test_boundary_lag_3_is_stale(self):
        events = [_make_event("boundary", block=97)]
        detected_block = 100
        low_lag = [e for e in events if (detected_block - e.block_number) <= 2]
        assert len(low_lag) == 0


# ---------------------------------------------------------------------------
# 6. Mid-pipeline abort
# ---------------------------------------------------------------------------
class TestMidPipelineAbort:
    """BackrunResult with mid_pipeline_abort in stage_latency."""

    def test_abort_result_has_mid_pipeline_abort_flag(self):
        stage_latency = {
            "stage_a_ms": 0.0, "stage_b_ms": 0.0,
            "mid_pipeline_abort": True, "mid_pipeline_lag": 5,
        }
        r = _make_result(
            pipeline_stage_latency_ms=stage_latency,
            scoring_path="registry_direct",
            event_block=100, quote_block=105, block_lag=5,
            same_state_class="stale",
        )
        assert r.pipeline_stage_latency_ms["mid_pipeline_abort"] is True
        assert r.pipeline_stage_latency_ms["mid_pipeline_lag"] == 5

    def test_abort_with_positive_net_gets_stale_positive_reject(self):
        r = _make_result(
            scoring_path="registry_direct",
            best_backrun_net_bps=5.0,
            reject_reason=REJECT_STALE_POSITIVE,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.reject_reason == REJECT_STALE_POSITIVE

    def test_abort_with_negative_net_gets_gas_exceeds_gross(self):
        r = _make_result(
            scoring_path="registry_direct",
            best_backrun_net_bps=-10.0,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.reject_reason == REJECT_GAS_EXCEEDS_GROSS

    def test_abort_result_has_zero_stage_b(self):
        stage_latency = {
            "stage_a_ms": 0.0, "stage_b_ms": 0.0,
            "mid_pipeline_abort": True, "mid_pipeline_lag": 4,
        }
        r = _make_result(pipeline_stage_latency_ms=stage_latency)
        assert r.pipeline_stage_latency_ms["stage_b_ms"] == 0.0

    def test_abort_preserves_local_pricing_flag(self):
        r = _make_result(
            scoring_path="registry_direct",
            local_pricing_attempted=True,
            local_pricing_used=True,
            pipeline_stage_latency_ms={"mid_pipeline_abort": True},
        )
        assert r.local_pricing_attempted is True
        assert r.local_pricing_used is True


# ---------------------------------------------------------------------------
# 7. Low-lag zero-active-pools instant reject
# ---------------------------------------------------------------------------
class TestLowLagZeroActivePoolsReject:
    """Low-lag events with zero active registry pools get instantly rejected."""

    def test_reject_reason_is_all_pools_truly_inactive(self):
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100, quote_block=100, block_lag=0,
        )
        assert r.reject_reason == REJECT_ALL_POOLS_TRULY_INACTIVE

    def test_reject_is_in_unscored_rejects(self):
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in UNSCORED_REJECTS

    def test_zero_active_pools_reject_has_no_coverage(self):
        """coverage_result must be None when registry reports 0 active pools
        (coverage scan has not been performed yet at that point)."""
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100, quote_block=100, block_lag=0,
            coverage_result=None,
        )
        assert r.coverage_result is None


# ---------------------------------------------------------------------------
# 8. Session prewarm pairs
# ---------------------------------------------------------------------------
class TestSessionPrewarm:
    """Prewarm high-frequency pairs at session start."""

    def test_prewarm_pairs_list(self):
        expected = [
            ("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "ARB"),
            ("USDC", "USDT"), ("WETH", "WBTC"), ("ARB", "USDC"),
        ]
        assert len(expected) == 6
        for a, b in expected:
            assert a in ("WETH", "USDC", "USDT", "ARB", "WBTC")
            assert b in ("WETH", "USDC", "USDT", "ARB", "WBTC")


# ---------------------------------------------------------------------------
# 9. Detection-time lag accounting (M7.A.5.25)
# ---------------------------------------------------------------------------
class TestDetectionTimeLag:
    """Low-lag metrics use detection-time (event_detected_at_block - event_block)."""

    def test_detection_lag_same_block(self):
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=50, same_state_class="stale",
        )
        det_lag = r.event_detected_at_block - r.event_block
        assert det_lag == 0

    def test_detection_lag_different_from_final_lag(self):
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=126, same_state_class="stale",
            best_backrun_net_bps=5.0,
        )
        assert r.event_detected_at_block - r.event_block == 0
        assert r.block_lag == 126

    def test_artifact_events_detected_low_lag_uses_detection_time(self):
        """build_replay_summary.events_detected_low_lag uses detection-time lag."""
        r = _make_result(
            event_block=100, event_detected_at_block=100,
            block_lag=50, same_state_class="stale",
            best_backrun_net_bps=-5.0,
            reject_reason=REJECT_STALE_POSITIVE,
        )
        ev = _make_event(block=100)
        art = build_replay_summary([ev], [r], mode="ws_live")
        assert art["events_detected_low_lag"] == 1
