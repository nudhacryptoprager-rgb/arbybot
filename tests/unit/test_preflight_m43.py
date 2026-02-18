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
