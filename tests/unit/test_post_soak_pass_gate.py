from __future__ import annotations

import importlib.util
import json
from pathlib import Path


def _load_gate_module():
    path = Path(__file__).resolve().parents[2] / "scripts" / "post_soak_pass_gate.py"
    spec = importlib.util.spec_from_file_location("post_soak_pass_gate", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _write_json(path: Path, data: dict) -> None:
    path.write_text(json.dumps(data), encoding="utf-8")


def _passing_bridge() -> dict:
    return {
        "production_sized_candidate_total": 1,
        "cold_executable": [
            {
                "amount_in_optimal_usd": 50.0,
                "expected_profit_usd": 0.02,
            }
        ],
    }


def test_post_soak_gate_does_not_use_lifetime_submit_ready(tmp_path, monkeypatch, capsys):
    gate = _load_gate_module()
    _write_json(tmp_path / "m7_cold_hot_bridge.json", _passing_bridge())
    _write_json(
        tmp_path / "m7_hot_rollup_latest.json",
        {
            "submit_ready_total": 33,
            "roundtrip_profitable_total": 24,
            "current_session_delta": {
                "submit_ready_total": 0,
                "roundtrip_profitable_total": 1,
            },
            "ws_provider_health": {"subscribe_attempts": 10, "ws_429_count": 0},
        },
    )

    monkeypatch.setenv("ARBY_GATE_ROLLING_DIR", str(tmp_path))

    assert gate.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["submit_ready_delta"]["value"] == 0
    assert report["checks"]["submit_ready_delta"]["pass"] is False


def test_post_soak_gate_passes_with_fresh_session_deltas(tmp_path, monkeypatch):
    gate = _load_gate_module()
    _write_json(tmp_path / "m7_cold_hot_bridge.json", _passing_bridge())
    _write_json(
        tmp_path / "m7_hot_rollup_latest.json",
        {
            "current_session_delta": {
                "submit_ready_total": 1,
                "roundtrip_profitable_total": 1,
            },
            "ws_provider_health": {"subscribe_attempts": 10, "ws_429_count": 0},
        },
    )

    monkeypatch.setenv("ARBY_GATE_ROLLING_DIR", str(tmp_path))

    assert gate.main() == 0


def test_post_soak_gate_reads_ws_provider_health_rate(tmp_path, monkeypatch, capsys):
    gate = _load_gate_module()
    _write_json(tmp_path / "m7_cold_hot_bridge.json", _passing_bridge())
    _write_json(
        tmp_path / "m7_hot_rollup_latest.json",
        {
            "current_session_delta": {
                "submit_ready_total": 1,
                "roundtrip_profitable_total": 1,
            },
            "ws_provider_health": {"subscribe_attempts": 10, "ws_429_count": 4},
        },
    )

    monkeypatch.setenv("ARBY_GATE_ROLLING_DIR", str(tmp_path))

    assert gate.main() == 1
    report = json.loads(capsys.readouterr().out)
    assert report["checks"]["ws_429_rate"]["value"] == 0.4
    assert report["checks"]["ws_429_rate"]["pass"] is False


# E1.83 Step 4: factory_enriched_guard tests
def test_factory_enriched_guard_pass_when_enriched(tmp_path, monkeypatch):
    gate = _load_gate_module()
    bridge = _passing_bridge()
    bridge["factory_truth_loaded"] = True
    bridge["factory_enriched_pairs"] = 5
    bridge["factory_truth_age_s"] = 900.0
    result = gate._build_factory_enriched_check(bridge)
    assert result["pass"] is True
    assert result["factory_enriched_pairs"] == 5
    assert result["informational"] is True


def test_factory_enriched_guard_fail_when_loaded_but_zero(tmp_path, monkeypatch):
    gate = _load_gate_module()
    bridge = _passing_bridge()
    bridge["factory_truth_loaded"] = True
    bridge["factory_enriched_pairs"] = 0
    bridge["factory_truth_age_s"] = 900.0
    result = gate._build_factory_enriched_check(bridge)
    assert result["pass"] is False
    assert "wiring regression" in result["reason"]


def test_factory_enriched_guard_pass_when_not_loaded(tmp_path, monkeypatch):
    gate = _load_gate_module()
    bridge = _passing_bridge()
    # factory_truth_loaded absent (artifact missing)
    result = gate._build_factory_enriched_check(bridge)
    assert result["pass"] is True
    assert result["factory_truth_loaded"] is False


# E1.83 fix steps 2-5+7: micro_tier_gate tests
def test_micro_tier_gate_pass_when_profitable_candidate():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    # Candidate at $20, profit $0.30 >> required ($0.05 or 3x fee~$0.04)
    bridge["cold_executable"] = [
        {"amount_in_optimal_usd": 20.0, "expected_profit_usd": 0.30, "gas_usd": 0.003}
    ]
    result = gate._build_micro_tier_check(bridge, micro_min_usd=5.0, micro_max_usd=50.0)
    assert result["micro_candidate_count"] == 1
    assert result["micro_viable_count"] == 1
    assert result["pass"] is True
    assert result["informational"] is True
    # profit_after_all_costs_usd must be present in candidates
    assert "profit_after_all_costs_usd" in result["candidates"][0]


def test_micro_tier_gate_fail_when_profit_below_3x_fee():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    # profit $0.01 < required $0.05 (min floor)
    bridge["cold_executable"] = [
        {"amount_in_optimal_usd": 15.0, "expected_profit_usd": 0.01, "gas_usd": 0.003}
    ]
    result = gate._build_micro_tier_check(bridge, micro_min_usd=5.0, micro_max_usd=50.0)
    assert result["micro_candidate_count"] == 1
    assert result["micro_viable_count"] == 0
    assert result["pass"] is False


def test_micro_tier_gate_empty_when_no_micro_candidates():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    # $60 candidate is above micro range
    bridge["cold_executable"] = [
        {"amount_in_optimal_usd": 60.0, "expected_profit_usd": 0.50, "gas_usd": 0.005}
    ]
    result = gate._build_micro_tier_check(bridge, micro_min_usd=5.0, micro_max_usd=50.0)
    assert result["micro_candidate_count"] == 0
    assert result["pass"] is False


def test_micro_tier_gate_fee_model_exposed():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    result = gate._build_micro_tier_check(bridge)
    # Fee model fields must always be present
    assert "l1_fee_usd_approx" in result["micro_fee_model"]
    assert "eth_price_usd" in result["micro_fee_model"]
    assert result["micro_fee_model"]["eth_price_usd"] > 0


# E1.83 fix #2/#6: factory_enriched_guard strict mode tests
def test_factory_enriched_guard_strict_fail_when_not_loaded():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    # factory truth absent
    result = gate._build_factory_enriched_check(bridge, strict=True)
    assert result["pass"] is False
    assert result["informational"] is False
    assert "factory_truth_not_loaded" in result["reason"]


def test_factory_enriched_guard_strict_fail_when_loaded_but_zero():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    bridge["factory_truth_loaded"] = True
    bridge["factory_enriched_pairs"] = 0
    result = gate._build_factory_enriched_check(bridge, strict=True)
    assert result["pass"] is False
    assert result["informational"] is False
    assert "wiring regression" in result["reason"]


def test_factory_enriched_guard_strict_pass_when_enriched():
    gate = _load_gate_module()
    bridge = _passing_bridge()
    bridge["factory_truth_loaded"] = True
    bridge["factory_enriched_pairs"] = 7
    result = gate._build_factory_enriched_check(bridge, strict=True)
    assert result["pass"] is True
    assert result["informational"] is False
