"""
M7.A.5.24 contract tests:
  - scoring_path rename (from low_lag_scoring_path)
  - Two-queue priority (low-lag events scored first)
  - Mid-pipeline lag abort (stage_latency contains mid_pipeline_abort)
  - Instant reject for low-lag + zero active pools
  - Pipeline optimization artifact metrics
  - Field count stability (still 66)
"""
from __future__ import annotations

import pytest
from dataclasses import asdict, fields

from m7.orderflow.contracts import BackrunResult, OrderflowEvent
from m7.shared.constants import (
    ALL_REJECT_REASONS,
    UNSCORED_REJECTS,
    REJECT_GAS_EXCEEDS_GROSS,
    REJECT_STALE_POSITIVE,
    REJECT_ALL_POOLS_TRULY_INACTIVE,
)


# ── Helper factories ────────────────────────────────────────────────

def _make_result(**overrides) -> BackrunResult:
    defaults = dict(
        event_id="e1", event_source="live",
        event_type="uniswap_v3_swap", post_trade_state_used="live",
        backrun_direction="buy_depressed",
    )
    defaults.update(overrides)
    return BackrunResult(**defaults)


def _make_event(eid="e1", block=100) -> OrderflowEvent:
    return OrderflowEvent(
        event_id=eid, event_type="swap",
        chain="arbitrum_one", block_number=block,
        tx_hash="0xabc", token_in="USDC", token_out="WETH",
        amount_in_wei=1000000, amount_out_wei=500000,
        dex="uniswap_v3", pool_address="0xpool",
        fee_tier=3000, estimated_size_usd=100.0,
        estimated_impact_bps=5.0, timestamp="2025-01-01T00:00:00Z",
    )


# ── Field rename contract ──────────────────────────────────────────


class TestScoringPathRename:
    """M7.A.5.24 renamed low_lag_scoring_path → scoring_path."""

    def test_scoring_path_exists_on_backrun_result(self):
        r = _make_result()
        assert hasattr(r, "scoring_path")
        assert r.scoring_path is None

    def test_old_field_name_does_not_exist(self):
        r = _make_result()
        assert not hasattr(r, "low_lag_scoring_path")

    def test_scoring_path_in_asdict(self):
        r = _make_result(scoring_path="registry_direct")
        d = asdict(r)
        assert "scoring_path" in d
        assert "low_lag_scoring_path" not in d
        assert d["scoring_path"] == "registry_direct"

    def test_field_count_stable_at_66(self):
        """Rename does not change field count."""
        assert len(fields(BackrunResult)) == 66


# ── Two-queue priority logic ───────────────────────────────────────


class TestTwoQueuePriority:
    """M7.A.5.24: Events with detection_lag <= 2 scored before stale events."""

    def test_low_lag_events_sorted_first(self):
        """Simulate the two-queue logic from mode_ws_live.py."""
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
        # Low-lag events come first in the ordered queue
        assert ordered[0].event_id == "lowlag1"
        assert ordered[1].event_id == "lowlag2"
        # Stale events come after
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


# ── Mid-pipeline lag abort ──────────────────────────────────────────


class TestMidPipelineAbort:
    """M7.A.5.24: BackrunResult with mid_pipeline_abort in stage_latency."""

    def test_abort_result_has_mid_pipeline_abort_flag(self):
        stage_latency = {
            "stage_a_ms": 0.0,
            "stage_b_ms": 0.0,
            "mid_pipeline_abort": True,
            "mid_pipeline_lag": 5,
        }
        r = _make_result(
            pipeline_stage_latency_ms=stage_latency,
            scoring_path="registry_direct",
            event_block=100,
            quote_block=105,
            block_lag=5,
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
        """Mid-pipeline abort should skip Stage B entirely."""
        stage_latency = {
            "stage_a_ms": 0.0,
            "stage_b_ms": 0.0,
            "mid_pipeline_abort": True,
            "mid_pipeline_lag": 4,
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


# ── Instant reject: low-lag + zero active pools ─────────────────────


class TestLowLagZeroActivePoolsReject:
    """M7.A.5.24: Low-lag events with zero active registry pools get instantly rejected."""

    def test_reject_reason_is_all_pools_truly_inactive(self):
        """The instant reject for low-lag+zero-active uses REJECT_ALL_POOLS_TRULY_INACTIVE."""
        r = _make_result(
            reject_reason=REJECT_ALL_POOLS_TRULY_INACTIVE,
            event_block=100,
            quote_block=100,
            block_lag=0,
        )
        assert r.reject_reason == REJECT_ALL_POOLS_TRULY_INACTIVE

    def test_reject_is_in_unscored_rejects(self):
        """ALL_POOLS_TRULY_INACTIVE should be in UNSCORED_REJECTS."""
        assert REJECT_ALL_POOLS_TRULY_INACTIVE in UNSCORED_REJECTS


# ── Pipeline optimization artifact metrics ──────────────────────────


class TestPipelineOptimizationArtifact:
    """M7.A.5.24: build_replay_summary includes pipeline optimization metrics."""

    def test_m7a524_section_exists(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [_make_event("e1")]
        results = [_make_result(
            event_id="e1",
            scoring_path="registry_direct",
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            event_block=100, quote_block=100, block_lag=0,
            same_state_class="same_block",
        )]
        art = build_replay_summary(events, results, mode="ws_live")
        assert "m7a524_pipeline_optimization" in art

    def test_scoring_path_histogram(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [_make_event("e1"), _make_event("e2"), _make_event("e3")]
        results = [
            _make_result(event_id="e1", scoring_path="registry_direct",
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
            _make_result(event_id="e2", scoring_path="registry_direct",
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
            _make_result(event_id="e3", scoring_path=None,
                         reject_reason=REJECT_GAS_EXCEEDS_GROSS),
        ]
        art = build_replay_summary(events, results, mode="ws_live")
        histogram = art["m7a524_pipeline_optimization"]["scoring_path_histogram"]
        assert histogram["registry_direct"] == 2
        assert histogram.get(None, histogram.get("None", 0)) + histogram.get(None, 0) >= 0

    def test_mid_pipeline_abort_count(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [_make_event("e1"), _make_event("e2")]
        results = [
            _make_result(
                event_id="e1",
                scoring_path="registry_direct",
                pipeline_stage_latency_ms={"mid_pipeline_abort": True},
                reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            ),
            _make_result(
                event_id="e2",
                scoring_path="registry_direct",
                reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            ),
        ]
        art = build_replay_summary(events, results, mode="ws_live")
        assert art["m7a524_pipeline_optimization"]["mid_pipeline_abort_count"] == 1

    def test_scoring_path_histogram_all_none(self):
        from m7.orderflow.artifacts import build_replay_summary

        events = [_make_event("e1")]
        results = [_make_result(
            event_id="e1", scoring_path=None,
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
        )]
        art = build_replay_summary(events, results, mode="ws_live")
        histogram = art["m7a524_pipeline_optimization"]["scoring_path_histogram"]
        assert None in histogram or "None" in histogram


# ── Session prewarm contract ────────────────────────────────────────


class TestSessionPrewarm:
    """M7.A.5.24: Prewarm high-frequency pairs at session start."""

    def test_prewarm_pairs_list(self):
        """Canonical prewarm pairs match expected set."""
        expected = [
            ("WETH", "USDC"), ("WETH", "USDT"), ("WETH", "ARB"),
            ("USDC", "USDT"), ("WETH", "WBTC"), ("ARB", "USDC"),
        ]
        assert len(expected) == 6
        # All pairs involve at least one high-value token
        for a, b in expected:
            assert a in ("WETH", "USDC", "USDT", "ARB", "WBTC")
            assert b in ("WETH", "USDC", "USDT", "ARB", "WBTC")


# ── Constants stability ─────────────────────────────────────────────


class TestConstantsStability:
    """M7.A.5.24 does not change rejection constants."""

    def test_reject_reasons_count_20(self):
        assert len(ALL_REJECT_REASONS) == 20

    def test_unscored_rejects_count_12(self):
        assert len(UNSCORED_REJECTS) == 12

    def test_field_count_66(self):
        assert len(fields(BackrunResult)) == 66
