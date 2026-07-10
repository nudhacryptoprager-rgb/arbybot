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


def test_enrich_targeted_recomputes_metrics_over_all_routes(tmp_path, monkeypatch):
    """Codex Patch 5 issue #3/#4 regression: targeted enrichment must
    recompute ``depth_known_rate`` / ``route_capacity_histogram`` /
    ``pre_shadow_blockers`` over ALL active routes (not just the filtered
    probe subset). Otherwise the summary stays stale after enrichment even
    though the underlying route depth values were refreshed.

    The CLI ``main()`` resolves public-RPC guard and returns 1; to keep this
    offline deterministic we patch RPC resolution to succeed.
    """
    inventory_path = tmp_path / "bridge.json"
    output_path = tmp_path / "bridge_out.json"
    # Two routes; only r2 has effective_depth_usd already set. The fake
    # enricher "discovers" depth on r1 (mutating the shared dict in place),
    # so ALL-routes depth_known_rate becomes 1.0 (2/2 known).
    routes = [
        {
            "route_id": "r1",
            "pool_address": "0x" + "11" * 20,
            "adapter_type": "uniswap_v3",
            "dex_id": "uniswap_v3",
        },
        {
            "route_id": "r2",
            "pool_address": "0x" + "22" * 20,
            "adapter_type": "uniswap_v3",
            "dex_id": "uniswap_v3",
            "effective_depth_usd": 500.0,
            "depth_probe_status": "DEPTH_PROBE_MEASURED_CAPACITY",
        },
    ]
    inventory_path.write_text(
        json.dumps(
            {
                "active_routes": routes,
                "bridge_source_metrics": {
                    "depth_known_rate": 0.5,
                    "pre_shadow_blockers": ["DEPTH_ENRICHMENT_REQUIRED"],
                    "routes_decimals_unknown": 0,
                    "m8_3_authority_applied": True,
                },
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(enrich_cli, "_load_dex_quoters", lambda *a, **k: {})

    def _fake_enrich(route_subset, *args, **kwargs):
        # Confirm the CLI only probes the targeted subset.
        assert {r["route_id"] for r in route_subset} == {"r1"}
        # Mutate the shared route dict (mimicking the real probe path):
        r1 = next(r for r in route_subset if r["route_id"] == "r1")
        r1["effective_depth_usd"] = 300.0
        r1["depth_probe_status"] = "DEPTH_PROBE_MEASURED_CAPACITY"
        return {
            "candidates": 1,
            "probed_ok": 1,
            "probe_failed": 0,
            "no_anchor": 0,
            "skipped_v4": 0,
            "toxic": 0,
            "low_depth": 0,
            "v4_depth_candidates": 0,
            "v4_depth_probe_ok": 0,
            "v4_depth_probe_failed": 0,
        }

    monkeypatch.setattr(
        "m9.graph_arb.pool_depth_probe.enrich_routes_missing_depth", _fake_enrich
    )

    # Patch RPC guard so offline test can pass.
    monkeypatch.setenv("ARBY_OFFLINE", "1")
    from core import rpc_urls as _rpc_urls

    monkeypatch.setattr(_rpc_urls, "resolve_productive_http_rpc", lambda chain: "https://example.invalid/rpc")
    monkeypatch.setattr(_rpc_urls, "is_public_rpc_url", lambda url: False)
    # apply_productive_rpc_env is imported INSIDE main(), so patch the source
    # module attr instead of the script namespace.
    monkeypatch.setattr(_rpc_urls, "apply_productive_rpc_env", lambda chain: {})
    import core.env as _env

    monkeypatch.setattr(_env, "load_root_dotenv", lambda *a, **k: None)
    route_ids_path = tmp_path / "target_ids.json"
    route_ids_path.write_text(json.dumps({"enrichment_targets": {"route_ids": ["r1"]}}), encoding="utf-8")
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "m9_enrich_bridge_depth.py",
            "--inventory", str(inventory_path),
            "--output", str(output_path),
            "--route-ids-file", str(route_ids_path),
            "--allow-public-rpc",
        ],
    )

    assert enrich_cli.main() == 0
    written = json.loads(output_path.read_text(encoding="utf-8"))
    metrics = written["bridge_source_metrics"]
    # ALL routes: both r1 and r2 now have known depth → 1.0 (was 0.5 stale).
    assert metrics["depth_known_rate"] == 1.0
    # DEPTH_ENRICHMENT_REQUIRED must be removed from pre_shadow_blockers.
    assert "DEPTH_ENRICHMENT_REQUIRED" not in (
        metrics.get("pre_shadow_blockers") or []
    )
