"""Tests for effective inventory integrity and materialization."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from m9.graph_arb.effective_inventory import (
    ENV_ALLOW_LIVE_MATERIALIZE,
    MANIFEST_SCHEMA_VERSION,
    _materialize_lock,
    _source_bridge_content_hash,
    build_execution_content_fingerprint,
    materialize_effective_inventory,
    validate_effective_inventory_integrity,
)


def _bridge_doc() -> dict:
    return {
        "active_routes": [
            {
                "route_id": "r1",
                "pool_address": "0xabc",
                "token0": "0xt0",
                "token1": "0xt1",
                "token0_decimals": 18,
                "token1_decimals": 6,
                "factory_verified": True,
                "effective_depth_usd": 1000.0,
                "source": "m8_sniper",
            }
        ],
        "depth_enrichment": {
            "post_depth_content_hash": "post",
            "depth_enrichment_session_id": "sess",
        },
    }


def test_materialize_is_idempotent_without_force(tmp_path, monkeypatch):
    bridge = tmp_path / "bridge.json"
    out = tmp_path / "effective.json"
    bridge.write_text(json.dumps(_bridge_doc()), encoding="utf-8")

    calls = {"n": 0, "output_paths": []}

    def _fake_enrich(inventory_path, config_path, **kwargs):
        calls["n"] += 1
        calls["output_paths"].append(kwargs.get("output_path"))
        doc = json.loads(open(inventory_path, encoding="utf-8").read())
        doc["quote_truth_enriched"] = True
        path = kwargs.get("output_path")
        open(path, "w", encoding="utf-8").write(json.dumps(doc))
        return str(path)

    monkeypatch.setattr(
        "m9.graph_arb.inventory_truth.enrich_inventory_for_quote_truth",
        _fake_enrich,
    )
    monkeypatch.setenv(ENV_ALLOW_LIVE_MATERIALIZE, "1")

    prices = {"0xt0": 1.0, "0xt1": 1.0}
    first = materialize_effective_inventory(
        str(bridge),
        "config/exotic_base_anchor.yaml",
        output_path=str(out),
        session_id="sess_mat",
        token_prices=prices,
    )
    second = materialize_effective_inventory(
        str(bridge),
        "config/exotic_base_anchor.yaml",
        output_path=str(out),
        session_id="sess_mat",
        token_prices={"0xt0": 9.0},
    )
    assert first == second
    assert calls["n"] == 1
    assert all(str(p).endswith(".enrich.tmp") for p in calls["output_paths"])
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["effective_inventory_manifest"]["schema_version"] == MANIFEST_SCHEMA_VERSION
    assert doc["frozen_token_prices"]["0xt0"] == 1.0


def test_validate_rejects_session_and_price_tampering(tmp_path):
    bridge = tmp_path / "bridge.json"
    out = tmp_path / "effective.json"
    bridge.write_text(json.dumps(_bridge_doc()), encoding="utf-8")
    doc = _bridge_doc()
    doc["quote_truth_enriched"] = True
    doc["frozen_token_prices"] = {"0xt0": 1.0}
    doc["effective_inventory_manifest"] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "immutable": True,
        "session_id": "sess_a",
        "execution_content_fingerprint": build_execution_content_fingerprint(doc),
        "token_prices_content_hash": "deadbeef",
        "prices_frozen": True,
    }
    out.write_text(json.dumps(doc), encoding="utf-8")
    blockers = validate_effective_inventory_integrity(
        json.loads(out.read_text(encoding="utf-8")),
        expected_session_id="sess_b",
    )
    assert "EFFECTIVE_INVENTORY_SESSION_MISMATCH" in blockers
    assert "EFFECTIVE_INVENTORY_FROZEN_PRICES_HASH_MISMATCH" in blockers


def test_validate_rejects_missing_manifest_session(tmp_path):
    doc = _bridge_doc()
    doc["quote_truth_enriched"] = True
    doc["frozen_token_prices"] = {"0xt0": 1.0, "0xt1": 1.0}
    doc["effective_inventory_manifest"] = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "immutable": True,
        "session_id": "",
        "execution_content_fingerprint": build_execution_content_fingerprint(doc),
        "token_prices_content_hash": "abc",
        "prices_frozen": True,
    }
    blockers = validate_effective_inventory_integrity(doc, expected_session_id="sess_expected")
    assert "EFFECTIVE_INVENTORY_SESSION_MISSING" in blockers


def test_source_bridge_hash_detects_depth_change():
    base = _bridge_doc()
    fp_a = _source_bridge_content_hash(base)
    mutated = json.loads(json.dumps(base))
    mutated["active_routes"][0]["effective_depth_usd"] = 42.0
    fp_b = _source_bridge_content_hash(mutated)
    assert fp_a != fp_b


def test_execution_content_fingerprint_changes_with_decimals():
    base = _bridge_doc()
    fp_a = build_execution_content_fingerprint(base)
    mutated = json.loads(json.dumps(base))
    mutated["active_routes"][0]["token1_decimals"] = 8
    fp_b = build_execution_content_fingerprint(mutated)
    assert fp_a != fp_b


def test_lock_contention_preserves_foreign_lock(tmp_path):
    effective = tmp_path / "effective.json"
    lock_path = Path(f"{effective}.materialize.lock")
    lock_path.write_text("foreign", encoding="utf-8")

    with pytest.raises(RuntimeError):
        with _materialize_lock(str(effective), "sess"):
            pass
    assert lock_path.is_file()
    assert lock_path.read_text(encoding="utf-8") == "foreign"
