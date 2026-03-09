"""
Test ChainQualityLevel classification (v2.0.9).

Tests for classify_chain_quality() - the chain quality maturity assessment.
"""

import pytest

from m4.policy import (
    ChainQualityLevel,
    MIN_CYCLES_FOR_QUALITY_RAISED,
    classify_chain_quality,
)


class TestChainQualityLevel:
    """Tests for ChainQualityLevel constants."""

    def test_level_values_defined(self):
        """All quality levels must be defined."""
        assert ChainQualityLevel.INFRA_READY == "INFRA_READY"
        assert ChainQualityLevel.SIGNAL_PRODUCING == "SIGNAL_PRODUCING"
        assert ChainQualityLevel.QUALITY_RAISED == "QUALITY_RAISED"

    def test_min_cycles_constant_defined(self):
        """MIN_CYCLES_FOR_QUALITY_RAISED must be at least 2."""
        assert MIN_CYCLES_FOR_QUALITY_RAISED >= 2


class TestClassifyChainQuality:
    """Tests for classify_chain_quality function."""

    # ============================================================
    # INFRA_READY cases (no signals)
    # ============================================================

    def test_infra_ready_zero_signals(self):
        """Zero signals -> INFRA_READY regardless of cycles."""
        result = classify_chain_quality(
            signals_count=0,
            consecutive_non_nodata_cycles=0,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.INFRA_READY

    def test_infra_ready_zero_signals_high_cycles(self):
        """Zero signals in current run = INFRA_READY even with history."""
        result = classify_chain_quality(
            signals_count=0,
            consecutive_non_nodata_cycles=10,  # History doesn't matter if current = 0
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.INFRA_READY

    def test_infra_ready_gate_failed(self):
        """Infra gate failed -> INFRA_READY (lowest level)."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=5,
            infra_gate_pass=False,
        )
        assert result == ChainQualityLevel.INFRA_READY

    # ============================================================
    # SIGNAL_PRODUCING cases (signals but not enough cycles)
    # ============================================================

    def test_signal_producing_first_signal(self):
        """First run with signals -> SIGNAL_PRODUCING."""
        result = classify_chain_quality(
            signals_count=3,
            consecutive_non_nodata_cycles=1,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_signal_producing_second_cycle(self):
        """Two consecutive signal runs -> still SIGNAL_PRODUCING."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=2,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_signal_producing_just_below_threshold(self):
        """One cycle below threshold -> SIGNAL_PRODUCING."""
        result = classify_chain_quality(
            signals_count=10,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED - 1,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    # ============================================================
    # QUALITY_RAISED cases (signals + enough consecutive cycles)
    # ============================================================

    def test_quality_raised_at_threshold(self):
        """Exactly at threshold cycles -> QUALITY_RAISED."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.QUALITY_RAISED

    def test_quality_raised_above_threshold(self):
        """Above threshold cycles -> QUALITY_RAISED."""
        result = classify_chain_quality(
            signals_count=10,
            consecutive_non_nodata_cycles=10,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.QUALITY_RAISED

    def test_quality_raised_minimal_signal(self):
        """Even 1 signal counts if cycles are enough."""
        result = classify_chain_quality(
            signals_count=1,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            infra_gate_pass=True,
        )
        assert result == ChainQualityLevel.QUALITY_RAISED

    # ============================================================
    # Default arguments
    # ============================================================

    def test_default_cycles_single(self):
        """Default consecutive_non_nodata_cycles=1 gives SIGNAL_PRODUCING."""
        result = classify_chain_quality(signals_count=5)
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_default_infra_gate_pass(self):
        """Default infra_gate_pass=True assumed."""
        result = classify_chain_quality(signals_count=0, consecutive_non_nodata_cycles=0)
        assert result == ChainQualityLevel.INFRA_READY


class TestChainQualityLevelOrdering:
    """Tests for semantic ordering of quality levels."""

    def test_level_ordering_semantic(self):
        """Levels have semantic ordering: INFRA_READY < SIGNAL_PRODUCING < QUALITY_RAISED."""
        # We test this by classification thresholds, not string comparison
        levels = [
            classify_chain_quality(signals_count=0),  # INFRA_READY
            classify_chain_quality(signals_count=1, consecutive_non_nodata_cycles=1),  # SIGNAL_PRODUCING
            classify_chain_quality(signals_count=1, consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED),  # QUALITY_RAISED
        ]
        assert levels == [
            ChainQualityLevel.INFRA_READY,
            ChainQualityLevel.SIGNAL_PRODUCING,
            ChainQualityLevel.QUALITY_RAISED,
        ]


class TestEnhancedQualityRaised:
    """Tests for v3.2.56 enhanced QUALITY_RAISED path with quality metrics."""

    def test_quality_raised_with_quality_metrics_all_pass(self):
        """QUALITY_RAISED when all quality metrics pass."""
        from m4.policy import (
            MIN_SIGNALS_FOR_QUALITY_RAISED,
            MAX_FRAGILE_RATE_FOR_QUALITY_RAISED,
            MIN_DIVERSITY_FOR_QUALITY_RAISED,
        )
        result = classify_chain_quality(
            signals_count=MIN_SIGNALS_FOR_QUALITY_RAISED,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            fragile_rate=0.20,
            unique_pairs=MIN_DIVERSITY_FOR_QUALITY_RAISED,
            net_profit_usdc=0.10,
        )
        assert result == ChainQualityLevel.QUALITY_RAISED

    def test_signal_producing_when_fragile_rate_too_high(self):
        """SIGNAL_PRODUCING when fragile_rate exceeds threshold."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            fragile_rate=0.70,  # > 0.50
            unique_pairs=3,
            net_profit_usdc=0.10,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_signal_producing_when_diversity_too_low(self):
        """SIGNAL_PRODUCING when unique_pairs below threshold."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            fragile_rate=0.20,
            unique_pairs=1,  # < 2
            net_profit_usdc=0.10,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_signal_producing_when_not_profitable(self):
        """SIGNAL_PRODUCING when net_profit_usdc <= 0."""
        result = classify_chain_quality(
            signals_count=5,
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            fragile_rate=0.20,
            unique_pairs=3,
            net_profit_usdc=-0.05,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING

    def test_signal_producing_when_signals_below_min(self):
        """SIGNAL_PRODUCING when signals_count < MIN_SIGNALS_FOR_QUALITY_RAISED."""
        result = classify_chain_quality(
            signals_count=2,  # < 3
            consecutive_non_nodata_cycles=MIN_CYCLES_FOR_QUALITY_RAISED,
            fragile_rate=0.20,
            unique_pairs=3,
            net_profit_usdc=0.10,
        )
        assert result == ChainQualityLevel.SIGNAL_PRODUCING
