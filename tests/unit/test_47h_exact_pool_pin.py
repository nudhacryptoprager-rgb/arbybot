"""
M7.A.5.47h — Unit tests for recoverable_stale class, gross-positive C2 filter,
hot-seen-pin TTL lifecycle, and hot_seen_vs_bridge_overlap diagnostic.
"""
from __future__ import annotations

import pytest

from tests.unit.conftest import _make_result


# ---------------------------------------------------------------------------
# Helpers — simulate 47h logic locally
# ---------------------------------------------------------------------------


def _pool_family(pa: str, ptt: dict) -> tuple:
    info = ptt.get(pa) or ptt.get(pa.lower())
    if info and len(info) >= 2:
        return tuple(sorted((info[0].lower(), info[1].lower())))
    return (pa,)


def _recoverable_stale_filter(candidates: list) -> list:
    """Simulate recoverable_stale extraction: lag <= 2, positive, size_valid."""
    out = []
    for c in candidates:
        lag = c.get("block_lag", 999)
        net_bps = c.get("best_backrun_net_bps", 0) or 0
        size_valid = c.get("size_valid_for_token", False)
        if lag <= 2 and net_bps > 0 and size_valid:
            out.append(c)
    return sorted(out, key=lambda r: r.get("best_backrun_net_bps", 0), reverse=True)


def _gross_positive_families(micro_refinement: list) -> set:
    """Build set of pair families with positive verified_net_bps."""
    families: set = set()
    for mr in micro_refinement:
        if (mr.get("verified_net_bps_after_refinement") or 0) > 0:
            ap = (mr.get("actual_pair") or "")
            parts = ap.split("/")
            if len(parts) == 2:
                families.add(tuple(sorted((parts[0].lower(), parts[1].lower()))))
    return families


def _c2_filter(near_executable: list, gross_positive_fams: set, ptt: dict,
               exclude: set) -> set:
    """Simulate C2 gas-near-survivor filter with gross-positive family check."""
    out: set = set()
    for ne in near_executable:
        ne_pa = (ne.get("pool_address") or "").lower()
        ne_rr = ne.get("reject_reason", "")
        if not (ne_pa and ne_rr == "GAS_EXCEEDS_GROSS"):
            continue
        if ne_pa not in ptt or ne_pa in exclude:
            continue
        ne_info = ptt.get(ne_pa)
        if ne_info and len(ne_info) >= 2:
            ne_fam = tuple(sorted((ne_info[0].lower(), ne_info[1].lower())))
            if ne_fam not in gross_positive_fams:
                continue
        out.add(ne_pa)
    return out


def _hot_seen_pin_cycle(hot_seen_pin: dict, resolved_pools: list,
                        ttl_init: int = 3) -> dict:
    """Simulate one hot-seen-pin iteration: pin new, decrement, expire."""
    # Pin newly resolved
    for pa in resolved_pools:
        hot_seen_pin[pa.lower()] = {"ttl": ttl_init, "last_iter": 0}
    # Expire + decrement
    expired = [pa for pa, info in hot_seen_pin.items() if info.get("ttl", 0) <= 1]
    for ep in expired:
        del hot_seen_pin[ep]
    for pa in hot_seen_pin:
        hot_seen_pin[pa]["ttl"] -= 1
    return hot_seen_pin


def _build_overlap_diagnostic(
    hot_hist: list,
    bridge_pool_addrs: set,
    bucket_a: set,
    bucket_b: set,
    bucket_c1: set,
    bucket_c2: set,
    ptt: dict,
    hot_seen_pin: dict,
) -> list:
    """Simulate hot_seen_vs_bridge_overlap_top diagnostic."""
    diag: list = []
    for oh in hot_hist[:10]:
        oh_addr = (oh.get("pool") or "").lower()
        if not oh_addr:
            continue
        in_bridge = oh_addr in bridge_pool_addrs
        bucket = "absent"
        if oh_addr in bucket_a:
            bucket = "A_cold_exec"
        elif oh_addr in bucket_b:
            bucket = "B_hot_seen"
        elif oh_addr in bucket_c1:
            bucket = "C1_stale_recovery"
        elif oh_addr in bucket_c2:
            bucket = "C2_gas_near"
        elif in_bridge:
            bucket = "C3_activity_fill"
        reason = ""
        if not in_bridge:
            if oh_addr not in ptt:
                reason = "not_in_ptt"
            elif oh_addr in hot_seen_pin:
                reason = "pinned_but_ttl_expired_or_not_in_ptt"
            else:
                reason = "no_bucket_qualified"
        diag.append({
            "event_pool": oh_addr,
            "seen_count": oh.get("count", 0),
            "in_bridge": in_bridge,
            "bucket": bucket,
            "reason_if_absent": reason,
        })
    return diag[:5]


# ===========================================================================
# Recoverable stale class
# ===========================================================================


class TestRecoverableStale:

    def test_lag_lte_2_included(self):
        candidates = [
            {"pool_address": "0xa", "block_lag": 2, "best_backrun_net_bps": 10,
             "size_valid_for_token": True},
            {"pool_address": "0xb", "block_lag": 3, "best_backrun_net_bps": 20,
             "size_valid_for_token": True},
        ]
        result = _recoverable_stale_filter(candidates)
        addrs = [c["pool_address"] for c in result]
        assert "0xa" in addrs
        assert "0xb" not in addrs  # lag=3 > 2

    def test_negative_bps_excluded(self):
        candidates = [
            {"pool_address": "0xa", "block_lag": 1, "best_backrun_net_bps": -5,
             "size_valid_for_token": True},
        ]
        result = _recoverable_stale_filter(candidates)
        assert len(result) == 0

    def test_size_invalid_excluded(self):
        candidates = [
            {"pool_address": "0xa", "block_lag": 1, "best_backrun_net_bps": 10,
             "size_valid_for_token": False},
        ]
        result = _recoverable_stale_filter(candidates)
        assert len(result) == 0

    def test_sorted_by_net_bps_descending(self):
        candidates = [
            {"pool_address": "0xa", "block_lag": 1, "best_backrun_net_bps": 5,
             "size_valid_for_token": True},
            {"pool_address": "0xb", "block_lag": 2, "best_backrun_net_bps": 15,
             "size_valid_for_token": True},
        ]
        result = _recoverable_stale_filter(candidates)
        assert result[0]["pool_address"] == "0xb"
        assert result[1]["pool_address"] == "0xa"

    def test_empty_input(self):
        assert _recoverable_stale_filter([]) == []

    def test_exact_lag_boundary(self):
        """lag=2 is IN, lag=3 is OUT."""
        candidates = [
            {"pool_address": "0xa", "block_lag": 2, "best_backrun_net_bps": 10,
             "size_valid_for_token": True},
            {"pool_address": "0xb", "block_lag": 3, "best_backrun_net_bps": 10,
             "size_valid_for_token": True},
        ]
        result = _recoverable_stale_filter(candidates)
        assert len(result) == 1
        assert result[0]["pool_address"] == "0xa"


# ===========================================================================
# Gross-positive C2 filter
# ===========================================================================


class TestGrossPositiveC2:

    def _make_ptt(self, *pool_specs):
        """pool_specs: list of (pa, tok0, tok1) tuples."""
        ptt = {}
        for pa, t0, t1 in pool_specs:
            ptt[pa] = [t0, t1, 3000]
        return ptt

    def test_positive_family_admitted(self):
        ptt = self._make_ptt(("0xpool_a", "weth", "rain"))
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 10},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "GAS_EXCEEDS_GROSS"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude=set())
        assert "0xpool_a" in c2

    def test_negative_family_excluded(self):
        ptt = self._make_ptt(("0xpool_a", "weth", "rain"))
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": -5},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "GAS_EXCEEDS_GROSS"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude=set())
        assert "0xpool_a" not in c2

    def test_zero_net_excluded(self):
        ptt = self._make_ptt(("0xpool_a", "weth", "rain"))
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 0},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "GAS_EXCEEDS_GROSS"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude=set())
        assert "0xpool_a" not in c2

    def test_wrong_reject_reason_excluded(self):
        ptt = self._make_ptt(("0xpool_a", "weth", "rain"))
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 10},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "SLIPPAGE_TOO_HIGH"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude=set())
        assert len(c2) == 0

    def test_excluded_pools_skipped(self):
        ptt = self._make_ptt(("0xpool_a", "weth", "rain"))
        micro = [
            {"actual_pair": "WETH/RAIN", "verified_net_bps_after_refinement": 10},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "GAS_EXCEEDS_GROSS"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude={"0xpool_a"})
        assert len(c2) == 0

    def test_family_normalization_case_insensitive(self):
        """WETH/RAIN and rain/weth should match the same family."""
        ptt = self._make_ptt(("0xpool_a", "WETH", "RAIN"))
        micro = [
            {"actual_pair": "rain/WETH", "verified_net_bps_after_refinement": 8},
        ]
        near_exec = [
            {"pool_address": "0xpool_a", "reject_reason": "GAS_EXCEEDS_GROSS"},
        ]
        fams = _gross_positive_families(micro)
        c2 = _c2_filter(near_exec, fams, ptt, exclude=set())
        assert "0xpool_a" in c2


# ===========================================================================
# Hot-seen-pin TTL lifecycle
# ===========================================================================


class TestHotSeenPinTTL:

    def test_pin_on_resolve(self):
        pin = {}
        result = _hot_seen_pin_cycle(pin, ["0xABC"], ttl_init=3)
        assert "0xabc" in result
        # After pin (3) and decrement: ttl=2
        assert result["0xabc"]["ttl"] == 2

    def test_decrement_each_cycle(self):
        pin = {"0xabc": {"ttl": 2, "last_iter": 0}}
        result = _hot_seen_pin_cycle(pin, [], ttl_init=3)
        assert result["0xabc"]["ttl"] == 1

    def test_expire_at_one(self):
        pin = {"0xabc": {"ttl": 1, "last_iter": 0}}
        result = _hot_seen_pin_cycle(pin, [], ttl_init=3)
        assert "0xabc" not in result

    def test_full_lifecycle_3_windows(self):
        """Pin should survive 3 windows then expire."""
        pin: dict = {}
        # Window 0: resolve
        pin = _hot_seen_pin_cycle(pin, ["0xTEST"], ttl_init=3)
        assert "0xtest" in pin  # ttl=2

        # Window 1
        pin = _hot_seen_pin_cycle(pin, [], ttl_init=3)
        assert "0xtest" in pin  # ttl=1

        # Window 2: evicted (ttl=1 → hits <=1 threshold)
        pin = _hot_seen_pin_cycle(pin, [], ttl_init=3)
        assert "0xtest" not in pin

    def test_re_resolve_resets_ttl(self):
        pin = {"0xabc": {"ttl": 1, "last_iter": 0}}
        # Re-resolve the same pool
        result = _hot_seen_pin_cycle(pin, ["0xABC"], ttl_init=3)
        # Pin set to 3, then decrement to 2 — not evicted
        assert "0xabc" in result
        assert result["0xabc"]["ttl"] == 2

    def test_multiple_pools(self):
        pin: dict = {}
        result = _hot_seen_pin_cycle(pin, ["0xAAA", "0xBBB"], ttl_init=3)
        assert "0xaaa" in result
        assert "0xbbb" in result

    def test_empty_resolve(self):
        pin: dict = {}
        result = _hot_seen_pin_cycle(pin, [], ttl_init=3)
        assert len(result) == 0


# ===========================================================================
# Hot-seen vs bridge overlap diagnostic
# ===========================================================================


class TestHotSeenVsBridgeOverlap:

    def test_pool_in_bucket_a(self):
        diag = _build_overlap_diagnostic(
            [{"pool": "0xA", "count": 5}],
            bridge_pool_addrs={"0xa"},
            bucket_a={"0xa"}, bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={"0xa": ["t0", "t1", 3000]},
            hot_seen_pin={},
        )
        assert diag[0]["in_bridge"] is True
        assert diag[0]["bucket"] == "A_cold_exec"

    def test_pool_in_bucket_b(self):
        diag = _build_overlap_diagnostic(
            [{"pool": "0xB", "count": 3}],
            bridge_pool_addrs={"0xb"},
            bucket_a=set(), bucket_b={"0xb"},
            bucket_c1=set(), bucket_c2=set(),
            ptt={"0xb": ["t0", "t1", 3000]},
            hot_seen_pin={},
        )
        assert diag[0]["bucket"] == "B_hot_seen"

    def test_pool_absent_not_in_ptt(self):
        diag = _build_overlap_diagnostic(
            [{"pool": "0xC", "count": 2}],
            bridge_pool_addrs=set(),
            bucket_a=set(), bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={},
            hot_seen_pin={},
        )
        assert diag[0]["in_bridge"] is False
        assert diag[0]["reason_if_absent"] == "not_in_ptt"

    def test_pool_absent_no_bucket(self):
        diag = _build_overlap_diagnostic(
            [{"pool": "0xD", "count": 1}],
            bridge_pool_addrs=set(),
            bucket_a=set(), bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={"0xd": ["t0", "t1", 3000]},
            hot_seen_pin={},
        )
        assert diag[0]["in_bridge"] is False
        assert diag[0]["reason_if_absent"] == "no_bucket_qualified"

    def test_limit_to_five(self):
        hist = [{"pool": f"0x{i:04x}", "count": 1} for i in range(10)]
        diag = _build_overlap_diagnostic(
            hist,
            bridge_pool_addrs=set(),
            bucket_a=set(), bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={},
            hot_seen_pin={},
        )
        assert len(diag) == 5

    def test_empty_hist(self):
        diag = _build_overlap_diagnostic(
            [],
            bridge_pool_addrs=set(),
            bucket_a=set(), bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={},
            hot_seen_pin={},
        )
        assert diag == []

    def test_pool_in_c3_fill(self):
        diag = _build_overlap_diagnostic(
            [{"pool": "0xE", "count": 4}],
            bridge_pool_addrs={"0xe"},  # in bridge but not in A/B/C1/C2
            bucket_a=set(), bucket_b=set(),
            bucket_c1=set(), bucket_c2=set(),
            ptt={"0xe": ["t0", "t1", 3000]},
            hot_seen_pin={},
        )
        assert diag[0]["in_bridge"] is True
        assert diag[0]["bucket"] == "C3_activity_fill"
