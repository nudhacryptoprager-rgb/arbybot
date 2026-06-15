"""Diagnostic quarantine mode policy tests."""
from __future__ import annotations

import os
from datetime import datetime, timezone

from m9.graph_arb.artifacts import validate_scan_scope_telemetry
from m9.graph_arb.diagnostic_quarantine import (
    build_quarantine_plan,
    evaluate_quarantine_ab_pass,
    filter_revert_pools_with_ttl,
    get_diagnostic_quarantine_mode,
    resolve_diagnostic_quarantine_pools_fresh,
)


def test_diagnostic_soft_tags_feedback_not_hard(monkeypatch):
    monkeypatch.setenv("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", "diagnostic_soft")
    plan = build_quarantine_plan(
        depth_hard_pools={"0xdepth"},
        revert_data={
            "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            "routes": [
                {
                    "pool_address": "0xrevert",
                    "reject_reason": "QUOTE_REVERT",
                }
            ],
        },
        phantom_data={
            "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            "pools": [{"pool_address": "0xphantom"}],
        },
    )
    assert plan.mode == "diagnostic_soft"
    assert "0xdepth" in plan.hard_exclude
    assert "0xrevert" in plan.soft_tag
    assert "0xphantom" in plan.soft_tag
    assert "0xrevert" not in plan.hard_exclude


def test_production_mode_hard_excludes_feedback(monkeypatch):
    monkeypatch.setenv("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", "production")
    plan = build_quarantine_plan(
        depth_hard_pools=set(),
        revert_data={
            "updated_at_utc": datetime.now(tz=timezone.utc).isoformat(),
            "routes": [{"pool_address": "0xrevert", "reject_reason": "QUOTE_REVERT"}],
        },
    )
    assert "0xrevert" in plan.hard_exclude


def test_revert_ttl_expired_softens_non_permanent(monkeypatch):
    monkeypatch.setenv("ARBY_M9_QUARANTINE_TTL_HOURS", "1")
    old = datetime.now(tz=timezone.utc).replace(year=2020).isoformat()
    hard, soft, expired = filter_revert_pools_with_ttl(
        {
            "updated_at_utc": old,
            "routes": [
                {"pool_address": "0xperm", "quarantine_reason": "BALANCER_PAUSED"},
                {"pool_address": "0xrev", "reject_reason": "QUOTE_REVERT"},
            ],
        }
    )
    assert expired is True
    assert "0xperm" in hard
    assert "0xrev" in soft


def test_production_ttl_expired_softens_non_permanent_in_plan(monkeypatch):
    monkeypatch.setenv("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", "production")
    monkeypatch.setenv("ARBY_M9_QUARANTINE_TTL_HOURS", "1")
    old = datetime.now(tz=timezone.utc).replace(year=2020).isoformat()
    plan = build_quarantine_plan(
        depth_hard_pools=set(),
        revert_data={
            "updated_at_utc": old,
            "routes": [
                {"pool_address": "0xperm", "quarantine_reason": "BALANCER_PAUSED"},
                {"pool_address": "0xrev", "reject_reason": "QUOTE_REVERT"},
            ],
        },
        phantom_data={
            "updated_at_utc": old,
            "pools": [{"pool_address": "0xphantom"}],
        },
    )
    assert plan.breakdown["revert"]["ttl_expired"] is True
    assert "0xperm" in plan.hard_exclude
    assert "0xrev" not in plan.hard_exclude
    assert "0xphantom" not in plan.hard_exclude
    assert plan.breakdown["revert"].get("softened_by_ttl") == 1
    assert plan.breakdown["phantom"].get("softened_by_ttl") == 1


def test_phantom_ttl_expired_softens_non_permanent(monkeypatch):
    monkeypatch.setenv("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", "production")
    monkeypatch.setenv("ARBY_M9_QUARANTINE_TTL_HOURS", "1")
    old = datetime.now(tz=timezone.utc).replace(year=2020).isoformat()
    plan = build_quarantine_plan(
        depth_hard_pools=set(),
        phantom_data={
            "updated_at_utc": old,
            "pools": [
                {"pool_address": "0xphantom", "quarantine_reason": "PHANTOM_QUOTE_BPS_OVERFLOW"},
                {"pool_address": "0xperm", "quarantine_reason": "BALANCER_PAUSED"},
            ],
        },
    )
    assert plan.breakdown["phantom"]["ttl_expired"] is True
    assert "0xperm" in plan.hard_exclude
    assert "0xphantom" not in plan.hard_exclude
    assert plan.breakdown["phantom"].get("softened_by_ttl") == 1


def test_stale_diagnostic_ignored():
    pools, stale = resolve_diagnostic_quarantine_pools_fresh(
        {
            "run_timestamp": "2020-01-01T00:00:00Z",
            "rows": [{"ok": False, "reject_reason": "QUOTE_REVERT", "pool_address": "0xold"}],
        },
        max_age_hours=1.0,
    )
    assert stale is True
    assert pools == set()


def test_mode_default_production(monkeypatch):
    monkeypatch.delenv("ARBY_M9_DIAGNOSTIC_QUARANTINE_MODE", raising=False)
    assert get_diagnostic_quarantine_mode() == "production"


def test_productive_artifact_requires_scan_scope_telemetry():
    incomplete = {"scan_scope": {"pool_quality_lane": "productive"}}
    result = validate_scan_scope_telemetry(incomplete)
    assert result["valid"] is False
    assert "quarantine_exclusion_breakdown" in result["missing"]
    complete = {
        "scan_scope": {
            "pool_quality_lane": "productive",
            "quarantine_exclusion_breakdown": {"mode": "production"},
            "productive_admission_skip_histogram": {},
            "cycles_before_quarantine": 0,
            "cycles_after_quarantine": 0,
            "graph_build_metrics": {},
        }
    }
    assert validate_scan_scope_telemetry(complete)["valid"] is True


def test_ab_pass_when_diagnostic_soft_restores_topology():
    prod = {
        "cycles_found": 0,
        "scan_scope": {
            "diagnostic_quarantine_mode": "production",
            "cycles_after_quarantine": 0,
            "quarantine_exclusion_breakdown": {"revert": {"count": 5, "permanent": 1}},
        },
    }
    diag = {
        "cycles_found": 12,
        "scan_scope": {
            "diagnostic_quarantine_mode": "diagnostic_soft",
            "cycles_after_quarantine": 12,
        },
    }
    result = evaluate_quarantine_ab_pass(prod, diag)
    assert result["status"] == "PASS"
    assert result["cycles_delta"] == 12
