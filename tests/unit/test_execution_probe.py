# PATH: tests/unit/test_execution_probe.py
"""
Contract tests for strategy/execution_probe.py.

Verifies safety gates (execution_enabled, kill_switch, simulate_only)
and the dormant-by-default behavior.
"""

from strategy.execution_probe import probe_live_execution


def test_dormant_by_default():
    """Default config must keep execution probe disabled."""
    result = probe_live_execution(config={}, provider_http="http://rpc", opps_list=[{"a": 1}])
    assert result == {"enabled": False}


def test_kill_switch_blocks():
    config = {
        "execution_enabled": True,
        "kill_switch_active": True,  # safety: blocks execution
        "simulate_only": False,
    }
    result = probe_live_execution(config=config, provider_http="http://rpc", opps_list=[{"a": 1}])
    assert result == {"enabled": False}


def test_simulate_only_blocks():
    config = {
        "execution_enabled": True,
        "kill_switch_active": False,
        "simulate_only": True,  # safety: blocks execution
    }
    result = probe_live_execution(config=config, provider_http="http://rpc", opps_list=[{"a": 1}])
    assert result == {"enabled": False}


def test_no_provider_blocks():
    config = {
        "execution_enabled": True,
        "kill_switch_active": False,
        "simulate_only": False,
    }
    result = probe_live_execution(config=config, provider_http=None, opps_list=[{"a": 1}])
    assert result == {"enabled": False}


def test_empty_opps_blocks():
    config = {
        "execution_enabled": True,
        "kill_switch_active": False,
        "simulate_only": False,
    }
    result = probe_live_execution(config=config, provider_http="http://rpc", opps_list=[])
    assert result == {"enabled": False}
