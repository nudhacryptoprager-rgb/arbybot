"""Diagnostic admission mode tests."""
from __future__ import annotations

import os

from m9.graph_arb.admission_mode import (
    PRICE_STATUS_UNKNOWN_DIAGNOSTIC,
    get_diagnostic_admission_mode,
    is_topology_probe_mode,
)
from m9.graph_arb.builder import _edge_price_gate
from m9.graph_arb.pool_quality import maverick_admission_fail_reason, productive_admission_fail_reason


def test_topology_probe_mode_env(monkeypatch):
    monkeypatch.setenv("ARBY_M9_DIAGNOSTIC_ADMISSION_MODE", "topology_probe")
    assert get_diagnostic_admission_mode() == "topology_probe"
    assert is_topology_probe_mode() is True


def test_unknown_price_allowed_in_topology_probe():
    allow, status = _edge_price_gate(
        "0xdead000000000000000000000000000000000001",
        "UNKNOWN_SYM",
        {},
        topology_probe=True,
    )
    assert allow is True
    assert status == PRICE_STATUS_UNKNOWN_DIAGNOSTIC


def test_unknown_price_blocked_in_production_mode():
    allow, status = _edge_price_gate(
        "0xdead000000000000000000000000000000000001",
        "UNKNOWN_SYM",
        {},
        topology_probe=False,
    )
    assert allow is False
    assert status is None


def test_maverick_fail_reason_missing_token_a():
    reason = maverick_admission_fail_reason(
        {
            "factory_verified": True,
            "adapter_type": "maverick_v2",
            "dex_id": "maverick_v2",
            "effective_depth_usd": None,
            "quote_smoke_status": "QUOTE_REVERT",
        }
    )
    assert reason == "missing_token_a"


def test_productive_fail_reason_not_factory_verified():
    assert (
        productive_admission_fail_reason({"factory_verified": False})
        == "not_factory_verified"
    )
