"""Unit tests for M8.2 candidate DEX registry."""
from __future__ import annotations

from m8.discovery.candidate_dex_registry import (
    build_candidate_coverage_audit,
    build_radar_metrics,
    build_registry_summary,
    candidate_dex_rows_for_scan,
    load_candidate_dex_registry,
)
from m8.discovery.scan_telemetry import (
    empty_candidate_scan_telemetry,
    record_candidate_scan_attempt,
)


def test_load_candidate_registry_has_p0_entries():
    reg = load_candidate_dex_registry()
    entries = reg.get("candidates") or {}
    assert "iziswap_base" in entries
    assert entries["iziswap_base"]["registry_status"] == "configured"
    assert entries["hydrex"]["registry_status"] == "hint_only"


def test_candidate_rows_for_scan_merges_config_factory():
    reg = load_candidate_dex_registry()
    config = {
        "dexes": {
            "iziswap_base": {
                "adapter_type": "iziswap",
                "factory": "0x8c7d3063579bdb0b90997e18a770eae32e1ebb08",
            }
        }
    }
    rows = candidate_dex_rows_for_scan(reg, config)
    izi = next(r for r in rows if r["dex_id"] == "iziswap_base")
    assert izi["factory"]
    assert izi["registry_status"] == "configured"


def test_candidate_coverage_audit_passes_with_matrix():
    reg = load_candidate_dex_registry()
    telemetry = empty_candidate_scan_telemetry()
    for dex_id, meta in (reg.get("candidates") or {}).items():
        status = str(meta.get("registry_status") or "unsupported")
        if status in ("configured", "verified"):
            reason, result = "NO_POOL", "NO_POOL"
        else:
            reason = str(meta.get("unsupported_reason") or "UNSUPPORTED_HINT_ONLY")
            result = "UNSUPPORTED_DEX"
        record_candidate_scan_attempt(
            telemetry,
            token_address="0xabc",
            dex_id=dex_id,
            anchor="USDC",
            registry_status=status,
            attempted=True,
            result=result,
            reason=reason,
        )
    expansion = {
        "summary": {"tokens_in": 1, "m8_tokens_in": 1},
        "candidate_scan_telemetry": telemetry,
        "candidate_dex_attempt_matrix": telemetry["candidate_dex_attempt_matrix"],
    }
    audit = build_candidate_coverage_audit(expansion, reg)
    assert audit["blockers"] == []
    assert audit["goal_status"] == "REACHED"
    assert audit["candidate_scan_attempted_by_anchor"]["USDC"] >= 9


def test_radar_metrics_truth_status():
    hints = {
        "metrics": {
            "hint_status_counts": {"HINT_STALE": 10, "HINT_ONCHAIN_VERIFIED": 2},
            "per_source_verified_yield": {"dexscreener": 2},
            "hint_source_pool_counts": {"dexscreener": 12},
        }
    }
    radar = build_radar_metrics(hints)
    assert radar["stale_hint_rate"] > 0
    assert radar["truth_status"] == "STALE_HINT_RISK"
    assert "dexscreener" in radar["mirror_source_yield_by_provider"]


def test_registry_summary_counts():
    reg = load_candidate_dex_registry()
    summary = build_registry_summary(reg)
    assert summary["candidate_dexes_seen"] >= 9
    assert summary["candidate_dexes_configured"] >= 4
