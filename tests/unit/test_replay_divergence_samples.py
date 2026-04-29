"""Unit tests for scripts/replay_divergence_samples.py."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import importlib.util

_spec = importlib.util.spec_from_file_location(
    "replay_divergence_samples", SCRIPTS / "replay_divergence_samples.py"
)
replay_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(replay_mod)  # type: ignore[union-attr]


def _sample(**over):
    base = dict(
        event_id="e0",
        event_tx_hash="0xabc",
        pair="WETH/USDC",
        pool_address="0xpool",
        venue="uniswap_v3",
        fee_tier=500,
        adapter_type="v3",
        direction="buy",
        token_in="WETH",
        token_out="USDC",
        token_in_decimals=18,
        token_out_decimals=6,
        amount_in_wei=10**18,
        scored_net_bps=2424.7584,
        sim_output_wei=10**18,
        sim_input_wei=10**18,
        roundtrip_profit_bps=-9988.876,
        roundtrip_attempted=True,
        roundtrip_success=True,
        size_usd_estimate=2500.0,
        blocker_tag="SCORER_SIM_DIVERGENCE:2424.7584->-9988.8760",
        session_id="s0",
        sample_updated_at="2026-04-29T09:28:56Z",
    )
    base.update(over)
    return base


def test_summarize_empty():
    out = replay_mod.summarize([])
    assert out == {"count": 0}


def test_summarize_with_samples():
    samples = [_sample(), _sample(scored_net_bps=2441.8093, roundtrip_profit_bps=-9988.8592)]
    out = replay_mod.summarize(samples)
    assert out["count"] == 2
    assert out["with_numeric_gap"] == 2
    assert out["gap_min_bps"] > 12000
    assert out["unique_pairs"] == ["WETH/USDC"]
    assert out["fee_tiers"] == [500]
    assert "buy" in out["directions"]


def test_field_audit_complete():
    assert replay_mod.field_audit(_sample()) == []


def test_field_audit_flags_missing():
    s = _sample(amount_in_wei=None, fee_tier=None)
    audit = replay_mod.field_audit(s)
    assert "amount_in_wei" in audit
    assert "fee_tier" in audit


def test_build_manifest_structure():
    m = replay_mod.build_manifest(_sample(), idx=7)
    assert m["replay_index"] == 7
    assert m["scorer_inputs"]["pair"] == "WETH/USDC"
    assert m["scorer_inputs"]["amount_in_wei"] == 10**18
    assert m["sim_observed"]["roundtrip_profit_bps"] < 0
    assert m["scorer_observed_bps"] > 0
    assert m["missing_required_fields"] == []
    assert m["_session"]["session_id"] == "s0"


def test_main_no_samples(tmp_path):
    rollup = tmp_path / "rollup.json"
    rollup.write_text(json.dumps({"scorer_sim_divergence_samples_recent": []}), encoding="utf-8")
    out_dir = tmp_path / "out"
    rc = replay_mod.main.__wrapped__ if hasattr(replay_mod.main, "__wrapped__") else replay_mod.main
    sys_argv_saved = sys.argv
    try:
        sys.argv = ["replay", "--rollup", str(rollup), "--out-dir", str(out_dir), "--quiet"]
        assert replay_mod.main() == 1
    finally:
        sys.argv = sys_argv_saved


def test_main_writes_manifests(tmp_path, capsys):
    rollup = tmp_path / "rollup.json"
    rollup.write_text(json.dumps({
        "scorer_sim_divergence_samples_recent": [_sample(), _sample(event_id="e1")]
    }), encoding="utf-8")
    out_dir = tmp_path / "out"
    sys_argv_saved = sys.argv
    try:
        sys.argv = ["replay", "--rollup", str(rollup), "--out-dir", str(out_dir)]
        assert replay_mod.main() == 0
    finally:
        sys.argv = sys_argv_saved
    files = sorted(out_dir.glob("divergence_replay_*.json"))
    assert len(files) == 2
    m0 = json.loads(files[0].read_text(encoding="utf-8"))
    assert m0["replay_index"] == 0
    assert m0["scorer_inputs"]["pair"] == "WETH/USDC"


def test_main_missing_rollup(tmp_path):
    sys_argv_saved = sys.argv
    try:
        sys.argv = ["replay", "--rollup", str(tmp_path / "missing.json"), "--out-dir", str(tmp_path / "out")]
        assert replay_mod.main() == 2
    finally:
        sys.argv = sys_argv_saved
