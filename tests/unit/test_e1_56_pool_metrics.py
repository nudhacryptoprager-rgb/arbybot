"""E1.56 — pool-level visibility metrics in hot_gap_debug.

Verifies Step 6 of the E1.55-followup work-track:
  - cold_positive_pools_count: distinct pool addresses cold lane reported
    as profitable in current bridge.
  - cold_positive_pool_seen_in_hot_count: of those, how many actually hit
    the hot WS event stream this window.
  - pool_address_mismatch_count: hot events on pool addresses that share
    token-pair (family) with a cold-positive entry but the exact pool
    address differs (different fee tier / factory / version).

These exist to surface STRATEGY_GATING blocker: cold lane finds
profitable pools, but hot WS event stream is dominated by other pools
with thin spreads, so hot has no chance to attempt sim regardless of
code correctness.
"""
from __future__ import annotations

import inspect


def test_e1_56_pool_metrics_present_in_writer() -> None:
    """The new pool-level metrics must be emitted by `_write_hot_artifact`."""
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    source = inspect.getsource(_write_hot_artifact)
    assert "cold_positive_pools_count" in source
    assert "cold_positive_pool_seen_in_hot_count" in source
    assert "pool_address_mismatch_count" in source


def test_e1_56_pool_metrics_zero_when_bridge_empty(tmp_path, monkeypatch) -> None:
    """With empty bridge cold_executable, all three counters must be 0."""
    import m7.orderflow.runtime_io as rio
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    # Redirect artifact writes into tmp_path
    monkeypatch.setattr(rio, "_HOT_ARTIFACT_PATH", str(tmp_path / "m7_hot_latest.json"))
    monkeypatch.setattr(rio, "_HOT_ROLLUP_PATH", str(tmp_path / "m7_hot_rollup_latest.json"))

    artifact = {
        "events_count": 0,
        "_raw_results": [],
        "results": [],
        "viable_count": 0,
        "best_net_bps_clean": 0,
    }
    bridge_diag = {
        "_bridge_cold_executable": [],
        "_bridge_pool_addrs_set": set(),
    }
    _write_hot_artifact(
        artifact, iteration=1,
        bridge_diagnostics=bridge_diag,
        chain="base", profile="production",
    )
    import json
    with open(rio._HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    hgd = payload["hot_gap_debug"]
    assert hgd["cold_positive_pools_count"] == 0
    assert hgd["cold_positive_pool_seen_in_hot_count"] == 0
    assert hgd["pool_address_mismatch_count"] == 0


def test_e1_56_cold_positive_pools_count_distinct(tmp_path, monkeypatch) -> None:
    """Distinct pool addresses in cold_executable are counted exactly once."""
    import m7.orderflow.runtime_io as rio
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    monkeypatch.setattr(rio, "_HOT_ARTIFACT_PATH", str(tmp_path / "m7_hot_latest.json"))
    monkeypatch.setattr(rio, "_HOT_ROLLUP_PATH", str(tmp_path / "m7_hot_rollup_latest.json"))

    artifact = {
        "events_count": 0,
        "_raw_results": [],
        "results": [],
        "viable_count": 0,
        "best_net_bps_clean": 0,
    }
    # Bridge with 4 cold_executable entries on 2 distinct pool addresses
    cold_exec = [
        {"pool_address": "0xPOOLA", "token_in": "0xtokA", "token_out": "0xtokB"},
        {"pool_address": "0xpoola", "token_in": "0xtokA", "token_out": "0xtokB"},
        {"pool_address": "0xPOOLB", "token_in": "0xtokC", "token_out": "0xtokD"},
        {"pool_address": "", "token_in": "0xtokE", "token_out": "0xtokF"},  # ignored
    ]
    bridge_diag = {
        "_bridge_cold_executable": cold_exec,
        "_bridge_pool_addrs_set": set(),
    }
    _write_hot_artifact(
        artifact, iteration=1,
        bridge_diagnostics=bridge_diag,
        chain="base", profile="production",
    )
    import json
    with open(rio._HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    hgd = payload["hot_gap_debug"]
    # 0xpoola and 0xpoolb after lowercase normalization
    assert hgd["cold_positive_pools_count"] == 2
    assert hgd["cold_positive_pool_seen_in_hot_count"] == 0
    assert hgd["pool_address_mismatch_count"] == 0


def test_e1_56_cold_positive_pool_seen_in_hot(tmp_path, monkeypatch) -> None:
    """Hot event on a cold-positive pool address increments seen_in_hot."""
    import m7.orderflow.runtime_io as rio
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    monkeypatch.setattr(rio, "_HOT_ARTIFACT_PATH", str(tmp_path / "m7_hot_latest.json"))
    monkeypatch.setattr(rio, "_HOT_ROLLUP_PATH", str(tmp_path / "m7_hot_rollup_latest.json"))

    class _Evt:
        def __init__(self, pa: str, t0: str = "", t1: str = "") -> None:
            self.pool_address = pa
            self.token0 = t0
            self.token1 = t1

    class _Res:
        def __init__(self, evt: _Evt) -> None:
            self._source_event = evt
            self.scoring_path = "registry_fast"
            self.best_backrun_net_bps = -2.15
            self.size_valid_for_token = True
            self.reject_reason = "REJECT_GAS_EXCEEDS_GROSS"

    raw = [
        _Res(_Evt("0xPOOLA", "0xtokA", "0xtokB")),  # in cold_positive set
        _Res(_Evt("0xPOOLA", "0xtokA", "0xtokB")),  # second event on same pool
        _Res(_Evt("0xOTHER", "0xtokE", "0xtokF")),  # unrelated pool
    ]
    artifact = {
        "events_count": 3,
        "_raw_results": raw,
        "results": raw,
        "viable_count": 0,
        "best_net_bps_clean": 0,
    }
    bridge_diag = {
        "_bridge_cold_executable": [
            {"pool_address": "0xpoola", "token_in": "0xtoka", "token_out": "0xtokb"},
        ],
        "_bridge_pool_addrs_set": set(),
    }
    _write_hot_artifact(
        artifact, iteration=1,
        bridge_diagnostics=bridge_diag,
        chain="base", profile="production",
    )
    import json
    with open(rio._HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    hgd = payload["hot_gap_debug"]
    assert hgd["cold_positive_pools_count"] == 1
    # _Distinct_ pool addresses seen in hot, not event count
    assert hgd["cold_positive_pool_seen_in_hot_count"] == 1
    assert hgd["pool_address_mismatch_count"] == 0


def test_e1_56_pool_address_mismatch(tmp_path, monkeypatch) -> None:
    """Hot event on different pool address but same family → mismatch."""
    import m7.orderflow.runtime_io as rio
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    monkeypatch.setattr(rio, "_HOT_ARTIFACT_PATH", str(tmp_path / "m7_hot_latest.json"))
    monkeypatch.setattr(rio, "_HOT_ROLLUP_PATH", str(tmp_path / "m7_hot_rollup_latest.json"))

    class _Evt:
        def __init__(self, pa: str, t0: str = "", t1: str = "") -> None:
            self.pool_address = pa
            self.token0 = t0
            self.token1 = t1

    class _Res:
        def __init__(self, evt: _Evt) -> None:
            self._source_event = evt
            self.scoring_path = "registry_fast"
            self.best_backrun_net_bps = 0.0
            self.size_valid_for_token = True
            self.reject_reason = None

    # Cold positive: pool=0xCOLDPOOL on family (0xtokX, 0xtokY)
    # Hot event: pool=0xHOTPOOL on SAME family (0xtokY, 0xtokX swapped)
    raw = [_Res(_Evt("0xHOTPOOL", "0xTOKY", "0xTOKX"))]
    artifact = {
        "events_count": 1,
        "_raw_results": raw,
        "results": raw,
        "viable_count": 0,
        "best_net_bps_clean": 0,
    }
    bridge_diag = {
        "_bridge_cold_executable": [
            {"pool_address": "0xcoldpool", "token_in": "0xtokx", "token_out": "0xtoky"},
        ],
        "_bridge_pool_addrs_set": set(),
    }
    _write_hot_artifact(
        artifact, iteration=1,
        bridge_diagnostics=bridge_diag,
        chain="base", profile="production",
    )
    import json
    with open(rio._HOT_ARTIFACT_PATH, "r", encoding="utf-8") as f:
        payload = json.load(f)
    hgd = payload["hot_gap_debug"]
    assert hgd["cold_positive_pools_count"] == 1
    assert hgd["cold_positive_pool_seen_in_hot_count"] == 0
    assert hgd["pool_address_mismatch_count"] == 1
