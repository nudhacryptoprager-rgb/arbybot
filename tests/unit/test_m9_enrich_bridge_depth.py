"""Unit tests for the M9 bridge depth-enrichment CLI."""
from __future__ import annotations

import json
import sys

import scripts.m9_enrich_bridge_depth as enrich_cli


def test_enrich_bridge_depth_writes_v4_metrics(tmp_path, monkeypatch):
    inventory_path = tmp_path / "bridge.json"
    output_path = tmp_path / "bridge_out.json"
    inventory_path.write_text(
        json.dumps({
            "active_routes": [{"adapter_type": "uniswap_v4"}],
            "bridge_source_metrics": {"existing": 1},
        }),
        encoding="utf-8",
    )

    monkeypatch.setattr(enrich_cli, "_load_dex_quoters", lambda *a, **k: {})

    def _fake_enrich(*args, **kwargs):
        return {
            "candidates": 1,
            "probed_ok": 0,
            "probe_failed": 1,
            "no_anchor": 0,
            "skipped_v4": 0,
            "toxic": 0,
            "low_depth": 0,
            "v4_depth_candidates": 1,
            "v4_depth_probe_ok": 0,
            "v4_depth_probe_failed": 1,
        }

    monkeypatch.setattr("m9.graph_arb.pool_depth_probe.enrich_routes_missing_depth", _fake_enrich)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "m9_enrich_bridge_depth.py",
            "--inventory", str(inventory_path),
            "--output", str(output_path),
        ],
    )

    assert enrich_cli.main() == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    metrics = written["bridge_source_metrics"]
    assert metrics["existing"] == 1
    assert metrics["v4_depth_candidates"] == 1
    assert metrics["v4_depth_probe_ok"] == 0
    assert metrics["v4_depth_probe_failed"] == 1
    assert metrics["v4_depth_skipped_unsupported"] == 0
