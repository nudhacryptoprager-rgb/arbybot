"""
M7.E1.9 — Tests for discovery/production lane split.

Validates:
1. Discovery prewarm pairs: wider contour including DEGEN, BRETT, AMONGUS
2. Profile-aware get_prewarm_pairs dispatch
3. Backward compatibility: production profile unchanged
4. Discovery constants: graduation thresholds, valid profiles
5. Discovery scoreboard update logic
"""
from __future__ import annotations

import pytest

from m7.shared.constants import (
    PREWARM_PAIRS_BASE,
    PREWARM_PAIRS_BASE_DISCOVERY,
    PREWARM_PAIRS_ARBITRUM,
    VALID_PROFILES,
    DISCOVERY_GRADUATE_MIN_POSITIVE,
    DISCOVERY_GRADUATE_MIN_SESSIONS,
    PROMOTED_DISCOVERY_MAX_PAIRS,
    get_prewarm_pairs,
)


# ---------------------------------------------------------------------------
# 1. Discovery prewarm pairs
# ---------------------------------------------------------------------------

class TestDiscoveryPrewarmPairs:
    def test_discovery_contains_production_core(self):
        """Discovery pairs must be a superset of production pairs."""
        for pair in PREWARM_PAIRS_BASE:
            assert pair in PREWARM_PAIRS_BASE_DISCOVERY, (
                f"Production pair {pair} missing from discovery"
            )

    def test_discovery_includes_reactivated_families(self):
        """Discovery re-enables DEGEN, BRETT, AMONGUS, TOSHI families."""
        symbols = set()
        for a, b in PREWARM_PAIRS_BASE_DISCOVERY:
            symbols.add(a)
            symbols.add(b)
        assert "DEGEN" in symbols
        assert "BRETT" in symbols
        assert "AMONGUS" in symbols
        assert "TOSHI" in symbols

    def test_discovery_wider_than_production(self):
        assert len(PREWARM_PAIRS_BASE_DISCOVERY) > len(PREWARM_PAIRS_BASE)

    def test_discovery_pairs_are_tuples_of_two(self):
        for pair in PREWARM_PAIRS_BASE_DISCOVERY:
            assert isinstance(pair, tuple)
            assert len(pair) == 2

    def test_no_arb_token_in_base_discovery(self):
        """Base discovery should not contain ARB (Arbitrum-specific)."""
        for a, b in PREWARM_PAIRS_BASE_DISCOVERY:
            assert a != "ARB" and b != "ARB"


# ---------------------------------------------------------------------------
# 2. Profile-aware dispatch
# ---------------------------------------------------------------------------

class TestProfileDispatch:
    def test_production_profile_returns_narrow(self):
        pairs = get_prewarm_pairs("base", "production")
        assert pairs is PREWARM_PAIRS_BASE

    def test_discovery_profile_returns_wide(self):
        pairs = get_prewarm_pairs("base", "discovery")
        assert pairs is PREWARM_PAIRS_BASE_DISCOVERY

    def test_default_profile_is_production(self):
        pairs = get_prewarm_pairs("base")
        assert pairs is PREWARM_PAIRS_BASE

    def test_arbitrum_ignores_profile(self):
        """Arbitrum doesn't have discovery pairs yet — both profiles return same."""
        prod = get_prewarm_pairs("arbitrum_one", "production")
        disc = get_prewarm_pairs("arbitrum_one", "discovery")
        assert prod is PREWARM_PAIRS_ARBITRUM
        assert disc is PREWARM_PAIRS_ARBITRUM

    def test_unknown_chain_falls_back_to_arbitrum(self):
        pairs = get_prewarm_pairs("unknown_chain", "discovery")
        assert pairs is PREWARM_PAIRS_ARBITRUM


# ---------------------------------------------------------------------------
# 3. Backward compatibility — production unchanged
# ---------------------------------------------------------------------------

class TestProductionBackwardCompat:
    def test_production_base_pairs_unchanged(self):
        assert PREWARM_PAIRS_BASE == [
            ("USDC", "DAI"), ("USDC", "USDT"), ("WETH", "USDC"),
        ]

    def test_production_arbitrum_pairs_unchanged(self):
        assert len(PREWARM_PAIRS_ARBITRUM) == 6
        assert ("WETH", "USDC") in PREWARM_PAIRS_ARBITRUM


# ---------------------------------------------------------------------------
# 4. Discovery constants
# ---------------------------------------------------------------------------

class TestDiscoveryConstants:
    def test_valid_profiles(self):
        assert "production" in VALID_PROFILES
        assert "discovery" in VALID_PROFILES
        assert len(VALID_PROFILES) == 2

    def test_graduation_thresholds_positive(self):
        assert DISCOVERY_GRADUATE_MIN_POSITIVE >= 1
        assert DISCOVERY_GRADUATE_MIN_SESSIONS >= 1

    def test_discovery_max_pairs_wider(self):
        from m7.shared.constants import PROMOTED_MAX_PAIRS
        assert PROMOTED_DISCOVERY_MAX_PAIRS > PROMOTED_MAX_PAIRS


# ---------------------------------------------------------------------------
# 5. Discovery scoreboard update logic
# ---------------------------------------------------------------------------

class TestDiscoveryScoreboard:
    def _import_scoreboard_funcs(self):
        """Import scoreboard functions from loop module."""
        from scripts.m7a_orderflow_loop import (
            _read_discovery_scoreboard,
            _update_discovery_scoreboard,
        )
        return _read_discovery_scoreboard, _update_discovery_scoreboard

    def test_empty_artifact_no_crash(self):
        _, update = self._import_scoreboard_funcs()
        sb = {"families": {}, "updated_at": None, "profile": "discovery"}
        result = update(sb, {}, 1)
        assert result["families"] == {}

    def test_scored_positive_tracked(self):
        _, update = self._import_scoreboard_funcs()
        sb = {"families": {}, "updated_at": None}
        artifact = {
            "results": [
                {"pair_key": "DEGEN/WETH", "best_net_bps": 5.0},
                {"pair_key": "DEGEN/WETH", "best_net_bps": -2.0},
                {"pair_key": "BRETT/WETH", "best_net_bps": 3.0, "profit_guard_passed": True},
            ]
        }
        result = update(sb, artifact, 1)
        degen = result["families"]["DEGEN"]
        assert degen["total_scored"] == 2
        assert degen["scored_positive"] == 1
        assert 1 in degen["sessions_with_signal"]

        brett = result["families"]["BRETT"]
        assert brett["total_scored"] == 1
        assert brett["scored_positive"] == 1
        assert brett["guard_passed"] == 1

    def test_route_viable_excludes_hard_rejects(self):
        _, update = self._import_scoreboard_funcs()
        sb = {"families": {}, "updated_at": None}
        artifact = {
            "results": [
                {"pair_key": "TOSHI/WETH", "reject_reason": "TOKEN_PAIR_UNRESOLVED"},
                {"pair_key": "TOSHI/WETH", "reject_reason": "GAS_EXCEEDS_GROSS"},
            ]
        }
        result = update(sb, artifact, 1)
        toshi = result["families"]["TOSHI"]
        assert toshi["total_scored"] == 2
        # TOKEN_PAIR_UNRESOLVED is a hard reject → not route_viable
        # GAS_EXCEEDS_GROSS is a soft reject → route_viable
        assert toshi["route_viable"] == 1

    def test_sessions_accumulate_across_iterations(self):
        _, update = self._import_scoreboard_funcs()
        sb = {"families": {}, "updated_at": None}
        artifact1 = {"results": [{"pair_key": "DEGEN/WETH", "best_net_bps": 1.0}]}
        sb = update(sb, artifact1, 1)
        artifact2 = {"results": [{"pair_key": "DEGEN/WETH", "best_net_bps": 2.0}]}
        sb = update(sb, artifact2, 2)
        degen = sb["families"]["DEGEN"]
        assert degen["sessions_with_signal"] == [1, 2]
        assert degen["scored_positive"] == 2

    def test_iteration_dedup(self):
        """Same iteration should not be added twice to sessions_with_signal."""
        _, update = self._import_scoreboard_funcs()
        sb = {"families": {}, "updated_at": None}
        artifact = {
            "results": [
                {"pair_key": "DEGEN/WETH", "best_net_bps": 1.0},
                {"pair_key": "DEGEN/WETH", "best_net_bps": 2.0},
            ]
        }
        sb = update(sb, artifact, 1)
        degen = sb["families"]["DEGEN"]
        assert degen["sessions_with_signal"].count(1) == 1


# ---------------------------------------------------------------------------
# 6. M7.E1.9.1 — Artifact namespace isolation
# ---------------------------------------------------------------------------

class TestArtifactNamespaceIsolation:
    """Verify _rolling_path and _init_artifact_paths produce correct paths."""

    def _import_path_funcs(self):
        from scripts.m7a_orderflow_loop import _rolling_path, _init_artifact_paths
        return _rolling_path, _init_artifact_paths

    def test_rolling_path_production_unchanged(self):
        _rolling_path, _ = self._import_path_funcs()
        import os
        result = _rolling_path("m7_hot_latest.json", "production")
        assert result == os.path.join("data", "runs", "_rolling", "m7_hot_latest.json")

    def test_rolling_path_discovery_suffix(self):
        _rolling_path, _ = self._import_path_funcs()
        import os
        result = _rolling_path("m7_hot_latest.json", "discovery")
        assert result == os.path.join("data", "runs", "_rolling", "m7_hot_latest_discovery.json")

    def test_rolling_path_default_is_production(self):
        _rolling_path, _ = self._import_path_funcs()
        default = _rolling_path("m7_hot_latest.json")
        prod = _rolling_path("m7_hot_latest.json", "production")
        assert default == prod

    def test_init_artifact_paths_production(self):
        """Production profile keeps canonical names."""
        import scripts.m7a_orderflow_loop as loop
        _, _init = self._import_path_funcs()
        _init("production")
        assert "m7_hot_latest.json" in loop._HOT_ARTIFACT_PATH
        assert "_discovery" not in loop._HOT_ARTIFACT_PATH
        assert "_discovery" not in loop._PROMOTED_PAIRS_PATH
        assert "_discovery" not in loop._COLD_HOT_BRIDGE_PATH
        assert "_discovery" not in loop._HOT_INTENTS_PATH
        assert "_discovery" not in loop._HOT_ROLLUP_PATH
        # _DISCOVERY_SCOREBOARD_PATH base name contains "_discovery" inherently
        # (it's the scoreboard FOR discovery). Check it doesn't have the
        # namespace _discovery suffix (i.e. no _discovery_discovery).
        assert "_discovery_discovery" not in loop._DISCOVERY_SCOREBOARD_PATH

    def test_init_artifact_paths_discovery(self):
        """Discovery profile redirects all 6 paths to _discovery suffix."""
        import scripts.m7a_orderflow_loop as loop
        _, _init = self._import_path_funcs()
        _init("discovery")
        assert "_discovery.json" in loop._HOT_ARTIFACT_PATH
        assert "_discovery.json" in loop._PROMOTED_PAIRS_PATH
        assert "_discovery.json" in loop._COLD_HOT_BRIDGE_PATH
        assert "_discovery.json" in loop._HOT_INTENTS_PATH
        assert "_discovery.json" in loop._HOT_ROLLUP_PATH
        assert "_discovery.json" in loop._DISCOVERY_SCOREBOARD_PATH
        # Restore production to not break other tests
        _init("production")

    def test_no_overlap_between_profiles(self):
        """Production and discovery paths must never collide."""
        import scripts.m7a_orderflow_loop as loop
        _, _init = self._import_path_funcs()

        _init("production")
        prod_paths = {
            loop._HOT_ARTIFACT_PATH,
            loop._PROMOTED_PAIRS_PATH,
            loop._COLD_HOT_BRIDGE_PATH,
            loop._HOT_INTENTS_PATH,
            loop._HOT_ROLLUP_PATH,
            loop._DISCOVERY_SCOREBOARD_PATH,
        }

        _init("discovery")
        disc_paths = {
            loop._HOT_ARTIFACT_PATH,
            loop._PROMOTED_PAIRS_PATH,
            loop._COLD_HOT_BRIDGE_PATH,
            loop._HOT_INTENTS_PATH,
            loop._HOT_ROLLUP_PATH,
            loop._DISCOVERY_SCOREBOARD_PATH,
        }

        assert prod_paths.isdisjoint(disc_paths), (
            f"Overlap: {prod_paths & disc_paths}"
        )
        # Restore production
        _init("production")


class TestModeWsLiveProfilePath:
    """Verify _set_rolling_m7_profile redirects cold lane artifact."""

    def test_production_path_canonical(self):
        from m7.orderflow.mode_ws_live import _set_rolling_m7_profile
        import m7.orderflow.mode_ws_live as ws
        _set_rolling_m7_profile("production")
        assert "m7_orderflow_latest.json" in ws._ROLLING_M7_PATH
        assert "_discovery" not in ws._ROLLING_M7_PATH

    def test_discovery_path_namespaced(self):
        from m7.orderflow.mode_ws_live import _set_rolling_m7_profile
        import m7.orderflow.mode_ws_live as ws
        _set_rolling_m7_profile("discovery")
        assert "m7_orderflow_latest_discovery.json" in ws._ROLLING_M7_PATH
        # Restore
        _set_rolling_m7_profile("production")


class TestE193DashboardContracts:
    """E1.9.3: Tests for signal_counts backfill and dashboard server discovery endpoint."""

    def test_signal_counts_backfill_on_empty_window(self, tmp_path):
        """Cold lane heartbeat on old snapshot without signal_counts should add it."""
        import json
        import m7.orderflow.mode_ws_live as ws

        # Create an old-style artifact without signal_counts
        old_artifact = {
            "mode": "ws_live",
            "timestamp": "2026-04-08T09:54:01Z",
            "run_context": {"run_timestamp": "2026-04-08T09:54:01Z"},
            "events_count": 5,
            "results_count": 3,
        }
        rolling_path = str(tmp_path / "m7_orderflow_latest.json")
        with open(rolling_path, "w") as f:
            json.dump(old_artifact, f)

        # Patch module-level path and call _write_rolling_m7 with empty artifact
        original_path = ws._ROLLING_M7_PATH
        try:
            ws._ROLLING_M7_PATH = rolling_path
            empty_artifact = {
                "events_count": 0,
                "m7_loop_context": {"iteration": 42},
            }
            ws._write_rolling_m7(empty_artifact)

            with open(rolling_path) as f:
                result = json.load(f)

            assert "signal_counts" in result
            assert result["signal_counts"]["scored"] == 0
            assert result["signal_counts"]["submit_ready"] == 0
            assert result["snapshot_preserved"] is True
        finally:
            ws._ROLLING_M7_PATH = original_path

    def test_signal_counts_preserved_when_already_exists(self, tmp_path):
        """Cold lane heartbeat should not overwrite existing signal_counts."""
        import json
        import m7.orderflow.mode_ws_live as ws

        existing_artifact = {
            "mode": "ws_live",
            "timestamp": "2026-04-09T10:00:00Z",
            "run_context": {"run_timestamp": "2026-04-09T10:00:00Z"},
            "events_count": 10,
            "signal_counts": {
                "scored": 10, "pair_resolved": 8,
                "size_valid_for_token": 7, "same_block": 10,
                "positive": 3, "route_viable": 2,
                "profit_guard_passed": 1, "sim_passed": 0,
                "submit_ready": 0,
            },
        }
        rolling_path = str(tmp_path / "m7_orderflow_latest.json")
        with open(rolling_path, "w") as f:
            json.dump(existing_artifact, f)

        original_path = ws._ROLLING_M7_PATH
        try:
            ws._ROLLING_M7_PATH = rolling_path
            empty_artifact = {
                "events_count": 0,
                "m7_loop_context": {"iteration": 99},
            }
            ws._write_rolling_m7(empty_artifact)

            with open(rolling_path) as f:
                result = json.load(f)

            # signal_counts should be unchanged (preserving the historical data)
            assert result["signal_counts"]["scored"] == 10
            assert result["signal_counts"]["positive"] == 3
        finally:
            ws._ROLLING_M7_PATH = original_path

    def test_dashboard_server_discovery_files(self):
        """Dashboard server has DISCOVERY_ARTIFACT_FILES dict with correct paths."""
        from monitoring.dashboard_server import DISCOVERY_ARTIFACT_FILES
        assert "m7_hot" in DISCOVERY_ARTIFACT_FILES
        assert "m7_hot_rollup" in DISCOVERY_ARTIFACT_FILES
        assert "m7_orderflow" in DISCOVERY_ARTIFACT_FILES
        assert "m7_discovery_scoreboard" in DISCOVERY_ARTIFACT_FILES
        for key, path in DISCOVERY_ARTIFACT_FILES.items():
            assert "_discovery" in str(path), f"{key} path should contain _discovery"

    def test_dashboard_server_has_discovery_endpoint(self):
        """Dashboard server handler should have _serve_discovery_data method."""
        from monitoring.dashboard_server import DashboardHandler
        assert hasattr(DashboardHandler, "_serve_discovery_data")
