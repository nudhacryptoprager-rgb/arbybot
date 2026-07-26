"""Tests for M9 capacity/runner universe contract alignment."""
from __future__ import annotations

from m9.graph_arb.universe_contract import (
    BLOCKER_CAPACITY_UNIVERSE_MISMATCH,
    CONTRACT_SCHEMA_VERSION,
    build_universe_contract,
    compare_universe_contracts,
    validate_capacity_for_runner,
)


def _graph_fp(**overrides):
    base = {
        "resolved_inventory_path": "/data/tmp/bridge.json",
        "active_route_count": 1,
        "graph_edge_count": 2,
        "graph_route_count": 1,
        "route_universe_hash": "abc123",
        "post_depth_content_hash": "posthash",
        "execution_content_fingerprint": "execfp123",
    }
    base.update(overrides)
    return base


def _runner_contract(**overrides):
    fp = overrides.pop("graph_fingerprint", None) or _graph_fp()
    base = build_universe_contract(
        inventory_path=overrides.pop("inventory_path", "data/tmp/bridge.json"),
        config_path=overrides.pop("config_path", "config/exotic_base_anchor.yaml"),
        lane=overrides.pop("lane", "productive"),
        require_factory_verified=overrides.pop("require_factory_verified", True),
        cycle_lengths=overrides.pop("cycle_lengths", (3, 4)),
        active_economics_profile=overrides.pop(
            "active_economics_profile", "production_conservative"
        ),
        session_id=overrides.pop("session_id", "sess_a"),
        graph_fingerprint=fp,
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
    graph_keys = (
        "resolved_inventory_path",
        "active_route_count",
        "graph_edge_count",
        "graph_route_count",
        "route_universe_hash",
        "post_depth_content_hash",
        "execution_content_fingerprint",
    )
    cap = {
        "universe_contract": dict(runner),
        "graph_fingerprint": {
            key: runner[key]
            for key in graph_keys
            if key in runner
        },
    }
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert ok
    assert mismatches == []


def test_validate_fail_close_missing_graph_fingerprint():
    runner = _runner_contract()
    cap = {"universe_contract": dict(runner)}
    ok, mismatches = validate_capacity_for_runner(cap, runner)
    assert not ok
    assert "graph_fingerprint_missing_in_capacity" in mismatches


def test_compare_fail_close_missing_runner_graph_keys():
    runner = _runner_contract()
    for key in (
        "resolved_inventory_path",
        "active_route_count",
        "graph_edge_count",
        "graph_route_count",
        "route_universe_hash",
        "post_depth_content_hash",
    ):
        broken = dict(runner)
        broken.pop(key, None)
        mismatches = compare_universe_contracts(
            broken, runner, require_graph_fingerprint=True
        )
        assert f"graph_fingerprint_missing_in_runner_{key}" in mismatches


def test_graph_route_count_is_required_compare_key():
    from m9.graph_arb.universe_contract import _GRAPH_COMPARE_KEYS

    assert "graph_route_count" in _GRAPH_COMPARE_KEYS
    assert "route_universe_hash" in _GRAPH_COMPARE_KEYS
    assert "execution_content_fingerprint" in _GRAPH_COMPARE_KEYS


def test_contract_schema_version_v2():
    contract = _runner_contract()
    assert contract["schema_version"] == CONTRACT_SCHEMA_VERSION
    assert "admission_policy" in contract


def test_blocker_constant_exported():
    assert BLOCKER_CAPACITY_UNIVERSE_MISMATCH == "CAPACITY_UNIVERSE_MISMATCH"
