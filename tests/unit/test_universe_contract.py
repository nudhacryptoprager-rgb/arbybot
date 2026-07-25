"""Tests for M9 capacity/runner universe contract alignment."""
from __future__ import annotations

from m9.graph_arb.universe_contract import (
    BLOCKER_CAPACITY_UNIVERSE_MISMATCH,
    CONTRACT_SCHEMA_VERSION,
    build_universe_contract,
    compare_universe_contracts,
    validate_capacity_for_runner,
)


def _runner_contract(**overrides):
    base = build_universe_contract(
        inventory_path="data/tmp/bridge.json",
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_a",
    )
    base.update(overrides)
    return base


def test_compare_detects_cycle_length_mismatch():
    a = _runner_contract()
    b = dict(a)
    b["cycle_lengths"] = [2, 3, 4]
    assert "cycle_lengths" in compare_universe_contracts(a, b)


def test_compare_detects_missing_runner_session():
    runner = _runner_contract(session_id=None)
    capacity = _runner_contract(session_id="sess_a")
    assert "session_id_missing_in_runner" in compare_universe_contracts(
        runner, capacity
    )


def test_compare_detects_missing_capacity_session():
    runner = _runner_contract(session_id="sess_a")
    capacity = dict(runner)
    capacity["session_id"] = None
    assert "session_id_missing_in_capacity" in compare_universe_contracts(
        runner, capacity
    )


def test_validate_requires_universe_contract_field():
    cap = {
        "inventory_path": "data/tmp/bridge.json",
        "config_path": "config/exotic_base_anchor.yaml",
        "lane": "productive",
        "require_factory_verified": True,
        "cycle_lengths": [3, 4],
        "active_economics_profile": "production_conservative",
        "session_id": "sess_a",
    }
    runner = _runner_contract()
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert not ok
    assert "universe_contract_missing" in mismatches


def test_validate_passes_when_contracts_match():
    runner = _runner_contract()
    cap = {"universe_contract": dict(runner)}
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert ok
    assert mismatches == []


def test_contract_schema_version_v2():
    contract = _runner_contract()
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSION
    assert "admission_policy" in contract


def test_blocker_constant_exported():
    assert BLOCKER_CAPACITY_UNIVERSE_MISMATCH == "CAPACITY_UNIVERSE_MISMATCH"
