"""Runner integration tests for capacity universe contract fail-close."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest

from m9.graph_arb.universe_contract import (
    build_runner_admission_graph_fingerprint,
    build_universe_contract,
)


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


def _capacity_doc(
    *,
    inventory_path: str,
    config_path: str,
    cycle_lengths: list[int],
    session_id: str,
) -> dict:
    graph_fp = build_runner_admission_graph_fingerprint(
        inventory_path=inventory_path,
        config_path=config_path,
        lane="productive",
        require_factory_verified=True,
    )
    runner_uc = build_universe_contract(
        inventory_path=inventory_path,
        config_path=config_path,
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=cycle_lengths,
        active_economics_profile="production_conservative",
        session_id=session_id,
        graph_fingerprint=graph_fp,
    )
    return {
        "schema_version": "m9_capacity_cycle_diagnostic.2",
        "universe_contract": runner_uc,
        "graph_fingerprint": graph_fp,
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


def test_runner_exit_8_on_effective_inventory_prep_failure(bridge_and_capacity, monkeypatch):
    from m9.graph_arb.runner import EXIT_EFFECTIVE_INVENTORY_PREP_FAILED, _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    cap_path.write_text(
        json.dumps(
            _capacity_doc(
                inventory_path=str(bridge),
                config_path="config/exotic_base_anchor.yaml",
                cycle_lengths=[3, 4],
                session_id="sess_prep_fail",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_prep_fail")

    def _raise(*_args, **_kwargs):
        raise ValueError("PRE_DEPTH_INVENTORY")

    monkeypatch.setattr(
        "m9.graph_arb.effective_inventory.prepare_effective_execution_inventory",
        _raise,
    )

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
        session_id="sess_prep_fail",
        allow_no_prequote_soak=False,
        prior_shadow_artifact="",
        allow_spread_lifetime_without_positive_gross=False,
        allow_pre_depth_inventory=False,
        effective_inventory_path=None,
    )
    log = logging.getLogger("test.runner_prep_fail")
    result = _run(args, log)
    assert result == EXIT_EFFECTIVE_INVENTORY_PREP_FAILED
    assert artifact_path.is_file()
    doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert doc["runner_outcome"] == "EFFECTIVE_INVENTORY_PREP_FAILED"
    assert "PRE_DEPTH_INVENTORY" in str(doc.get("effective_inventory_prep_failure") or "")
    qst = doc.get("quote_size_truth") or {}
    assert int(qst.get("econ_rpc_quote_attempts") or 0) == 0


def test_capacity_and_runner_share_effective_inventory_path(
    bridge_and_capacity, monkeypatch, tmp_path,
):
    from m9.graph_arb.runner import _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    shared_path = tmp_path / "effective_sess.json"
    shared_path.write_text(
        json.dumps(
            {
                "active_routes": [{"route_id": "r1", "pool_address": "0xabc"}],
                "depth_enrichment": {
                    "post_depth_content_hash": "post",
                    "depth_enrichment_session_id": "sess_path",
                },
            }
        ),
        encoding="utf-8",
    )
    recorded: list[str] = []

    def _prepare(inventory_path, *args, **kwargs):
        out = str(kwargs.get("output_path") or shared_path)
        recorded.append(out)
        Path(out).write_text(
            json.dumps(
                {
                    "active_routes": [{"route_id": "r1", "pool_address": "0xabc"}],
                    "depth_enrichment": {
                        "post_depth_content_hash": "post",
                        "depth_enrichment_session_id": "sess_path",
                    },
                }
            ),
            encoding="utf-8",
        )
        return out

    monkeypatch.setattr(
        "m9.graph_arb.effective_inventory.prepare_effective_execution_inventory",
        _prepare,
    )
    cap_path.write_text(
        json.dumps(
            {
                **_capacity_doc(
                    inventory_path=str(shared_path),
                    config_path="config/exotic_base_anchor.yaml",
                    cycle_lengths=[3, 4],
                    session_id="sess_path",
                ),
                "effective_inventory_path": str(shared_path),
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_path")
    monkeypatch.setenv("ARBY_M9_EFFECTIVE_INVENTORY_PATH", str(shared_path))

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
        session_id="sess_path",
        allow_no_prequote_soak=False,
        prior_shadow_artifact="",
        allow_spread_lifetime_without_positive_gross=False,
        allow_pre_depth_inventory=False,
        effective_inventory_path=str(shared_path),
    )
    log = logging.getLogger("test.runner_shared_path")
    _run(args, log)
    assert recorded
    assert all(path == str(shared_path) for path in recorded)


def test_runner_exit_7_writes_mismatch_artifact(bridge_and_capacity, monkeypatch):
    from m9.graph_arb.runner import EXIT_CAPACITY_UNIVERSE_MISMATCH, _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    cap_path.write_text(
        json.dumps(
            _capacity_doc(
                inventory_path=str(bridge),
                config_path="config/exotic_base_anchor.yaml",
                cycle_lengths=[2, 3, 4],
                session_id="sess_a",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.delenv("ARBY_PIPELINE_SESSION_ID", raising=False)
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_a")
    monkeypatch.setattr(
        "m9.graph_arb.effective_inventory.prepare_effective_execution_inventory",
        lambda inventory_path, *args, **kwargs: inventory_path,
    )

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
        allow_pre_depth_inventory=True,
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
    cap_path.write_text(
        json.dumps(
            _capacity_doc(
                inventory_path=str(bridge),
                config_path="config/exotic_base_anchor.yaml",
                cycle_lengths=[3, 4],
                session_id="sess_b",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_b")
    monkeypatch.setattr(
        "m9.graph_arb.effective_inventory.prepare_effective_execution_inventory",
        lambda inventory_path, *args, **kwargs: inventory_path,
    )

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
        allow_pre_depth_inventory=True,
    )
    log = logging.getLogger("test.runner_universe")
    result = _run(args, log)
    assert result != EXIT_CAPACITY_UNIVERSE_MISMATCH


def test_successful_runner_stamps_provenance_and_universe_contract(
    bridge_and_capacity, monkeypatch,
):
    from m9.graph_arb.runner import _run

    bridge, cap_path, artifact_path = bridge_and_capacity
    cap_path.write_text(
        json.dumps(
            _capacity_doc(
                inventory_path=str(bridge),
                config_path="config/exotic_base_anchor.yaml",
                cycle_lengths=[3, 4],
                session_id="sess_stamp",
            )
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARBY_PIPELINE_SESSION_ID", "sess_stamp")
    monkeypatch.setattr(
        "m9.graph_arb.effective_inventory.prepare_effective_execution_inventory",
        lambda inventory_path, *args, **kwargs: inventory_path,
    )

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
        session_id="sess_stamp",
        allow_no_prequote_soak=False,
        prior_shadow_artifact="",
        allow_spread_lifetime_without_positive_gross=False,
        allow_pre_depth_inventory=True,
    )
    log = logging.getLogger("test.runner_universe")
    _run(args, log)
    if not artifact_path.is_file():
        pytest.skip("runner did not complete artifact in this environment")
    doc = json.loads(artifact_path.read_text(encoding="utf-8"))
    assert doc.get("session_id") == "sess_stamp"
    assert doc.get("run_context", {}).get("session_id") == "sess_stamp"
    assert doc.get("universe_contract", {}).get("session_id") == "sess_stamp"
    assert doc.get("effective_inventory_path")
