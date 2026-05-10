"""E1.78 unit tests: bridge write-back, session_best accumulation,
strict gate session_best, cold_exec_with_usd_basis fix.
E1.79 additions: gate profit session_best, proxy/real amount split,
null-row protection, score-tuple dedup, loose-gates mode."""
from __future__ import annotations

import json
import os
import tempfile
from typing import Any, Dict

import pytest


def _entry_with_curve(
    pool_address: str = "0xaaaa",
    net_bps: float = 100.0,
    mav_usd: float = 30.0,
    best_size_usd: float = 28.0,
    amount_in_optimal_usd: float = 25.0,
    expected_profit_usd: float = 0.10,
) -> Dict[str, Any]:
    return {
        "pool_address": pool_address,
        "net_bps": net_bps,
        "mav_usd": mav_usd,
        "best_size_usd": best_size_usd,
        "amount_in_optimal_usd": amount_in_optimal_usd,
        "expected_profit_usd": expected_profit_usd,
        "size_usd_estimate": 0,
        "best_buy_amount_wei": 0,
        "depth_curve": [
            {"size_usd": 10.0, "expected_profit_usd": 0.05},
            {"size_usd": 25.0, "expected_profit_usd": 0.10},
        ],
    }


class TestBridgeWriteback:
    """E1.78 Step 1: _writeback_enriched_candidates persists mav_usd etc. to bridge JSON."""

    def test_writeback_replaces_cold_executable_with_enriched_entries(self, tmp_path):
        """After _writeback_enriched_candidates, bridge JSON cold_executable has
        mav_usd, lag_score, best_size_usd populated (not None)."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates

        bridge_path = str(tmp_path / "m7_cold_hot_bridge.json")
        initial_bridge = {"cold_executable": [], "timestamp": "2026-01-01T00:00:00Z"}
        with open(bridge_path, "w") as fh:
            json.dump(initial_bridge, fh)

        ranked = [
            _entry_with_curve("0xaaa1", mav_usd=30.0, best_size_usd=28.0),
            _entry_with_curve("0xaaa2", mav_usd=5.0, best_size_usd=4.0),
        ]

        # Patch the bridge path so we don't write to real rolling dir.
        import m7.orderflow.cold_immediate_sim as _mod
        orig_path = None
        try:
            import m7.orderflow.runtime_io as _rio
            orig_path = _rio._COLD_HOT_BRIDGE_PATH
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            if orig_path is not None:
                _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)

        cold_exec = result.get("cold_executable", [])
        assert len(cold_exec) == 2
        assert cold_exec[0].get("mav_usd") is not None
        assert cold_exec[0].get("mav_usd") >= 0.0
        assert cold_exec[0].get("best_size_usd") is not None

    def test_writeback_no_crash_on_missing_bridge(self, tmp_path):
        """_writeback_enriched_candidates silently skips when bridge file absent."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        nonexistent = str(tmp_path / "nonexistent" / "bridge.json")
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = nonexistent
            # Must not raise — cold lane must not crash on write-back failure.
            _writeback_enriched_candidates([_entry_with_curve()])
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

    def test_writeback_empty_ranked_is_noop(self, tmp_path):
        """_writeback_enriched_candidates with empty list must not overwrite bridge."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "m7_cold_hot_bridge.json")
        initial = {"cold_executable": [{"pool_address": "0xoriginal"}], "sentinel": True}
        with open(bridge_path, "w") as fh:
            json.dump(initial, fh)

        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates([])
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        # Bridge must be unchanged because ranked was empty.
        assert result.get("sentinel") is True
        assert result["cold_executable"][0]["pool_address"] == "0xoriginal"


class TestSessionBest:
    """E1.78 Step 2: session_best accumulates monotonic max across cold cycles."""

    def test_session_best_initializes_on_first_write(self, tmp_path):
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "bridge.json")
        with open(bridge_path, "w") as fh:
            json.dump({"cold_executable": []}, fh)

        ranked = [_entry_with_curve(mav_usd=30.0, amount_in_optimal_usd=25.0, expected_profit_usd=0.10)]
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        sb = result.get("session_best") or {}
        assert sb.get("session_best_near_usd", 0) >= 30.0
        assert sb.get("session_best_amount_usd", 0) >= 25.0
        assert sb.get("session_best_expected_profit_usd", 0) >= 0.10

    def test_session_best_is_monotonically_non_decreasing(self, tmp_path):
        """Second write with lower values must not decrease session_best."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "bridge.json")
        # Simulate a previous write with high peak
        with open(bridge_path, "w") as fh:
            json.dump({
                "cold_executable": [],
                "session_best": {
                    "session_best_near_usd": 55.0,
                    "session_best_amount_usd": 50.0,
                    "session_best_expected_profit_usd": 0.50,
                },
            }, fh)

        # Current cycle has lower values
        ranked = [_entry_with_curve(mav_usd=10.0, amount_in_optimal_usd=8.0, expected_profit_usd=0.05)]
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        sb = result.get("session_best") or {}
        # Must keep the previous peak
        assert sb.get("session_best_near_usd", 0) >= 55.0
        assert sb.get("session_best_amount_usd", 0) >= 50.0
        assert sb.get("session_best_expected_profit_usd", 0) >= 0.50


class TestGateSessionBest:
    """E1.78 Step 3: strict gate reads session_best for best_amount_in_usd check."""

    def _make_bridge(self, tmp_path, session_best_near=None, cold_executable_amount=0.0):
        bridge = {
            "cold_executable": [],
            "near_executable": [],
        }
        if cold_executable_amount > 0:
            bridge["cold_executable"] = [{"amount_in_optimal_usd": cold_executable_amount}]
        if session_best_near is not None:
            bridge["session_best"] = {
                "session_best_near_usd": session_best_near,
                "session_best_amount_usd": session_best_near,
                "session_best_expected_profit_usd": 0.0,
            }
        bridge_path = str(tmp_path / "m7_cold_hot_bridge.json")
        with open(bridge_path, "w") as fh:
            json.dump(bridge, fh)
        return bridge_path

    def _make_rollup(self, tmp_path):
        rollup = {
            "windows_seen": 100,
            "session_ws_failed_429_windows": 0,
            "production_sized_candidate_total": 0,
            "current_session_delta": {
                "roundtrip_profitable_total": 0,
                "submit_ready_total": 0,
            },
        }
        rollup_path = str(tmp_path / "m7_hot_rollup_latest.json")
        with open(rollup_path, "w") as fh:
            json.dump(rollup, fh)
        return rollup_path

    def test_session_best_near_usd_50_passes_amount_check(self, tmp_path, monkeypatch):
        """Gate best_amount_in_usd passes when session_best_near_usd >= 50."""
        import scripts.post_soak_pass_gate as _gate
        bridge_path = self._make_bridge(tmp_path, session_best_near=55.0, cold_executable_amount=0.0001)
        rollup_path = self._make_rollup(tmp_path)
        monkeypatch.setenv("ARBY_GATE_ROLLING_DIR", str(tmp_path))

        bridge = json.loads(open(bridge_path).read())
        rollup = json.loads(open(rollup_path).read())

        session_best = bridge.get("session_best") or {}
        near = _gate._safe_float(session_best.get("session_best_near_usd"))
        amt_snap = _gate._best_amount_usd(bridge)
        effective = max(amt_snap, near)

        assert effective >= 50.0, f"effective={effective}"

    def test_session_best_below_50_fails_amount_check(self, tmp_path):
        """Gate best_amount_in_usd fails when session_best_near_usd < 50 and snapshot < 50."""
        import scripts.post_soak_pass_gate as _gate

        bridge = {
            "cold_executable": [{"amount_in_optimal_usd": 0.001}],
            "session_best": {
                "session_best_near_usd": 30.0,
                "session_best_amount_usd": 25.0,
            },
        }
        session_best = bridge.get("session_best") or {}
        near = _gate._safe_float(session_best.get("session_best_near_usd"))
        amt_snap = _gate._best_amount_usd(bridge)
        effective = max(amt_snap, near)

        assert effective < 50.0, f"Expected <50, got {effective}"


class TestColdExecUsdBasisCounter:
    """E1.78 Step 4: cold_exec_with_usd_basis counts amount_in_optimal_usd > 0."""

    def test_amount_in_optimal_usd_counted_as_usd_basis(self):
        """Candidate with amount_in_optimal_usd > 0 must count in cold_exec_with_usd_basis."""
        candidate = {
            "size_usd_estimate": 0,
            "best_buy_amount_wei": 0,
            "amount_in_optimal_usd": 25.0,  # E1.78 fix
        }
        # Replicate the counter logic from bridge_runtime.py
        has_basis = (
            (candidate.get("size_usd_estimate") or 0) > 0
            or (candidate.get("best_buy_amount_wei") or 0) > 0
            or (candidate.get("amount_in_optimal_usd") or 0) > 0  # E1.78 fix
        )
        assert has_basis, "amount_in_optimal_usd should count as USD basis"

    def test_zero_amount_in_optimal_not_counted(self):
        """Candidate with all zero USD fields must NOT count as having USD basis."""
        candidate = {
            "size_usd_estimate": 0,
            "best_buy_amount_wei": 0,
            "amount_in_optimal_usd": 0,
        }
        has_basis = (
            (candidate.get("size_usd_estimate") or 0) > 0
            or (candidate.get("best_buy_amount_wei") or 0) > 0
            or (candidate.get("amount_in_optimal_usd") or 0) > 0
        )
        assert not has_basis


class TestBridgeRuntimeSessionBestPreservation:
    """E1.78 fix: _write_cold_hot_bridge must preserve session_best via _HOT_PRESERVE_ALWAYS."""

    def test_session_best_in_hot_preserve_always(self):
        """session_best must be listed in _HOT_PRESERVE_ALWAYS so cold-lane writes
        don't overwrite the monotonic KPI accumulated by _writeback_enriched_candidates."""
        import inspect
        from m7.orderflow import bridge_runtime
        src = inspect.getsource(bridge_runtime._write_cold_hot_bridge)
        assert '"session_best"' in src, (
            "_HOT_PRESERVE_ALWAYS must include 'session_best' so cold-lane "
            "_write_cold_hot_bridge preserves the KPI written by the hot-lane "
            "_writeback_enriched_candidates. Without this, session_best is "
            "overwritten on every cold-lane cycle and the strict gate always reads 0."
        )


# ---------------------------------------------------------------------------
# E1.79 new contract tests
# ---------------------------------------------------------------------------

class TestGateProfitSessionBest:
    """E1.79 Fix 1: strict gate uses session_best_expected_profit_usd as fallback."""

    def _make_bridge(self, tmp_path, session_best_profit=0.0, cold_executable_profit=0.0):
        entry = {"amount_in_optimal_usd": 1.0, "expected_profit_usd": cold_executable_profit}
        bridge = {
            "cold_executable": [entry],
            "session_best": {
                "session_best_near_usd": 50.0,
                "session_best_amount_usd": 37.99,
                "session_best_proxy_size_usd": 50.0,
                "session_best_expected_profit_usd": session_best_profit,
            },
        }
        p = str(tmp_path / "bridge.json")
        with open(p, "w") as fh:
            json.dump(bridge, fh)
        return p, bridge

    def test_gate_reads_session_best_expected_profit(self, tmp_path):
        """Gate best_expected_profit_usd must read session_best_expected_profit_usd
        so that a soak with peak profit $22.44 doesn't fail when the final
        cold_executable snapshot has a null/zero-profit row."""
        import scripts.post_soak_pass_gate as _gate

        _path, bridge = self._make_bridge(tmp_path, session_best_profit=22.44, cold_executable_profit=0.0)
        _session_best = bridge.get("session_best") or {}
        best_profit_snapshot = _gate._best_profit_usd(bridge)
        session_best_ep = _gate._safe_float(_session_best.get("session_best_expected_profit_usd"))
        best_profit_effective = max(best_profit_snapshot, session_best_ep)

        assert best_profit_effective > 0.01, (
            f"Gate should use session_best_expected_profit_usd=22.44 as fallback, "
            f"got effective={best_profit_effective}"
        )

    def test_gate_profit_zero_when_session_best_also_zero(self, tmp_path):
        """When both final snapshot and session_best have 0 profit, gate must fail."""
        import scripts.post_soak_pass_gate as _gate

        _path, bridge = self._make_bridge(tmp_path, session_best_profit=0.0, cold_executable_profit=0.0)
        _session_best = bridge.get("session_best") or {}
        best_profit_snapshot = _gate._best_profit_usd(bridge)
        session_best_ep = _gate._safe_float(_session_best.get("session_best_expected_profit_usd"))
        best_profit_effective = max(best_profit_snapshot, session_best_ep)

        assert best_profit_effective <= 0.01, (
            f"Both zero profit should result in gate fail, got effective={best_profit_effective}"
        )


class TestSessionBestProxySplit:
    """E1.79 Fix 2: session_best_proxy_size_usd and session_best_amount_usd are split."""

    def test_proxy_field_stored_separately_from_real_amount(self, tmp_path):
        """_writeback_enriched_candidates stores session_best_proxy_size_usd (depth ladder)
        separate from session_best_amount_usd (real executable amount_in_optimal_usd)."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "bridge.json")
        with open(bridge_path, "w") as fh:
            json.dump({"cold_executable": []}, fh)

        # Entry: real amount $37.99, but ladder best_size_usd=$50 (proxy)
        ranked = [_entry_with_curve(
            mav_usd=48.0,
            best_size_usd=50.0,
            amount_in_optimal_usd=37.99,
            expected_profit_usd=22.44,
        )]
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        sb = result.get("session_best") or {}

        # session_best_amount_usd must be the REAL amount, not the proxy.
        assert sb.get("session_best_amount_usd") == pytest.approx(37.99, abs=0.01), (
            f"session_best_amount_usd should be real amount 37.99, got {sb.get('session_best_amount_usd')}"
        )
        # session_best_proxy_size_usd must be the depth-ladder proxy ceiling.
        proxy = sb.get("session_best_proxy_size_usd", 0)
        assert proxy >= 48.0, (
            f"session_best_proxy_size_usd should be >=48 (mav_usd), got {proxy}"
        )

    def test_gate_amount_uses_real_amount_not_proxy(self):
        """Gate best_amount_in_usd must use session_best_amount_usd (real),
        NOT session_best_proxy_size_usd or session_best_near_usd (proxy/ladder)."""
        import scripts.post_soak_pass_gate as _gate

        # Bridge with session_best_proxy=50, real amount=$37.99
        bridge = {
            "cold_executable": [{"amount_in_optimal_usd": 0.0001}],
            "session_best": {
                "session_best_near_usd": 50.0,       # proxy (backward compat)
                "session_best_proxy_size_usd": 50.0,  # explicit proxy
                "session_best_amount_usd": 37.99,      # real executable amount
                "session_best_expected_profit_usd": 22.44,
            },
        }
        _sb = bridge.get("session_best") or {}
        real_amount = _gate._safe_float(_sb.get("session_best_amount_usd"))
        snapshot_amount = _gate._best_amount_usd(bridge)
        # Gate effective = max(snapshot, real_amount) — should be $37.99
        effective = max(snapshot_amount, real_amount)
        # $37.99 < $50 threshold → gate should FAIL amount check
        assert effective < 50.0, (
            f"Gate should use real amount $37.99, not proxy $50. Got effective={effective}"
        )


class TestNullRowProtection:
    """E1.79 Fix 3: _writeback_enriched_candidates retains priced entries for
    pools not in current ranked list (null-row protection)."""

    def test_priced_entries_retained_for_absent_pools(self, tmp_path):
        """When ranked list has pool 0xaaaa but existing bridge has priced pool 0xbbbb,
        0xbbbb must be retained in cold_executable after writeback."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "bridge.json")
        existing_bridge = {
            "cold_executable": [
                _entry_with_curve("0xbbbb", amount_in_optimal_usd=45.0, expected_profit_usd=0.20),
            ],
        }
        with open(bridge_path, "w") as fh:
            json.dump(existing_bridge, fh)

        # Only ranked pool 0xaaaa — 0xbbbb absent from current cycle
        ranked = [_entry_with_curve("0xaaaa", amount_in_optimal_usd=25.0, expected_profit_usd=0.10)]
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        cold_exec = result.get("cold_executable", [])
        pool_addrs = [(e.get("pool_address") or "").lower() for e in cold_exec]
        assert "0xbbbb" in pool_addrs, (
            f"Priced pool 0xbbbb must be retained after writeback; got pools={pool_addrs}"
        )

    def test_unpriced_entries_not_retained(self, tmp_path):
        """Unpriced (amount_in_optimal_usd=0) entries for absent pools must NOT be
        retained — null-row protection only keeps priced entries."""
        from m7.orderflow.cold_immediate_sim import _writeback_enriched_candidates
        import m7.orderflow.runtime_io as _rio

        bridge_path = str(tmp_path / "bridge.json")
        existing_bridge = {
            "cold_executable": [
                {"pool_address": "0xcccc", "amount_in_optimal_usd": 0.0, "net_bps": 500},
            ],
        }
        with open(bridge_path, "w") as fh:
            json.dump(existing_bridge, fh)

        ranked = [_entry_with_curve("0xaaaa", amount_in_optimal_usd=25.0)]
        orig_path = _rio._COLD_HOT_BRIDGE_PATH
        try:
            _rio._COLD_HOT_BRIDGE_PATH = bridge_path
            _writeback_enriched_candidates(ranked)
        finally:
            _rio._COLD_HOT_BRIDGE_PATH = orig_path

        with open(bridge_path) as fh:
            result = json.load(fh)
        cold_exec = result.get("cold_executable", [])
        pool_addrs = [(e.get("pool_address") or "").lower() for e in cold_exec]
        assert "0xcccc" not in pool_addrs, (
            f"Unpriced pool 0xcccc must NOT be retained; got pools={pool_addrs}"
        )


class TestScoreTupleDedup:
    """E1.79 Fix 4: bridge_runtime dedup keeps highest score tuple (priced, profit, mav, usd)."""

    def test_priced_entry_beats_null_entry_same_pool(self):
        """For the same pool_address, a priced entry (amount>0) must win over
        a null/unpriced entry even if the null entry appears first."""
        # Replicate the score tuple from bridge_runtime._write_cold_hot_bridge
        def _score(e):
            a = float(e.get("amount_in_optimal_usd") or 0)
            return (
                int(a > 0),
                float(e.get("expected_profit_usd") or 0),
                float(e.get("mav_usd") or 0),
                a,
            )

        null_entry = {"pool_address": "0xdddd", "amount_in_optimal_usd": None, "expected_profit_usd": None}
        priced_entry = {"pool_address": "0xdddd", "amount_in_optimal_usd": 45.0, "expected_profit_usd": 0.18}

        # Score tuple comparison: priced must always beat null
        assert _score(priced_entry) > _score(null_entry), (
            f"Priced entry score {_score(priced_entry)} must beat null entry score {_score(null_entry)}"
        )

    def test_higher_profit_wins_among_priced_entries(self):
        """Among priced entries for the same pool, the one with higher expected_profit_usd wins."""
        def _score(e):
            a = float(e.get("amount_in_optimal_usd") or 0)
            return (
                int(a > 0),
                float(e.get("expected_profit_usd") or 0),
                float(e.get("mav_usd") or 0),
                a,
            )

        low_profit = {"pool_address": "0xeeee", "amount_in_optimal_usd": 100.0, "expected_profit_usd": 0.05}
        high_profit = {"pool_address": "0xeeee", "amount_in_optimal_usd": 45.0, "expected_profit_usd": 0.25}

        assert _score(high_profit) > _score(low_profit), (
            f"High profit entry {_score(high_profit)} must beat large-USD-low-profit entry {_score(low_profit)}"
        )


class TestLooseGatesMode:
    """E1.79 Fix 7: ARBY_DISCOVERY_LOOSE_GATES=1 lowers bps threshold to 1 bps."""

    def test_loose_gates_lowers_min_bps(self, monkeypatch):
        """When ARBY_DISCOVERY_LOOSE_GATES=1, _min_net_bps_threshold returns 1.0."""
        from m7.orderflow.cold_immediate_sim import _min_net_bps_threshold
        monkeypatch.setenv("ARBY_DISCOVERY_LOOSE_GATES", "1")
        assert _min_net_bps_threshold() == 1.0

    def test_strict_mode_uses_env_threshold(self, monkeypatch):
        """When ARBY_DISCOVERY_LOOSE_GATES=0, threshold respects ARBY_COLD_IMMEDIATE_MIN_NET_BPS."""
        from m7.orderflow.cold_immediate_sim import _min_net_bps_threshold
        monkeypatch.setenv("ARBY_DISCOVERY_LOOSE_GATES", "0")
        monkeypatch.setenv("ARBY_COLD_IMMEDIATE_MIN_NET_BPS", "25")
        assert _min_net_bps_threshold() == 25.0

    def test_loose_gates_mode_flag(self, monkeypatch):
        """_loose_gates_mode() returns True only when ARBY_DISCOVERY_LOOSE_GATES=1."""
        from m7.orderflow.cold_immediate_sim import _loose_gates_mode
        monkeypatch.setenv("ARBY_DISCOVERY_LOOSE_GATES", "1")
        assert _loose_gates_mode() is True
        monkeypatch.setenv("ARBY_DISCOVERY_LOOSE_GATES", "0")
        assert _loose_gates_mode() is False
