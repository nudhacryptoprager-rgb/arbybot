"""Unit tests for distinct-pricing DEX lane metrics."""
from __future__ import annotations

from m8.discovery.distinct_pricing_lane import (
    BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY,
    BLOCKER_DISTINCT_PRICING_LANE_NOT_READY,
    build_per_adapter_lane_report,
    count_distinct_pricing_routes,
    evaluate_distinct_pricing_lane,
    merge_distinct_pricing_into_acceptance,
)
from m8.discovery.hot_path_common import bridge_shadow_acceptance_from_candidates


def test_count_distinct_pricing_routes():
    routes = [
        {"dex_id": "curve_stable", "adapter_type": "curve_stable"},
        {"dex_id": "balancer_vault", "adapter_type": "balancer_vault"},
        {"dex_id": "uniswap_v4", "adapter_type": "uniswap_v4"},
    ]
    counts = count_distinct_pricing_routes(routes)
    assert counts["curve_routes_ready"] == 1
    assert counts["balancer_routes_ready"] == 1
    assert counts["maverick_routes_ready"] == 0
    assert counts["distinct_pricing_routes_ready"] == 2


def test_merge_blocks_bridge_shadow_without_distinct_pricing():
    acceptance = {
        "subgraph_ready": True,
        "bridge_shadow_lane_eligible": True,
        "ready_for_bridge_shadow": True,
    }
    out = merge_distinct_pricing_into_acceptance(
        acceptance,
        routes=[{"dex_id": "uniswap_v4", "adapter_type": "uniswap_v4"}],
    )
    assert out["ready_for_bridge_shadow"] is False
    assert out["existence_blocker"] == BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY


def test_bridge_shadow_acceptance_requires_distinct_lane():
    candidates = [
        {
            "cross_mechanic": True,
            "token_class": "fresh_long_tail",
            "mechanic_pair": "cross_mechanic",
            "bridge_shadow_lane_eligible": True,
            "routes_admitted": [
                {"dex_id": "uniswap_v4", "adapter_type": "uniswap_v4"},
                {"dex_id": "aerodrome", "adapter_type": "aerodrome_v2"},
            ],
            "summary": {
                "token_seen_on_dexes": 2,
                "connector_token_count": 1,
                "routes_admitted_count": 4,
                "unique_tokens": 4,
            },
        }
    ]
    acc = bridge_shadow_acceptance_from_candidates(candidates)
    assert acc["subgraph_ready"] is True
    assert acc["ready_for_bridge_shadow"] is False
    assert acc["existence_blocker"] == BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY


def test_per_adapter_lane_report():
    report = build_per_adapter_lane_report(
        routes_admitted=[
            {
                "dex_id": "maverick_v2",
                "adapter_type": "maverick_v2",
                "quote_smoke": "OK",
            }
        ],
        reject_rows=[{"dex_id": "curve_stable", "reason": "NO_POOL"}],
        pools_found_by_dex={"curve_stable": 2, "maverick_v2": 1},
    )
    assert report["maverick_v2"]["admitted"] == 1
    assert report["maverick_v2"]["quoteable"] == 1
    assert report["curve_stable"]["rejected"] == 1
    assert report["curve_stable"]["discovered"] == 2


def test_curve_only_does_not_satisfy_all_lanes():
    lane = evaluate_distinct_pricing_lane(
        [{"dex_id": "curve_stable", "adapter_type": "curve_stable"}]
    )
    assert lane["curve_lane_ready"] is True
    assert lane["balancer_lane_ready"] is False
    assert lane["maverick_lane_ready"] is False
    assert lane["distinct_pricing_all_lanes_ready"] is False
    assert lane["existence_blocker"] == BLOCKER_DISTINCT_PRICING_BALANCER_MAVERICK_LANES_NOT_READY


def test_all_lanes_ready_when_each_has_routes():
    routes = [
        {"dex_id": "curve_stable", "quote_smoke_status": "QUOTE_OK"},
        {
            "dex_id": "balancer_vault",
            "quote_smoke_status": "QUOTE_OK_BALANCER",
        },
        {"dex_id": "maverick_v2", "quote_smoke_status": "QUOTE_OK_MAVERICK"},
    ]
    lane = evaluate_distinct_pricing_lane(routes)
    assert lane["distinct_pricing_all_lanes_ready"] is True
    assert lane["existence_blocker"] is None
    assert lane["missing_distinct_pricing_lanes"] == []
    assert lane["quote_lanes_not_ready"] == []
    assert lane["balancer_quoteable_routes"] == 1
    assert lane["maverick_quoteable_routes"] == 1


def test_missing_lanes_and_quote_not_ready_fields():
    lane = evaluate_distinct_pricing_lane(
        [
            {"dex_id": "balancer_vault", "quote_smoke_status": "BALANCER_QUOTE_REVERT"},
            {"dex_id": "maverick_v2", "quote_smoke_status": "MAVERICK_QUOTE_REVERT"},
        ]
    )
    assert lane["missing_distinct_pricing_lanes"] == ["curve"]
    assert "balancer" in lane["quote_lanes_not_ready"]
    assert "maverick" in lane["quote_lanes_not_ready"]


def test_merge_shadow_requires_quoteable_distinct_pricing():
    acceptance = {
        "subgraph_ready": True,
        "bridge_shadow_lane_eligible": True,
        "ready_for_bridge_shadow": True,
    }
    routes = [
        {"dex_id": "curve_stable", "quote_smoke_status": "QUOTE_OK"},
        {"dex_id": "balancer_vault", "quote_smoke_status": "BALANCER_QUOTE_REVERT"},
        {"dex_id": "maverick_v2", "quote_smoke_status": "MAVERICK_QUOTE_REVERT"},
    ]
    out = merge_distinct_pricing_into_acceptance(acceptance, routes=routes)
    assert out["ready_for_bridge_shadow"] is False
    assert out["distinct_pricing_shadow_quote_ready"] is False


def test_stamp_productive_from_diagnostic_and_curve_indices(tmp_path):
    diag = {
        "productive_quote_counts": {
            "balancer_vault:0xpool1": "QUOTE_OK_PRODUCTIVE",
            "maverick_v2:0xpool2": "QUOTE_OK_PRODUCTIVE",
        }
    }
    curve = {
        "pools": {
            "0xcurve1": {"probe_status": "QUOTE_OK_INT128"},
        }
    }
    (tmp_path / "data/tmp").mkdir(parents=True)
    (tmp_path / "data/runs/_rolling").mkdir(parents=True)
    (tmp_path / "data/tmp/m9_productive_quote_diagnostic_latest.json").write_text(
        __import__("json").dumps(diag), encoding="utf-8"
    )
    (tmp_path / "data/runs/_rolling/m9_curve_pool_indices_latest.json").write_text(
        __import__("json").dumps(curve), encoding="utf-8"
    )
    routes = [
        {
            "dex_id": "balancer_vault",
            "pool_address": "0xpool1",
            "quote_smoke_status": "QUOTE_OK_BALANCER",
        },
        {"dex_id": "maverick_v2", "pool_address": "0xpool2", "quote_smoke_status": "QUOTE_OK_MAVERICK"},
        {"dex_id": "curve_stable", "pool_address": "0xcurve1"},
    ]
    from m8.discovery.distinct_pricing_lane import (
        evaluate_distinct_pricing_lane,
        stamp_productive_quote_status_from_artifacts,
    )

    stamp_productive_quote_status_from_artifacts(routes, repo_root=tmp_path)
    lane = evaluate_distinct_pricing_lane(routes)
    assert lane["productive_balancer_quoteable_routes"] == 1
    assert lane["productive_maverick_quoteable_routes"] == 1
    assert lane["productive_curve_quoteable_routes"] == 1
    assert lane["distinct_pricing_productive_quote_ready"] is True


def test_merge_shadow_requires_productive_quote_not_only_discovery():
    acceptance = {
        "subgraph_ready": True,
        "bridge_shadow_lane_eligible": True,
    }
    routes = [
        {
            "dex_id": "curve_stable",
            "pool_address": "0x" + "1" * 40,
            "quote_smoke_status": "QUOTE_OK",
        },
        {
            "dex_id": "balancer_vault",
            "pool_id": "0x" + "2" * 64,
            "quote_smoke_status": "QUOTE_OK_BALANCER",
        },
        {
            "dex_id": "maverick_v2",
            "pool_address": "0x" + "3" * 40,
            "quote_smoke_status": "QUOTE_OK_MAVERICK",
        },
    ]
    out_discovery_only = merge_distinct_pricing_into_acceptance(acceptance, routes=routes)
    assert out_discovery_only["distinct_pricing_shadow_quote_ready"] is True
    assert out_discovery_only["distinct_pricing_productive_quote_ready"] is False
    assert out_discovery_only["ready_for_bridge_shadow"] is False

    productive_counts = {
        "curve_stable:0x" + "1" * 40: "QUOTE_OK_PRODUCTIVE",
        "balancer_vault:0x" + "2" * 64: "QUOTE_OK_PRODUCTIVE",
        "maverick_v2:0x" + "3" * 40: "QUOTE_OK_PRODUCTIVE",
    }
    out_productive = merge_distinct_pricing_into_acceptance(
        acceptance,
        routes=[dict(r) for r in routes],
        productive_counts=productive_counts,
    )
    assert out_productive["productive_balancer_quoteable_routes"] == 1
    assert out_productive["productive_maverick_quoteable_routes"] == 1
    assert out_productive["productive_curve_quoteable_routes"] == 1
    assert out_productive["distinct_pricing_productive_quote_ready"] is True
    assert out_productive["ready_for_bridge_shadow"] is True
