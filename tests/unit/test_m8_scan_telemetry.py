"""Unit tests for M8.2 scan coverage telemetry."""
from __future__ import annotations

from unittest.mock import patch

from m8.discovery.cross_dex_expand import expand_token_neighborhood
from m8.discovery.scan_telemetry import (
    active_scan_coverage_rate,
    build_coverage_audit,
    empty_scan_telemetry,
    merge_scan_telemetry,
    record_scan_attempt,
)
from scripts.m8_2_acceptance_report import build_m8_2_acceptance_report


def test_record_scan_attempt_counts_no_pool_and_unsupported():
    tel = empty_scan_telemetry()
    record_scan_attempt(
        tel,
        token_address="0xabc",
        dex_id="uniswap_v3",
        anchor="USDC",
        attempted=True,
        result="NO_POOL",
        reason="NO_POOL",
    )
    record_scan_attempt(
        tel,
        token_address="0xabc",
        dex_id="curve_stable",
        anchor="USDC",
        attempted=True,
        result="UNSUPPORTED_DEX",
        reason="UNSUPPORTED_DEX",
    )
    assert tel["active_scan_no_pool_by_dex"]["uniswap_v3"] == 1
    assert tel["active_scan_unsupported_dex_by_dex"]["curve_stable"] == 1
    assert tel["scan_actual_attempts"] == 2
    assert tel["scan_attempt_matrix"]["0xabc"]["uniswap_v3"]["USDC"]["result"] == "NO_POOL"


def test_coverage_rate_and_audit_blocker_when_matrix_missing():
    expansion = {
        "summary": {
            "dex_ids_checked": ["uniswap_v3", "aerodrome"],
            "tokens_in": 10,
        }
    }
    audit = build_coverage_audit(expansion)
    assert "ACTIVE_SCAN_COVERAGE_INCOMPLETE" in audit["blockers"]
    assert audit["goal_status"] == "BLOCKED"


def test_coverage_audit_reached_when_matrix_complete():
    expansion = {
        "summary": {
            "dex_ids_checked": ["uniswap_v3", "aerodrome"],
            "tokens_in": 2,
            "active_scan_coverage_rate": 1.0,
            "scan_expected_attempts": 4,
            "scan_actual_attempts": 4,
            "active_scan_attempted_by_dex": {"uniswap_v3": 2, "aerodrome": 2},
        },
        "scan_attempt_matrix": {
            "0xabc": {
                "uniswap_v3": {"USDC": {"attempted": True, "result": "NO_POOL"}},
                "aerodrome": {"USDC": {"attempted": True, "result": "NO_POOL"}},
            }
        },
        "scan_telemetry": {
            "scan_expected_attempts": 4,
            "scan_actual_attempts": 4,
            "active_scan_attempted_by_dex": {"uniswap_v3": 2, "aerodrome": 2},
        },
    }
    audit = build_coverage_audit(expansion)
    assert audit["blockers"] == []
    assert audit["goal_status"] == "REACHED"
    assert active_scan_coverage_rate(expansion["scan_telemetry"]) == 1.0


def test_acceptance_report_flags_coverage_incomplete():
    report = build_m8_2_acceptance_report(
        sniper={"generated_at_utc": "2026-06-11T10:00:00Z"},
        hints={"generated_at_utc": "2026-06-11T11:00:00Z"},
        expansion={
            "generated_at_utc": "2026-06-11T12:00:00Z",
            "summary": {
                "m8_tokens_in": 5,
                "routes_admitted_count": 10,
                "multi_venue_tokens": 20,
                "verified_second_pool_count": 20,
                "connector_routes_count": 5,
                "subgraph_ready_tokens": 5,
                "dex_ids_checked": ["uniswap_v3"],
            },
        },
        strict=True,
    )
    assert "ACTIVE_SCAN_COVERAGE_INCOMPLETE" in report["blockers"]


def test_active_scan_dry_run_records_matrix():
    cfg = {
        "tokens": {
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
            "WETH": {"address": "0x4200000000000000000000000000000000000006"},
        },
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "aerodrome": {"adapter_type": "ve33", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {"enabled_for_discovery": True, "enabled_for_productive": True},
            "aerodrome": {"enabled_for_discovery": True, "enabled_for_productive": True},
        },
    }
    registry = {
        "tokens": {
            "0xabc0000000000000000000000000000000000001": {
                "symbol": "FOO",
                "venues": {
                    "u::p1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0": "0xabc0000000000000000000000000000000000001",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                    }
                },
            }
        }
    }
    nh = expand_token_neighborhood(
        chain="base",
        config=cfg,
        registry=registry,
        exotic_address="0xabc0000000000000000000000000000000000001",
        exotic_symbol="FOO",
        dry_run=True,
    )
    matrix = nh.get("scan_telemetry", {}).get("scan_attempt_matrix") or {}
    token_row = matrix.get("0xabc0000000000000000000000000000000000001") or {}
    assert "aerodrome" in token_row
    assert token_row["aerodrome"]["USDC"]["result"] == "SKIPPED_DRY_RUN"


@patch("m8.discovery.cross_dex_expand._resolve_via_factory")
def test_active_scan_logs_no_pool(mock_resolve):
    mock_resolve.return_value = (None, "NO_POOL")
    cfg = {
        "tokens": {
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        },
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "aerodrome": {"adapter_type": "ve33", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {"enabled_for_discovery": True, "enabled_for_productive": True},
            "aerodrome": {"enabled_for_discovery": True, "enabled_for_productive": True},
        },
    }
    registry = {
        "tokens": {
            "0xabc0000000000000000000000000000000000001": {
                "symbol": "FOO",
                "venues": {
                    "u::p1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0": "0xabc0000000000000000000000000000000000001",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                    }
                },
            }
        }
    }
    nh = expand_token_neighborhood(
        chain="base",
        config=cfg,
        registry=registry,
        exotic_address="0xabc0000000000000000000000000000000000001",
        exotic_symbol="FOO",
        dry_run=False,
    )
    tel = nh.get("scan_telemetry") or {}
    assert tel.get("active_scan_no_pool_by_dex", {}).get("aerodrome", 0) >= 1
    assert nh.get("reject_reason_histogram", {}).get("ACTIVE_SCAN_NO_POOL", 0) >= 1


def test_merge_scan_telemetry_aggregates():
    a = empty_scan_telemetry()
    b = empty_scan_telemetry()
    record_scan_attempt(
        a,
        token_address="0x1",
        dex_id="uniswap_v3",
        anchor="USDC",
        attempted=True,
        result="NO_POOL",
        reason="NO_POOL",
    )
    record_scan_attempt(
        b,
        token_address="0x2",
        dex_id="aerodrome",
        anchor="USDC",
        attempted=True,
        result="NO_POOL",
        reason="NO_POOL",
    )
    merged = merge_scan_telemetry(a, b)
    assert merged["scan_actual_attempts"] == 2
    assert set(merged["scan_attempt_matrix"].keys()) == {"0x1", "0x2"}
