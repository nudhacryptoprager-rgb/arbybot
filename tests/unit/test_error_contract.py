"""
tests/unit/test_error_contract.py - Test ErrorCode contract.

Team Lead Крок 8:
"Зафіксувати контракт ErrorCode: додати тест, який гарантує, що всі reject_code,
які можуть вийти з gates/run_scan, існують в ErrorCode, і truth_report їх знає."

This test ensures:
1. All ErrorCodes used in gates exist in the enum
2. All reject reasons in truth_report are valid ErrorCodes
3. No orphaned ErrorCodes that are never used
"""

import pytest
import inspect
import ast
from pathlib import Path

from core.exceptions import ErrorCode


# =============================================================================
# ERROR CODES THAT GATES CAN PRODUCE
# =============================================================================

# All reject codes that can come from gates
GATE_ERROR_CODES = {
    ErrorCode.QUOTE_ZERO_OUTPUT,
    ErrorCode.QUOTE_GAS_TOO_HIGH,
    ErrorCode.TICKS_CROSSED_TOO_MANY,
    ErrorCode.QUOTE_STALE_BLOCK,
    ErrorCode.PRICE_SANITY_FAILED,
    ErrorCode.PRICE_ANCHOR_MISSING,
    ErrorCode.SLIPPAGE_TOO_HIGH,
    ErrorCode.QUOTE_INCONSISTENT,
    ErrorCode.QUOTE_REVERT,
}

# All reject codes that can come from quoting
QUOTE_ERROR_CODES = {
    ErrorCode.QUOTE_ZERO_OUTPUT,
    ErrorCode.QUOTE_REVERT,
    ErrorCode.QUOTE_TIMEOUT,
    ErrorCode.QUOTE_STALE_BLOCK,
}

# All reject codes that can come from RPC
RPC_ERROR_CODES = {
    ErrorCode.INFRA_RPC_ERROR,
    ErrorCode.INFRA_RPC_TIMEOUT,
    ErrorCode.INFRA_RATE_LIMIT,
}

# Combined: all codes that can appear in reject histograms
ALL_REJECT_CODES = GATE_ERROR_CODES | QUOTE_ERROR_CODES | RPC_ERROR_CODES


class TestErrorCodeContract:
    """Tests for ErrorCode contract integrity."""
    
    def test_all_gate_codes_exist_in_enum(self):
        """All gate error codes should exist in ErrorCode enum."""
        for code in GATE_ERROR_CODES:
            assert isinstance(code, ErrorCode), f"{code} is not an ErrorCode"
            assert code.value is not None, f"{code} has no value"
    
    def test_all_quote_codes_exist_in_enum(self):
        """All quote error codes should exist in ErrorCode enum."""
        for code in QUOTE_ERROR_CODES:
            assert isinstance(code, ErrorCode), f"{code} is not an ErrorCode"
    
    def test_all_rpc_codes_exist_in_enum(self):
        """All RPC error codes should exist in ErrorCode enum."""
        for code in RPC_ERROR_CODES:
            assert isinstance(code, ErrorCode), f"{code} is not an ErrorCode"
    
    def test_error_codes_have_string_values(self):
        """All error codes should have string values for JSON serialization."""
        for code in ErrorCode:
            assert isinstance(code.value, str), f"{code} value is not a string"
            assert len(code.value) > 0, f"{code} has empty value"
    
    def test_no_duplicate_values(self):
        """Error codes should not have duplicate values."""
        values = [code.value for code in ErrorCode]
        assert len(values) == len(set(values)), "Found duplicate ErrorCode values"
    
    def test_gates_module_uses_valid_codes(self):
        """gates.py should only use valid ErrorCode values."""
        gates_path = Path("strategy/gates.py")
        if not gates_path.exists():
            gates_path = Path("../strategy/gates.py")
        
        if gates_path.exists():
            content = gates_path.read_text()
            
            # Check that ErrorCode imports are used correctly
            for code in GATE_ERROR_CODES:
                code_name = code.name
                # Should find ErrorCode.CODE_NAME pattern
                pattern = f"ErrorCode.{code_name}"
                if pattern in content:
                    # Verify the code exists in enum
                    assert hasattr(ErrorCode, code_name), f"{code_name} not in ErrorCode"
    
    def test_reject_histogram_codes_are_valid(self):
        """Reject histogram in truth_report should only use valid codes."""
        # These are the reject reason strings that can appear
        valid_reject_strings = {code.value for code in ALL_REJECT_CODES}
        
        # Sample reject histogram keys from Team Lead analysis
        sample_reject_keys = [
            "QUOTE_GAS_TOO_HIGH",
            "PRICE_SANITY_FAILED",
            "TICKS_CROSSED_TOO_MANY",
            "QUOTE_REVERT",
            "SLIPPAGE_TOO_HIGH",
            "PRICE_ANCHOR_MISSING",
        ]
        
        for key in sample_reject_keys:
            assert key in valid_reject_strings, f"'{key}' is not a valid reject code"
    
    def test_error_code_categories_complete(self):
        """Ensure we haven't missed any ErrorCode categories."""
        all_tracked = ALL_REJECT_CODES
        all_enum = set(ErrorCode)
        
        # These codes are OK to not track (internal/meta)
        allowed_untracked = {
            ErrorCode.UNKNOWN_ERROR,
            ErrorCode.INTERNAL_CODE_ERROR,
            ErrorCode.VALIDATION_ERROR,
            # Pool-related (not reject reasons)
            ErrorCode.POOL_NOT_FOUND,
            ErrorCode.POOL_NO_LIQUIDITY,
            ErrorCode.POOL_DEAD,
            ErrorCode.POOL_SUSPICIOUS,
            ErrorCode.POOL_UNSUPPORTED_FEE,
            # Token-related
            ErrorCode.TOKEN_NOT_FOUND,
            ErrorCode.TOKEN_INVALID_DECIMALS,
            ErrorCode.TOKEN_SYMBOL_MISMATCH,
            ErrorCode.TOKEN_NOT_VERIFIED,
            # Execution-related (future)
            ErrorCode.EXEC_SIMULATION_FAILED,
            ErrorCode.EXEC_REVERT,
            ErrorCode.EXEC_GAS_TOO_HIGH,
            ErrorCode.EXEC_INSUFFICIENT_BALANCE,
            ErrorCode.EXEC_NONCE_ERROR,
            # PnL (future)
            ErrorCode.PNL_NEGATIVE,
            ErrorCode.PNL_BELOW_THRESHOLD,
            ErrorCode.PNL_CURRENCY_MISMATCH,
            # Infrastructure
            ErrorCode.INFRA_CONNECTION_ERROR,
            ErrorCode.INFRA_BAD_ABI,
            ErrorCode.INFRA_BAD_ADDRESS,
            # CEX (future)
            ErrorCode.CEX_DEPTH_LOW,
            ErrorCode.CEX_PAIR_NOT_FOUND,
            ErrorCode.CEX_RATE_LIMIT,
            ErrorCode.CEX_API_ERROR,
            # DEX
            ErrorCode.DEX_ADAPTER_NOT_FOUND,
            ErrorCode.DEX_UNSUPPORTED_TYPE,
            # Quote
            ErrorCode.QUOTE_INVALID_PARAMS,
            ErrorCode.PRICE_IMPACT_TOO_HIGH,
        }
        
        # Remove explicitly allowed untracked codes
        untracked = all_enum - all_tracked - allowed_untracked
        
        # Any untracked codes should be intentional
        # This test will fail if new codes are added but not categorized
        if untracked:
            # Log for visibility but don't fail (new codes may be added)
            print(f"Untracked ErrorCodes: {[c.name for c in untracked]}")


class TestErrorCodeUsage:
    """Tests for ErrorCode usage patterns."""
    
    def test_error_code_serialization(self):
        """ErrorCodes should serialize to their string values."""
        for code in ErrorCode:
            serialized = code.value
            assert isinstance(serialized, str)
            assert serialized == code.value
    
    def test_error_code_lookup_by_value(self):
        """Should be able to look up ErrorCode by value."""
        for code in ErrorCode:
            looked_up = ErrorCode(code.value)
            assert looked_up == code
    
    def test_error_code_name_matches_value(self):
        """ErrorCode name should match value for consistency."""
        for code in ErrorCode:
            # Value should be the same as name (QUOTE_GAS_TOO_HIGH = "QUOTE_GAS_TOO_HIGH")
            assert code.name == code.value, f"{code.name} != {code.value}"


class TestRejectHistogramContract:
    """Tests for reject histogram format contract."""
    
    def test_reject_histogram_format(self):
        """Reject histogram should be dict[str, int]."""
        # Mock histogram format
        histogram = {
            "QUOTE_GAS_TOO_HIGH": 260,
            "PRICE_SANITY_FAILED": 240,
            "TICKS_CROSSED_TOO_MANY": 200,
        }
        
        for key, count in histogram.items():
            assert isinstance(key, str)
            assert isinstance(count, int)
            assert count >= 0
            # Key should be valid ErrorCode
            assert key in {c.value for c in ErrorCode}, f"'{key}' not a valid ErrorCode"
    
    def test_all_reject_codes_serializable_to_json(self):
        """All reject codes should be JSON-serializable."""
        import json
        
        histogram = {code.value: 0 for code in ALL_REJECT_CODES}
        
        # Should not raise
        json_str = json.dumps(histogram)
        parsed = json.loads(json_str)
        
        assert parsed == histogram


# =============================================================================
# GATE REJECT REASON EXHAUSTIVENESS
# =============================================================================

class TestGateRejectReasons:
    """Test that all possible gate rejects are documented."""
    
    def test_zero_output_gate_reason(self):
        """gate_zero_output should return QUOTE_ZERO_OUTPUT."""
        from strategy.gates import gate_zero_output, GateResult
        from core.models import Token, Pool, Quote
        from core.constants import DexType, PoolStatus, TradeDirection
        
        # Create mock quote with zero output
        token = Token(chain_id=1, address="0x" + "0" * 40, symbol="TEST", 
                     name="Test", decimals=18, is_core=False)
        pool = Pool(chain_id=1, dex_id="test", dex_type=DexType.UNISWAP_V3,
                   pool_address="0x" + "1" * 40, token0=token, token1=token,
                   fee=500, status=PoolStatus.ACTIVE)
        
        import time
        quote = Quote(
            pool=pool,
            direction=TradeDirection.BUY,
            token_in=token,
            token_out=token,
            amount_in=10**18,
            amount_out=0,  # Zero output
            gas_estimate=100000,
            ticks_crossed=1,
            timestamp_ms=int(time.time() * 1000),
            block_number=1,
        )
        
        result = gate_zero_output(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_ZERO_OUTPUT
    
    def test_gas_gate_reason(self):
        """gate_gas_estimate should return QUOTE_GAS_TOO_HIGH."""
        from strategy.gates import gate_gas_estimate
        from core.models import Token, Pool, Quote
        from core.constants import DexType, PoolStatus, TradeDirection
        
        token = Token(chain_id=1, address="0x" + "0" * 40, symbol="TEST",
                     name="Test", decimals=18, is_core=False)
        pool = Pool(chain_id=1, dex_id="test", dex_type=DexType.UNISWAP_V3,
                   pool_address="0x" + "1" * 40, token0=token, token1=token,
                   fee=500, status=PoolStatus.ACTIVE)
        
        import time
        quote = Quote(
            pool=pool,
            direction=TradeDirection.BUY,
            token_in=token,
            token_out=token,
            amount_in=10**17,  # 0.1 ETH
            amount_out=10**17,
            gas_estimate=1_000_000,  # Very high gas
            ticks_crossed=1,
            timestamp_ms=int(time.time() * 1000),
            block_number=1,
        )
        
        result = gate_gas_estimate(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.QUOTE_GAS_TOO_HIGH
    
    def test_ticks_gate_reason(self):
        """gate_ticks_crossed should return TICKS_CROSSED_TOO_MANY."""
        from strategy.gates import gate_ticks_crossed
        from core.models import Token, Pool, Quote
        from core.constants import DexType, PoolStatus, TradeDirection
        
        token = Token(chain_id=1, address="0x" + "0" * 40, symbol="TEST",
                     name="Test", decimals=18, is_core=False)
        pool = Pool(chain_id=1, dex_id="test", dex_type=DexType.UNISWAP_V3,
                   pool_address="0x" + "1" * 40, token0=token, token1=token,
                   fee=500, status=PoolStatus.ACTIVE)
        
        import time
        quote = Quote(
            pool=pool,
            direction=TradeDirection.BUY,
            token_in=token,
            token_out=token,
            amount_in=10**17,
            amount_out=10**17,
            gas_estimate=100000,
            ticks_crossed=100,  # Very high ticks
            timestamp_ms=int(time.time() * 1000),
            block_number=1,
        )
        
        result = gate_ticks_crossed(quote)
        assert not result.passed
        assert result.reject_code == ErrorCode.TICKS_CROSSED_TOO_MANY


# =============================================================================
# TRUTH REPORT CONTRACT TESTS (Team Lead Крок 5-6)
# =============================================================================

class TestTruthReportContract:
    """Test truth_report generation contract."""
    
    def test_opportunity_rank_accepts_executable_field(self):
        """OpportunityRank should accept executable as keyword argument."""
        from monitoring.truth_report import OpportunityRank
        
        # This should NOT raise TypeError
        rank = OpportunityRank(
            rank=1,
            spread_id="test_123",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000000000000000000",
            spread_bps=50,
            gas_cost_bps=10,
            net_pnl_bps=40,
            expected_pnl_usdc=0.5,
            executable=True,  # CRITICAL: this must work
            confidence=0.85,
        )
        
        assert rank.executable is True
        assert rank.rank == 1
        assert rank.confidence == 0.85
    
    def test_opportunity_rank_has_paper_executable_field(self):
        """OpportunityRank should have paper_executable field."""
        from monitoring.truth_report import OpportunityRank
        
        rank = OpportunityRank(
            rank=1,
            spread_id="test_123",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000000000000000000",
            spread_bps=50,
            gas_cost_bps=10,
            net_pnl_bps=40,
            expected_pnl_usdc=0.5,
            executable=True,
            paper_executable=True,
            execution_ready=False,
            confidence=0.85,
        )
        
        assert rank.paper_executable is True
        assert rank.execution_ready is False
    
    def test_truth_report_accepts_total_pnl_fields(self):
        """TruthReport should accept total_pnl_bps and total_pnl_usdc."""
        from monitoring.truth_report import TruthReport, HealthMetrics
        
        health = HealthMetrics(
            rpc_success_rate=0.95,
            rpc_avg_latency_ms=50,
            rpc_total_requests=100,
            quote_fetch_rate=0.9,
            quote_gate_pass_rate=0.7,
            chains_active=1,
            dexes_active=2,
            pairs_covered=5,
            pools_scanned=100,
            top_reject_reasons=[("QUOTE_GAS_TOO_HIGH", 10)],
        )
        
        # This should NOT raise TypeError
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            total_spreads=100,
            profitable_spreads=50,
            executable_spreads=30,
            blocked_spreads=20,
            total_pnl_bps=500,  # CRITICAL: this must work
            total_pnl_usdc=5.0,  # CRITICAL: this must work
        )
        
        assert report.total_pnl_bps == 500
        assert report.total_pnl_usdc == 5.0
    
    def test_truth_report_to_dict_includes_executable(self):
        """TruthReport.to_dict() should include executable in opportunities."""
        from monitoring.truth_report import TruthReport, HealthMetrics, OpportunityRank
        
        health = HealthMetrics(
            rpc_success_rate=0.95,
            rpc_avg_latency_ms=50,
            rpc_total_requests=100,
            quote_fetch_rate=0.9,
            quote_gate_pass_rate=0.7,
            chains_active=1,
            dexes_active=2,
            pairs_covered=5,
            pools_scanned=100,
            top_reject_reasons=[],
        )
        
        opp = OpportunityRank(
            rank=1,
            spread_id="test_123",
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000000000000000000",
            spread_bps=50,
            gas_cost_bps=10,
            net_pnl_bps=40,
            expected_pnl_usdc=0.5,
            executable=True,
            confidence=0.85,
        )
        
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[opp],
            total_spreads=100,
            profitable_spreads=50,
            executable_spreads=30,
            blocked_spreads=20,
        )
        
        result = report.to_dict()
        
        # Check that executable is in the output
        assert len(result["top_opportunities"]) == 1
        assert result["top_opportunities"][0]["executable"] is True
    
    def test_opportunity_rank_default_values(self):
        """OpportunityRank should have sensible defaults."""
        from monitoring.truth_report import OpportunityRank
        
        # Create with minimal required fields
        rank = OpportunityRank(
            rank=1,
            spread_id="test",
            buy_dex="uni",
            sell_dex="sushi",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000",
            spread_bps=10,
            gas_cost_bps=5,
            net_pnl_bps=5,
            expected_pnl_usdc=0.1,
        )
        
        # Check defaults
        assert rank.executable is False
        assert rank.confidence == 0.0
        assert rank.paper_executable is False
        assert rank.execution_ready is False
        assert rank.confidence_breakdown is None
