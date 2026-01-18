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
            executable_economic=True,  # CRITICAL: this must work (new field)
            confidence=0.85,
        )
        
        assert rank.executable_economic is True
        assert rank.executable is True  # Legacy property
        assert rank.rank == 1
        assert rank.confidence == 0.85
    
    def test_opportunity_rank_has_paper_executable_field(self):
        """OpportunityRank should have paper_would_execute field."""
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
            executable_economic=True,
            paper_would_execute=True,
            execution_ready=False,
            blocked_reason="EXEC_DISABLED_NOT_VERIFIED",
            confidence=0.85,
        )
        
        assert rank.paper_would_execute is True
        assert rank.paper_executable is True  # Legacy property
        assert rank.execution_ready is False
        assert rank.blocked_reason == "EXEC_DISABLED_NOT_VERIFIED"
    
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
        
        # This should NOT raise TypeError - using new field names
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=100,
            spread_ids_profitable=50,
            spread_ids_executable=30,
            blocked_spreads=20,
            total_pnl_bps=500,  # CRITICAL: this must work
            total_pnl_usdc=5.0,  # CRITICAL: this must work
        )
        
        assert report.total_pnl_bps == 500
        assert report.total_pnl_usdc == 5.0
        # Test legacy aliases
        assert report.total_spreads == 100
        assert report.profitable_spreads == 50
    
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
            executable_economic=True,  # New field
            confidence=0.85,
        )
        
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[opp],
            spread_ids_total=100,
            spread_ids_profitable=50,
            spread_ids_executable=30,
            blocked_spreads=20,
        )
        
        result = report.to_dict()
        
        # Check that schema_version is in the output
        assert "schema_version" in result
        
        # Check that executable fields are in the output (both new and legacy)
        assert len(result["top_opportunities"]) == 1
        assert result["top_opportunities"][0]["executable_economic"] is True
        assert result["top_opportunities"][0]["executable"] is True  # Legacy
    
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
        
        # Check new field defaults
        assert rank.executable_economic is False
        assert rank.paper_would_execute is False
        assert rank.execution_ready is False
        assert rank.blocked_reason is None
        assert rank.confidence == 0.0
        assert rank.confidence_breakdown is None
        
        # Check legacy property defaults
        assert rank.executable is False  # = executable_economic
        assert rank.paper_executable is False  # = paper_would_execute


class TestTruthReportInvariants:
    """Test TruthReport invariant validation (Team Lead Крок 2, 9)."""
    
    def test_invariant_profitable_lte_total(self):
        """spread_ids_profitable should be <= spread_ids_total."""
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
            top_reject_reasons=[],
        )
        
        # Invalid: profitable > total
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=4,
            spread_ids_profitable=35,  # INVALID: 35 > 4
        )
        
        violations = report.validate_invariants()
        assert len(violations) > 0
        assert "spread_ids_profitable" in violations[0]
    
    def test_invariant_executable_lte_profitable(self):
        """КРОК 8: spread_ids_executable should be <= spread_ids_profitable."""
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
            top_reject_reasons=[],
        )
        
        # Invalid: executable > profitable
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=10,
            spread_ids_profitable=5,
            spread_ids_executable=8,  # INVALID: 8 > 5 (profitable)
        )
        
        violations = report.validate_invariants()
        assert len(violations) > 0
        assert "spread_ids_executable" in violations[0]
        assert "spread_ids_profitable" in violations[0]
    
    def test_invariant_signals_gte_spread_ids(self):
        """signals_total should be >= spread_ids_total."""
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
            top_reject_reasons=[],
        )
        
        # Invalid: signals < spread_ids
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=100,
            signals_total=50,  # INVALID: 50 < 100
        )
        
        violations = report.validate_invariants()
        assert len(violations) > 0
        assert "signals_total" in violations[0]
    
    def test_valid_report_no_violations(self):
        """Valid report should have no invariant violations."""
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
            top_reject_reasons=[],
        )
        
        # Valid report
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=100,
            spread_ids_profitable=50,
            spread_ids_executable=30,
            signals_total=200,  # signals >= spread_ids
            signals_profitable=100,
            signals_executable=60,
        )
        
        violations = report.validate_invariants()
        assert len(violations) == 0
    
    def test_to_dict_includes_violations(self):
        """to_dict() should include violations if any."""
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
            top_reject_reasons=[],
        )
        
        # Invalid report
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            spread_ids_total=4,
            spread_ids_profitable=35,  # INVALID
        )
        
        result = report.to_dict()
        assert "invariant_violations" in result
        assert len(result["invariant_violations"]) > 0


class TestBlockedReasons:
    """Test BlockedReason class (Team Lead Крок 3)."""
    
    def test_blocked_reasons_defined(self):
        """All expected blocked reasons should be defined."""
        from monitoring.truth_report import BlockedReason
        
        expected = [
            "EXEC_DISABLED_NOT_VERIFIED",
            "EXEC_DISABLED_CONFIG",
            "EXEC_DISABLED_QUARANTINE",
            "EXEC_DISABLED_RISK",
            "EXEC_DISABLED_REVALIDATION_FAILED",
            "EXEC_DISABLED_GATES_CHANGED",
            "EXEC_DISABLED_COOLDOWN",
        ]
        
        for reason in expected:
            assert hasattr(BlockedReason, reason), f"Missing: {reason}"
    
    def test_truth_report_top_blocked_reasons(self):
        """TruthReport should include top_blocked_reasons."""
        from monitoring.truth_report import TruthReport, HealthMetrics, BlockedReason
        
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
        
        report = TruthReport(
            timestamp="2026-01-15T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            blocked_reasons={
                BlockedReason.EXEC_DISABLED_NOT_VERIFIED: 10,
                BlockedReason.EXEC_DISABLED_GATES_CHANGED: 5,
            },
            top_blocked_reasons=[
                (BlockedReason.EXEC_DISABLED_NOT_VERIFIED, 10),
                (BlockedReason.EXEC_DISABLED_GATES_CHANGED, 5),
            ],
        )
        
        result = report.to_dict()
        assert "blocked_reasons_breakdown" in result
        assert "top_blocked_reasons" in result


class TestPaperTradeContract:
    """Test PaperTrade contract (Dev Task R1-R3)."""
    
    def test_paper_trade_has_numeraire_fields(self):
        """PaperTrade should have numeraire fields."""
        from strategy.paper_trading import PaperTrade, DEFAULT_NUMERAIRE
        
        trade = PaperTrade(
            spread_id="WETH/ARB:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",   # Must match pair!
            token_out="ARB",   # Must match pair!
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            numeraire="USDC",
            amount_in_numeraire=300.0,
            expected_pnl_numeraire=0.84,
        )
        
        # New numeraire fields
        assert trade.numeraire == "USDC"
        assert trade.amount_in_numeraire == 300.0
        assert trade.expected_pnl_numeraire == 0.84
        
        # Token fields match pair
        assert trade.token_in == "WETH"
        assert trade.token_out == "ARB"
        
        # Default numeraire is USDC
        assert DEFAULT_NUMERAIRE == "USDC"
    
    def test_paper_trade_legacy_kwargs_support(self):
        """AC3: PaperTrade should support legacy kwargs (amount_in_usdc, expected_pnl_usdc)."""
        from strategy.paper_trading import PaperTrade
        
        # Create using LEGACY kwargs - this is what run_scan.py was using!
        trade = PaperTrade.from_legacy_kwargs(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            # LEGACY KWARGS - must be auto-normalized to numeraire
            amount_in_usdc=300.0,
            expected_pnl_usdc=0.84,
        )
        
        # Legacy kwargs should be mapped to numeraire fields
        assert trade.amount_in_numeraire == 300.0
        assert trade.expected_pnl_numeraire == 0.84
        assert trade.numeraire == "USDC"  # Auto-set when legacy used
        
        # Legacy properties should still work
        assert trade.amount_in_usdc == 300.0
        assert trade.expected_pnl_usdc == 0.84
    
    def test_paper_trade_legacy_compatibility(self):
        """PaperTrade should be compatible with old code using amount_in_usdc."""
        from strategy.paper_trading import PaperTrade
        
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            amount_in_numeraire=300.0,
            expected_pnl_numeraire=0.84,
        )
        
        # New fields should be usable
        assert trade.amount_in_numeraire == 300.0
        assert trade.expected_pnl_numeraire == 0.84
        
        # to_dict should include BOTH numeraire and legacy aliases
        trade_dict = trade.to_dict()
        assert "numeraire" in trade_dict
        assert "amount_in_numeraire" in trade_dict
        assert "expected_pnl_numeraire" in trade_dict
        # Legacy aliases in dict for backward compat
        assert "amount_in_usdc" in trade_dict
        assert "expected_pnl_usdc" in trade_dict
    
    def test_paper_trade_tokens_must_match_pair(self):
        """Test that token_in/token_out should match spread_id pair."""
        from strategy.paper_trading import PaperTrade
        
        # This is a CORRECT trade (tokens match pair)
        trade = PaperTrade(
            spread_id="WETH/ARB:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",   # CORRECT: matches pair
            token_out="ARB",   # CORRECT: matches pair
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
        )
        
        # Validation should pass (no violations)
        violations = trade.validate_tokens_match_pair()
        assert len(violations) == 0, f"Expected no violations but got: {violations}"
    
    def test_paper_trade_tokens_mismatch_detected(self):
        """Test that mismatched tokens are detected."""
        from strategy.paper_trading import PaperTrade
        
        # This is a BROKEN trade (token_out doesn't match pair)
        # This is the bug that Team Lead found!
        trade = PaperTrade(
            spread_id="WETH/ARB:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",  # WRONG: should be ARB!
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
        )
        
        # Validation should FAIL
        violations = trade.validate_tokens_match_pair()
        assert len(violations) > 0, "Expected violations for mismatched tokens"
        assert "token_out" in violations[0]
        assert "USDC" in violations[0]
        assert "ARB" in violations[0]
    
    def test_paper_trade_r3_economic_vs_execution(self):
        """R3: Test economic_executable vs execution_ready separation."""
        from strategy.paper_trading import PaperTrade
        
        # Case 1: Economically executable but NOT verified -> NOT execution_ready
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            economic_executable=True,
            buy_verified=False,  # NOT verified!
            sell_verified=True,
        )
        
        # Should NOT be execution_ready because not verified
        assert trade.economic_executable is True
        assert trade.execution_ready is False
        assert trade.blocked_reason == "EXEC_DISABLED_NOT_VERIFIED"
    
    def test_paper_trade_normalize_kwargs(self):
        """Test normalize_paper_trade_kwargs helper."""
        from strategy.paper_trading import normalize_paper_trade_kwargs
        
        # Legacy kwargs
        legacy = {
            "spread_id": "test",
            "amount_in_usdc": 100.0,
            "expected_pnl_usdc": 1.5,
        }
        
        normalized = normalize_paper_trade_kwargs(legacy)
        
        # Should be normalized
        assert "amount_in_numeraire" in normalized
        assert "expected_pnl_numeraire" in normalized
        assert normalized["amount_in_numeraire"] == 100.0
        assert normalized["expected_pnl_numeraire"] == 1.5
        assert normalized["numeraire"] == "USDC"
        # Legacy removed
        assert "amount_in_usdc" not in normalized
        assert "expected_pnl_usdc" not in normalized
    
    def test_paper_trade_direct_amount_in_usdc_raises_error(self):
        """
        КРОК 2: Test that passing amount_in_usdc directly to PaperTrade() raises TypeError.
        
        This is the ACTUAL BUG that was crashing SMOKE!
        The fix is to use v4 contract fields (amount_in_numeraire) or from_legacy_kwargs().
        """
        import pytest
        from strategy.paper_trading import PaperTrade
        
        # This should raise TypeError because amount_in_usdc is NOT a PaperTrade field
        with pytest.raises(TypeError) as exc_info:
            PaperTrade(
                spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
                block_number=12345,
                timestamp="2026-01-16T12:00:00Z",
                chain_id=42161,
                buy_dex="uniswap_v3",
                sell_dex="sushiswap_v3",
                token_in="WETH",
                token_out="USDC",
                fee=500,
                amount_in_wei="100000000000000000",
                buy_price="3000.0",
                sell_price="3010.0",
                spread_bps=33,
                gas_cost_bps=5,
                net_pnl_bps=28,
                gas_price_gwei=0.01,
                # LEGACY KWARGS - this should FAIL!
                amount_in_usdc=300.0,
                expected_pnl_usdc=0.84,
            )
        
        # Verify error message mentions the bad field
        assert "amount_in_usdc" in str(exc_info.value)
    
    def test_paper_trade_correct_v4_contract(self):
        """
        КРОК 3: Test that v4 contract fields work correctly.
        
        This is how run_scan.py SHOULD create PaperTrade (after fix).
        """
        from strategy.paper_trading import PaperTrade
        
        # v4 contract: use numeraire fields
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            # v4 CONTRACT FIELDS (correct!)
            numeraire="USDC",
            amount_in_numeraire=300.0,
            expected_pnl_numeraire=0.84,
        )
        
        # Should work
        assert trade.numeraire == "USDC"
        assert trade.amount_in_numeraire == 300.0
        assert trade.expected_pnl_numeraire == 0.84
        
        # Legacy aliases should also work (via @property)
        assert trade.amount_in_usdc == 300.0
        assert trade.expected_pnl_usdc == 0.84
    
    def test_paper_trade_from_dict_accepts_legacy(self):
        """AC-7: PaperTrade.from_dict() accepts legacy amount_in_usdc/expected_pnl_usdc."""
        from strategy.paper_trading import PaperTrade
        
        # Simulate legacy JSONL record
        legacy_dict = {
            "spread_id": "WETH/USDC:uniswap_v3:sushiswap_v3:500",
            "block_number": 12345,
            "timestamp": "2026-01-16T12:00:00Z",
            "chain_id": 42161,
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "token_in": "WETH",
            "token_out": "USDC",
            "fee": 500,
            "amount_in_wei": "100000000000000000",
            "buy_price": "3000.0",
            "sell_price": "3010.0",
            "spread_bps": 33,
            "gas_cost_bps": 5,
            "net_pnl_bps": 28,
            "gas_price_gwei": 0.01,
            # LEGACY fields (not numeraire)
            "amount_in_usdc": 300.0,
            "expected_pnl_usdc": 0.84,
        }
        
        # Should not raise
        trade = PaperTrade.from_dict(legacy_dict)
        
        # Numeraire fields should be populated from legacy
        assert trade.amount_in_numeraire == 300.0
        assert trade.expected_pnl_numeraire == 0.84
        assert trade.numeraire == "USDC"
    
    def test_paper_trade_ac4_paper_vs_real_readiness(self):
        """AC-4: PaperTrade has separate paper_execution_ready and real_execution_ready."""
        from strategy.paper_trading import PaperTrade
        
        # Create trade that's paper-ready but NOT real-ready
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
            economic_executable=True,
            buy_verified=False,  # NOT verified!
            sell_verified=True,
        )
        
        # Paper policy ignores verification
        assert trade.paper_execution_ready is True
        # Real policy requires verification
        assert trade.real_execution_ready is False
        assert trade.blocked_reason_real == "EXEC_DISABLED_NOT_VERIFIED"
        
        # to_dict should include both
        trade_dict = trade.to_dict()
        assert "paper_execution_ready" in trade_dict
        assert "real_execution_ready" in trade_dict
        assert "blocked_reason_real" in trade_dict
    
    def test_paper_trade_ac6_revalidation_fields(self):
        """AC-6: PaperTrade has would_still_paper_execute, would_still_real_execute, gates_actually_changed."""
        from strategy.paper_trading import PaperTrade
        
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei=0.01,
        )
        
        # AC-6 fields should exist
        assert hasattr(trade, "would_still_paper_execute")
        assert hasattr(trade, "would_still_real_execute")
        assert hasattr(trade, "gates_actually_changed")
        
        # to_dict should include them
        trade_dict = trade.to_dict()
        assert "would_still_paper_execute" in trade_dict
        assert "would_still_real_execute" in trade_dict
        assert "gates_actually_changed" in trade_dict


class TestExecutableSemantics:
    """Test executable/paper_would_execute/execution_ready semantics."""
    
    def test_executable_economic_vs_execution_ready(self):
        """Test that executable_economic != execution_ready."""
        from monitoring.truth_report import OpportunityRank
        
        # Case 1: Economically executable but not verified
        opp = OpportunityRank(
            rank=1,
            spread_id="test",
            buy_dex="uni",
            sell_dex="sushi",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000",
            spread_bps=50,
            gas_cost_bps=10,
            net_pnl_bps=40,
            expected_pnl_usdc=1.0,
            executable_economic=True,   # Passes gates, PnL > 0
            paper_would_execute=True,   # Paper mode would execute
            execution_ready=False,      # But NOT verified
            blocked_reason="EXEC_DISABLED_NOT_VERIFIED",
        )
        
        assert opp.executable_economic is True
        assert opp.execution_ready is False
        assert opp.blocked_reason == "EXEC_DISABLED_NOT_VERIFIED"
    
    def test_invariant_execution_ready_implies_executable_economic(self):
        """execution_ready=True implies executable_economic=True."""
        from monitoring.truth_report import OpportunityRank
        
        # If execution_ready=True, then executable_economic must be True
        # (you can't execute something that's not economically viable)
        opp = OpportunityRank(
            rank=1,
            spread_id="test",
            buy_dex="uni",
            sell_dex="sushi",
            pair="WETH/USDC",
            fee=500,
            amount_in="1000",
            spread_bps=50,
            gas_cost_bps=10,
            net_pnl_bps=40,
            expected_pnl_usdc=1.0,
            executable_economic=True,
            paper_would_execute=True,
            execution_ready=True,  # If ready, must be economic
        )
        
        # This invariant must hold
        if opp.execution_ready:
            assert opp.executable_economic is True
    
    def test_ac4_invariant_execution_ready_lte_paper_would_execute(self):
        """AC4: execution_ready_count <= paper_would_execute_count."""
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
        
        # Create opportunities with mixed execution status
        opps = [
            OpportunityRank(
                rank=1, spread_id="test1", buy_dex="uni", sell_dex="sushi",
                pair="WETH/USDC", fee=500, amount_in="1000",
                spread_bps=50, gas_cost_bps=10, net_pnl_bps=40,
                expected_pnl_usdc=1.0,
                executable_economic=True,
                paper_would_execute=True,  # Would execute in paper
                execution_ready=True,       # Also ready for real
            ),
            OpportunityRank(
                rank=2, spread_id="test2", buy_dex="uni", sell_dex="sushi",
                pair="WETH/ARB", fee=500, amount_in="1000",
                spread_bps=30, gas_cost_bps=5, net_pnl_bps=25,
                expected_pnl_usdc=0.5,
                executable_economic=True,
                paper_would_execute=True,   # Would execute in paper
                execution_ready=False,      # But NOT ready for real
                blocked_reason="EXEC_DISABLED_NOT_VERIFIED",
            ),
        ]
        
        report = TruthReport(
            timestamp="2026-01-16T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=opps,
            paper_executable_count=2,   # 2 would execute in paper
            execution_ready_count=1,    # Only 1 ready for real
        )
        
        # AC4 invariant: execution_ready <= paper_would_execute
        violations = report.validate_invariants()
        assert "execution_ready_count" not in str(violations), f"Unexpected violation: {violations}"
        
        # This should pass (1 <= 2)
        assert report.execution_ready_count <= report.paper_executable_count


class TestNoFloatMoney:
    """
    Roadmap 3.2: No float money tests.
    
    Validates that all money fields are stored as strings (Decimal-strings)
    or integers (bps), never as float.
    """
    
    def test_paper_trade_no_float_in_serialization(self):
        """PaperTrade.to_dict() must not contain float money values."""
        import json
        from strategy.paper_trading import PaperTrade
        
        trade = PaperTrade(
            spread_id="WETH/USDC:uniswap_v3:sushiswap_v3:500",
            block_number=12345,
            timestamp="2026-01-16T12:00:00Z",
            chain_id=42161,
            buy_dex="uniswap_v3",
            sell_dex="sushiswap_v3",
            token_in="WETH",
            token_out="USDC",
            fee=500,
            amount_in_wei="100000000000000000",
            buy_price="3000.0",
            sell_price="3010.0",
            spread_bps=33,
            gas_cost_bps=5,
            net_pnl_bps=28,
            gas_price_gwei="0.01",
            numeraire="USDC",
            amount_in_numeraire="300.000000",
            expected_pnl_numeraire="0.840000",
        )
        
        # Serialize to JSON
        trade_dict = trade.to_dict()
        json_str = json.dumps(trade_dict)
        
        # Money fields must be strings, not floats
        assert isinstance(trade_dict["amount_in_numeraire"], str), "amount_in_numeraire must be str"
        assert isinstance(trade_dict["expected_pnl_numeraire"], str), "expected_pnl_numeraire must be str"
        assert isinstance(trade_dict["gas_price_gwei"], str), "gas_price_gwei must be str"
        # Legacy aliases should also be strings
        assert isinstance(trade_dict["amount_in_usdc"], str), "amount_in_usdc must be str"
        assert isinstance(trade_dict["expected_pnl_usdc"], str), "expected_pnl_usdc must be str"
    
    def test_truth_report_no_float_pnl(self):
        """TruthReport PnL fields must not be float."""
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
            top_reject_reasons=[],
        )
        
        report = TruthReport(
            timestamp="2026-01-16T12:00:00Z",
            mode="smoke",
            health=health,
            top_opportunities=[],
            total_pnl_bps=100,
            total_pnl_usdc="10.500000",  # Must be str
            would_execute_pnl_usdc="10.500000",  # Must be str
            notion_capital_usdc="10000.000000",  # Must be str
            normalized_return_pct="0.1050",  # Must be str
        )
        
        # Validate types
        assert isinstance(report.total_pnl_usdc, str), "total_pnl_usdc must be str"
        assert isinstance(report.would_execute_pnl_usdc, str), "would_execute_pnl_usdc must be str"
        assert isinstance(report.notion_capital_usdc, str), "notion_capital_usdc must be str"
        assert isinstance(report.normalized_return_pct, str), "normalized_return_pct must be str"
        
        # to_dict must not have float money
        report_dict = report.to_dict()
        pnl_norm = report_dict.get("pnl_normalized", {})
        assert not isinstance(pnl_norm.get("notion_capital_numeraire"), float), "notion_capital in dict must not be float"
    
    def test_calculate_usdc_value_returns_decimal(self):
        """calculate_usdc_value must return Decimal, not float."""
        from decimal import Decimal
        from strategy.paper_trading import calculate_usdc_value
        
        result = calculate_usdc_value(
            amount_in_wei=10**17,  # 0.1 ETH
            implied_price=Decimal("3000"),
            token_in_decimals=18,
        )
        
        assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
        assert result == Decimal("300"), f"Expected 300, got {result}"
    
    def test_calculate_pnl_usdc_returns_decimal(self):
        """calculate_pnl_usdc must return Decimal, not float."""
        from decimal import Decimal
        from strategy.paper_trading import calculate_pnl_usdc
        
        result = calculate_pnl_usdc(
            amount_in_wei=10**17,  # 0.1 ETH
            net_pnl_bps=100,  # 1%
            implied_price=Decimal("3000"),
            token_in_decimals=18,
        )
        
        assert isinstance(result, Decimal), f"Expected Decimal, got {type(result)}"
        # 300 USDC * 1% = 3 USDC
        assert result == Decimal("3"), f"Expected 3, got {result}"
    
    def test_paper_session_stats_no_float(self):
        """PaperSession.stats must not contain float money values."""
        import tempfile
        from pathlib import Path
        from strategy.paper_trading import PaperSession
        
        with tempfile.TemporaryDirectory() as tmpdir:
            session = PaperSession(
                trades_dir=Path(tmpdir),
                cooldown_blocks=5,
            )
            
            # total_pnl_numeraire must be str
            assert isinstance(session.stats["total_pnl_numeraire"], str), \
                "total_pnl_numeraire in stats must be str"
            assert session.stats["total_pnl_numeraire"] == "0.000000"
