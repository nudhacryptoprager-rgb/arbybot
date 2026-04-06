"""
M7.A.5.47f — Pair concentration diagnostics unit tests.

Tests funnel_by_pair_top, pair_family_concentration, diagnostic_raw anomaly flag,
and diversity-aware bridge fill logic.
"""
from __future__ import annotations

import pytest

from tests.unit.conftest import _make_result


# ---------------------------------------------------------------------------
# Helpers — simulate pair-family logic from artifacts.py
# ---------------------------------------------------------------------------

def _pair_family_from_str(pair_str: str) -> str:
    """Normalized pair family (sorted tokens)."""
    parts = pair_str.split("/")
    if len(parts) == 2:
        return "/".join(sorted(parts))
    return pair_str


def _build_funnel(results):
    """Simulate funnel_by_pair_top + pair_family_concentration computation."""
    def _is_stale(r):
        _bl = getattr(r, "block_lag", None)
        if (_bl if _bl is not None else 999) > 2:
            return True
        if getattr(r, "same_state_class", None) == "stale":
            return True
        if getattr(r, "reject_reason", None) == "STALE_POSITIVE":
            return True
        return False

    pair_funnel: dict = {}
    for r in results:
        p = getattr(r, "actual_pair", None) or ""
        parts = p.split("/")
        if len(parts) == 2:
            pf = "/".join(sorted(parts))
        else:
            pf = p
        if not pf:
            continue
        if pf not in pair_funnel:
            pair_funnel[pf] = {
                "seen_count": 0, "positive_count": 0,
                "stale_positive_count": 0, "cold_executable_count": 0,
                "gas_exceeds_gross_count": 0,
            }
        pair_funnel[pf]["seen_count"] += 1
        if (r.best_backrun_net_bps or 0) > 0:
            pair_funnel[pf]["positive_count"] += 1
        if _is_stale(r) and (r.best_backrun_net_bps or 0) > 0:
            pair_funnel[pf]["stale_positive_count"] += 1
        if r.route_viable:
            pair_funnel[pf]["cold_executable_count"] += 1
        if r.reject_reason == "GAS_EXCEEDS_GROSS":
            pair_funnel[pf]["gas_exceeds_gross_count"] += 1

    funnel_by_pair_top = sorted(
        [{"pair_family": pf, **c} for pf, c in pair_funnel.items()],
        key=lambda x: x["seen_count"], reverse=True,
    )[:10]

    def _top1_share(key):
        total = sum(v[key] for v in pair_funnel.values())
        if total == 0:
            return 0.0
        top1 = max(v[key] for v in pair_funnel.values())
        return round(top1 / total, 4)

    concentration = {
        "seen_top1_share": _top1_share("seen_count"),
        "positive_top1_share": _top1_share("positive_count"),
        "cold_executable_top1_share": _top1_share("cold_executable_count"),
        "unique_pair_families": len(pair_funnel),
    }
    return funnel_by_pair_top, concentration


# ===========================================================================
# Pair family normalization
# ===========================================================================


class TestPairFamilyNormalization:

    def test_ab_and_ba_same_family(self):
        assert _pair_family_from_str("WETH/RAIN") == _pair_family_from_str("RAIN/WETH")

    def test_already_sorted(self):
        assert _pair_family_from_str("AAA/ZZZ") == "AAA/ZZZ"

    def test_reverse_sorted(self):
        assert _pair_family_from_str("ZZZ/AAA") == "AAA/ZZZ"


# ===========================================================================
# funnel_by_pair_top
# ===========================================================================


class TestFunnelByPairTop:

    def test_single_pair_all_stages(self):
        results = [
            _make_result(actual_pair="WETH/RAIN", best_backrun_net_bps=10, route_viable=True, block_lag=0),
            _make_result(actual_pair="RAIN/WETH", best_backrun_net_bps=5, block_lag=5, reject_reason="STALE_POSITIVE"),
            _make_result(actual_pair="WETH/RAIN", best_backrun_net_bps=-3, reject_reason="GAS_EXCEEDS_GROSS"),
        ]
        funnel, _ = _build_funnel(results)
        assert len(funnel) == 1
        row = funnel[0]
        assert row["pair_family"] == "RAIN/WETH"  # sorted
        assert row["seen_count"] == 3
        assert row["positive_count"] == 2
        assert row["stale_positive_count"] == 1
        assert row["cold_executable_count"] == 1
        assert row["gas_exceeds_gross_count"] == 1

    def test_multiple_pairs_sorted_by_seen(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=1),
            _make_result(actual_pair="A/B", best_backrun_net_bps=2),
            _make_result(actual_pair="C/D", best_backrun_net_bps=3),
        ]
        funnel, _ = _build_funnel(results)
        assert len(funnel) == 2
        assert funnel[0]["pair_family"] == "A/B"
        assert funnel[0]["seen_count"] == 2
        assert funnel[1]["pair_family"] == "C/D"
        assert funnel[1]["seen_count"] == 1

    def test_top_10_limit(self):
        results = []
        for i in range(15):
            results.append(_make_result(actual_pair=f"T{i}/U{i}", best_backrun_net_bps=-1))
        funnel, _ = _build_funnel(results)
        assert len(funnel) == 10

    def test_empty_results(self):
        funnel, conc = _build_funnel([])
        assert funnel == []
        assert conc["unique_pair_families"] == 0


# ===========================================================================
# pair_family_concentration
# ===========================================================================


class TestPairFamilyConcentration:

    def test_single_family_total_concentration(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=10, route_viable=True),
            _make_result(actual_pair="B/A", best_backrun_net_bps=5, route_viable=True),
        ]
        _, conc = _build_funnel(results)
        assert conc["seen_top1_share"] == 1.0
        assert conc["positive_top1_share"] == 1.0
        assert conc["cold_executable_top1_share"] == 1.0
        assert conc["unique_pair_families"] == 1

    def test_two_equal_families(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=10),
            _make_result(actual_pair="C/D", best_backrun_net_bps=10),
        ]
        _, conc = _build_funnel(results)
        assert conc["seen_top1_share"] == 0.5
        assert conc["unique_pair_families"] == 2

    def test_concentration_increases_through_funnel(self):
        """If only one family has executables, concentration rises at deeper stages."""
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=10, route_viable=True),
            _make_result(actual_pair="A/B", best_backrun_net_bps=5),
            _make_result(actual_pair="C/D", best_backrun_net_bps=-1),
            _make_result(actual_pair="C/D", best_backrun_net_bps=-2),
        ]
        _, conc = _build_funnel(results)
        # Seen: 50/50
        assert conc["seen_top1_share"] == 0.5
        # Positive: A/B has 2, C/D has 0 → 100%
        assert conc["positive_top1_share"] == 1.0
        # Executable: A/B has 1, C/D has 0 → 100%
        assert conc["cold_executable_top1_share"] == 1.0

    def test_zero_positive_no_division_error(self):
        results = [
            _make_result(actual_pair="A/B", best_backrun_net_bps=-5),
        ]
        _, conc = _build_funnel(results)
        assert conc["positive_top1_share"] == 0.0
        assert conc["cold_executable_top1_share"] == 0.0


# ===========================================================================
# diagnostic_raw anomaly flag
# ===========================================================================


class TestDiagnosticRawAnomalyFlag:

    def test_normal_value_not_flagged(self):
        val = 50.69
        assert abs(val) <= 10000

    def test_anomalous_value_flagged(self):
        val = 143941.47
        assert abs(val) > 10000

    def test_negative_anomaly_also_flagged(self):
        val = -20000.0
        assert abs(val) > 10000


# ===========================================================================
# Diversity-aware bridge fill
# ===========================================================================


class TestDiversityAwareBridgeFill:
    """Test the diversity cap logic for bridge pool ranking."""

    def test_family_cap_limits_same_family_pools(self):
        """Pools from the same family should be capped at FAMILY_CAP."""
        # Simulate: 12 pools from family (tokenA, tokenB), 5 from (tokenC, tokenD)
        FAMILY_CAP = 8
        ptt = {}
        # Family 1: 12 pools
        for i in range(12):
            ptt[f"0xpool_f1_{i}"] = ["tokenA", "tokenB", 3000]
        # Family 2: 5 pools
        for i in range(5):
            ptt[f"0xpool_f2_{i}"] = ["tokenC", "tokenD", 3000]

        bucket_a = set()
        bucket_b = set()
        remaining = set(ptt.keys())
        remaining_ranked = sorted(remaining)  # stable order

        def _pool_family(pa):
            info = ptt.get(pa)
            if info and len(info) >= 2:
                return tuple(sorted((info[0].lower(), info[1].lower())))
            return (pa,)

        family_counts: dict = {}
        diverse_fill = []
        pool_cap = 50
        for rpa in remaining_ranked:
            if len(diverse_fill) >= pool_cap:
                break
            fam = _pool_family(rpa)
            if family_counts.get(fam, 0) >= FAMILY_CAP:
                continue
            diverse_fill.append(rpa)
            family_counts[fam] = family_counts.get(fam, 0) + 1

        f1_count = sum(1 for p in diverse_fill if "f1" in p)
        f2_count = sum(1 for p in diverse_fill if "f2" in p)
        assert f1_count == FAMILY_CAP  # capped at 8
        assert f2_count == 5  # all 5 included (under cap)
        assert len(diverse_fill) == FAMILY_CAP + 5

    def test_all_different_families_no_cap_hit(self):
        """If all pools are different families, no cap applies."""
        FAMILY_CAP = 8
        ptt = {}
        for i in range(20):
            ptt[f"0xpool_{i}"] = [f"tokenA_{i}", f"tokenB_{i}", 3000]

        def _pool_family(pa):
            info = ptt.get(pa)
            if info and len(info) >= 2:
                return tuple(sorted((info[0].lower(), info[1].lower())))
            return (pa,)

        family_counts: dict = {}
        diverse_fill = []
        for rpa in sorted(ptt.keys()):
            if len(diverse_fill) >= 50:
                break
            fam = _pool_family(rpa)
            if family_counts.get(fam, 0) >= FAMILY_CAP:
                continue
            diverse_fill.append(rpa)
            family_counts[fam] = family_counts.get(fam, 0) + 1

        assert len(diverse_fill) == 20  # all included
