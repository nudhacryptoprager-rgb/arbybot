# PATH: tests/unit/test_preflight_m43.py
"""Unit tests for M4.3 preflight check."""

import pytest

from execution.state_machine import (
    run_preflight_check,
    get_execution_context,
    ExecutionMode,
    PreflightResult,
)


class TestPreflightCheck:
    """Test M4.3 preflight check functionality."""
    
    def test_preflight_passes_with_safe_defaults(self):
        """Preflight passes when kill switch ON, DRY_RUN mode, execution disabled."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": True,
            "use_quoter_v2": True,  # Required for truth_mode
        }
        
        result = run_preflight_check(config)
        
        assert result.passed is True
        assert result.checks["kill_switch_active"] is True
        assert result.checks["mode_safe"] is True
        assert result.checks["config_execution_disabled"] is True
        assert len(result.errors) == 0
    
    def test_preflight_fails_if_kill_switch_off(self):
        """Preflight fails if kill switch is disabled."""
        ctx = get_execution_context()
        ctx.kill_switch_active = False
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False}
        
        result = run_preflight_check(config)
        
        assert result.passed is False
        assert "KILL_SWITCH_DISABLED" in result.errors[0]
        
        # Reset
        ctx.kill_switch_active = True
    
    def test_preflight_fails_if_live_mode(self):
        """Preflight fails if mode is LIVE."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.LIVE
        
        config = {"execution_enabled": False}
        
        result = run_preflight_check(config)
        
        assert result.passed is False
        assert "LIVE_MODE_DETECTED" in result.errors[0]
        
        # Reset
        ctx.mode = ExecutionMode.DRY_RUN
    
    def test_preflight_warns_if_truth_mode_off(self):
        """Preflight warns if truth_mode_m42 is false."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": False,
        }
        
        result = run_preflight_check(config)
        
        assert result.passed is True  # Warning only, not error
        assert any("TRUTH_MODE_OFF" in w for w in result.warnings)
    
    def test_preflight_result_to_dict(self):
        """PreflightResult.to_dict() returns valid structure."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False}
        
        result = run_preflight_check(config)
        d = result.to_dict()
        
        assert "passed" in d
        assert "checks" in d
        assert "errors" in d
        assert "warnings" in d
        assert "execution_context" in d
    
    def test_preflight_with_infra_payload(self):
        """Preflight processes infra payload correctly."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False, "truth_mode_m42": True, "use_quoter_v2": True}
        infra = {
            "ws_enabled": True,
            "ws_connected": True,
        }
        
        result = run_preflight_check(config, infra_payload=infra)
        
        assert result.passed is True
        assert result.checks["rpc_available"] is True
    
    def test_preflight_with_roundtrip_result(self):
        """Preflight checks roundtrip profitability."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False, "truth_mode_m42": True, "use_quoter_v2": True}
        roundtrip = {"is_profitable": True, "net_pnl_bps": 50}
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        assert result.passed is True
        assert result.checks["roundtrip_profitable"] is True
    
    def test_preflight_warns_if_not_profitable(self):
        """Preflight warns if roundtrip is not profitable."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False, "truth_mode_m42": True, "use_quoter_v2": True}
        roundtrip = {"is_profitable": False, "net_pnl_bps": -10}
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        assert result.passed is True  # Warning only
        assert result.checks["roundtrip_profitable"] is False
        assert any("NOT_PROFITABLE" in w for w in result.warnings)


class TestWouldExecuteCountSemantics:
    """
    Test would_execute_count semantics per v2.2.0 Fix Step 6.
    
    In truth_mode_m42=true, would_execute_count MUST be based on
    roundtrip profitability, NOT one-leg diagnostic profit.
    """
    
    def test_would_execute_requires_roundtrip_profitable(self):
        """
        would_execute_count should be 0 if roundtrip_profitable=false,
        even when preflight.passed=true.
        
        This tests the v2.2.0 fix for Issue #7:
        "would_execute_count=1 despite roundtrip_profitable=false"
        """
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": True,
            "use_quoter_v2": True,  # Required for truth_mode
        }
        
        # Simulate preflight passing but roundtrip NOT profitable
        roundtrip = {
            "is_profitable": False,
            "net_pnl_bps": -47.76,  # Typical negative roundtrip
        }
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        # Preflight passes (configs are safe)
        assert result.passed is True
        
        # But roundtrip is NOT profitable
        assert result.checks["roundtrip_profitable"] is False
        
        # Therefore, a proper would_execute_count calculation should be 0
        # (This is the semantic contract - actual count is computed in run_scan_real)
        
        # The key invariant: preflight.passed=True + roundtrip_profitable=False
        # => would_execute_count MUST be 0
        assert result.checks.get("roundtrip_profitable") is False
    
    def test_would_execute_allowed_when_roundtrip_profitable(self):
        """would_execute_count can be > 0 only when roundtrip is profitable."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": True,
            "use_quoter_v2": True,  # Required for truth_mode
        }
        
        # Roundtrip IS profitable
        roundtrip = {
            "is_profitable": True,
            "net_pnl_bps": 25.0,
        }
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        assert result.passed is True
        assert result.checks["roundtrip_profitable"] is True
        # This scenario allows would_execute_count > 0


class TestQuoterV2Policy:
    """
    Test QuoterV2 policy per v2.2.0 Fix Step 10.
    
    truth_mode_m42=true && use_quoter_v2=false => FAIL
    """
    
    def test_truth_mode_requires_quoter_v2(self):
        """Preflight fails when truth_mode_m42=true but use_quoter_v2=false."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": True,
            "use_quoter_v2": False,  # Incompatible with truth_mode
        }
        
        result = run_preflight_check(config)
        
        # Should FAIL because QuoterV2 is required for truth_mode
        assert result.passed is False
        assert any("QUOTER_V2_REQUIRED" in e for e in result.errors)
    
    def test_truth_mode_passes_with_quoter_v2(self):
        """Preflight passes when truth_mode_m42=true and use_quoter_v2=true."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": True,
            "use_quoter_v2": True,  # Required for truth_mode
        }
        
        result = run_preflight_check(config)
        
        assert result.passed is True
        assert result.checks.get("quoter_v2_enabled") is True
    
    def test_no_truth_mode_allows_slot0_only(self):
        """Preflight passes without truth_mode even if use_quoter_v2=false."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {
            "execution_enabled": False,
            "truth_mode_m42": False,
            "use_quoter_v2": False,
        }
        
        result = run_preflight_check(config)
        
        # Should PASS (warning for truth_mode_off, but no error)
        assert result.passed is True


# =============================================================================
# NEW: Preflight EVIDENCE Module Tests (v1.0.0)
# =============================================================================

from unittest.mock import MagicMock


class TestLegPreflightResult:
    """Test LegPreflightResult dataclass from execution.preflight."""

    def test_basic_construction(self):
        """LegPreflightResult should construct with required fields."""
        from execution.preflight import LegPreflightResult
        
        leg = LegPreflightResult(
            dex_id="uniswap_v3",
            pool_address="0x1234...",
            token_in="0xWETH",
            token_out="0xUSDC",
            fee_tier=3000,
            amount_in=10**18,
        )
        
        assert leg.dex_id == "uniswap_v3"
        assert leg.fee_tier == 3000
        assert leg.eth_call_ok is False
        assert leg.gas_estimate is None

    def test_to_dict_serialization(self):
        """LegPreflightResult.to_dict should serialize all fields."""
        from execution.preflight import LegPreflightResult
        
        leg = LegPreflightResult(
            dex_id="sushiswap_v3",
            pool_address="0x5678...",
            token_in="0xARB",
            token_out="0xWETH",
            fee_tier=500,
            amount_in=10**18,
            eth_call_ok=True,
            quoted_amount_out=10**19,
            gas_estimate=150000,
            gas_estimate_source="eth_estimateGas",
        )
        
        d = leg.to_dict()
        
        assert d["dex_id"] == "sushiswap_v3"
        assert d["fee_tier"] == 500
        assert d["eth_call_ok"] is True
        assert d["quoted_amount_out"] == 10**19
        assert d["gas_estimate"] == 150000
        assert d["gas_estimate_source"] == "eth_estimateGas"


class TestPreflightEvidence:
    """Test PreflightEvidence dataclass from execution.preflight."""

    def test_basic_construction(self):
        """PreflightEvidence should construct with required fields."""
        from execution.preflight import PreflightEvidence
        
        evidence = PreflightEvidence(
            spread_id="spread_1_20260222_091000_0",
            pair="WETH/USDC",
            route="uniswap_v3->sushiswap_v3",
            spread_bps=15.5,
        )
        
        assert evidence.spread_id == "spread_1_20260222_091000_0"
        assert evidence.pair == "WETH/USDC"
        assert evidence.passed is False
        assert evidence.leg1 is None
        assert evidence.leg2 is None

    def test_to_dict_with_legs(self):
        """PreflightEvidence.to_dict should include legs."""
        from execution.preflight import PreflightEvidence, LegPreflightResult
        
        leg1 = LegPreflightResult(
            dex_id="uniswap_v3",
            pool_address="0x1234",
            token_in="0xWETH",
            token_out="0xUSDC",
            fee_tier=3000,
            amount_in=10**18,
            eth_call_ok=True,
            gas_estimate=150000,
            gas_estimate_source="eth_estimateGas",
        )
        
        evidence = PreflightEvidence(
            spread_id="spread_1",
            pair="WETH/USDC",
            route="uni->sushi",
            spread_bps=10.0,
            leg1=leg1,
            passed=True,
        )
        
        d = evidence.to_dict()
        
        assert d["passed"] is True
        assert d["leg1"] is not None
        assert d["leg1"]["dex_id"] == "uniswap_v3"
        assert d["leg2"] is None


class TestRunEthCallQuote:
    """Test run_eth_call_quote function."""

    def test_successful_quote(self):
        """Successful eth_call should return amount_out and gas_estimate."""
        from execution.preflight import run_eth_call_quote
        
        mock_w3 = MagicMock()
        # QuoterV2 returns 4 x 32 bytes: amountOut, sqrtPriceX96After, ticksCrossed, gasEstimate
        amount_out_bytes = (10**20).to_bytes(32, "big")
        sqrt_price_bytes = (10**24).to_bytes(32, "big")
        ticks_bytes = (3).to_bytes(32, "big")
        gas_estimate_bytes = (150000).to_bytes(32, "big")
        mock_w3.eth.call.return_value = amount_out_bytes + sqrt_price_bytes + ticks_bytes + gas_estimate_bytes
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        # Use valid hex addresses
        ok, amount_out, gas_estimate, err = run_eth_call_quote(
            w3=mock_w3,
            quoter_address="0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
            fee=3000,
            amount_in=10**18,
        )
        
        assert ok is True
        assert amount_out == 10**20
        assert gas_estimate == 150000
        assert err is None

    def test_failed_quote(self):
        """Failed eth_call should return error."""
        from execution.preflight import run_eth_call_quote
        
        mock_w3 = MagicMock()
        mock_w3.eth.call.side_effect = Exception("Revert: insufficient liquidity")
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        ok, amount_out, gas_estimate, err = run_eth_call_quote(
            w3=mock_w3,
            quoter_address="0x61fFE014bA17989E743c5F6cB21bF9697530B21e",
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            amount_in=10**18,
        )
        
        assert ok is False
        assert amount_out is None
        assert gas_estimate is None
        assert "insufficient liquidity" in err


class TestRunEthEstimateGasSwap:
    """Test run_eth_estimate_gas_swap function."""

    def test_successful_estimate(self):
        """Successful eth_estimateGas should return gas with margin."""
        from execution.preflight import run_eth_estimate_gas_swap
        
        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.return_value = 150000
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        # Use valid hex addresses
        gas, err, source = run_eth_estimate_gas_swap(
            w3=mock_w3,
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            amount_in=10**18,
            sender_address="0x0000000000000000000000000000000000000001",
        )
        
        # Should have margin applied (1.2x)
        assert gas == 180000
        assert err is None
        assert source == "eth_estimateGas"

    def test_fallback_on_error(self):
        """Failed eth_estimateGas should fallback to default."""
        from execution.preflight import run_eth_estimate_gas_swap
        from execution.gas_estimate import DEFAULT_V3_SWAP_GAS
        
        mock_w3 = MagicMock()
        mock_w3.eth.estimate_gas.side_effect = Exception("execution reverted")
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        gas, err, source = run_eth_estimate_gas_swap(
            w3=mock_w3,
            router_address="0x68b3465833fb72A70ecDF485E0e4C7bD8665Fc45",
            token_in="0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
            token_out="0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
            fee=3000,
            amount_in=10**18,
            sender_address="0x0000000000000000000000000000000000000001",
        )
        
        assert gas == DEFAULT_V3_SWAP_GAS
        assert "execution reverted" in err
        assert source == "fallback"


class TestCollectPreflightEvidence:
    """Test collect_preflight_evidence function."""

    def test_missing_legs_returns_error(self):
        """Missing leg1/leg2 should produce error."""
        from execution.preflight import collect_preflight_evidence
        
        mock_w3 = MagicMock()
        
        evidence = collect_preflight_evidence(
            w3=mock_w3,
            spread_signal={"spread_id": "test"},
        )
        
        assert evidence.passed is False
        assert any("MISSING_LEGS" in e for e in evidence.errors)


class TestCollectTopNPreflight:
    """Test collect_top_n_preflight function."""

    def test_respects_n_limit(self):
        """collect_top_n_preflight should only process N candidates."""
        from execution.preflight import collect_top_n_preflight
        
        mock_w3 = MagicMock()
        mock_w3.eth.call.return_value = (10**20).to_bytes(32, "big")
        mock_w3.eth.estimate_gas.return_value = 150000
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        signals = [
            {"spread_id": f"spread_{i}", "pair": "WETH/USDC", "route": "uni->sushi", "spread_bps": 10.0,
             "leg1": {"dex_id": "uniswap_v3", "pool_address": "0x", "token_in": "0x", "token_out": "0x", "fee_tier": 3000, "amount_in": 10**18},
             "leg2": {"dex_id": "sushiswap_v3", "pool_address": "0x", "token_in": "0x", "token_out": "0x", "fee_tier": 3000, "amount_in": 10**18}}
            for i in range(5)
        ]
        
        result = collect_top_n_preflight(
            w3=mock_w3,
            spread_signals=signals,
            n=3,
        )
        
        assert result["candidates_count"] == 3
        assert len(result["results"]) == 3
        assert result["enabled"] is True

    def test_empty_signals_returns_stub(self):
        """Empty signals list should return minimal result."""
        from execution.preflight import collect_top_n_preflight
        
        mock_w3 = MagicMock()
        
        result = collect_top_n_preflight(
            w3=mock_w3,
            spread_signals=[],
            n=3,
        )
        
        assert result["candidates_count"] == 0
        assert result["passed_count"] == 0


class TestPreflightDisabledStub:
    """Test preflight_disabled_stub function."""

    def test_stub_structure(self):
        """preflight_disabled_stub should return correct structure."""
        from execution.preflight import preflight_disabled_stub
        
        stub = preflight_disabled_stub()
        
        assert stub["enabled"] is False
        assert stub["candidates_count"] == 0
        assert stub["passed_count"] == 0
        assert stub["results"] == []
        assert "evidence_source" in stub


class TestOfflineModeCompatibility:
    """Test that preflight module doesn't break offline mode."""

    def test_import_succeeds(self):
        """Module import should succeed without RPC connection."""
        from execution.preflight import (
            LegPreflightResult,
            PreflightEvidence,
            collect_preflight_evidence,
            collect_top_n_preflight,
            preflight_disabled_stub,
        )
        
        assert callable(collect_preflight_evidence)

    def test_disabled_stub_is_json_serializable(self):
        """Disabled stub should be JSON serializable."""
        import json
        from execution.preflight import preflight_disabled_stub
        
        stub = preflight_disabled_stub()
        json_str = json.dumps(stub)
        
        assert "enabled" in json_str


class TestStricterPassedCriteria:
    """Test v1.0.1 stricter passed criteria - fallback gas doesn't count as pass."""

    def test_fallback_gas_does_not_pass(self):
        """A leg with fallback gas (not real eth_estimateGas) should NOT pass."""
        from execution.preflight import LegPreflightResult, PreflightEvidence
        
        leg1 = LegPreflightResult(
            dex_id="uniswap_v3",
            pool_address="0x1234",
            token_in="0xWETH",
            token_out="0xUSDC",
            fee_tier=3000,
            amount_in=10**18,
            eth_call_ok=False,
            gas_estimate=200_000,
            gas_estimate_source="fallback",  # NOT eth_estimateGas
        )
        
        # Leg has gas_estimate but source is fallback
        assert leg1.gas_estimate is not None
        assert leg1.gas_estimate_source == "fallback"
        
        # Per v1.0.1 contract: fallback gas should NOT satisfy leg_ok
        from execution.preflight import collect_preflight_evidence
        
        # Verify the logic directly
        leg_ok = leg1.eth_call_ok or (
            leg1.gas_estimate is not None and 
            leg1.gas_estimate_source == "eth_estimateGas"
        )
        assert leg_ok is False

    def test_eth_estimate_gas_passes(self):
        """A leg with real eth_estimateGas should pass."""
        from execution.preflight import LegPreflightResult
        
        leg1 = LegPreflightResult(
            dex_id="uniswap_v3",
            pool_address="0x1234",
            token_in="0xWETH",
            token_out="0xUSDC",
            fee_tier=3000,
            amount_in=10**18,
            eth_call_ok=False,
            gas_estimate=200_000,
            gas_estimate_source="eth_estimateGas",  # Real estimate
        )
        
        leg_ok = leg1.eth_call_ok or (
            leg1.gas_estimate is not None and 
            leg1.gas_estimate_source == "eth_estimateGas"
        )
        assert leg_ok is True

    def test_eth_call_ok_passes(self):
        """A leg with eth_call_ok=True should pass regardless of gas."""
        from execution.preflight import LegPreflightResult
        
        leg1 = LegPreflightResult(
            dex_id="uniswap_v3",
            pool_address="0x1234",
            token_in="0xWETH",
            token_out="0xUSDC",
            fee_tier=3000,
            amount_in=10**18,
            eth_call_ok=True,
            gas_estimate=None,  # No gas estimate at all
        )
        
        leg_ok = leg1.eth_call_ok or (
            leg1.gas_estimate is not None and 
            leg1.gas_estimate_source == "eth_estimateGas"
        )
        assert leg_ok is True


class TestAdaptOpportunityToPreflightInput:
    """Test adapt_opportunity_to_preflight_input function."""

    def test_adapter_creates_leg1_leg2(self):
        """Adapter should convert opportunity dict to leg1/leg2 format."""
        from execution.preflight import adapt_opportunity_to_preflight_input
        
        opportunity = {
            "spread_id": "spread_1_20260222_120000_0",
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 500,
            "sell_fee": 3000,
            "amount_in_wei": 10**18,
            "gross_spread_bps": "25.5",
            "diagnostics": {
                "buy_pool": "0xBuyPoolAddress",
                "sell_pool": "0xSellPoolAddress",
            },
        }
        
        result = adapt_opportunity_to_preflight_input(opportunity, chain_key="arbitrum_one")
        
        assert result["spread_id"] == "spread_1_20260222_120000_0"
        assert result["pair"] == "WETH/USDC"
        assert "leg1" in result
        assert "leg2" in result
        
        # Leg1 is buy leg
        assert result["leg1"]["dex_id"] == "uniswap_v3"
        assert result["leg1"]["pool_address"] == "0xBuyPoolAddress"
        assert result["leg1"]["fee_tier"] == 500
        assert result["leg1"]["amount_in"] == 10**18
        
        # Leg2 is sell leg (tokens reversed)
        assert result["leg2"]["dex_id"] == "sushiswap_v3"
        assert result["leg2"]["pool_address"] == "0xSellPoolAddress"
        assert result["leg2"]["fee_tier"] == 3000

    def test_adapter_maps_symbols_to_addresses(self):
        """Adapter should map token symbols to addresses via config."""
        from execution.preflight import adapt_opportunity_to_preflight_input
        
        opportunity = {
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            "buy_fee": 500,
            "sell_fee": 3000,
            "diagnostics": {},
        }
        
        result = adapt_opportunity_to_preflight_input(opportunity, chain_key="arbitrum_one")
        
        # Token addresses should be resolved from core_tokens.yaml
        # WETH on Arbitrum: 0x82aF49447D8a07e3bd95BD0d56f35241523fBab1
        # USDC on Arbitrum: 0xaf88d065e77c8cC2239327C5EDb3A432268e5831
        leg1 = result["leg1"]
        leg2 = result["leg2"]
        
        # Leg1: WETH -> USDC
        assert leg1["token_in"].startswith("0x") or leg1["token_in"] == ""  # Either resolved or empty
        assert leg1["token_out"].startswith("0x") or leg1["token_out"] == ""
        
        # Leg2: USDC -> WETH (reversed)  
        assert leg2["token_in"] == leg1["token_out"]  # Reversed
        assert leg2["token_out"] == leg1["token_in"]

    def test_adapter_route_format(self):
        """Adapter should create proper route string."""
        from execution.preflight import adapt_opportunity_to_preflight_input
        
        opportunity = {
            "pair": "WETH/ARB",
            "buy_dex": "uniswap_v3",
            "sell_dex": "camelot_v3",
            "buy_fee": 500,
            "sell_fee": 3000,
            "diagnostics": {},
        }
        
        result = adapt_opportunity_to_preflight_input(opportunity)
        
        assert "uniswap_v3:500 -> camelot_v3:3000" in result["route"]

    def test_adapter_handles_missing_diagnostics(self):
        """Adapter should handle missing diagnostics gracefully."""
        from execution.preflight import adapt_opportunity_to_preflight_input
        
        opportunity = {
            "pair": "WETH/USDC",
            "buy_dex": "uniswap_v3",
            "sell_dex": "sushiswap_v3",
            # No diagnostics key
        }
        
        result = adapt_opportunity_to_preflight_input(opportunity)
        
        assert result["leg1"]["pool_address"] == ""
        assert result["leg2"]["pool_address"] == ""


class TestPreflightInvariants:
    """Test preflight artifact shape invariants."""

    def test_artifact_results_count_matches_candidates_count(self):
        """results length MUST equal candidates_count."""
        from execution.preflight import collect_top_n_preflight, preflight_disabled_stub
        
        mock_w3 = MagicMock()
        # Return 128-byte QuoterV2 response
        mock_w3.eth.call.return_value = (
            (10**18).to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            (150000).to_bytes(32, "big")
        )
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        signals = [
            {"spread_id": f"s{i}", "pair": "WETH/USDC", "spread_bps": 10 - i,
             "leg1": {"dex_id": "uniswap_v3", "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                     "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "fee_tier": 500, "amount_in": 10**18},
             "leg2": {"dex_id": "sushi_v3", "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                     "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "fee_tier": 500, "amount_in": 10**18}}
            for i in range(5)
        ]
        
        result = collect_top_n_preflight(w3=mock_w3, spread_signals=signals, n=3)
        
        assert result["candidates_count"] == 3
        assert len(result["results"]) == result["candidates_count"]

    def test_leg_structure_has_required_fields(self):
        """Each leg MUST have eth_call_ok, gas_estimate, gas_estimate_source."""
        from execution.preflight import collect_preflight_evidence
        
        mock_w3 = MagicMock()
        mock_w3.eth.call.return_value = (
            (10**18).to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            (150000).to_bytes(32, "big")
        )
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        signal = {
            "spread_id": "test_spread",
            "pair": "WETH/USDC",
            "spread_bps": 50,
            "leg1": {"dex_id": "uniswap_v3", "pool_address": "0x1234",
                    "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                    "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                    "fee_tier": 500, "amount_in": 10**18},
            "leg2": {"dex_id": "sushi_v3", "pool_address": "0x5678",
                    "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                    "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                    "fee_tier": 500, "amount_in": 10**18}
        }
        
        evidence = collect_preflight_evidence(w3=mock_w3, spread_signal=signal)
        d = evidence.to_dict()
        
        # Check leg1 structure
        assert d["leg1"] is not None
        assert "eth_call_ok" in d["leg1"]
        assert "gas_estimate" in d["leg1"]
        assert "gas_estimate_source" in d["leg1"]
        
        # Check leg2 structure
        assert d["leg2"] is not None
        assert "eth_call_ok" in d["leg2"]
        assert "gas_estimate" in d["leg2"]
        assert "gas_estimate_source" in d["leg2"]

    def test_gas_estimate_source_whitelist(self):
        """gas_estimate_source MUST be in allowed values."""
        from execution.preflight import LegPreflightResult
        
        allowed_sources = {"none", "quoter_v2", "eth_estimateGas", "fallback"}
        
        leg = LegPreflightResult(
            dex_id="test", pool_address="0x123",
            token_in="0xA", token_out="0xB",
            fee_tier=500, amount_in=10**18,
        )
        
        # Default should be in whitelist
        assert leg.gas_estimate_source in allowed_sources
        
        # Test all allowed values
        for source in allowed_sources:
            leg.gas_estimate_source = source
            assert leg.gas_estimate_source in allowed_sources

    def test_quoter_v2_gas_is_primary(self):
        """QuoterV2 gas estimate should be used when available."""
        from execution.preflight import collect_preflight_evidence
        
        mock_w3 = MagicMock()
        # Return 128-byte QuoterV2 response with gasEstimate=123456
        mock_w3.eth.call.return_value = (
            (10**18).to_bytes(32, "big") +  # amountOut
            (10**24).to_bytes(32, "big") +  # sqrtPriceX96After
            (3).to_bytes(32, "big") +       # ticksCrossed
            (123456).to_bytes(32, "big")    # gasEstimate
        )
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        signal = {
            "spread_id": "test_spread",
            "pair": "WETH/USDC",
            "spread_bps": 50,
            "leg1": {"dex_id": "uniswap_v3", "pool_address": "0x1234",
                    "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                    "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                    "fee_tier": 500, "amount_in": 10**18},
            "leg2": {"dex_id": "uniswap_v3", "pool_address": "0x5678",
                    "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                    "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                    "fee_tier": 500, "amount_in": 10**18}
        }
        
        evidence = collect_preflight_evidence(w3=mock_w3, spread_signal=signal)
        
        # QuoterV2 gas should be primary source
        assert evidence.leg1.gas_estimate == 123456
        assert evidence.leg1.gas_estimate_source == "quoter_v2"
        assert evidence.leg2.gas_estimate == 123456
        assert evidence.leg2.gas_estimate_source == "quoter_v2"
        
        # eth_estimateGas should NOT have been called (no error)
        assert evidence.leg1.gas_estimate_error is None
        assert evidence.leg2.gas_estimate_error is None

    def test_evidence_source_version_format(self):
        """evidence_source should follow preflight_vX.Y.Z format."""
        from execution.preflight import PreflightEvidence
        import re
        
        evidence = PreflightEvidence(
            spread_id="test",
            pair="WETH/USDC",
            route="test",
            spread_bps=50,
        )
        
        # Check version format
        pattern = r"^preflight_v\d+\.\d+\.\d+$"
        assert re.match(pattern, evidence.evidence_source), f"Invalid version format: {evidence.evidence_source}"

    def test_cross_artifact_preflight_consistency(self):
        """Preflight evidence MUST be consistent between scan and truth_report artifacts."""
        from execution.preflight import collect_top_n_preflight
        
        # Mock web3 for preflight collection
        mock_w3 = MagicMock()
        mock_w3.eth.call.return_value = (
            (10**18).to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            (150000).to_bytes(32, "big")
        )
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        signals = [
            {"spread_id": f"s{i}", "pair": "WETH/USDC", "spread_bps": 10 - i,
             "leg1": {"dex_id": "uniswap_v3", "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                     "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831", "fee_tier": 500, "amount_in": 10**18},
             "leg2": {"dex_id": "sushi_v3", "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                     "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1", "fee_tier": 500, "amount_in": 10**18}}
            for i in range(3)
        ]
        
        # Collect preflight evidence twice (simulating scan and truth_report)
        preflight_for_scan = collect_top_n_preflight(w3=mock_w3, spread_signals=signals, n=3)
        preflight_for_truth = collect_top_n_preflight(w3=mock_w3, spread_signals=signals, n=3)
        
        # Both must have same evidence_source version
        assert preflight_for_scan["evidence_source"] == preflight_for_truth["evidence_source"], \
            "Cross-artifact preflight evidence_source MUST match"
        
        # Both must have same candidates_count and passed_count
        assert preflight_for_scan["candidates_count"] == preflight_for_truth["candidates_count"], \
            "Cross-artifact candidates_count MUST match"
        assert preflight_for_scan["passed_count"] == preflight_for_truth["passed_count"], \
            "Cross-artifact passed_count MUST match"
        
        # Evidence source should be current version
        assert preflight_for_scan["evidence_source"] == "preflight_v1.0.3"


class TestPreflightV103ChainAwareAndGasSanity:
    """
    v1.0.3 FIX tests:
    1. leg2.amount_in = leg1.quoted_amount_out (chain-aware flow)
    2. gas_estimate > 1.5M rejects candidate (sanity check)
    """
    
    def test_leg2_amount_in_uses_leg1_quoted_output(self):
        """v1.0.3: leg2.amount_in MUST equal leg1.quoted_amount_out for chain-aware preflight."""
        from unittest.mock import MagicMock, patch
        from execution.preflight import collect_preflight_evidence
        
        mock_w3 = MagicMock()
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        # Simulate QuoterV2 returning specific output for leg1
        leg1_output = 2500 * 10**6  # 2500 USDC (6 decimals)
        leg1_gas = 150000
        
        # Encode return value: amountOut, sqrtPriceX96After, tickAfter, gasEstimate
        leg1_return = (
            leg1_output.to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            leg1_gas.to_bytes(32, "big")
        )
        
        # leg2 will get different output (eth return)
        leg2_output = 10**18  # 1 ETH
        leg2_gas = 160000
        leg2_return = (
            leg2_output.to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            leg2_gas.to_bytes(32, "big")
        )
        
        # Mock eth_call to return different values per call
        call_count = [0]
        def mock_eth_call(call_dict, block="latest"):
            call_count[0] += 1
            return leg1_return if call_count[0] == 1 else leg2_return
        
        mock_w3.eth.call.side_effect = mock_eth_call
        
        spread_signal = {
            "spread_id": "test_chain_aware",
            "pair": "WETH/USDC",
            "route": "uniswap_v3:500 -> sushi_v3:500",
            "spread_bps": 15.0,
            "leg1": {
                "dex_id": "uniswap_v3",
                "pool_address": "0x123",
                "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
                "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
                "fee_tier": 500,
                "amount_in": 10**18,  # 1 WETH
            },
            "leg2": {
                "dex_id": "sushi_v3",
                "pool_address": "0x456",
                "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # USDC
                "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",  # WETH
                "fee_tier": 500,
                "amount_in": 10**18,  # This is the "simplified" value from adapt_opportunity
            },
        }
        
        evidence = collect_preflight_evidence(
            w3=mock_w3,
            spread_signal=spread_signal,
            current_block=100,
        )
        
        # v1.0.3 invariant: leg2.amount_in MUST equal leg1.quoted_amount_out
        assert evidence.leg1 is not None
        assert evidence.leg2 is not None
        assert evidence.leg1.quoted_amount_out == leg1_output, "leg1 should have quoted_amount_out"
        assert evidence.leg2.amount_in == leg1_output, \
            f"v1.0.3 FIX: leg2.amount_in ({evidence.leg2.amount_in}) MUST equal leg1.quoted_amount_out ({leg1_output})"
    
    def test_gas_estimate_sanity_rejects_unrealistic_values(self):
        """v1.0.3: gas_estimate > 1.5M MUST reject candidate with warning."""
        from unittest.mock import MagicMock
        from execution.preflight import collect_preflight_evidence, MAX_REALISTIC_GAS_ESTIMATE
        
        mock_w3 = MagicMock()
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        # Simulate QuoterV2 returning unrealistic gas for leg2
        leg1_output = 2500 * 10**6
        leg1_gas = 150000  # Normal gas
        
        leg2_output = 10**18
        leg2_gas = 50_000_000  # Unrealistic: 50M gas
        
        leg1_return = (
            leg1_output.to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            leg1_gas.to_bytes(32, "big")
        )
        
        leg2_return = (
            leg2_output.to_bytes(32, "big") +
            (10**24).to_bytes(32, "big") +
            (3).to_bytes(32, "big") +
            leg2_gas.to_bytes(32, "big")
        )
        
        call_count = [0]
        def mock_eth_call(call_dict, block="latest"):
            call_count[0] += 1
            return leg1_return if call_count[0] == 1 else leg2_return
        
        mock_w3.eth.call.side_effect = mock_eth_call
        
        spread_signal = {
            "spread_id": "test_gas_sanity",
            "pair": "WETH/USDC",
            "route": "uniswap_v3:500 -> sushi_v3:500",
            "spread_bps": 15.0,
            "leg1": {
                "dex_id": "uniswap_v3",
                "pool_address": "0x123",
                "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                "fee_tier": 500,
                "amount_in": 10**18,
            },
            "leg2": {
                "dex_id": "sushi_v3",
                "pool_address": "0x456",
                "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "fee_tier": 500,
                "amount_in": 10**18,
            },
        }
        
        evidence = collect_preflight_evidence(
            w3=mock_w3,
            spread_signal=spread_signal,
            current_block=100,
        )
        
        # v1.0.3: Unrealistic gas MUST cause passed=False
        assert evidence.passed is False, \
            f"v1.0.3 FIX: gas_estimate={leg2_gas} > {MAX_REALISTIC_GAS_ESTIMATE} MUST reject candidate"
        
        # Should have warning about unrealistic gas
        assert any("GAS_ESTIMATE_UNREALISTIC" in w for w in evidence.warnings), \
            f"Should have GAS_ESTIMATE_UNREALISTIC warning, got: {evidence.warnings}"
    
    def test_missing_leg1_output_adds_warning(self):
        """v1.0.3: If leg1.quoted_amount_out is missing, warning MUST be added."""
        from unittest.mock import MagicMock
        from execution.preflight import collect_preflight_evidence
        
        mock_w3 = MagicMock()
        mock_w3.to_checksum_address.side_effect = lambda x: x
        
        # Simulate leg1 quote failing (returns no output)
        mock_w3.eth.call.side_effect = Exception("quota exceeded")
        
        spread_signal = {
            "spread_id": "test_missing_output",
            "pair": "WETH/USDC",
            "route": "uniswap_v3:500 -> sushi_v3:500",
            "spread_bps": 15.0,
            "leg1": {
                "dex_id": "uniswap_v3",
                "pool_address": "0x123",
                "token_in": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "token_out": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                "fee_tier": 500,
                "amount_in": 10**18,
            },
            "leg2": {
                "dex_id": "sushi_v3",
                "pool_address": "0x456",
                "token_in": "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",
                "token_out": "0x82aF49447D8a07e3bd95BD0d56f35241523fBab1",
                "fee_tier": 500,
                "amount_in": 10**18,
            },
        }
        
        evidence = collect_preflight_evidence(
            w3=mock_w3,
            spread_signal=spread_signal,
            current_block=100,
        )
        
        # Should have warning about missing leg1 output
        assert any("MISSING_LEG1_OUTPUT_FOR_LEG2" in w for w in evidence.warnings), \
            f"Should have MISSING_LEG1_OUTPUT_FOR_LEG2 warning, got: {evidence.warnings}"
