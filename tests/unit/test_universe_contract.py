"""Tests for M9 capacity/runner universe contract alignment."""
from __future__ import annotations

from m9.graph_arb.universe_contract import (
    BLOCKER_CAPACITY_UNIVERSE_MISMATCH,
    build_universe_contract,
    compare_universe_contracts,
    validate_capacity_for_runner,
)


def test_compare_detects_cycle_length_mismatch():
    a = build_universe_contract(
        inventory_path="data/tmp/bridge.json",
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_a",
    )
    b = dict(a)
    b["cycle_lengths"] = [2, 3, 4]
    assert "cycle_lengths" in compare_universe_contracts(a, b)


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
    runner = build_universe_contract(
        inventory_path="data/tmp/bridge.json",
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_a",
    )
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert not ok
    assert "universe_contract_missing" in mismatches


def test_validate_passes_when_contracts_match():
    runner = build_universe_contract(
        inventory_path="data/tmp/bridge.json",
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_a",
    )
    cap = {"universe_contract": dict(runner)}
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert ok
    assert mismatches == []


def test_blocker_constant_exported():
    assert BLOCKER_CAPACITY_UNIVERSE_MISMATCH == "CAPACITY_UNIVERSE_MISMATCH"
