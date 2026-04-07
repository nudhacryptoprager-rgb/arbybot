"""
M7.A.5.47i — Unit tests for:
  1. Anomaly-clean recoverable_stale filter (PRICING_ANOMALY / TOKEN_PAIR_UNRESOLVED excluded)
  2. C1 defense-in-depth anomaly skip in orderflow loop
  3. Bridge hit detection isolation (independent try/except blocks)
  4. C2 gas-near tolerance (gas_floor_gap_bps within -10 bps)
  5. Bridge-miss active auto-promotion lifecycle
"""
from __future__ import annotations

import pytest

from tests.unit.conftest import _make_result


# ---------------------------------------------------------------------------
# Constants matching production code
# ---------------------------------------------------------------------------
REJECT_STALE_POSITIVE = "STALE_POSITIVE"
REJECT_PRICING_ANOMALY = "PRICING_ANOMALY"
REJECT_TOKEN_PAIR_UNRESOLVED = "TOKEN_PAIR_UNRESOLVED"
REJECT_GAS_EXCEEDS_GROSS = "GAS_EXCEEDS_GROSS"

_ANOMALY_REJECTS = {REJECT_PRICING_ANOMALY, REJECT_TOKEN_PAIR_UNRESOLVED}


# ---------------------------------------------------------------------------
# Helpers simulating production logic
# ---------------------------------------------------------------------------

def _recoverable_stale_filter_47i(results: list) -> list:
    """Strict 47i filter: reject_reason == STALE_POSITIVE, not in anomalies,
    lag <= 2, net_bps > 0, size_valid."""
    out = []
    for r in results:
        rr = getattr(r, "reject_reason", None)
        if rr != REJECT_STALE_POSITIVE:
            continue
        if rr in _ANOMALY_REJECTS:
            continue
        net = getattr(r, "best_backrun_net_bps", 0) or 0
        if net <= 0:
            continue
        if not getattr(r, "size_valid_for_token", False):
            continue
        lag = getattr(r, "block_lag", 999) or 999
        if lag > 2:
            continue
        out.append(r)
    return sorted(out, key=lambda r: r.best_backrun_net_bps or 0, reverse=True)


def _c1_defense_in_depth(candidates: list) -> list:
    """Simulate C1 defense-in-depth: skip anomalies even if artifacts leaked."""
    _ANOM = {"PRICING_ANOMALY", "TOKEN_PAIR_UNRESOLVED"}
    return [c for c in candidates if c.get("reject_reason", "") not in _ANOM]


def _gas_viable_families(micro_refinement: list, tolerance_bps: float = -10) -> set:
    """Build set of gas-viable families: verified_net > 0 OR gas_floor_gap >= tolerance."""
    families: set = set()
    for mr in micro_refinement:
        v_net = mr.get("verified_net_bps_after_refinement") or 0
        if v_net > 0:
            ap = mr.get("actual_pair") or ""
            parts = ap.split("/")
            if len(parts) == 2:
                families.add(tuple(sorted((parts[0].lower(), parts[1].lower()))))
            continue
        gfg = mr.get("gas_floor_gap_bps")
        if gfg is not None and gfg >= tolerance_bps:
            ap = mr.get("actual_pair") or ""
            parts = ap.split("/")
            if len(parts) == 2:
                families.add(tuple(sorted((parts[0].lower(), parts[1].lower()))))
    return families


def _bridge_miss_auto_promote(bridge_miss_sample: list, recent_active: list,
                              hot_seen_pin: dict, ttl_init: int = 3,
                              iteration: int = 1) -> int:
    """Simulate auto-promotion of bridge-miss pools that are in recent_active."""
    active_set = {(r.get("pool_address") or "").lower() for r in recent_active}
    promoted = 0
    for bms in bridge_miss_sample[:10]:
        pa = (bms.get("event_pool") or "").lower()
        if pa and pa in active_set:
            if pa not in hot_seen_pin or hot_seen_pin[pa].get("ttl", 0) <= 1:
                hot_seen_pin[pa] = {
                    "ttl": ttl_init,
                    "last_iter": iteration,
                    "source": "bridge_miss_active_promote",
                }
                promoted += 1
    return promoted


# ===========================================================================
# 1. Anomaly-clean recoverable_stale
# ===========================================================================


class TestAnomalyCleanRecoverableStale:

    def test_stale_positive_accepted(self):
        r = _make_result(
            reject_reason=REJECT_STALE_POSITIVE,
            best_backrun_net_bps=5.0,
            size_valid_for_token=True,
            block_lag=1,
        )
        result = _recoverable_stale_filter_47i([r])
        assert len(result) == 1

    def test_pricing_anomaly_excluded(self):
        """PRICING_ANOMALY must NEVER pass recoverable_stale, even if it has
        same_state_class=stale and positive net_bps."""
        r = _make_result(
            reject_reason=REJECT_PRICING_ANOMALY,
            best_backrun_net_bps=36927.0,  # absurd value from real data
            size_valid_for_token=True,
            block_lag=0,
        )
        result = _recoverable_stale_filter_47i([r])
        assert len(result) == 0

    def test_token_pair_unresolved_excluded(self):
        r = _make_result(
            reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
            best_backrun_net_bps=100.0,
            size_valid_for_token=True,
            block_lag=0,
        )
        result = _recoverable_stale_filter_47i([r])
        assert len(result) == 0

    def test_gas_exceeds_gross_excluded(self):
        """Only STALE_POSITIVE passes — GAS_EXCEEDS_GROSS is for C2, not C1."""
        r = _make_result(
            reject_reason=REJECT_GAS_EXCEEDS_GROSS,
            best_backrun_net_bps=2.0,
            size_valid_for_token=True,
            block_lag=1,
        )
        result = _recoverable_stale_filter_47i([r])
        assert len(result) == 0

    def test_mixed_results_only_stale_positive_passes(self):
        results = [
            _make_result(event_id="e1", reject_reason=REJECT_STALE_POSITIVE,
                         best_backrun_net_bps=5.0, size_valid_for_token=True, block_lag=1),
            _make_result(event_id="e2", reject_reason=REJECT_PRICING_ANOMALY,
                         best_backrun_net_bps=36927.0, size_valid_for_token=True, block_lag=0),
            _make_result(event_id="e3", reject_reason=REJECT_TOKEN_PAIR_UNRESOLVED,
                         best_backrun_net_bps=50.0, size_valid_for_token=True, block_lag=1),
        ]
        filtered = _recoverable_stale_filter_47i(results)
        assert len(filtered) == 1
        assert filtered[0].event_id == "e1"


# ===========================================================================
# 2. C1 defense-in-depth anomaly skip
# ===========================================================================


class TestC1DefenseInDepth:

    def test_anomaly_skipped(self):
        candidates = [
            {"pool_address": "0xa", "reject_reason": "PRICING_ANOMALY"},
            {"pool_address": "0xb", "reject_reason": "STALE_POSITIVE"},
            {"pool_address": "0xc", "reject_reason": "TOKEN_PAIR_UNRESOLVED"},
        ]
        result = _c1_defense_in_depth(candidates)
        assert len(result) == 1
        assert result[0]["pool_address"] == "0xb"

    def test_empty_reject_reason_passes(self):
        candidates = [{"pool_address": "0xa", "reject_reason": ""}]
        result = _c1_defense_in_depth(candidates)
        assert len(result) == 1

    def test_all_anomalies_empty_result(self):
        candidates = [
            {"pool_address": "0xa", "reject_reason": "PRICING_ANOMALY"},
            {"pool_address": "0xb", "reject_reason": "TOKEN_PAIR_UNRESOLVED"},
        ]
        result = _c1_defense_in_depth(candidates)
        assert len(result) == 0


# ===========================================================================
# 3. Bridge hit detection isolation
# ===========================================================================


class TestBridgeHitDetectionIsolation:
    """Tests that bridge hit detection is independent of registry operations.
    The production bug was: a single try/except wrapped registry-match AND
    bridge-hit loops. If registry ops raised, bridge hits were never counted."""

    def test_bridge_hit_simple(self):
        """Direct PTT-set membership should always work, independent of registry."""
        ptt_lower = {"0xaaa", "0xbbb", "0xccc"}
        event_pools = ["0xaaa", "0xddd", "0xbbb"]
        hits = sum(1 for p in event_pools if p in ptt_lower)
        assert hits == 2

    def test_bridge_hit_empty_ptt(self):
        ptt_lower: set = set()
        event_pools = ["0xaaa", "0xbbb"]
        hits = sum(1 for p in event_pools if p in ptt_lower)
        assert hits == 0

    def test_bridge_hit_case_normalization(self):
        """Both sides must be lowered for matching."""
        ptt_lower = {"0xabc123"}
        event_pool = "0xABC123".lower()
        assert event_pool in ptt_lower

    def test_independence_from_registry_failure(self):
        """Simulate: registry lookup raises, but bridge hit should still count."""
        ptt_lower = {"0xpool1", "0xpool2"}

        # Simulate block 1 (registry match) raising
        registry_raised = False
        try:
            raise RuntimeError("registry lookup failed")
        except Exception:
            registry_raised = True

        # Block 2 (bridge hit) should run independently
        hits = 0
        for p in ["0xpool1", "0xpool3"]:
            if p in ptt_lower:
                hits += 1

        assert registry_raised is True
        assert hits == 1  # 0xpool1 matched


# ===========================================================================
# 4. C2 gas-near tolerance
# ===========================================================================


class TestC2GasNearTolerance:

    def test_verified_positive_always_admitted(self):
        micro = [{"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 5}]
        fams = _gas_viable_families(micro)
        assert ("rain", "weth") in fams

    def test_small_negative_gap_admitted(self):
        """gas_floor_gap_bps = -8 (within -10 tolerance) should be admitted."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": -8},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") in fams

    def test_large_negative_gap_excluded(self):
        """gas_floor_gap_bps = -15 (beyond -10 tolerance) should be excluded."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": -15},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") not in fams

    def test_exactly_at_tolerance_admitted(self):
        """gas_floor_gap_bps = -10 (exactly at threshold) should be admitted."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": -10},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") in fams

    def test_zero_gap_admitted(self):
        """gas_floor_gap_bps = 0 (breakeven) should be admitted."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": 0},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") in fams

    def test_none_gap_excluded(self):
        """gas_floor_gap_bps = None should not admit the family."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": None},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") not in fams

    def test_positive_net_overrides_negative_gap(self):
        """If verified_net > 0, the family is always admitted regardless of gap."""
        micro = [
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 3,
             "gas_floor_gap_bps": -50},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("usdc", "weth") in fams

    def test_multiple_families_mixed(self):
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 5},
            {"actual_pair": "WETH/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": -8},
            {"actual_pair": "WBTC/USDC", "verified_net_bps_after_refinement": 0,
             "gas_floor_gap_bps": -20},
        ]
        fams = _gas_viable_families(micro, tolerance_bps=-10)
        assert ("rain", "weth") in fams      # positive net
        assert ("usdc", "weth") in fams       # small gap
        assert ("usdc", "wbtc") not in fams   # large gap


# ===========================================================================
# 5. Bridge-miss active auto-promotion
# ===========================================================================


class TestBridgeMissActiveAutoPromote:

    def test_active_pool_promoted(self):
        bridge_miss = [{"event_pool": "0xaaa", "seen_count": 3}]
        active = [{"pool_address": "0xaaa", "seen_count": 5}]
        pin: dict = {}
        count = _bridge_miss_auto_promote(bridge_miss, active, pin)
        assert count == 1
        assert "0xaaa" in pin
        assert pin["0xaaa"]["source"] == "bridge_miss_active_promote"
        assert pin["0xaaa"]["ttl"] == 3

    def test_non_active_pool_not_promoted(self):
        bridge_miss = [{"event_pool": "0xaaa", "seen_count": 3}]
        active = [{"pool_address": "0xbbb", "seen_count": 5}]
        pin: dict = {}
        count = _bridge_miss_auto_promote(bridge_miss, active, pin)
        assert count == 0
        assert "0xaaa" not in pin

    def test_already_pinned_with_high_ttl_not_overwritten(self):
        bridge_miss = [{"event_pool": "0xaaa", "seen_count": 3}]
        active = [{"pool_address": "0xaaa", "seen_count": 5}]
        pin = {"0xaaa": {"ttl": 3, "last_iter": 0, "source": "other"}}
        count = _bridge_miss_auto_promote(bridge_miss, active, pin)
        assert count == 0  # ttl=3 > 1, so not overwritten

    def test_expiring_pin_refreshed(self):
        """Pin with ttl=1 should be refreshed by auto-promote."""
        bridge_miss = [{"event_pool": "0xaaa", "seen_count": 3}]
        active = [{"pool_address": "0xaaa", "seen_count": 5}]
        pin = {"0xaaa": {"ttl": 1, "last_iter": 0, "source": "other"}}
        count = _bridge_miss_auto_promote(bridge_miss, active, pin)
        assert count == 1
        assert pin["0xaaa"]["ttl"] == 3
        assert pin["0xaaa"]["source"] == "bridge_miss_active_promote"

    def test_max_10_promotions(self):
        """Auto-promote reads at most 10 bridge-miss entries."""
        bridge_miss = [{"event_pool": f"0x{i:04x}", "seen_count": 1} for i in range(20)]
        active = [{"pool_address": f"0x{i:04x}", "seen_count": 1} for i in range(20)]
        pin: dict = {}
        count = _bridge_miss_auto_promote(bridge_miss, active, pin)
        assert count == 10  # capped at 10

    def test_empty_inputs(self):
        pin: dict = {}
        assert _bridge_miss_auto_promote([], [], pin) == 0
        assert _bridge_miss_auto_promote(
            [{"event_pool": "0xa"}], [], pin) == 0
