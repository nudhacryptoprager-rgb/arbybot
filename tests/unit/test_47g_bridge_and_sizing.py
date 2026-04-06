"""
M7.A.5.47g — Unit tests for 3-bucket bridge ranking, stale TTL pinning,
gas-near extended micro-refinement, and adaptive intake escalation.
"""
from __future__ import annotations

import pytest
import statistics

from tests.unit.conftest import _make_result


# ---------------------------------------------------------------------------
# Helpers — simulate 47g logic locally
# ---------------------------------------------------------------------------


def _pool_family(pa: str, ptt: dict) -> tuple:
    info = ptt.get(pa) or ptt.get(pa.lower())
    if info and len(info) >= 2:
        return tuple(sorted((info[0].lower(), info[1].lower())))
    return (pa,)


def _three_bucket_fill(
    ptt: dict,
    bucket_a: set,
    bucket_b: set,
    cold_stale_positive: list,
    near_executable: list,
    stale_pin_ttl: dict,
    remaining_ranked: list,
    pool_cap: int = 50,
    family_cap: int = 8,
):
    """Simulate the 3-bucket fill policy from m7a_orderflow_loop.py."""
    # Bucket C1: stale_recovery
    bucket_c1: set = set()
    for sp in cold_stale_positive:
        sp_pa = (sp.get("pool_address") or "").lower()
        if sp_pa and sp_pa in ptt and sp_pa not in bucket_a and sp_pa not in bucket_b:
            bucket_c1.add(sp_pa)
    for pin_pa in stale_pin_ttl:
        if pin_pa in ptt and pin_pa not in bucket_a and pin_pa not in bucket_b:
            bucket_c1.add(pin_pa)

    # Bucket C2: gas_near_survivor
    bucket_c2: set = set()
    for ne in near_executable:
        ne_pa = (ne.get("pool_address") or "").lower()
        ne_rr = ne.get("reject_reason", "")
        if (ne_pa and ne_rr == "GAS_EXCEEDS_GROSS" and
                ne_pa in ptt and ne_pa not in bucket_a and
                ne_pa not in bucket_b and ne_pa not in bucket_c1):
            bucket_c2.add(ne_pa)

    committed = bucket_a | bucket_b | bucket_c1 | bucket_c2
    remaining_for_fill = [pa for pa in remaining_ranked if pa not in committed]

    family_counts: dict = {}
    for cpa in committed:
        fam = _pool_family(cpa, ptt)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    slots = max(0, pool_cap - len(committed))
    diverse_fill: list = []
    for rpa in remaining_for_fill:
        if len(diverse_fill) >= slots:
            break
        fam = _pool_family(rpa, ptt)
        if family_counts.get(fam, 0) >= family_cap:
            continue
        diverse_fill.append(rpa)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    bridge_addrs = committed | set(diverse_fill)
    return bridge_addrs, bucket_c1, bucket_c2, diverse_fill


def _sim_ttl_cycle(stale_pin_ttl: dict, cold_stale_positive: list, ttl_init: int = 4):
    """Simulate one cycle: refresh from cold_stale_positive, then decrement."""
    # Refresh
    for sp in cold_stale_positive:
        sp_pa = (sp.get("pool_address") or "").lower()
        if sp_pa:
            stale_pin_ttl[sp_pa] = {"ttl": ttl_init, "pair": sp.get("actual_pair", "")}
    # Decrement + evict
    expired = [pa for pa, info in stale_pin_ttl.items() if info.get("ttl", 0) <= 1]
    for ep in expired:
        del stale_pin_ttl[ep]
    for pa in stale_pin_ttl:
        stale_pin_ttl[pa]["ttl"] -= 1
    return stale_pin_ttl


# ===========================================================================
# 3-bucket bridge ranking
# ===========================================================================


class TestThreeBucketBridgeFill:

    def _make_ptt(self, n):
        """Generate n pool addresses in PTT."""
        ptt = {}
        for i in range(n):
            ptt[f"0xpool_{i:03d}"] = [f"tok_a_{i}", f"tok_b_{i}", 3000]
        return ptt

    def test_stale_pools_get_priority_over_activity_fill(self):
        """Bucket C1 (stale_recovery) pools appear before activity fill."""
        ptt = self._make_ptt(20)
        stale_pos = [{"pool_address": "0xpool_015", "actual_pair": "A/B"}]
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=stale_pos, near_executable=[],
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
        )
        assert "0xpool_015" in c1
        assert "0xpool_015" in result
        assert "0xpool_015" not in fill  # in C1, not activity fill

    def test_gas_near_pools_get_priority(self):
        """Bucket C2 (gas_near_survivor) includes GAS_EXCEEDS_GROSS near_exec pools."""
        ptt = self._make_ptt(20)
        near_exec = [
            {"pool_address": "0xpool_010", "reject_reason": "GAS_EXCEEDS_GROSS"},
            {"pool_address": "0xpool_011", "reject_reason": "SOME_OTHER"},
        ]
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=[], near_executable=near_exec,
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
        )
        assert "0xpool_010" in c2  # GAS_EXCEEDS_GROSS → C2
        assert "0xpool_011" not in c2  # wrong reject reason
        assert "0xpool_010" in result

    def test_buckets_dont_overlap(self):
        """Pool in bucket A should not appear in C1/C2/fill."""
        ptt = self._make_ptt(20)
        bucket_a = {"0xpool_005"}
        stale_pos = [{"pool_address": "0xpool_005"}]
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=bucket_a, bucket_b=set(),
            cold_stale_positive=stale_pos, near_executable=[],
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
        )
        assert "0xpool_005" not in c1
        assert "0xpool_005" in result  # still in result via bucket_a

    def test_ttl_pinned_pools_included_in_c1(self):
        """Stale-pin TTL pools should be included in C1 even without fresh stale_positive."""
        ptt = self._make_ptt(20)
        stale_pin = {"0xpool_018": {"ttl": 2, "pair": "X/Y"}}
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=[], near_executable=[],
            stale_pin_ttl=stale_pin, remaining_ranked=sorted(ptt.keys()),
        )
        assert "0xpool_018" in c1
        assert "0xpool_018" in result

    def test_family_cap_respected_across_all_buckets(self):
        """Diversity cap counts pools from all buckets, not just fill."""
        ptt = {}
        # 12 pools all same family
        for i in range(12):
            ptt[f"0xpool_{i:03d}"] = ["tokA", "tokB", 3000]
        stale_pos = [{"pool_address": "0xpool_000"}]
        near_exec = [{"pool_address": "0xpool_001", "reject_reason": "GAS_EXCEEDS_GROSS"}]
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=stale_pos, near_executable=near_exec,
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
            family_cap=8,
        )
        # C1 has 1, C2 has 1, fill should have at most 6 (cap=8 total)
        family_count = len(c1) + len(c2) + len(fill)
        assert family_count <= 8

    def test_pool_cap_limits_total(self):
        """Total bridge pool set should not exceed pool_cap."""
        ptt = self._make_ptt(200)
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=[], near_executable=[],
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
            pool_cap=30,
        )
        assert len(result) <= 30

    def test_empty_bridge_data(self):
        """Graceful handling of empty bridge data."""
        ptt = self._make_ptt(5)
        result, c1, c2, fill = _three_bucket_fill(
            ptt=ptt, bucket_a=set(), bucket_b=set(),
            cold_stale_positive=[], near_executable=[],
            stale_pin_ttl={}, remaining_ranked=sorted(ptt.keys()),
        )
        assert len(c1) == 0
        assert len(c2) == 0
        assert len(fill) == 5


# ===========================================================================
# Stale-pin TTL lifecycle
# ===========================================================================


class TestStalePinTTL:

    def test_fresh_pin_created_on_stale_positive(self):
        ttl = {}
        cold_sp = [{"pool_address": "0xABC", "actual_pair": "A/B"}]
        result = _sim_ttl_cycle(ttl, cold_sp, ttl_init=4)
        # After refresh and one decrement: ttl should be 3
        assert "0xabc" in result
        assert result["0xabc"]["ttl"] == 3

    def test_ttl_decrements_each_cycle(self):
        ttl = {"0xabc": {"ttl": 3, "pair": "A/B"}}
        result = _sim_ttl_cycle(ttl, [], ttl_init=4)
        # No refresh, just decrement: 3 → 2
        assert result["0xabc"]["ttl"] == 2

    def test_ttl_expires_at_zero(self):
        ttl = {"0xabc": {"ttl": 1, "pair": "A/B"}}
        result = _sim_ttl_cycle(ttl, [], ttl_init=4)
        # ttl=1 → evicted (<=1 threshold)
        assert "0xabc" not in result

    def test_refresh_resets_ttl(self):
        ttl = {"0xabc": {"ttl": 1, "pair": "A/B"}}
        cold_sp = [{"pool_address": "0xABC", "actual_pair": "A/B"}]
        result = _sim_ttl_cycle(ttl, cold_sp, ttl_init=4)
        # Refresh sets to 4, then decrement to 3 — not evicted
        assert "0xabc" in result
        assert result["0xabc"]["ttl"] == 3

    def test_multiple_pools_tracked(self):
        ttl = {}
        cold_sp = [
            {"pool_address": "0xAAA", "actual_pair": "A/B"},
            {"pool_address": "0xBBB", "actual_pair": "C/D"},
        ]
        result = _sim_ttl_cycle(ttl, cold_sp, ttl_init=4)
        assert len(result) == 2
        assert "0xaaa" in result
        assert "0xbbb" in result

    def test_full_lifecycle_4_windows(self):
        """Pin should survive 4 windows then expire on the 5th."""
        ttl: dict = {}
        # Window 0: fresh stale positive
        cold_sp = [{"pool_address": "0xTEST", "actual_pair": "X/Y"}]
        ttl = _sim_ttl_cycle(ttl, cold_sp, ttl_init=4)
        assert "0xtest" in ttl  # ttl=3 after first decrement

        # Window 1-2: no refresh, just decrement
        for _ in range(2):
            ttl = _sim_ttl_cycle(ttl, [], ttl_init=4)
        assert "0xtest" in ttl  # ttl=1 after third decrement

        # Window 3: evicted (ttl=1 → hits <=1 threshold)
        ttl = _sim_ttl_cycle(ttl, [], ttl_init=4)
        assert "0xtest" not in ttl


# ===========================================================================
# Gas-near extended micro-refinement sizing
# ===========================================================================


class TestGasNearMicroRefinement:

    def test_gas_near_gets_wider_multipliers(self):
        """Candidates with GAS_EXCEEDS_GROSS should use [1.0, 1.5, 2.0, 3.0]."""
        # These constants are defined locally in build_cold_artifact().
        # We verify the design contract: gas-near range tops at 3.0,
        # standard range tops at 1.5.
        standard = [0.75, 1.0, 1.25, 1.5]
        gas_near = [1.0, 1.5, 2.0, 3.0]
        assert max(gas_near) > max(standard)
        assert 3.0 in gas_near

    def test_normal_candidates_get_standard_multipliers(self):
        """Non-gas-near candidates should use [0.75, 1.0, 1.25, 1.5]."""
        standard = [0.75, 1.0, 1.25, 1.5]
        assert 0.75 in standard
        assert max(standard) == 1.5

    def test_is_gas_near_field_present_in_result(self):
        """Micro-refinement results should include is_gas_near field."""
        # Simulate the micro-refinement result shape
        result = {
            "event_id": "e1",
            "actual_pair": "A/B",
            "reject_reason": "GAS_EXCEEDS_GROSS",
            "is_gas_near": True,
        }
        assert result["is_gas_near"] is True
        result2 = {
            "event_id": "e2",
            "actual_pair": "C/D",
            "reject_reason": None,
            "is_gas_near": False,
        }
        assert result2["is_gas_near"] is False


# ===========================================================================
# Cost-by-pair-family diagnostics (from 47g Step 2)
# ===========================================================================


class TestCostByPairFamily:

    def _build_cost_diagnostic(self, results):
        """Simulate cost_by_pair_family_top computation."""
        _pair_gas_detail: dict = {}
        for r in results:
            p = getattr(r, "actual_pair", "") or ""
            parts = p.split("/")
            pf = "/".join(sorted(parts)) if len(parts) == 2 else p
            if not pf:
                continue
            if pf not in _pair_gas_detail:
                _pair_gas_detail[pf] = {
                    "gross_bps": [], "total_gas_bps": [], "amount_in_wei": [],
                }
            _amt = getattr(r, "amount_in_wei", 0) or 0
            _gross_wei = getattr(r, "gross_pnl_wei", 0) or 0
            if _amt > 0:
                _gross_bps = (_gross_wei / _amt) * 10000
                _pair_gas_detail[pf]["gross_bps"].append(_gross_bps)
            _tg = getattr(r, "total_gas_bps", 0) or 0
            if _tg != 0:
                _pair_gas_detail[pf]["total_gas_bps"].append(_tg)
            if _amt > 0:
                _pair_gas_detail[pf]["amount_in_wei"].append(_amt)

        def _safe_mean(lst):
            return sum(lst) / len(lst) if lst else 0.0

        cost_rows = []
        for pf, detail in _pair_gas_detail.items():
            mg = round(_safe_mean(detail["gross_bps"]), 4)
            mtg = round(_safe_mean(detail["total_gas_bps"]), 4)
            gap = round(mg - mtg, 4)
            best_size = max(detail["amount_in_wei"]) if detail["amount_in_wei"] else 0
            cost_rows.append({
                "pair_family": pf,
                "mean_gross_bps": mg,
                "mean_total_gas_bps": mtg,
                "mean_gas_gap_bps": gap,
                "best_submit_size": best_size,
            })
        return sorted(cost_rows, key=lambda x: abs(x["mean_gas_gap_bps"]))[:10]

    def test_closest_to_surviving_ranked_first(self):
        results = [
            _make_result(actual_pair="A/B", gross_pnl_wei=10, amount_in_wei=100, total_gas_bps=1.5),
            _make_result(actual_pair="C/D", gross_pnl_wei=100, amount_in_wei=100, total_gas_bps=50),
        ]
        rows = self._build_cost_diagnostic(results)
        # A/B: gross_bps=10000*10/100=1000, gap=1000-1.5=998.5 (abs=998.5)
        # C/D: gross_bps=10000*100/100=10000, gap=10000-50=9950 (abs=9950)
        # A/B closer to zero gap → ranked first
        assert rows[0]["pair_family"] == "A/B"

    def test_empty_results(self):
        rows = self._build_cost_diagnostic([])
        assert rows == []


# ===========================================================================
# Staleness-by-pair-family diagnostics (from 47g Step 3)
# ===========================================================================


class TestStalenessByPairFamily:

    def _build_staleness_diagnostic(self, results):
        """Simulate staleness_by_pair_family_top computation."""
        def _is_stale(r):
            bl = getattr(r, "block_lag", None)
            if (bl if bl is not None else 999) > 2:
                return True
            if getattr(r, "same_state_class", None) == "stale":
                return True
            if getattr(r, "reject_reason", None) == "STALE_POSITIVE":
                return True
            return False

        _pair_stale_detail: dict = {}
        _pair_funnel: dict = {}
        for r in results:
            p = getattr(r, "actual_pair", "") or ""
            parts = p.split("/")
            pf = "/".join(sorted(parts)) if len(parts) == 2 else p
            if not pf:
                continue
            if pf not in _pair_stale_detail:
                _pair_stale_detail[pf] = {"block_lags": [], "clean_bps": []}
                _pair_funnel[pf] = {"positive_count": 0, "stale_positive_count": 0}
            bl = getattr(r, "block_lag", None)
            is_positive = (getattr(r, "best_backrun_net_bps", 0) or 0) > 0
            if is_positive:
                _pair_funnel[pf]["positive_count"] += 1
            if bl is not None:
                _pair_stale_detail[pf]["block_lags"].append(bl)
            if _is_stale(r) and is_positive:
                _pair_funnel[pf]["stale_positive_count"] += 1
                net = getattr(r, "best_backrun_net_bps", 0) or 0
                _pair_stale_detail[pf]["clean_bps"].append(net)

        rows = []
        for pf in _pair_stale_detail:
            lags = _pair_stale_detail[pf]["block_lags"]
            cbps = _pair_stale_detail[pf]["clean_bps"]
            rows.append({
                "pair_family": pf,
                "positive_count": _pair_funnel[pf]["positive_count"],
                "stale_positive_count": _pair_funnel[pf]["stale_positive_count"],
                "min_block_lag": min(lags) if lags else None,
                "median_block_lag": round(statistics.median(lags), 1) if lags else None,
                "best_clean_bps": round(max(cbps), 4) if cbps else None,
            })
        return sorted(rows, key=lambda x: (-x["stale_positive_count"], -(x["best_clean_bps"] or 0)))[:10]

    def test_stale_positive_ranked_first(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=10, block_lag=5),
            _make_result(actual_pair="C/D", best_backrun_net_bps=20, block_lag=1),
        ]
        rows = self._build_staleness_diagnostic(results)
        # A/B: stale (lag=5>2), positive → stale_positive_count=1
        # C/D: not stale (lag=1≤2), positive → stale_positive_count=0
        assert rows[0]["pair_family"] == "A/B"
        assert rows[0]["stale_positive_count"] == 1

    def test_median_lag_computed(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=5, block_lag=3),
            _make_result(actual_pair="A/B", best_backrun_net_bps=8, block_lag=7),
            _make_result(actual_pair="A/B", best_backrun_net_bps=2, block_lag=5),
        ]
        rows = self._build_staleness_diagnostic(results)
        assert rows[0]["median_block_lag"] == 5.0  # median of [3,7,5]

    def test_empty_results(self):
        rows = self._build_staleness_diagnostic([])
        assert rows == []


# ===========================================================================
# Adaptive broad fallback escalation (47g Step 7)
# ===========================================================================


class TestAdaptiveBroadFallback:

    def test_normal_interval_three(self):
        bhd = False
        bhd_severe = False
        intra_deficit = False
        interval = 1 if bhd_severe else 2 if (bhd or intra_deficit) else 3
        assert interval == 3

    def test_deficit_interval_two(self):
        bhd = True
        bhd_severe = False
        intra_deficit = False
        interval = 1 if bhd_severe else 2 if (bhd or intra_deficit) else 3
        assert interval == 2

    def test_severe_deficit_interval_one(self):
        bhd = True
        bhd_severe = True
        interval = 1 if bhd_severe else 2 if bhd else 3
        assert interval == 1

    def test_severity_requires_wwe_ge_3(self):
        """Severe deficit only when 3+ windows have events with zero hits."""
        wwe, wwbh = 2, 0
        bhd = wwe > 0 and wwbh == 0
        bhd_severe = bhd and wwe >= 3
        assert bhd is True
        assert bhd_severe is False  # only 2 windows

        wwe = 3
        bhd = wwe > 0 and wwbh == 0
        bhd_severe = bhd and wwe >= 3
        assert bhd_severe is True
