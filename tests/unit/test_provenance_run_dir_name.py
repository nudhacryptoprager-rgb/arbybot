"""E1.33: Tests for provenance fix — run_dir_name at top-level and in run_context.

Ensures rolling _latest.json and run_summary_latest.json both expose run_dir_name
at top-level and inside run_context, so auditability does not rely on drilling
into inputs.run_dir_name as a hidden fallback.
"""
from __future__ import annotations

import json
from pathlib import Path


def _write_run_summary(run_dir: Path, timestamp: str = "2026-04-17T12:00:00Z") -> Path:
    reports_dir = run_dir / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    run_summary = {
        "schema_version": "m4:run_summary:v2.0",
        "policy_version": "2.0.9",
        "timestamp": timestamp,
        "run_id": run_dir.name,
        "run_kind": "NORMAL",
        "run_context": {
            "run_timestamp": timestamp,
            "code_identity": f"ts:{timestamp}",
            "run_dir_name": run_dir.name,
            "code_sha": None,
            "code_dirty": None,
            "code_desc": None,
            "evidence_sha": None,
        },
        "inputs": {
            "run_mode": "REGISTRY_REAL",
            "run_dir_name": run_dir.name,
            "chain_key": "base",
            "chain_id": 8453,
            "run_kind": "NORMAL",
            "require_cross_dex": False,
            "paper_size_usd": 100,
        },
        "metrics": {
            "signals_count": 0,
            "included_signals_count": 0,
            "excluded_signals_count": 0,
            "total_net_usdc": 0.0,
            "mae_net_usdc": 0.0,
            "est_sign_correct_rate": 0.0,
            "sign_mismatch_count": 0,
            "fragile_count": 0,
            "fragile_rate": 0.0,
            "no_data_reason": "NO_DATA",
            "profit_realism_status": "ONE_LEG_ONLY_DIAGNOSTIC",
            "roundtrip": {"evaluated_count": 0, "profitable_count": 0, "real_quote_count": 0},
        },
        "thresholds": {"threshold_profile_name": "profit"},
        "status": "PASS",
        "reasons": [],
    }
    out = reports_dir / f"run_summary_20260417_120000.json"
    out.write_text(json.dumps(run_summary), encoding="utf-8")
    return out


def test_latest_exposes_top_level_run_dir_name(tmp_path: Path):
    """_latest.json must contain top-level run_dir_name and run_context.run_dir_name."""
    from m4.rolling_store import emit_rolling_artifacts

    run_dir = tmp_path / "ci_m4_test_20260417_120000_abcdef"
    run_dir.mkdir()
    _write_run_summary(run_dir)

    emit_rolling_artifacts(run_dir)

    rolling_dir = tmp_path / "_rolling"
    latest_path = rolling_dir / "_latest.json"
    assert latest_path.exists(), f"_latest.json not emitted: {latest_path}"
    latest = json.loads(latest_path.read_text(encoding="utf-8"))

    # E1.33: top-level run_dir_name must be set, not None
    assert latest.get("run_dir_name") == run_dir.name, (
        f"top-level run_dir_name wrong: {latest.get('run_dir_name')!r}"
    )
    assert latest.get("run_context", {}).get("run_dir_name") == run_dir.name

    # run_summary_latest.json must also expose run_context.run_dir_name
    rs_path = rolling_dir / "run_summary_latest.json"
    rs = json.loads(rs_path.read_text(encoding="utf-8"))
    assert rs.get("run_context", {}).get("run_dir_name") == run_dir.name
