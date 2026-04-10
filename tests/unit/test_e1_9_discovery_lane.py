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
