"""Runner integration tests for capacity universe contract fail-close."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from m9.graph_arb.universe_contract import build_universe_contract


def _minimal_bridge(path: Path) -> None:
    path.write_text(
        json.dumps(
            {
                "active_routes": [
                    {
                        "route_id": "r1",
                        "pool_address": "0xabc",
                        "factory_verified": True,
                    }
                ],
                "bridge_source_metrics": {"graph_ready_total": 1},
            }
        ),
        encoding="utf-8",
    )


def _capacity_doc(*, inventory_path: str, cycle_lengths: list[int], session_id: str) -> dict:
    runner_uc = build_universe_contract(
        inventory_path=inventory_path,
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=cycle_lengths,
        active_economics_profile="production_conservative",
        session_id=session_id,
    )
    return {
        "schema_version": "m9_capacity_cycle_diagnostic.2",
        "universe_contract": runner_uc,
        "capacity_valid_cycle_ids": ["cid_a"],
        "cycles_at_production_floor": 1,
    }


@pytest.fixture
def bridge_and_capacity(tmp_path):
    bridge = tmp_path / "bridge.json"
    cap = tmp_path / "capacity.json"
    artifact = tmp_path / "shadow.json"
    _minimal_bridge(bridge)
    return bridge, cap, artifact


def test_runner_exit_7_writes_mismatch_artifact(bridge_and_capacity, monkeypatch):
    from m9.graph_arb.runner import EXIT_CAPACITY_UNIVERSE_MISMATCH, _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    cap_path.write_text(
        json.dumps(
            _capacity_doc(
                inventory_path=str(bridge),
                cycle_lengths=[2, 3, 4],
                session_id="sess_a",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARBY_PIPELINE_SESSION_ID", raising=False)
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_a")

    import argparse

    args = argparse.Namespace(
        chain="base",
        config="config/exotic_base_anchor.yaml",
        inventory=str(bridge),
        no_prequote=False,
        dynamic_sizes=False,
        sizes_usd=[100.0, 250.0, 500.0],
        dynamic_size_max_cycles=3,
        require_premium_rpc=False,
        require_factory_verified=True,
        productive_lane=True,
        verbose=False,
        artifact_path=str(artifact_path),
        capacity_diagnostic=str(cap_path),
        require_cycles_at_floor=False,
        duration_minutes=1.0,
        cycles_limit=100,
        session_id=None,
        allow_no_prequote_soak=False,
        prior_shadow_artifact="",
        allow_spread_lifetime_without_positive_gross=False,
    )
    log = logging.getLogger("test.runner_universe")
    result = _run(args, log)
    assert result == EXIT_CAPACITY_UNIVERSE_MISMATCH
    assert artifact_path.is_file()
    doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert doc["runner_outcome"] == "CAPACITY_UNIVERSE_MISMATCH"
    assert "cycle_lengths" in (doc.get("universe_mismatch_keys") or [])
    assert doc.get("run_context", {}).get("session_id") == "sess_a"


def test_runner_accepts_matching_capacity_contract(bridge_and_capacity, monkeypatch):
    from m9.graph_arb.runner import EXIT_CAPACITY_UNIVERSE_MISMATCH, _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    uc = build_universe_contract(
        inventory_path=str(bridge),
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_b",
    )
    cap_path.write_text(
        json.dumps(
            {
                "schema_version": "m9_capacity_cycle_diagnostic.2",
                "universe_contract": uc,
                "capacity_valid_cycle_ids": ["cid_a"],
                "cycles_at_production_floor": 1,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_b")

    import argparse

    args = argparse.Namespace(
        chain="base",
        config="config/exotic_base_anchor.yaml",
        inventory=str(bridge),
        no_prequote=False,
        dynamic_sizes=False,
        sizes_usd=[100.0, 250.0, 500.0],
        dynamic_size_max_cycles=3,
        require_premium_rpc=False,
        require_factory_verified=True,
        productive_lane=True,
        verbose=False,
        artifact_path=str(artifact_path),
        capacity_diagnostic=str(cap_path),
        require_cycles_at_floor=False,
        duration_minutes=1.0,
        cycles_limit=100,
        session_id="sess_b",
        allow_no_prequote_soak=False,
        prior_shadow_artifact="",
        allow_spread_lifetime_without_positive_gross=False,
    )
    log = logging.getLogger("test.runner_universe")
    result = _run(args, log)
    assert result != EXIT_CAPACITY_UNIVERSE_MISMATCH
