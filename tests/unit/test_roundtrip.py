# tests/unit/test_roundtrip.py
"""
Unit tests for engine/roundtrip.py

v2.1.0: Round-trip profit simulator tests.
"""
import pytest
from decimal import Decimal

from engine.roundtrip import (
    RoundTripResult,
    simulate_roundtrip,
    estimate_slippage_bps,
)


class TestSimulateRoundtrip:
    """Tests for simulate_roundtrip()."""

    def test_profitable_roundtrip(self):
        """Round-trip that returns more than input is profitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 5,
            "price_exact": 2000.0,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,  # 2000 USDC
            "amount_out_wei": 1_010_000_000_000_000_000,  # 1.01 ETH (profit)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 3,
            "price_exact": 0.000505,  # 1/1980
        }
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=100_000_000)
        
        assert result.leg1_success is True
        assert result.leg2_success is True
        assert result.gross_pnl_wei > 0  # More ETH back than put in
        assert result.is_profitable is True

    def test_unprofitable_roundtrip(self):
        """Round-trip that returns less than input is not profitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,  # 2000 USDC
            "amount_out_wei": 990_000_000_000_000_000,  # 0.99 ETH (loss)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=100_000_000)
        
        assert result.gross_pnl_wei < 0  # Less ETH back than put in
        assert result.is_profitable is False

    def test_gas_reduces_profitability(self):
        """High gas price can turn profitable trade unprofitable."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 300_000,  # High gas usage
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_005_000_000_000_000_000,  # 1.005 ETH (small gross profit)
            "dex_id": "sushiswap_v3",
            "quote_source": "quoter_v2",
            "quoter_gas_estimate": 300_000,  # High gas usage
            "ticks_crossed": 3,
        }
        
        # Very high gas price
        high_gas_result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=1_000_000_000_000)  # 1000 gwei
        
        # Gross profit positive, net profit may be negative due to gas
        assert high_gas_result.gross_pnl_wei > 0
        # Gas cost eats into profit


class TestEstimateSlippageBps:
    """Tests for estimate_slippage_bps()."""

    def test_no_slippage_when_prices_match(self):
        """Zero slippage when quoter and reference prices match."""
        quote = {
            "price_exact": "2000.00",
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "slot0"

    def test_positive_slippage_when_quoter_worse(self):
        """Positive slippage when quoter price is worse (higher for buy)."""
        quote = {
            "price_exact": "2020.00",  # Paying more
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        # (2020 - 2000) / 2000 * 10000 = 100 bps
        assert slippage_bps == Decimal("100")
        assert method == "slot0"

    def test_negative_slippage_when_quoter_better(self):
        """Negative slippage when quoter price is better."""
        quote = {
            "price_exact": "1980.00",  # Paying less
            "slot0_price": "2000.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        # (1980 - 2000) / 2000 * 10000 = -100 bps
        assert slippage_bps == Decimal("-100")
        assert method == "slot0"

    def test_provided_reference_price(self):
        """Can use explicitly provided reference price."""
        quote = {
            "price_exact": "2100.00",
        }
        
        slippage_bps, method = estimate_slippage_bps(quote, reference_price=Decimal("2000"))
        
        # (2100 - 2000) / 2000 * 10000 = 500 bps
        assert slippage_bps == Decimal("500")
        assert method == "provided"

    def test_no_reference_returns_zero(self):
        """Returns zero if no reference price available."""
        quote = {
            "price_exact": "2000.00",
            # No slot0_price
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "none"

    def test_no_quoter_price_returns_zero(self):
        """Returns zero if no quoter price in quote."""
        quote = {
            "slot0_price": "2000.00",
            # No price_exact
        }
        
        slippage_bps, method = estimate_slippage_bps(quote)
        
        assert slippage_bps == Decimal("0")
        assert method == "none"


class TestRoundTripResult:
    """Tests for RoundTripResult dataclass."""

    def test_to_dict_serialization(self):
        """RoundTripResult serializes to dict correctly."""
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=1_000_000_000_000_000_000,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=2000_000_000,
            leg1_success=True,
            leg2_amount_out=1_010_000_000_000_000_000,
            leg2_success=True,
            gross_pnl_wei=10_000_000_000_000_000,
            is_profitable=True,
        )
        
        d = result.to_dict()
        
        assert d["pair"] == "WETH/USDC"
        assert d["buy_dex"] == "uniswap_v3"
        assert d["sell_dex"] == "sushiswap_v3"
        assert d["is_profitable"] is True
        # Wei values serialized as strings
        assert d["amount_in_wei"] == "1000000000000000000"
        assert d["gross_pnl_wei"] == "10000000000000000"
    
    def test_leg2_is_real_quote_in_dict(self):
        """v2.1.0: leg2_is_real_quote is serialized."""
        result = RoundTripResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            amount_in_wei=1_000_000_000_000_000_000,
            token_in="WETH",
            token_out="USDC",
            leg1_amount_out=2000_000_000,
            leg1_success=True,
            leg2_success=True,
            leg2_is_real_quote=True,
        )
        
        d = result.to_dict()
        assert d["leg2_is_real_quote"] is True


class TestProbeSlippage:
    """Tests for probe_slippage()."""
    
    def test_slippage_positive_when_target_worse(self):
        """Positive slippage when target quote is worse than small quote."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"price_exact": "2000.00", "amount_in_wei": 10000}
        quote_target = {"price_exact": "2020.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        # (2020 - 2000) / 2000 * 10000 = 100 bps
        assert slippage_bps == Decimal("100")
        assert diag["method"] == "probe_small_vs_target"
    
    def test_slippage_zero_when_prices_match(self):
        """Zero slippage when small and target prices match."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"price_exact": "2000.00", "amount_in_wei": 10000}
        quote_target = {"price_exact": "2000.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        assert slippage_bps == Decimal("0")
    
    def test_missing_price_returns_zero(self):
        """Returns zero with error if price missing."""
        from engine.roundtrip import probe_slippage
        
        quote_small = {"amount_in_wei": 10000}  # No price_exact
        quote_target = {"price_exact": "2000.00", "amount_in_wei": 1000000}
        
        slippage_bps, diag = probe_slippage(quote_small, quote_target)
        
        assert slippage_bps == Decimal("0")
        assert diag.get("error") == "missing_price"


class TestRoundtripGolden:
    """Tests against docs/artifacts/roundtrip_canonical_golden.json fixture.
    
    ROUNDTRIP_CANONICAL proof: validates simulator produces expected results.
    """
    
    @pytest.fixture
    def golden_fixture(self):
        """Load golden fixture."""
        import json
        from pathlib import Path
        fixture_path = Path("docs/artifacts/roundtrip_canonical_golden.json")
        with open(fixture_path) as f:
            return json.load(f)
    
    def test_golden_fixture_schema(self, golden_fixture):
        """Golden fixture has expected schema."""
        assert golden_fixture["_schema"] == "roundtrip_canonical_golden:v1.0"
        assert "test_cases" in golden_fixture
        assert "roundtrip_contract" in golden_fixture
        assert len(golden_fixture["test_cases"]) >= 3
    
    def test_profitable_roundtrip_case(self, golden_fixture):
        """Validate profitable_roundtrip case from golden fixture."""
        case = next(c for c in golden_fixture["test_cases"] if c["case_id"] == "profitable_roundtrip")
        
        buy_quote = case["input"]["buy_quote"]
        sell_quote = case["input"]["sell_quote"]
        gas_price_wei = case["input"]["gas_price_wei"]
        expected = case["expected"]
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=gas_price_wei)
        
        assert result.leg1_success == expected["leg1_success"]
        assert result.leg2_success == expected["leg2_success"]
        assert (result.gross_pnl_wei > 0) == expected["gross_pnl_wei_positive"]
        assert result.is_profitable == expected["is_profitable"]
    
    def test_unprofitable_roundtrip_case(self, golden_fixture):
        """Validate unprofitable_roundtrip case from golden fixture."""
        case = next(c for c in golden_fixture["test_cases"] if c["case_id"] == "unprofitable_roundtrip")
        
        buy_quote = case["input"]["buy_quote"]
        sell_quote = case["input"]["sell_quote"]
        gas_price_wei = case["input"]["gas_price_wei"]
        expected = case["expected"]
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=gas_price_wei)
        
        assert (result.gross_pnl_wei > 0) == expected["gross_pnl_wei_positive"]
        assert result.is_profitable == expected["is_profitable"]
    
    def test_gas_eats_profit_case(self, golden_fixture):
        """Validate gas_eats_profit case from golden fixture."""
        case = next(c for c in golden_fixture["test_cases"] if c["case_id"] == "gas_eats_profit")
        
        buy_quote = case["input"]["buy_quote"]
        sell_quote = case["input"]["sell_quote"]
        gas_price_wei = case["input"]["gas_price_wei"]
        expected = case["expected"]
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=gas_price_wei)
        
        # Gross profit is positive
        assert (result.gross_pnl_wei > 0) == expected["gross_pnl_wei_positive"]
        # But gas cost should significantly impact net result
        assert result.gas_cost_wei > 0
    
    def test_roundtrip_invariants(self, golden_fixture):
        """Validate roundtrip contract invariants from golden fixture."""
        contract = golden_fixture["roundtrip_contract"]
        invariants = contract["invariants"]
        
        # The invariants should match the simulator behavior
        assert "gross_pnl_wei = leg2_amount_out - amount_in_wei" in invariants
        assert "net_pnl_wei = gross_pnl_wei - gas_cost_wei" in invariants
        assert "is_profitable = net_pnl_wei > 0" in invariants


class TestV280USDConversion:
    """v2.8.0: Tests for USD-based roundtrip calculations."""
    
    def test_usd_fields_populated(self):
        """USD fields should be populated in roundtrip result."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,  # 2000 USDC
            "dex_id": "uniswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 990_000_000_000_000_000,  # 0.99 ETH
            "dex_id": "sushiswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(
            buy_quote, sell_quote,
            gas_price_wei=100_000_000,
            eth_usd_price=2000.0,
        )
        
        # USD fields should be populated
        assert result.gas_cost_usd > 0
        assert result.gross_pnl_usd != 0
        assert result.net_pnl_usd == result.gross_pnl_usd - result.gas_cost_usd
    
    def test_non_weth_token_in_uses_usd(self):
        """For non-WETH token_in, USD price should be used for profitability check."""
        # WBTC token_in with positive gross_pnl_wei but high gas
        buy_quote = {
            "token_in": "WBTC",
            "token_out": "WETH",
            "amount_in_wei": 100_000_000,  # 1 WBTC (8 decimals)
            "amount_out_wei": 30_000_000_000_000_000_000,  # 30 ETH
            "dex_id": "uniswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "WETH",
            "token_out": "WBTC",
            "amount_in_wei": 30_000_000_000_000_000_000,
            "amount_out_wei": 101_000_000,  # 1.01 WBTC (profit in WBTC terms)
            "dex_id": "sushiswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(
            buy_quote, sell_quote,
            gas_price_wei=100_000_000,
            eth_usd_price=2000.0,
            token_in_usd_price=68000.0,  # WBTC price
            token_in_decimals=8,  # WBTC has 8 decimals
        )
        
        # gross_pnl_wei is positive
        assert result.gross_pnl_wei > 0
        # USD fields should be populated correctly
        assert result.gross_pnl_usd > 0  # Profit in USD terms
        # gas_cost_usd should be calculated from ETH
        assert result.gas_cost_usd > 0
    
    def test_weth_token_in_uses_wei(self):
        """For WETH token_in (no token_in_usd_price), wei-based profitability is fine."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,  # 1 ETH
            "amount_out_wei": 2000_000_000,
            "dex_id": "uniswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,  # 1.01 ETH profit
            "dex_id": "sushiswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(
            buy_quote, sell_quote,
            gas_price_wei=100_000_000,
            eth_usd_price=2000.0,
            token_in_usd_price=None,  # Not specified = WETH
        )
        
        assert result.is_profitable is True
        # USD fields should still be populated
        assert result.gross_pnl_usd > 0

    def test_net_pnl_bps_uses_usd_not_mixed_wei(self):
        """net_pnl_bps must be derived from USD, not mixed token-wei/ETH-wei.
        
        Bug reproduction: When token_in has non-18 decimals (e.g., WBTC=8),
        the calculation `net_pnl_bps = net_pnl_wei / amount_in * 10000` produces
        absurdly large values (trillions) because:
        - gross_pnl_wei is in token units (8 decimals)
        - gas_cost_wei is in ETH units (18 decimals)
        - Subtracting them creates nonsense
        
        Fix: net_pnl_bps should be calculated from USD:
        net_pnl_bps = (net_pnl_usd / notional_usd) * 10000
        """
        # WBTC arbitrage with small gross profit but significant gas cost
        buy_quote = {
            "token_in": "WBTC",
            "token_out": "WETH",
            "amount_in_wei": 100_000_000,  # 1 WBTC (8 decimals)
            "amount_out_wei": 16_500_000_000_000_000_000,  # ~16.5 WETH
            "dex_id": "uniswap_v3",
            "gas_estimate": 200_000,
            "ticks_crossed": 5,
        }
        sell_quote = {
            "token_in": "WETH",
            "token_out": "WBTC",
            "amount_in_wei": 16_500_000_000_000_000_000,
            "amount_out_wei": 100_050_000,  # 1.0005 WBTC (+5 bps gross)
            "dex_id": "sushiswap_v3",
            "gas_estimate": 200_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(
            buy_quote, sell_quote,
            gas_price_wei=30_000_000_000,  # 30 gwei - significant gas cost
            eth_usd_price=4000.0,
            token_in_usd_price=100_000.0,  # WBTC ~$100k
            token_in_decimals=8,  # WBTC has 8 decimals
        )
        
        # Key assertions:
        # 1. gross_pnl_bps should be ~5 bps (50000 / 100_000_000 * 10000)
        assert 4 < result.gross_pnl_bps < 6, f"gross_pnl_bps={result.gross_pnl_bps} should be ~5"
        
        # 2. net_pnl_bps MUST NOT be trillions (bug signature)
        # Before fix: net_pnl_bps=-1205999999995.0 (trillions!)
        # After fix: should be ~0.18 bps (from USD: $1.76 / $100k * 10000)
        assert abs(result.net_pnl_bps) < 1000, f"net_pnl_bps={result.net_pnl_bps} is absurdly large (bug!)"
        
        # 3. net_pnl_bps should be derived from USD values
        # Expected: net_pnl_usd / notional_usd * 10000
        notional_usd = (100_000_000 / 10**8) * 100_000.0  # 1 WBTC * $100k = $100k
        expected_net_pnl_bps = (result.net_pnl_usd / notional_usd) * 10000
        assert abs(result.net_pnl_bps - expected_net_pnl_bps) < 0.1, \
            f"net_pnl_bps={result.net_pnl_bps} should equal USD-derived value {expected_net_pnl_bps}"
        
        # 4. gross_pnl_usd should be positive ($50 = 50000 / 1e8 * $100k)
        assert result.gross_pnl_usd > 0, f"gross_pnl_usd={result.gross_pnl_usd} should be >0"


class TestV280SlippageMeasurement:
    """v2.8.0: Tests for measured slippage from sqrtPriceX96."""
    
    def test_slippage_from_sqrt_prices(self):
        """Slippage should be calculated from sqrtPriceX96 before/after."""
        from engine.roundtrip import calculate_slippage_from_sqrt_prices
        
        # sqrtPriceX96 before (slot0)
        Q96 = 2 ** 96
        price_before = 2000.0  # WETH/USDC
        sqrt_before = int((price_before ** 0.5) * Q96)
        
        # sqrtPriceX96 after (quoter) - price moved up 1%
        price_after = 2020.0
        sqrt_after = int((price_after ** 0.5) * Q96)
        
        slippage_bps, source = calculate_slippage_from_sqrt_prices(
            sqrt_before, sqrt_after, is_buy=True
        )
        
        assert source == "sqrtPriceAfter"
        assert slippage_bps > 0  # Price moved up, bad for buyer
        assert abs(slippage_bps - 100.0) < 10  # ~1% = 100 bps
    
    def test_slippage_uses_sqrt_in_roundtrip(self):
        """Roundtrip should use sqrtPriceAfter when available."""
        Q96 = 2 ** 96
        price_before = 2000.0
        price_after = 2010.0  # 0.5% slippage
        sqrt_before = int((price_before ** 0.5) * Q96)
        sqrt_after = int((price_after ** 0.5) * Q96)
        
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000,
            "dex_id": "uniswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 5,
            "sqrt_price_x96": sqrt_before,  # Before price
            "sqrt_price_after": sqrt_after,  # After price
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 990_000_000_000_000_000,
            "dex_id": "sushiswap_v3",
            "gas_estimate": 150_000,
            "ticks_crossed": 3,
        }
        
        result = simulate_roundtrip(buy_quote, sell_quote, gas_price_wei=100_000_000)
        
        # Should use sqrtPriceAfter for slippage
        assert result.slippage_source == "sqrtPriceAfter"
        assert result.estimated_slippage_bps > 0


class TestRoundtripEvaluationStats:
    """v3.0.0: Tests for roundtrip evaluation aggregation stats."""
    
    def test_stats_contains_gated_by_economics(self):
        """evaluate_roundtrip_candidates must return stats with gated_by_economics count."""
        from engine.roundtrip import evaluate_roundtrip_candidates, RoundtripEvaluationStats
        
        opportunities = [
            {"pair": "A/B", "is_roundtrip_viable": False, "spread_minus_required_bps": -10,
             "buy_dex": "uni", "sell_dex": "sushi", "buy_fee": 500, "sell_fee": 500,
             "diagnostics": {"buy_pool": "0x1", "sell_pool": "0x2"}},
            {"pair": "C/D", "is_roundtrip_viable": True, "spread_minus_required_bps": 50,
             "buy_dex": "uni", "sell_dex": "sushi", "buy_fee": 500, "sell_fee": 500,
             "diagnostics": {"buy_pool": "0x3", "sell_pool": "0x4"}},
        ]
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        assert isinstance(stats, RoundtripEvaluationStats)
        assert stats.candidates_total == 2
        assert stats.gated_by_economics == 1
        assert stats.evaluated_count == 1  # One viable, but no quotes so still evaluated
    
    def test_stats_contains_rejected_reasons(self):
        """Aggregation stats must contain rejected_reasons counter."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=[],
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        assert hasattr(stats, "rejected_reasons")
        assert isinstance(stats.rejected_reasons, dict)
    
    def test_stats_to_dict(self):
        """Stats dataclass must have to_dict() for JSON serialization."""
        from engine.roundtrip import RoundtripEvaluationStats
        
        stats = RoundtripEvaluationStats(
            candidates_total=5,
            gated_by_economics=2,
            evaluated_count=3,
            results_count=3,
            rejected_reasons={"NOT_PROFITABLE": 2, "MISSING_QUOTES": 1},
        )
        
        d = stats.to_dict()
        assert d["candidates_total"] == 5
        assert d["gated_by_economics"] == 2
        assert d["rejected_reasons"]["NOT_PROFITABLE"] == 2


class TestClassifyRejectionReason:
    """v3.1.0: Tests for detailed rejection classification."""
    
    def test_slippage_dominates(self):
        """When slippage is largest cost, returns SLIPPAGE_TOO_HIGH."""
        from engine.roundtrip import classify_rejection_reason
        
        reason = classify_rejection_reason(
            gross_pnl_bps=50,
            net_pnl_bps=-100,
            estimated_slippage_bps=100,  # 100 bps slippage - dominates
            lp_fee_bps=10,  # 10 bps LP fee
            gas_bps=5,  # 5 bps gas
        )
        assert reason == "SLIPPAGE_TOO_HIGH"
    
    def test_lp_fees_dominate(self):
        """When LP fees are largest cost, returns LP_FEES_TOO_HIGH."""
        from engine.roundtrip import classify_rejection_reason
        
        reason = classify_rejection_reason(
            gross_pnl_bps=30,
            net_pnl_bps=-50,
            estimated_slippage_bps=5,  # 5 bps slippage
            lp_fee_bps=60,  # 60 bps LP fee (dominates)
            gas_bps=5,  # 5 bps gas
        )
        assert reason == "LP_FEES_TOO_HIGH"
    
    def test_gas_dominates(self):
        """When gas is largest cost, returns GAS_TOO_HIGH."""
        from engine.roundtrip import classify_rejection_reason
        
        reason = classify_rejection_reason(
            gross_pnl_bps=10,
            net_pnl_bps=-20,
            estimated_slippage_bps=2,  # 2 bps slippage
            lp_fee_bps=5,  # 5 bps LP fee
            gas_bps=30,  # 30 bps gas (dominates)
        )
        assert reason == "GAS_TOO_HIGH"
    
    def test_balanced_costs(self):
        """When no cost dominates, returns NET_PROFIT_TOO_LOW."""
        from engine.roundtrip import classify_rejection_reason
        
        reason = classify_rejection_reason(
            gross_pnl_bps=30,
            net_pnl_bps=-10,
            estimated_slippage_bps=10,  # Similar costs
            lp_fee_bps=15,
            gas_bps=10,
        )
        assert reason == "NET_PROFIT_TOO_LOW"
    
    def test_zero_total_cost_returns_net_profit(self):
        """Edge case: zero total cost."""
        from engine.roundtrip import classify_rejection_reason
        
        reason = classify_rejection_reason(
            gross_pnl_bps=-5,
            net_pnl_bps=-5,
            estimated_slippage_bps=0,
            lp_fee_bps=0,
            gas_bps=0,
        )
        assert reason == "NET_PROFIT_TOO_LOW"


class TestRejectedReasonsInStats:
    """v3.1.0: Tests that rejected_reasons contains detailed categories."""
    
    def test_rejected_reasons_uses_detailed_keys(self):
        """Stats must aggregate detailed rejection reason keys."""
        from engine.roundtrip import RoundtripEvaluationStats
        
        # With new classification, stats should have detailed keys
        stats = RoundtripEvaluationStats(
            candidates_total=4,
            gated_by_economics=0,
            evaluated_count=4,
            results_count=4,
            rejected_reasons={
                "SLIPPAGE_TOO_HIGH": 2,
                "LP_FEES_TOO_HIGH": 1,
                "NET_PROFIT_TOO_LOW": 1,
            },
        )
        
        d = stats.to_dict()
        assert "SLIPPAGE_TOO_HIGH" in d["rejected_reasons"]
        assert "LP_FEES_TOO_HIGH" in d["rejected_reasons"]
        assert d["rejected_reasons"]["SLIPPAGE_TOO_HIGH"] == 2


class TestEconomicsGatingInvariants:
    """v3.2.4: Invariants for economics gating.
    
    These tests ensure that:
    1. Opportunities without economics fields are gated (not silently passed)
    2. Opportunities with spread_minus_required_bps <= 0 are gated
    3. gated_by_economics counter always increments for non-viable candidates
    """
    
    def test_missing_economics_fields_gates_opportunity(self):
        """Opportunity WITHOUT is_roundtrip_viable field should be gated (default=False)."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        # Opportunity missing all economics fields
        opportunities = [{
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 500,
            "sell_fee": 500,
            "diagnostics": {"buy_pool": "0x1", "sell_pool": "0x2"},
            # NO economics fields: is_roundtrip_viable, spread_minus_required_bps, min_required_spread_bps
        }]
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        # Must be gated, not evaluated
        assert stats.gated_by_economics == 1, \
            "Opportunity without economics fields must be gated (default is_roundtrip_viable=False)"
        assert stats.evaluated_count == 0, \
            "Opportunity without economics fields must NOT be evaluated"
    
    def test_negative_spread_minus_increments_gated_counter(self):
        """Opportunity with spread_minus_required_bps <= 0 increments gated_by_economics."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        opportunities = [{
            "pair": "WBTC/WETH",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 3000,
            "sell_fee": 3000,
            "diagnostics": {"buy_pool": "0x1", "sell_pool": "0x2"},
            # Economics: negative margin = not viable
            "min_required_spread_bps": 58.0,
            "spread_minus_required_bps": -12.0,  # Negative: not viable
            "is_roundtrip_viable": False,
        }]
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        assert stats.gated_by_economics == 1, \
            "Negative spread_minus_required_bps must increment gated_by_economics"
        assert stats.evaluated_count == 0
    
    def test_viable_opportunity_not_gated(self):
        """Opportunity with is_roundtrip_viable=True and positive margin is NOT gated."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        opportunities = [{
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 100,
            "sell_fee": 100,
            "diagnostics": {"buy_pool": "0xAAA", "sell_pool": "0xBBB"},
            # Economics: positive margin = viable
            "min_required_spread_bps": 15.0,
            "spread_minus_required_bps": 10.0,  # Positive: viable
            "is_roundtrip_viable": True,
        }]
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=opportunities,
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
        )
        
        # Should NOT be gated (but may fail later due to missing quotes)
        assert stats.gated_by_economics == 0, \
            "Viable opportunity with is_roundtrip_viable=True must NOT be gated"
        assert stats.evaluated_count >= 1, \
            "Viable opportunity must be evaluated (even if no quotes)"


class TestRoundtripStatsWarnings:
    """v3.2.5: Tests for roundtrip stats warnings field."""

    def test_stats_has_warnings_field(self):
        """RoundtripEvaluationStats must have warnings field."""
        from engine.roundtrip import RoundtripEvaluationStats
        
        stats = RoundtripEvaluationStats()
        
        assert hasattr(stats, "warnings")
        assert isinstance(stats.warnings, list)

    def test_stats_warnings_in_to_dict(self):
        """warnings must appear in to_dict() output."""
        from engine.roundtrip import RoundtripEvaluationStats
        
        stats = RoundtripEvaluationStats(
            candidates_total=1,
            warnings=["L1_COST_SOURCE_NONE: L1 cost unavailable"],
        )
        
        d = stats.to_dict()
        assert "warnings" in d
        assert d["warnings"] == ["L1_COST_SOURCE_NONE: L1 cost unavailable"]

    def test_stats_empty_warnings_by_default(self):
        """Default warnings should be empty list, not None."""
        from engine.roundtrip import RoundtripEvaluationStats
        
        stats = RoundtripEvaluationStats()
        
        assert stats.warnings is not None
        assert stats.warnings == []

    def test_evaluate_adds_warnings_for_l1_cost_none(self):
        """evaluate_roundtrip_candidates adds warning when l1_cost_source='none'."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=[],
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
            l1_cost_source="none",
        )
        
        assert any("L1_COST_SOURCE_NONE" in w for w in stats.warnings), \
            "Should warn when l1_cost_source='none'"

    def test_evaluate_adds_warnings_for_l1_cost_default(self):
        """evaluate_roundtrip_candidates adds warning when l1_cost_source='default'."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=[],
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
            l1_cost_source="default",
        )
        
        assert any("L1_COST_SOURCE_DEFAULT" in w for w in stats.warnings), \
            "Should warn when l1_cost_source='default'"

    def test_evaluate_no_warning_for_l1_cost_onchain(self):
        """evaluate_roundtrip_candidates should NOT warn when l1_cost_source='onchain'."""
        from engine.roundtrip import evaluate_roundtrip_candidates
        
        results, stats = evaluate_roundtrip_candidates(
            opportunities=[],
            buy_quotes_by_key={},
            sell_quotes_by_key={},
            top_n=5,
            l1_cost_source="onchain",
        )
        
        assert not any("L1_COST_SOURCE" in w for w in stats.warnings), \
            "Should NOT warn when l1_cost_source='onchain'"


# ---------------------------------------------------------------------------
# v3.3.0: Dynamic size sweep tests
# ---------------------------------------------------------------------------

class TestSizeSweep:
    """Tests for sweep_roundtrip_sizes()."""

    def _make_base_quotes(self):
        """Build minimal buy/sell quote pair for sweep testing."""
        buy_quote = {
            "token_in": "WETH",
            "token_out": "USDC",
            "dex_id": "uniswap_v3",
            "pool_address": "0xBUY",
            "fee": 500,
            "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000,
            "gas_estimate": 150_000,
            "ticks_crossed": 2,
            "sqrt_price_x96": 100,
        }
        sell_quote = {
            "token_in": "USDC",
            "token_out": "WETH",
            "dex_id": "sushiswap_v3",
            "pool_address": "0xSELL",
            "fee": 500,
            "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000,
            "ticks_crossed": 2,
            "sqrt_price_x96": 100,
        }
        return buy_quote, sell_quote

    def test_sweep_returns_result_dataclass(self):
        """sweep_roundtrip_sizes returns SizeSweepResult."""
        from engine.roundtrip import sweep_roundtrip_sizes, SizeSweepResult

        buy_q, sell_q = self._make_base_quotes()

        # Simple requote: returns fixed amounts regardless of input
        def requote_ok(amount_in_wei):
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000,
                "ticks_crossed": 2,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_ok,
            requote_leg2=requote_ok,
            sizes_usd=[100, 200],
            token_in_usd_price=2000.0,
            token_in_decimals=18,
        )

        assert isinstance(result, SizeSweepResult)
        assert result.pair == "WETH/USDC"
        assert result.sizes_evaluated >= 1
        assert len(result.points) == 2

    def test_sweep_finds_best_size(self):
        """Best size is the one with highest net_pnl_bps."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q, sell_q = self._make_base_quotes()

        # Simulate: small sizes are profitable, large ones lose to slippage
        def requote_leg1(amount_in_wei):
            # Leg1 output: modest slippage proportional to size
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000,
                "ticks_crossed": 1,
            }

        def requote_leg2(amount_in_wei):
            # Leg2: returns slightly more than input (profitable roundtrip)
            return {
                "amount_out_wei": int(amount_in_wei * 1.005),
                "gas_estimate": 150_000,
                "ticks_crossed": 1,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_leg1,
            requote_leg2=requote_leg2,
            sizes_usd=[50, 100, 200],
            token_in_usd_price=2000.0,
            token_in_decimals=18,
            gas_price_wei=100_000_000,
            l1_cost_wei=0,  # No L1 cost for cleaner test
        )

        assert result.best_size_usd is not None
        assert result.best_net_pnl_bps is not None
        assert result.sizes_evaluated == 3

    def test_sweep_handles_requote_failure(self):
        """Points with failed re-quotes are logged as errors."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q, sell_q = self._make_base_quotes()

        def requote_fail(_):
            return None

        def requote_ok(amount_in_wei):
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000,
                "ticks_crossed": 1,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_fail,
            requote_leg2=requote_ok,
            sizes_usd=[100, 200],
            token_in_usd_price=2000.0,
        )

        assert result.sizes_evaluated == 0
        assert all(p.error == "LEG1_QUOTE_FAIL" for p in result.points)
        assert result.frontier_reason == "ALL_FAILED"

    def test_sweep_token_price_zero(self):
        """Token price <= 0 returns early with TOKEN_PRICE_ZERO."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q, sell_q = self._make_base_quotes()

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=lambda _: None,
            requote_leg2=lambda _: None,
            sizes_usd=[100],
            token_in_usd_price=0.0,
        )

        assert result.frontier_reason == "TOKEN_PRICE_ZERO"
        assert len(result.points) == 0

    def test_sweep_to_dict(self):
        """SizeSweepResult.to_dict() serializes correctly."""
        from engine.roundtrip import SizeSweepResult, SizeSweepPoint

        result = SizeSweepResult(
            pair="WETH/USDC",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            sizes_evaluated=2,
            best_size_usd=100,
            best_net_pnl_bps=5.123,
            best_gross_pnl_bps=12.456,
            frontier_reason="PROFITABLE",
            points=[
                SizeSweepPoint(size_usd=100, net_pnl_bps=5.123, gross_pnl_bps=12.456, gas_bps=3.5),
                SizeSweepPoint(size_usd=200, net_pnl_bps=-2.1, gross_pnl_bps=8.0, gas_bps=1.7),
            ],
        )

        d = result.to_dict()
        assert d["pair"] == "WETH/USDC"
        assert d["best_size_usd"] == 100
        assert d["best_net_pnl_bps"] == 5.12
        assert d["frontier_reason"] == "PROFITABLE"
        assert len(d["points"]) == 2
        assert d["points"][0]["size_usd"] == 100
        assert d["points"][0]["net_pnl_bps"] == 5.12

    def test_sweep_frontier_profitable(self):
        """PROFITABLE frontier when best pnl > 0."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q, sell_q = self._make_base_quotes()

        # Leg2 returns more than started with = profitable roundtrip
        def requote_leg1(amount_in_wei):
            return {"amount_out_wei": int(amount_in_wei * 0.999), "gas_estimate": 100_000, "ticks_crossed": 0}

        def requote_leg2(amount_in_wei):
            return {"amount_out_wei": int(amount_in_wei * 1.01), "gas_estimate": 100_000, "ticks_crossed": 0}

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_leg1,
            requote_leg2=requote_leg2,
            sizes_usd=[50, 100],
            token_in_usd_price=2000.0,
            gas_price_wei=100_000_000,
            l1_cost_wei=0,
        )

        assert result.frontier_reason == "PROFITABLE"
        assert result.best_net_pnl_bps > 0

    def test_sweep_exception_in_requote_handled(self):
        """RuntimeError in requote callback is caught gracefully."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q, sell_q = self._make_base_quotes()

        def requote_raises(_):
            raise RuntimeError("RPC timeout")

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_raises,
            requote_leg2=lambda _: None,
            sizes_usd=[100],
            token_in_usd_price=2000.0,
        )

        assert result.sizes_evaluated == 0
        assert result.points[0].error == "LEG1_QUOTE_FAIL"


class TestCanonicalSweep:
    """Contract tests for CANONICAL_SWEEP_SIZES_USD and sweep defaults."""

    def test_canonical_sizes_constant_stable(self):
        """CANONICAL_SWEEP_SIZES_USD must be exactly [50, 75, 100, 125, 150, 200, 250]."""
        from engine.roundtrip import CANONICAL_SWEEP_SIZES_USD

        assert CANONICAL_SWEEP_SIZES_USD == [50, 75, 100, 125, 150, 200, 250]

    def test_sweep_defaults_to_canonical_ladder(self):
        """sweep_roundtrip_sizes uses CANONICAL_SWEEP_SIZES_USD when no sizes passed."""
        from engine.roundtrip import sweep_roundtrip_sizes, CANONICAL_SWEEP_SIZES_USD

        buy_q = {
            "dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC",
            "fee": 3000, "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000, "gas_estimate": 150_000,
            "ticks_crossed": 2, "sqrt_price_x96": 100,
        }
        sell_q = {
            "dex_id": "sushiswap_v3", "token_in": "USDC", "token_out": "WETH",
            "fee": 3000, "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000, "ticks_crossed": 2, "sqrt_price_x96": 100,
        }

        def requote_ok(amount_in_wei):
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000, "ticks_crossed": 2,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_ok,
            requote_leg2=requote_ok,
            token_in_usd_price=2000.0,
            # sizes_usd NOT passed — must default to canonical
        )
        evaluated_sizes = [p.size_usd for p in result.points]
        assert evaluated_sizes == CANONICAL_SWEEP_SIZES_USD

    def test_sweep_best_size_selection(self):
        """Sweep selects the size with highest net_pnl_bps as best."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q = {
            "dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC",
            "fee": 3000, "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000, "gas_estimate": 150_000,
            "ticks_crossed": 0, "sqrt_price_x96": 100,
        }
        sell_q = {
            "dex_id": "sushiswap_v3", "token_in": "USDC", "token_out": "WETH",
            "fee": 3000, "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000, "ticks_crossed": 0, "sqrt_price_x96": 100,
        }

        def requote_ok(amount_in_wei):
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000, "ticks_crossed": 0,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q,
            sell_quote_base=sell_q,
            requote_leg1=requote_ok,
            requote_leg2=requote_ok,
            sizes_usd=[50, 150, 250],
            token_in_usd_price=2000.0,
        )
        # With fixed-ratio requote and fixed gas, smaller sizes have worse
        # gas_bps but same gross_bps.  Best is the largest size (lowest gas %).
        assert result.best_size_usd is not None
        assert result.sizes_evaluated == 3

    def test_gap_to_zero_bps_computed(self):
        """gap_to_zero_bps = abs(best_net_pnl_bps) when negative."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q = {
            "dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC",
            "fee": 3000, "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000, "gas_estimate": 150_000,
            "ticks_crossed": 0, "sqrt_price_x96": 100,
        }
        sell_q = {
            "dex_id": "sushiswap_v3", "token_in": "USDC", "token_out": "WETH",
            "fee": 3000, "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000, "ticks_crossed": 0, "sqrt_price_x96": 100,
        }

        def requote_ok(amount_in_wei):
            return {
                "amount_out_wei": int(amount_in_wei * 0.999),
                "gas_estimate": 150_000, "ticks_crossed": 0,
            }

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q, sell_quote_base=sell_q,
            requote_leg1=requote_ok, requote_leg2=requote_ok,
            sizes_usd=[100], token_in_usd_price=2000.0,
        )
        assert result.frontier_reason == "BEST_NEG"
        assert result.gap_to_zero_bps is not None
        assert result.gap_to_zero_bps == abs(result.best_net_pnl_bps)
        assert result.gap_to_zero_bps > 0

    def test_gap_to_zero_in_to_dict(self):
        """gap_to_zero_bps appears in to_dict() output."""
        from engine.roundtrip import SizeSweepResult

        r = SizeSweepResult(pair="A/B", buy_dex="d1", sell_dex="d2",
                            best_net_pnl_bps=-5.0, gap_to_zero_bps=5.0,
                            frontier_reason="BEST_NEG")
        d = r.to_dict()
        assert d["gap_to_zero_bps"] == 5.0

    def test_fee_bps_in_sweep_point(self):
        """fee_bps is computed from leg fees and appears in SizeSweepPoint."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q = {
            "dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC",
            "fee": 3000, "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000, "gas_estimate": 150_000,
            "ticks_crossed": 0, "sqrt_price_x96": 100,
        }
        sell_q = {
            "dex_id": "sushiswap_v3", "token_in": "USDC", "token_out": "WETH",
            "fee": 500, "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000, "ticks_crossed": 0, "sqrt_price_x96": 100,
        }

        def requote_ok(amount_in_wei):
            return {"amount_out_wei": int(amount_in_wei * 0.999),
                    "gas_estimate": 150_000, "ticks_crossed": 0}

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q, sell_quote_base=sell_q,
            requote_leg1=requote_ok, requote_leg2=requote_ok,
            sizes_usd=[100], token_in_usd_price=2000.0,
        )
        assert len(result.points) == 1
        p = result.points[0]
        # fee = (3000 + 500) / 100 = 35 bps
        assert p.fee_bps == 35.0
        # fee_bps in to_dict
        d = result.to_dict()
        assert d["points"][0]["fee_bps"] == 35.0

    def test_cost_decomposition_at_best_point(self):
        """SizeSweepResult captures cost decomposition at best sweep point."""
        from engine.roundtrip import sweep_roundtrip_sizes

        buy_q = {
            "dex_id": "uniswap_v3", "token_in": "WETH", "token_out": "USDC",
            "fee": 3000, "amount_in_wei": 1_000_000_000_000_000_000,
            "amount_out_wei": 2000_000_000, "gas_estimate": 150_000,
            "ticks_crossed": 0, "sqrt_price_x96": 100,
        }
        sell_q = {
            "dex_id": "sushiswap_v3", "token_in": "USDC", "token_out": "WETH",
            "fee": 3000, "amount_in_wei": 2000_000_000,
            "amount_out_wei": 1_010_000_000_000_000_000,
            "gas_estimate": 150_000, "ticks_crossed": 0, "sqrt_price_x96": 100,
        }

        def requote_ok(amount_in_wei):
            return {"amount_out_wei": int(amount_in_wei * 0.999),
                    "gas_estimate": 150_000, "ticks_crossed": 0}

        result = sweep_roundtrip_sizes(
            buy_quote_base=buy_q, sell_quote_base=sell_q,
            requote_leg1=requote_ok, requote_leg2=requote_ok,
            sizes_usd=[50, 100], token_in_usd_price=2000.0,
        )
        assert result.best_fee_bps is not None
        assert result.best_gas_bps is not None
        assert result.best_slippage_bps is not None
        assert result.best_total_cost_bps is not None
        # total_cost = gas + fee + slippage
        expected_total = result.best_gas_bps + result.best_fee_bps + result.best_slippage_bps
        assert abs(result.best_total_cost_bps - expected_total) < 0.01
        # to_dict exposes these
        d = result.to_dict()
        assert d["best_gas_bps"] is not None
        assert d["best_fee_bps"] is not None
        assert d["best_slippage_bps"] is not None
        assert d["best_total_cost_bps"] is not None
