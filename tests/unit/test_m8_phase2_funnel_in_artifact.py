"""Tests: Phase 2 funnel counters (reject histogram, would_enter, expected_pnl_non_null)
appear in the new_pool_sniper_latest.json artifact produced by make_sniper_artifact.

Contract: metrics["phase2_reject_histogram"], metrics["phase2_would_enter_count"], and
metrics["phase2_expected_pnl_non_null_count"] must be present and reflect FunnelTracker state.
"""
from __future__ import annotations

import pytest

from monitoring.sniper_artifacts import make_sniper_artifact
from monitoring.sniper_funnel import FunnelTracker


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _build_funnel(**phase2_kwargs) -> FunnelTracker:
    """Return a FunnelTracker with optional Phase 2 counter increments."""
    ft = FunnelTracker()
    # Satisfy REQUIRED_METRIC_KEYS with minimal counters
    ft.inc("raw_fetched", 3)
    ft.inc("parse_ok", 3)
    ft.inc("dedup_new", 3)
    ft.inc("filter_passed", 3)
    ft.inc("candidates_queued", 3)
    for name, n in phase2_kwargs.items():
        if name == "reject":
            for reason, count in n.items():
                for _ in range(count):
                    ft.inc_phase2_reject(reason)
        elif name == "would_enter":
            for _ in range(n):
                ft.inc_phase2_would_enter()
        elif name == "pnl_non_null":
            for _ in range(n):
                ft.inc_phase2_expected_pnl_non_null()
    return ft


def _make_artifact(ft: FunnelTracker) -> dict:
    return make_sniper_artifact(
        metrics=ft.snapshot(),
        status="ACTIVE",
        reasons=[],
        source="test",
        freshness_s=10.0,
    )


# ---------------------------------------------------------------------------
# Tests: phase2_reject_histogram appears in artifact metrics
# ---------------------------------------------------------------------------

class TestPhase2RejectHistogramInArtifact:
    def test_reject_histogram_in_metrics_by_default(self):
        """phase2_reject_histogram must always be present (even when empty)."""
        ft = _build_funnel()
        art = _make_artifact(ft)
        assert "phase2_reject_histogram" in art["metrics"]

    def test_reject_histogram_empty_when_no_decisions(self):
        ft = _build_funnel()
        art = _make_artifact(ft)
        assert art["metrics"]["phase2_reject_histogram"] == {}

    def test_reject_histogram_counts_insufficient_data(self):
        ft = _build_funnel(reject={"INSUFFICIENT_DATA": 5})
        art = _make_artifact(ft)
        hist = art["metrics"]["phase2_reject_histogram"]
        assert hist["INSUFFICIENT_DATA"] == 5

    def test_reject_histogram_counts_v4_liquidity_unsupported(self):
        ft = _build_funnel(reject={"V4_LIQUIDITY_UNSUPPORTED": 3})
        art = _make_artifact(ft)
        hist = art["metrics"]["phase2_reject_histogram"]
        assert hist["V4_LIQUIDITY_UNSUPPORTED"] == 3

    def test_reject_histogram_multiple_reasons(self):
        ft = _build_funnel(reject={
            "INSUFFICIENT_DATA": 2,
            "V4_LIQUIDITY_UNSUPPORTED": 1,
            "LOW_LIQUIDITY": 4,
        })
        art = _make_artifact(ft)
        hist = art["metrics"]["phase2_reject_histogram"]
        assert hist["INSUFFICIENT_DATA"] == 2
        assert hist["V4_LIQUIDITY_UNSUPPORTED"] == 1
        assert hist["LOW_LIQUIDITY"] == 4


# ---------------------------------------------------------------------------
# Tests: phase2_would_enter_count in artifact metrics
# ---------------------------------------------------------------------------

class TestPhase2WouldEnterCountInArtifact:
    def test_would_enter_zero_by_default(self):
        ft = _build_funnel()
        art = _make_artifact(ft)
        assert art["metrics"]["phase2_would_enter_count"] == 0

    def test_would_enter_reflects_increments(self):
        ft = _build_funnel(would_enter=3)
        art = _make_artifact(ft)
        assert art["metrics"]["phase2_would_enter_count"] == 3


# ---------------------------------------------------------------------------
# Tests: phase2_expected_pnl_non_null_count in artifact metrics
# ---------------------------------------------------------------------------

class TestPhase2PnlNonNullCountInArtifact:
    def test_pnl_non_null_zero_by_default(self):
        ft = _build_funnel()
        art = _make_artifact(ft)
        assert art["metrics"]["phase2_expected_pnl_non_null_count"] == 0

    def test_pnl_non_null_reflects_increments(self):
        ft = _build_funnel(pnl_non_null=2)
        art = _make_artifact(ft)
        assert art["metrics"]["phase2_expected_pnl_non_null_count"] == 2


# ---------------------------------------------------------------------------
# Tests: combined scenario — real-input gate acceptance
# ---------------------------------------------------------------------------

class TestPhase2RealInputGateAcceptance:
    def test_not_all_decisions_insufficient_data_when_pnl_non_null_gt_0(self):
        """Acceptance criterion: expected_pnl_non_null_count >= 1 means real inputs seen."""
        ft = _build_funnel(
            reject={"INSUFFICIENT_DATA": 3, "V4_LIQUIDITY_UNSUPPORTED": 5},
            pnl_non_null=1,
        )
        art = _make_artifact(ft)
        m = art["metrics"]
        assert m["phase2_expected_pnl_non_null_count"] >= 1

    def test_all_v4_goes_to_v4_unsupported_not_insufficient(self):
        """V4 events must use V4_LIQUIDITY_UNSUPPORTED, not INSUFFICIENT_DATA."""
        ft = _build_funnel(reject={"V4_LIQUIDITY_UNSUPPORTED": 10})
        art = _make_artifact(ft)
        hist = art["metrics"]["phase2_reject_histogram"]
        assert "INSUFFICIENT_DATA" not in hist
        assert hist["V4_LIQUIDITY_UNSUPPORTED"] == 10

    def test_all_three_counters_present_in_single_artifact(self):
        """All three phase2 counter keys must be present together in every artifact."""
        ft = _build_funnel(
            reject={"INSUFFICIENT_DATA": 1},
            would_enter=1,
            pnl_non_null=1,
        )
        art = _make_artifact(ft)
        m = art["metrics"]
        for key in (
            "phase2_reject_histogram",
            "phase2_would_enter_count",
            "phase2_expected_pnl_non_null_count",
        ):
            assert key in m, f"Expected key missing from metrics: {key!r}"
