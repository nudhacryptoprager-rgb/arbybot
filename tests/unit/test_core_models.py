# PATH: tests/unit/test_core_models.py
"""
Unit tests for core data models.

Includes:
- SPREAD_ID CONTRACT v1.1 tests (backward compatible)
- CONFIDENCE SCORING monotonicity tests
"""

import unittest
from decimal import Decimal

from core.models import (
    Quote, Opportunity, Trade, PnLBreakdown,
    generate_spread_id, generate_opportunity_id, parse_spread_id,
    validate_spread_id, format_spread_timestamp, is_spread_id_v1_1,
    calculate_confidence, CONFIDENCE_WEIGHTS,
    SPREAD_ID_PATTERN_V1_1, SPREAD_ID_PATTERN_V1_0,
)
from core.constants import TradeOutcome


class TestSpreadIdContractV1_1(unittest.TestCase):
    """
    SPREAD_ID CONTRACT v1.1 tests.
    
    Key property: tests should NEVER flap due to format changes.
    The parser accepts all "spread_*" strings as valid.
    """

    def test_generate_spread_id_format(self):
        """spread_id follows v1.1 format."""
        spread_id = generate_spread_id(1, "20260122_171426", 0)
        self.assertEqual(spread_id, "spread_1_20260122_171426_0")

    def test_generate_spread_id_deterministic(self):
        """Same inputs produce same spread_id."""
        id1 = generate_spread_id(5, "20260122_120000", 3)
        id2 = generate_spread_id(5, "20260122_120000", 3)
        self.assertEqual(id1, id2)

    def test_roundtrip_generate_parse(self):
        """CRITICAL: generate -> parse roundtrip is stable."""
        original_cycle = 7
        original_ts = "20260115_143022"
        original_idx = 12
        
        spread_id = generate_spread_id(original_cycle, original_ts, original_idx)
        parsed = parse_spread_id(spread_id)
        
        self.assertTrue(parsed["valid"])
        self.assertEqual(parsed["format"], "v1.1")
        self.assertEqual(parsed["cycle"], original_cycle)
        self.assertEqual(parsed["timestamp"], original_ts)
        self.assertEqual(parsed["index"], original_idx)

    def test_roundtrip_generate_parse_regenerate(self):
        """generate -> parse -> regenerate produces same ID."""
        original_id = generate_spread_id(3, "20260122_093438", 5)
        
        parsed = parse_spread_id(original_id)
        self.assertTrue(parsed["valid"])
        
        regenerated_id = generate_spread_id(
            parsed["cycle"], 
            parsed["timestamp"], 
            parsed["index"]
        )
        
        self.assertEqual(original_id, regenerated_id)


class TestSpreadIdBackwardCompatibility(unittest.TestCase):
    """
    BACKWARD COMPATIBILITY tests.
    
    Parser accepts legacy formats to prevent test flapping.
    """

    def test_parse_v1_1_format(self):
        """v1.1 format parses correctly."""
        result = parse_spread_id("spread_1_20260122_171426_0")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["format"], "v1.1")
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(result["date"], "20260122")
        self.assertEqual(result["time"], "171426")
        self.assertEqual(result["index"], 0)

    def test_parse_v1_0_legacy_format(self):
        """v1.0 format (no index) parses as valid."""
        result = parse_spread_id("spread_1_20260122_171426")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["format"], "v1.0")
        self.assertEqual(result["cycle"], 1)
        self.assertEqual(result["timestamp"], "20260122_171426")
        self.assertIsNone(result["index"])

    def test_parse_legacy_uuid_format(self):
        """Legacy UUID format parses as valid."""
        result = parse_spread_id("spread_abc123-def456")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["format"], "legacy")
        self.assertEqual(result["suffix"], "abc123-def456")

    def test_parse_legacy_simple_format(self):
        """Legacy simple format parses as valid."""
        result = parse_spread_id("spread_001")
        
        self.assertTrue(result["valid"])
        self.assertEqual(result["format"], "legacy")

    def test_validate_accepts_all_spread_formats(self):
        """validate_spread_id accepts any spread_* string."""
        self.assertTrue(validate_spread_id("spread_1_20260122_171426_0"))
        self.assertTrue(validate_spread_id("spread_1_20260122_171426"))
        self.assertTrue(validate_spread_id("spread_abc123"))
        self.assertTrue(validate_spread_id("spread_"))

    def test_invalid_no_spread_prefix(self):
        """Strings without spread_ prefix are invalid."""
        result = parse_spread_id("opportunity_123")
        self.assertFalse(result["valid"])
        
        result = parse_spread_id("invalid")
        self.assertFalse(result["valid"])

    def test_is_spread_id_v1_1_checker(self):
        """is_spread_id_v1_1 correctly identifies current format."""
        self.assertTrue(is_spread_id_v1_1("spread_1_20260122_171426_0"))
        self.assertFalse(is_spread_id_v1_1("spread_1_20260122_171426"))
        self.assertFalse(is_spread_id_v1_1("spread_abc"))


class TestRealArtifactExamples(unittest.TestCase):
    """
    COMPAT TEST: Real spread_ids from artifacts must parse.
    """

    def test_artifact_spread_id_20260122_171426(self):
        """Real example from scan_20260122_171426.json."""
        result = parse_spread_id("spread_1_20260122_171426_0")
        self.assertTrue(result["valid"])
        self.assertEqual(result["format"], "v1.1")

    def test_artifact_spread_id_212412(self):
        """Real example from truth_report_20260122_212412.json."""
        result = parse_spread_id("spread_1_20260122_212412_0")
        self.assertTrue(result["valid"])


class TestConfidenceScoring(unittest.TestCase):
    """
    CONFIDENCE SCORING tests.
    
    Tests determinism and monotonicity properties.
    """

    def test_confidence_deterministic(self):
        """Same inputs produce same confidence."""
        c1 = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)
        c2 = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)
        self.assertEqual(c1, c2)

    def test_confidence_range(self):
        """Confidence is always in [0, 1]."""
        # All zeros
        self.assertEqual(calculate_confidence(0, 0, 0, 0, 0), 0.0)
        # All ones
        self.assertEqual(calculate_confidence(1, 1, 1, 1, 1), 1.0)
        # Mixed
        c = calculate_confidence(0.5, 0.5, 0.5, 0.5, 0.5)
        self.assertGreaterEqual(c, 0.0)
        self.assertLessEqual(c, 1.0)

    def test_confidence_clamped_inputs(self):
        """Inputs outside [0,1] are clamped."""
        c1 = calculate_confidence(1.5, 1.5, 1.5, 1.5, 1.5)  # All > 1
        c2 = calculate_confidence(-0.5, -0.5, -0.5, -0.5, -0.5)  # All < 0
        
        self.assertEqual(c1, 1.0)  # Clamped to max
        self.assertEqual(c2, 0.0)  # Clamped to min


class TestConfidenceMonotonicity(unittest.TestCase):
    """
    MONOTONICITY PROPERTY tests.
    
    These ensure confidence behaves intuitively:
    - Worse reliability → confidence does not increase
    - Better freshness → confidence does not decrease
    """

    def test_worse_quote_fetch_rate_no_increase(self):
        """Worse quote_fetch_rate → confidence does not increase."""
        base = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)
        worse = calculate_confidence(0.7, 0.8, 0.7, 0.95, 0.85)  # Lower fetch rate
        self.assertLessEqual(worse, base)

    def test_worse_quote_gate_pass_rate_no_increase(self):
        """Worse quote_gate_pass_rate → confidence does not increase."""
        base = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)
        worse = calculate_confidence(0.9, 0.6, 0.7, 0.95, 0.85)  # Lower gate pass
        self.assertLessEqual(worse, base)

    def test_worse_rpc_success_rate_no_increase(self):
        """Worse rpc_success_rate → confidence does not increase."""
        base = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)
        worse = calculate_confidence(0.9, 0.8, 0.5, 0.95, 0.85)  # Lower RPC success
        self.assertLessEqual(worse, base)

    def test_better_freshness_no_decrease(self):
        """Better freshness_score → confidence does not decrease."""
        base = calculate_confidence(0.9, 0.8, 0.7, 0.80, 0.85)
        better = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.85)  # Higher freshness
        self.assertGreaterEqual(better, base)

    def test_better_adapter_reliability_no_decrease(self):
        """Better adapter_reliability → confidence does not decrease."""
        base = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.70)
        better = calculate_confidence(0.9, 0.8, 0.7, 0.95, 0.90)  # Higher reliability
        self.assertGreaterEqual(better, base)

    def test_weights_sum_to_one(self):
        """Confidence weights sum to 1.0."""
        total = sum(CONFIDENCE_WEIGHTS.values())
        self.assertAlmostEqual(total, 1.0, places=6)


class TestQuote(unittest.TestCase):
    """Tests for Quote model."""

    def test_create_quote(self):
        """Can create a Quote."""
        quote = Quote(
            pool_address="0x1234",
            token_in="USDC",
            token_out="WETH",
            amount_in="1000000",
            amount_out="500000000000000000",
        )
        self.assertEqual(quote.pool_address, "0x1234")

    def test_quote_has_timestamp(self):
        """Quote auto-generates timestamp."""
        quote = Quote(pool_address="0x1234")
        self.assertIsNotNone(quote.timestamp)


class TestOpportunity(unittest.TestCase):
    """Tests for Opportunity model."""

    def test_create_opportunity(self):
        """Can create an Opportunity."""
        opp = Opportunity(spread_id="spread_001", net_pnl_usdc="10.000000")
        self.assertEqual(opp.spread_id, "spread_001")

    def test_opportunity_id_syncs_with_spread_id(self):
        """id field syncs with spread_id."""
        opp = Opportunity(spread_id="spread_123")
        self.assertEqual(opp.id, "spread_123")


class TestTrade(unittest.TestCase):
    """Tests for Trade model."""

    def test_create_trade(self):
        """Can create a Trade."""
        trade = Trade(
            trade_id="trade_001",
            spread_id="spread_001",
            outcome=TradeOutcome.EXECUTED,
        )
        self.assertEqual(trade.trade_id, "trade_001")


class TestPnLBreakdown(unittest.TestCase):
    """Tests for PnLBreakdown model."""

    def test_calculate_net(self):
        """calculate_net computes correctly."""
        breakdown = PnLBreakdown(
            gross_pnl="10.000000",
            dex_fees="0.500000",
            cex_fees="0.300000",
            gas_cost="0.100000",
            slippage_cost="0.050000",
        )
        net = breakdown.calculate_net()
        self.assertEqual(Decimal(net), Decimal("9.050000"))


if __name__ == "__main__":
    unittest.main()
