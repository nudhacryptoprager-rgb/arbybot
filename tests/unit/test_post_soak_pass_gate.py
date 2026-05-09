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
