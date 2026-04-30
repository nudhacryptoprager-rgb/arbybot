"""M7.E1.9/E1.10 -- Tests for discovery/production lane split.

Validates:
1. Discovery prewarm pairs: wider contour including DEGEN, BRETT (AMONGUS removed E1.10)
2. Profile-aware get_prewarm_pairs dispatch
3. Backward compatibility: production profile unchanged
4. Discovery constants: graduation thresholds, valid profiles
5. Discovery scoreboard update logic
6. Config contract: tokens in include_pairs exist in core_tokens.yaml
7. Cross-dex policy: diagnostic marking for low cross_dex_expected families
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
        """Discovery re-enables DEGEN, BRETT, TOSHI families (AMONGUS removed E1.10)."""
        symbols = set()
        for a, b in PREWARM_PAIRS_BASE_DISCOVERY:
            symbols.add(a)
            symbols.add(b)
        assert "VIRTUAL" in symbols
        assert "DEGEN" in symbols
        assert "BRETT" in symbols
        assert "TOSHI" in symbols
        # E1.10: AMONGUS removed — not in core_tokens.yaml (dead slot)
        assert "AMONGUS" not in symbols

    def test_discovery_wider_than_production(self):
        # E1.48: meme families promoted productive, so discovery may equal production.
        assert len(PREWARM_PAIRS_BASE_DISCOVERY) >= len(PREWARM_PAIRS_BASE)

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
        # E1.30: intent-driven — production returns intent.txt pairs for base.
        pairs = get_prewarm_pairs("base", "production")
        assert ("WETH", "USDC") in pairs
        assert ("USDC", "DAI") in pairs

    def test_discovery_profile_returns_wide(self):
        # E1.30: discovery is superset of production (intent ∪ hardcoded extras).
        prod = get_prewarm_pairs("base", "production")
        disc = get_prewarm_pairs("base", "discovery")
        assert len(disc) >= len(prod)
        for p in prod:
            assert p in disc or tuple(sorted(p)) in [tuple(sorted(d)) for d in disc]

    def test_default_profile_is_production(self):
        # E1.30: default == production profile.
        pairs = get_prewarm_pairs("base")
        prod = get_prewarm_pairs("base", "production")
        assert pairs == prod

    def test_arbitrum_ignores_profile(self):
        """Arbitrum: intent.txt covers both profiles identically (no discovery extras)."""
        prod = get_prewarm_pairs("arbitrum_one", "production")
        disc = get_prewarm_pairs("arbitrum_one", "discovery")
        # Discovery is superset (may equal or exceed production).
        assert len(disc) >= len(prod)

    def test_unknown_chain_falls_back_to_arbitrum(self):
        pairs = get_prewarm_pairs("unknown_chain", "discovery")
        # E1.30: returns list copy of hardcoded Arbitrum fallback.
        assert pairs == list(PREWARM_PAIRS_ARBITRUM)


# ---------------------------------------------------------------------------
# 3. Backward compatibility — production unchanged
# ---------------------------------------------------------------------------

class TestProductionBackwardCompat:
    def test_production_base_pairs_unchanged(self):
        # E1.48: BRETT/DEGEN/TOSHI promoted to productive (governance approved).
        assert PREWARM_PAIRS_BASE == [
            ("USDC", "DAI"), ("USDC", "USDT"), ("WETH", "USDC"),
            ("AERO", "USDC"), ("AERO", "WETH"),
            ("cbBTC", "USDC"), ("cbBTC", "WETH"),
            ("VIRTUAL", "USDC"), ("WETH", "VIRTUAL"),
            ("BRETT", "WETH"), ("DEGEN", "WETH"), ("TOSHI", "WETH"),
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


class TestE110DashboardEnhancements:
    """E1.10: Namespace badge and heartbeat in dashboard."""

    def test_dashboard_has_namespace_label(self):
        """Dashboard HTML has explicit Namespace label in session panel."""
        from pathlib import Path
        html = Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "Namespace: ${m7Profile.toUpperCase()}" in html

    def test_dashboard_has_heartbeat_in_cold_notice(self):
        """Dashboard cold snapshot notice shows heartbeat age."""
        from pathlib import Path
        html = Path("monitoring/dashboard.html").read_text(encoding="utf-8")
        assert "current_window_timestamp" in html
        assert "Heartbeat:" in html


# ---------------------------------------------------------------------------
# E1.10: Config contract tests — tokens in include_pairs must exist in core_tokens
# ---------------------------------------------------------------------------

class TestE110ConfigContract:
    """Every token referenced in discovery include_pairs must exist in core_tokens.yaml."""

    def _load_core_tokens_base(self):
        """Load Base section from core_tokens.yaml."""
        import yaml
        from pathlib import Path
        with open(Path("config/core_tokens.yaml"), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return set(data.get("base", {}).keys())

    def _load_discovery_include_pairs(self):
        """Load include_pairs from onboard_base_discovery.yaml."""
        import yaml
        from pathlib import Path
        with open(Path("config/onboard_base_discovery.yaml"), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("include_pairs", [])

    def test_all_discovery_tokens_in_core_tokens(self):
        """Every token symbol in discovery include_pairs must exist in core_tokens.yaml base section."""
        core_symbols = self._load_core_tokens_base()
        pairs = self._load_discovery_include_pairs()
        missing = set()
        for pair_str in pairs:
            parts = pair_str.split("/")
            for sym in parts:
                if sym not in core_symbols:
                    missing.add(sym)
        assert not missing, (
            f"Tokens in discovery include_pairs but not in core_tokens.yaml base: {missing}"
        )

    def test_all_prewarm_tokens_in_core_tokens(self):
        """Every token in PREWARM_PAIRS_BASE_DISCOVERY must exist in core_tokens.yaml base."""
        core_symbols = self._load_core_tokens_base()
        missing = set()
        for a, b in PREWARM_PAIRS_BASE_DISCOVERY:
            if a not in core_symbols:
                missing.add(a)
            if b not in core_symbols:
                missing.add(b)
        assert not missing, (
            f"Tokens in PREWARM_PAIRS_BASE_DISCOVERY but not in core_tokens.yaml: {missing}"
        )

    def test_production_config_tokens_also_valid(self):
        """Production include_pairs tokens must also be in core_tokens.yaml."""
        import yaml
        from pathlib import Path
        core_symbols = self._load_core_tokens_base()
        with open(Path("config/onboard_base_profit.yaml"), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        pairs = data.get("include_pairs", [])
        missing = set()
        for pair_str in pairs:
            parts = pair_str.split("/")
            for sym in parts:
                if sym not in core_symbols:
                    missing.add(sym)
        assert not missing, (
            f"Tokens in production include_pairs but not in core_tokens.yaml: {missing}"
        )


# ---------------------------------------------------------------------------
# E1.10: Cross-dex policy test
# ---------------------------------------------------------------------------

class TestE110CrossDexPolicy:
    """If require_cross_dex: true, pairs with cross_dex_expected < 2 must be diagnostic_only."""

    def _load_core_tokens_base(self):
        import yaml
        from pathlib import Path
        with open(Path("config/core_tokens.yaml"), "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)
        return data.get("base", {})

    def _load_discovery_config(self):
        import yaml
        from pathlib import Path
        with open(Path("config/onboard_base_discovery.yaml"), "r", encoding="utf-8") as f:
            return yaml.safe_load(f)

    def test_low_cross_dex_pairs_documented_as_diagnostic(self):
        """Pairs with cross_dex_expected < 2 under require_cross_dex: true must be
        marked as diagnostic_only in the config comment (structurally weak for arb)."""
        config = self._load_discovery_config()
        if not config.get("require_cross_dex", False):
            pytest.skip("require_cross_dex not set")
        tokens = self._load_core_tokens_base()
        pairs = config.get("include_pairs", [])
        low_cross_dex_pairs = []
        for pair_str in pairs:
            parts = pair_str.split("/")
            for sym in parts:
                info = tokens.get(sym, {})
                cde = info.get("cross_dex_expected", 0)
                if cde < 2 and sym not in ("WETH", "USDC", "USDT", "DAI"):
                    low_cross_dex_pairs.append((pair_str, sym, cde))
        # E1.48: meme families (BRETT/DEGEN/TOSHI) promoted to cross_dex=2.
        # If no low cross_dex pairs remain, the diagnostic_only invariant is moot.
        if not low_cross_dex_pairs:
            return  # post-E1.48 valid state: all pairs are productive
        # Verify the config file contains 'diagnostic_only' comment
        from pathlib import Path
        config_text = Path("config/onboard_base_discovery.yaml").read_text(encoding="utf-8")
        assert "diagnostic_only" in config_text, (
            "Discovery config with require_cross_dex: true must document low cross_dex pairs as diagnostic_only"
        )

    def test_structurally_strong_pairs_present(self):
        """Discovery contour must include structurally stronger Base pairs (cross_dex >= 2)."""
        config = self._load_discovery_config()
        pairs = config.get("include_pairs", [])
        required_strong = {
            "AERO/USDC",
            "AERO/WETH",
            "cbBTC/USDC",
            "cbBTC/WETH",
            "VIRTUAL/USDC",
            "WETH/VIRTUAL",
        }
        pair_set = set(pairs)
        missing = required_strong - pair_set
        assert not missing, f"Missing structurally strong pairs in discovery: {missing}"


# ---------------------------------------------------------------------------
# E1.10: Hot artifact fallback is profile-aware
# ---------------------------------------------------------------------------

class TestE110HotFallbackProfileAware:
    """_write_hot_artifact fallback uses profile-aware seed pairs, not HOT_WATCHLIST_PAIRS."""

    def test_fallback_uses_get_prewarm_pairs(self):
        """When no promoted/candidate pairs, fallback should use profile-aware seed."""
        import scripts.m7a_orderflow_loop as loop
        import inspect
        source = inspect.getsource(loop._write_hot_artifact)
        # Must use get_prewarm_pairs, not HOT_WATCHLIST_PAIRS in fallback
        assert "get_prewarm_pairs" in source, (
            "_write_hot_artifact fallback must use get_prewarm_pairs for profile-aware seed"
        )

    def test_signature_has_profile_param(self):
        """_write_hot_artifact must accept profile parameter."""
        import inspect
        import scripts.m7a_orderflow_loop as loop
        sig = inspect.signature(loop._write_hot_artifact)
        assert "profile" in sig.parameters, (
            "_write_hot_artifact must have profile parameter for profile-aware fallback"
        )


class TestE1122HotArtifactsPathRebinding:
    """E1.12.2 regression: hot_runtime_artifacts must see discovery paths after _init_artifact_paths."""

    def test_hot_artifacts_see_discovery_paths_after_init(self):
        """After _init_artifact_paths('discovery'), hot_runtime_artifacts must use _discovery suffix."""
        import m7.orderflow.runtime_io as rio
        import m7.orderflow.hot_runtime_artifacts as hra

        rio._init_artifact_paths("discovery")
        try:
            # hot_runtime_artifacts accesses paths through _rio module reference
            assert "_discovery" in hra._rio._HOT_ARTIFACT_PATH, (
                f"Expected _discovery in HOT_ARTIFACT_PATH, got: {hra._rio._HOT_ARTIFACT_PATH}"
            )
            assert "_discovery" in hra._rio._HOT_INTENTS_PATH, (
                f"Expected _discovery in HOT_INTENTS_PATH, got: {hra._rio._HOT_INTENTS_PATH}"
            )
            assert "_discovery" in hra._rio._HOT_ROLLUP_PATH, (
                f"Expected _discovery in HOT_ROLLUP_PATH, got: {hra._rio._HOT_ROLLUP_PATH}"
            )
        finally:
            rio._init_artifact_paths("production")

    def test_hot_artifacts_see_production_paths_default(self):
        """Under production profile, hot_runtime_artifacts paths must NOT have _discovery."""
        import m7.orderflow.runtime_io as rio
        import m7.orderflow.hot_runtime_artifacts as hra

        rio._init_artifact_paths("production")
        assert "_discovery" not in hra._rio._HOT_ARTIFACT_PATH
        assert "_discovery" not in hra._rio._HOT_INTENTS_PATH
        assert "_discovery" not in hra._rio._HOT_ROLLUP_PATH

    def test_discovery_and_production_paths_dont_collide(self):
        """Discovery and production hot paths must never be the same file."""
        import m7.orderflow.runtime_io as rio

        rio._init_artifact_paths("production")
        prod = (rio._HOT_ARTIFACT_PATH, rio._HOT_INTENTS_PATH, rio._HOT_ROLLUP_PATH)

        rio._init_artifact_paths("discovery")
        disc = (rio._HOT_ARTIFACT_PATH, rio._HOT_INTENTS_PATH, rio._HOT_ROLLUP_PATH)

        for p, d in zip(prod, disc):
            assert p != d, f"Collision: {p}"

        rio._init_artifact_paths("production")
