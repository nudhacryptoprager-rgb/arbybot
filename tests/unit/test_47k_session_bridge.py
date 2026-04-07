"""
M7.A.5.47k — Unit tests for:
  1. stale_sub_reason classification (pipeline_abort vs block_lag vs state_recheck)
  2. Auto-pin ALL bridge-miss pools (not just active ones)
  3. Recoverable-stale route_viable / not_viable split
  4. C2 unknown-family safe default (skip, not admit)
  5. Bridge exclusion reasons
  6. Session-scoped hot rollup reset
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. stale_sub_reason classification
# ---------------------------------------------------------------------------


class _FakeResult:
    """Minimal mock of BackrunResult for _compact_candidate tests."""

    def __init__(self, **kw):
        self.event_id = kw.get("event_id", "ev1")
        self.actual_pair = kw.get("actual_pair", "FOO/BAR")
        self.best_backrun_net_bps = kw.get("net_bps", 10.0)
        self.block_lag = kw.get("block_lag", 0)
        self.same_state_class = kw.get("same_state_class", None)
        self.route_viable = kw.get("route_viable", True)
        self.size_valid_for_token = kw.get("size_valid_for_token", True)
        self.scoring_path = kw.get("scoring_path", "cold")
        self.profit_guard_passed = kw.get("profit_guard_passed", False)
        self.quote_pipeline_latency_ms = kw.get("pipeline_latency_ms", 100.0)
        self.reject_reason = kw.get("reject_reason", None)
        self.pipeline_stage_latency_ms = kw.get("pipeline_stage_latency_ms", None)
        self.amount_in_wei = 0
        self.gross_pnl_wei = 0
        self._source_event = None


def _classify_stale_sub(r):
    """Mirror of the stale_sub_reason logic in artifacts.py _compact_candidate."""
    REJECT_STALE_POSITIVE = "REJECT_STALE_POSITIVE"
    if getattr(r, "reject_reason", None) != REJECT_STALE_POSITIVE:
        return None
    _stage = getattr(r, "pipeline_stage_latency_ms", None) or {}
    if _stage.get("mid_pipeline_abort"):
        return "pipeline_abort"
    elif r.block_lag > 2:
        return "block_lag"
    else:
        return "state_recheck"


class TestStaleSubReason:

    def test_pipeline_abort(self):
        """Mid-pipeline abort (wall-clock budget exceeded) → pipeline_abort."""
        r = _FakeResult(
            reject_reason="REJECT_STALE_POSITIVE",
            block_lag=0,
            same_state_class="stale",
            pipeline_stage_latency_ms={"mid_pipeline_abort": True, "total_ms": 1110.0},
        )
        assert _classify_stale_sub(r) == "pipeline_abort"

    def test_block_lag_high(self):
        """block_lag > 2, normal stale → block_lag."""
        r = _FakeResult(
            reject_reason="REJECT_STALE_POSITIVE",
            block_lag=58,
            same_state_class="stale",
        )
        assert _classify_stale_sub(r) == "block_lag"

    def test_state_recheck(self):
        """block_lag ≤ 2, no mid_pipeline_abort → state_recheck."""
        r = _FakeResult(
            reject_reason="REJECT_STALE_POSITIVE",
            block_lag=1,
            same_state_class="stale",
            pipeline_stage_latency_ms={"total_ms": 200.0},
        )
        assert _classify_stale_sub(r) == "state_recheck"

    def test_not_stale(self):
        """Non-stale result → None."""
        r = _FakeResult(reject_reason="REJECT_GAS_EXCEEDS_GROSS")
        assert _classify_stale_sub(r) is None

    def test_no_reject(self):
        """No reject_reason → None."""
        r = _FakeResult(reject_reason=None)
        assert _classify_stale_sub(r) is None


# ---------------------------------------------------------------------------
# 2. Auto-pin ALL bridge-miss pools
# ---------------------------------------------------------------------------


_HOT_SEEN_PIN_TTL_INIT = 3


def _auto_pin_bridge_miss(
    bridge_miss_sample: list,
    active_pool_set: set,
    hot_seen_pin: dict,
    iteration: int,
) -> int:
    """Mirror of 47k auto-promote logic: pins ALL miss pools, not just active."""
    promoted = 0
    for bms in bridge_miss_sample[:10]:
        bms_pa = (bms.get("event_pool") or "").lower()
        if not bms_pa:
            continue
        if bms_pa not in hot_seen_pin or hot_seen_pin[bms_pa].get("ttl", 0) <= 1:
            src = ("bridge_miss_active_promote"
                   if bms_pa in active_pool_set
                   else "bridge_miss_direct_pin")
            hot_seen_pin[bms_pa] = {
                "ttl": _HOT_SEEN_PIN_TTL_INIT,
                "last_iter": iteration,
                "source": src,
            }
            promoted += 1
    return promoted


class TestAutoPinBridgeMiss:

    def test_pins_active_pool(self):
        """Pool in recent_active should be pinned with active source."""
        pin: dict = {}
        miss = [{"event_pool": "0xabc123"}]
        count = _auto_pin_bridge_miss(miss, {"0xabc123"}, pin, 1)
        assert count == 1
        assert pin["0xabc123"]["source"] == "bridge_miss_active_promote"

    def test_pins_non_active_pool(self):
        """Pool NOT in recent_active should still be pinned (direct_pin)."""
        pin: dict = {}
        miss = [{"event_pool": "0xdef456"}]
        count = _auto_pin_bridge_miss(miss, set(), pin, 1)
        assert count == 1
        assert pin["0xdef456"]["source"] == "bridge_miss_direct_pin"

    def test_skips_already_pinned(self):
        """Pool already pinned with ttl > 1 should NOT be re-pinned."""
        pin = {"0xabc123": {"ttl": 3, "last_iter": 0, "source": "old"}}
        miss = [{"event_pool": "0xabc123"}]
        count = _auto_pin_bridge_miss(miss, set(), pin, 1)
        assert count == 0
        assert pin["0xabc123"]["source"] == "old"

    def test_refreshes_expired_pin(self):
        """Pool with ttl ≤ 1 should be refreshed."""
        pin = {"0xabc123": {"ttl": 1, "last_iter": 0, "source": "old"}}
        miss = [{"event_pool": "0xabc123"}]
        count = _auto_pin_bridge_miss(miss, set(), pin, 5)
        assert count == 1
        assert pin["0xabc123"]["ttl"] == _HOT_SEEN_PIN_TTL_INIT
        assert pin["0xabc123"]["last_iter"] == 5

    def test_empty_miss_sample(self):
        """No bridge miss → no pins."""
        pin: dict = {}
        count = _auto_pin_bridge_miss([], set(), pin, 1)
        assert count == 0
        assert len(pin) == 0


# ---------------------------------------------------------------------------
# 3. Recoverable-stale route_viable split
# ---------------------------------------------------------------------------


def _split_recoverable_stale(candidates: list) -> tuple:
    """Mirror of 47k split: route_viable vs not_viable."""
    viable = [c for c in candidates if c.get("route_viable")]
    not_viable = [c for c in candidates if not c.get("route_viable")]
    return viable, not_viable


class TestRecoverableStaleSplit:

    def test_all_viable(self):
        """All route_viable → viable list only."""
        cands = [
            {"route_viable": True, "net_bps": 20.0},
            {"route_viable": True, "net_bps": 15.0},
        ]
        v, nv = _split_recoverable_stale(cands)
        assert len(v) == 2
        assert len(nv) == 0

    def test_all_not_viable(self):
        """All not route_viable → not_viable list only."""
        cands = [
            {"route_viable": False, "net_bps": 20.0},
        ]
        v, nv = _split_recoverable_stale(cands)
        assert len(v) == 0
        assert len(nv) == 1

    def test_mixed(self):
        """Mixed → correct split."""
        cands = [
            {"route_viable": True, "net_bps": 20.0},
            {"route_viable": False, "net_bps": 15.0},
            {"route_viable": True, "net_bps": 10.0},
        ]
        v, nv = _split_recoverable_stale(cands)
        assert len(v) == 2
        assert len(nv) == 1

    def test_empty(self):
        """Empty → both empty."""
        v, nv = _split_recoverable_stale([])
        assert v == []
        assert nv == []


# ---------------------------------------------------------------------------
# 4. C2 unknown-family safe default
# ---------------------------------------------------------------------------


def _c2_family_check(pool_addr: str, ptt: dict, gas_viable_families: set) -> bool:
    """Mirror of 47k C2 family check: unknown family → skip (False)."""
    ne_info = ptt.get(pool_addr) or ptt.get(pool_addr.lower())
    if ne_info and len(ne_info) >= 2:
        fam = tuple(sorted((ne_info[0].lower(), ne_info[1].lower())))
        return fam in gas_viable_families
    else:
        return False  # unknown family → skip


class TestC2UnknownFamily:

    def test_known_viable_family(self):
        """Known family in gas_viable → True."""
        ptt = {"0xaaa": ("WETH", "USDC", "v3")}
        families = {("usdc", "weth")}
        assert _c2_family_check("0xaaa", ptt, families) is True

    def test_known_nonviable_family(self):
        """Known family NOT in gas_viable → False."""
        ptt = {"0xaaa": ("ESP", "USDC", "v3")}
        families = {("usdc", "weth")}
        assert _c2_family_check("0xaaa", ptt, families) is False

    def test_unknown_family(self):
        """Pool not in PTT → False (safe default, 47k fix)."""
        ptt: dict = {}
        families = {("usdc", "weth")}
        assert _c2_family_check("0xaaa", ptt, families) is False

    def test_short_info(self):
        """Pool info with < 2 elements → False."""
        ptt = {"0xaaa": ("WETH",)}
        families = {("usdc", "weth")}
        assert _c2_family_check("0xaaa", ptt, families) is False


# ---------------------------------------------------------------------------
# 5. Bridge exclusion reasons
# ---------------------------------------------------------------------------


def _build_exclusion_reasons(
    ptt: dict,
    bridge_pool_addrs: set,
    family_counts: dict,
    remaining_ranked: list,
    gas_viable_families: set,
    family_cap: int = 8,
) -> list:
    """Mirror of 47k bridge exclusion reason builder."""
    excluded = []
    for pa in list(ptt.keys())[:200]:
        pa_low = pa.lower()
        if pa_low in bridge_pool_addrs:
            continue
        ne_info = ptt.get(pa_low) or ptt.get(pa)
        bx_fam = None
        if ne_info and len(ne_info) >= 2:
            bx_fam = tuple(sorted((ne_info[0].lower(), ne_info[1].lower())))
        if bx_fam and family_counts.get(bx_fam, 0) >= family_cap:
            reason = "family_cap"
        elif pa_low not in set(remaining_ranked):
            reason = "not_recently_active"
        elif bx_fam and bx_fam not in gas_viable_families:
            reason = "gas_too_negative"
        else:
            reason = "capacity_limit"
        excluded.append({"pool_address": pa_low, "exclude_reason": reason})
    return excluded


class TestBridgeExclusionReasons:

    def test_family_cap(self):
        """Pool excluded by family cap → 'family_cap'."""
        ptt = {"0xaaa": ("WETH", "USDC", "v3")}
        family = ("usdc", "weth")
        family_counts = {family: 8}
        excluded = _build_exclusion_reasons(
            ptt, set(), family_counts, ["0xaaa"], {family},
        )
        assert len(excluded) == 1
        assert excluded[0]["exclude_reason"] == "family_cap"

    def test_not_recently_active(self):
        """Pool not in remaining_ranked → 'not_recently_active'."""
        ptt = {"0xbbb": ("WETH", "USDC", "v3")}
        excluded = _build_exclusion_reasons(
            ptt, set(), {}, [], {("usdc", "weth")},
        )
        assert excluded[0]["exclude_reason"] == "not_recently_active"

    def test_gas_too_negative(self):
        """Pool in remaining but family not gas-viable → 'gas_too_negative'."""
        ptt = {"0xccc": ("ESP", "USDC", "v3")}
        excluded = _build_exclusion_reasons(
            ptt, set(), {}, ["0xccc"], {("usdc", "weth")},
        )
        assert excluded[0]["exclude_reason"] == "gas_too_negative"

    def test_capacity_limit(self):
        """Pool viable but no space → 'capacity_limit'."""
        ptt = {"0xddd": ("WETH", "USDC", "v3")}
        excluded = _build_exclusion_reasons(
            ptt, set(), {}, ["0xddd"], {("usdc", "weth")},
        )
        assert excluded[0]["exclude_reason"] == "capacity_limit"

    def test_included_pool_not_in_list(self):
        """Pool in bridge → not excluded."""
        ptt = {"0xeee": ("WETH", "USDC", "v3")}
        excluded = _build_exclusion_reasons(
            ptt, {"0xeee"}, {}, [], set(),
        )
        assert len(excluded) == 0


# ---------------------------------------------------------------------------
# 6. Session-scoped hot rollup reset
# ---------------------------------------------------------------------------


def _update_session_counters(rollup: dict, session_id: str) -> dict:
    """Mirror of 47k session-scoped rollup logic."""
    if rollup.get("session", {}).get("session_id") != session_id:
        rollup["session"] = {
            "session_id": session_id,
            "session_started_at": "now",
            "session_windows_seen": 0,
            "session_events_seen_total": 0,
            "session_bridge_pool_hit_total": 0,
            "session_fast_path_scored_total": 0,
        }
    return rollup


class TestSessionScopedRollup:

    def test_new_session_resets(self):
        """New session ID resets session counters."""
        rollup = {
            "session": {
                "session_id": "old-id",
                "session_windows_seen": 50,
                "session_events_seen_total": 200,
            }
        }
        _update_session_counters(rollup, "new-id")
        assert rollup["session"]["session_id"] == "new-id"
        assert rollup["session"]["session_windows_seen"] == 0
        assert rollup["session"]["session_events_seen_total"] == 0

    def test_same_session_preserves(self):
        """Same session ID preserves counters."""
        rollup = {
            "session": {
                "session_id": "keep-id",
                "session_windows_seen": 50,
                "session_events_seen_total": 200,
            }
        }
        _update_session_counters(rollup, "keep-id")
        assert rollup["session"]["session_windows_seen"] == 50

    def test_first_init(self):
        """Empty rollup → session block created."""
        rollup: dict = {}
        _update_session_counters(rollup, "first-id")
        assert rollup["session"]["session_id"] == "first-id"
        assert rollup["session"]["session_windows_seen"] == 0
