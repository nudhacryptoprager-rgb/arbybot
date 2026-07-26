"""Tests for effective execution inventory alignment."""
from __future__ import annotations

import json

import pytest

from m9.graph_arb.effective_inventory import (
    assert_post_depth_inventory,
    build_route_universe_identity,
    prepare_effective_execution_inventory,
    resolve_effective_inventory_path,
    sanitize_session_token,
)
from m9.graph_arb.universe_contract import (
    build_runner_admission_graph_fingerprint,
    build_universe_contract,
    compare_universe_contracts,
    validate_capacity_for_runner,
)


def _bridge_doc(*, post_depth: bool = True) -> dict:
    doc = {
        "active_routes": [
            {
                "route_id": "r1",
                "pool_address": "0xabc",
                "factory_verified": True,
                "token0_decimals": 18,
                "token1_decimals": 6,
            }
        ],
    }
    if post_depth:
        doc["depth_enrichment"] = {
            "pre_depth_content_hash": "pre",
            "post_depth_content_hash": "post",
            "depth_enrichment_session_id": "sess_depth",
        }
    return doc


def test_assert_post_depth_inventory_requires_metadata():
    ok, blockers = assert_post_depth_inventory(_bridge_doc(post_depth=False))
    assert not ok
    assert "PRE_DEPTH_INVENTORY" in blockers


def test_prepare_effective_inventory_requires_post_depth(tmp_path, monkeypatch):
    monkeypatch.setenv("ARBY_M9_ALLOW_LIVE_EFFECTIVE_INVENTORY_MATERIALIZE", "1")
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps(_bridge_doc(post_depth=False)), encoding="utf-8")
    with pytest.raises(ValueError, match="PRE_DEPTH_INVENTORY"):
        prepare_effective_execution_inventory(
            str(bridge),
            "config/exotic_base_anchor.yaml",
            require_post_depth=True,
        )


def test_pre_depth_capacity_contract_fails_against_post_depth_effective_inventory(
    tmp_path, monkeypatch,
):
    bridge = tmp_path / "bridge.json"
    enriched = tmp_path / "enriched.json"
    bridge.write_text(json.dumps(_bridge_doc(post_depth=True)), encoding="utf-8")
    enriched.write_text(json.dumps(_bridge_doc(post_depth=True)), encoding="utf-8")

    pre_fp = build_runner_admission_graph_fingerprint(
        inventory_path=str(bridge),
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
    )
    post_fp = build_runner_admission_graph_fingerprint(
        inventory_path=str(enriched),
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
    )
    assert pre_fp != post_fp or str(bridge).lower() != str(enriched).lower()

    cap_contract = build_universe_contract(
        inventory_path=str(bridge),
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_x",
        graph_fingerprint=pre_fp,
    )
    runner_contract = build_universe_contract(
        inventory_path=str(enriched),
        config_path="config/exotic_base_anchor.yaml",
        lane="productive",
        require_factory_verified=True,
        cycle_lengths=(3, 4),
        active_economics_profile="production_conservative",
        session_id="sess_x",
        graph_fingerprint=post_fp,
    )
    mismatches = compare_universe_contracts(
        runner_contract, cap_contract, require_graph_fingerprint=True
    )
    assert "resolved_inventory_path" in mismatches

    cap_doc = {
        "universe_contract": cap_contract,
        "graph_fingerprint": pre_fp,
    }
    ok, validate_mismatches = validate_capacity_for_runner(cap_doc, runner_contract)
    assert not ok
    assert validate_mismatches


def test_resolve_effective_inventory_path_is_session_namespaced(monkeypatch, tmp_path):
    monkeypatch.delenv("ARBY_M9_EFFECTIVE_INVENTORY_PATH", raising=False)
    path = resolve_effective_inventory_path("sess/alpha")
    assert "m9_effective_execution_inventory_" in path
    assert sanitize_session_token("sess/alpha") in path
    assert path != "data/tmp/m9_inventory_truth_enriched.json"


def test_build_route_universe_identity_detects_route_change(tmp_path):
    bridge = tmp_path / "bridge.json"
    bridge.write_text(json.dumps(_bridge_doc(post_depth=True)), encoding="utf-8")
    identity_a = build_route_universe_identity(str(bridge))
    doc_b = _bridge_doc(post_depth=True)
    doc_b["active_routes"].append(
        {
            "route_id": "r2",
            "pool_address": "0xdef",
            "factory_verified": True,
            "token0_decimals": 18,
            "token1_decimals": 6,
        }
    )
    other = tmp_path / "other.json"
    other.write_text(json.dumps(doc_b), encoding="utf-8")
    identity_b = build_route_universe_identity(str(other))
    assert identity_a["route_universe_hash"] != identity_b["route_universe_hash"]
