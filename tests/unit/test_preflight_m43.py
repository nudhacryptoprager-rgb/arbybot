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
        
        config = {"execution_enabled": False, "truth_mode_m42": True}
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
        
        config = {"execution_enabled": False, "truth_mode_m42": True}
        roundtrip = {"is_profitable": True, "net_pnl_bps": 50}
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        assert result.passed is True
        assert result.checks["roundtrip_profitable"] is True
    
    def test_preflight_warns_if_not_profitable(self):
        """Preflight warns if roundtrip is not profitable."""
        ctx = get_execution_context()
        ctx.kill_switch_active = True
        ctx.mode = ExecutionMode.DRY_RUN
        
        config = {"execution_enabled": False, "truth_mode_m42": True}
        roundtrip = {"is_profitable": False, "net_pnl_bps": -10}
        
        result = run_preflight_check(config, roundtrip_result=roundtrip)
        
        assert result.passed is True  # Warning only
        assert result.checks["roundtrip_profitable"] is False
        assert any("NOT_PROFITABLE" in w for w in result.warnings)
