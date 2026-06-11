"""Unit tests for m8_2_acceptance_report script."""
from __future__ import annotations

from scripts.m8_2_acceptance_report import build_m8_2_acceptance_report


def _good_expansion_summary(**overrides):
    base = {
        "m8_tokens_in": 500,
        "routes_admitted_count": 800,
        "multi_venue_tokens": 20,
        "verified_second_pool_count": 15,
        "connector_routes_count": 50,
        "subgraph_ready_tokens": 5,
        "hint_tokens_matched": 300,
        "external_hints_enabled": True,
    }
    base.update(overrides)
    return base


def _coverage_fixture(summary: dict) -> dict:
    dexes = summary.get("dex_ids_checked") or [
        "uniswap_v3",
        "aerodrome",
        "balancer_vault",
    ]
    attempted = {dex: 10 for dex in dexes}
    return {
        "scan_attempt_matrix": {
            "0xabc": {
                dex: {"USDC": {"attempted": True, "result": "NO_POOL"}}
                for dex in dexes
            }
        },
        "scan_telemetry": {
            "scan_expected_attempts": len(dexes) * 10,
            "scan_actual_attempts": len(dexes) * 10,
            "active_scan_attempted_by_dex": attempted,
            "active_scan_attempted_by_anchor": {"USDC": len(dexes) * 10},
        },
    }


def _artifacts(
    *,
    sniper_ts="2026-06-11T10:00:00Z",
    hints_ts="2026-06-11T11:00:00Z",
    expansion_ts="2026-06-11T12:00:00Z",
    summary=None,
):
    summary = summary or _good_expansion_summary()
    summary = {**summary, "dex_ids_checked": summary.get("dex_ids_checked") or ["uniswap_v3", "aerodrome"]}
    coverage = _coverage_fixture(summary)
    return (
        {"generated_at_utc": sniper_ts, "recent_events": []},
        {"generated_at_utc": hints_ts, "hints": []},
        {
            "generated_at_utc": expansion_ts,
            "summary": {
                **summary,
                "active_scan_coverage_rate": 1.0,
                "scan_expected_attempts": coverage["scan_telemetry"]["scan_expected_attempts"],
                "scan_actual_attempts": coverage["scan_telemetry"]["scan_actual_attempts"],
                "active_scan_attempted_by_dex": coverage["scan_telemetry"]["active_scan_attempted_by_dex"],
            },
            "routes_admitted": [
                {
                    "origin_source": "m8_watchlist_hint",
                    "matched_m8_token": True,
                    "factory_verified": True,
                    "dex_id": "uniswap_v3",
                }
            ],
            **coverage,
        },
    )


def test_stale_hints_fail_m8_2():
    sniper, hints, expansion = _artifacts(
        sniper_ts="2026-06-11T12:00:00Z",
        hints_ts="2026-06-11T10:00:00Z",
    )
    report = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    assert "HINTS_STALE" in report["blockers"]
    assert report["goal_status"] == "BLOCKED"


def test_subgraph_ready_low_fails_m8_2():
    sniper, hints, expansion = _artifacts(
        summary=_good_expansion_summary(subgraph_ready_tokens=1)
    )
    report = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    assert "SUBGRAPH_READY_LOW" in report["blockers"]
    assert report["goal_status"] == "BLOCKED"


def test_cycles_quoteable_does_not_affect_m8_2():
    sniper, hints, expansion = _artifacts()
    report = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    assert report["goal_status"] == "REACHED"
    assert "NO_QUOTEABLE_CYCLES" not in report["blockers"]
    assert "cycles_quoteable" not in str(report)


def test_m8_2_pass_and_m9_fail_are_independent():
    from scripts.m9_lane_acceptance_report import build_acceptance_report

    sniper, hints, expansion = _artifacts()
    m8_2 = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    m9 = build_acceptance_report(
        sniper=sniper,
        anchor=None,
        expansion=expansion,
        bridge={"active_routes": [], "bridge_source_metrics": {"graph_ready_from_m8": 10}},
        shadow={
            "cycles_found": 100,
            "cycles_quoteable": 0,
            "cycles_positive_gross": 0,
            "qsr": 0.0,
            "qsr_econ": 0.0,
            "depth_aware_known_rate": 0.0,
        },
        rca={"summary": {"top_reject": "QUOTE_REVERT"}},
        m8_2_report=m8_2,
    )
    assert m8_2["goal_status"] == "REACHED"
    assert m9["m9_blockers"]
    assert "NO_QUOTEABLE_CYCLES" in m9["m9_blockers"]
    assert m9["m8_2_upstream"]["goal_status"] == "REACHED"


def test_m8_2_report_includes_per_source_yield_and_subgraph_debug():
    sniper, hints, expansion = _artifacts()
    hints["metrics"] = {
        "per_source_verified_yield": {"dexscreener": 5, "geckoterminal": 3},
    }
    expansion["subgraph_ready_debug"] = [
        {
            "token_address": "0xabc",
            "missing_reason": "TOKEN_SEEN_ON_ONE_DEX",
        }
    ]
    expansion["summary"]["routes_by_origin_source"] = {
        "m8_watchlist_hint": 10,
        "exploration": 2,
    }
    expansion["summary"]["canonical_routes_count"] = 10
    expansion["summary"]["exploration_routes_count"] = 2
    report = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    assert report["per_source_verified_yield"]["dexscreener"] == 5
    assert report["subgraph_ready_debug"]["top_missing_reasons"]["TOKEN_SEEN_ON_ONE_DEX"] == 1
    assert report["provenance"]["canonical_routes_count"] == 10


def test_m8_2_fail_sets_upstream_not_ready_on_m9():
    from scripts.m9_lane_acceptance_report import build_acceptance_report

    sniper, hints, expansion = _artifacts(
        summary=_good_expansion_summary(subgraph_ready_tokens=1)
    )
    m8_2 = build_m8_2_acceptance_report(
        sniper=sniper, hints=hints, expansion=expansion, strict=True
    )
    m9 = build_acceptance_report(
        sniper=sniper,
        anchor=None,
        expansion=expansion,
        bridge={"active_routes": [], "bridge_source_metrics": {}},
        shadow=None,
        rca=None,
        m8_2_report=m8_2,
    )
    assert m8_2["goal_status"] == "BLOCKED"
    assert "UPSTREAM_M8_2_NOT_READY" in m9["upstream_blockers"]
    assert "SUBGRAPH_READY_LOW" in m9["m8_2_upstream"]["blockers"]
