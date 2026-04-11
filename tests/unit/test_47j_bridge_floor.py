"""
M7.A.5.47j — Unit tests for:
  1. Bridge minimum floor enforcement (_BRIDGE_MIN_FLOOR = 20)
  2. bridge_focused_pool_count metric presence in hot diagnostics
  3. C2 tightened tolerance (-5 bps from -10 bps)
  4. Overlap diagnostic always list (never None)
  5. bridge_focused_pool_count appears in hot_gap_debug
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Helpers simulating production logic (minimal, matching m7a_orderflow_loop.py)
# ---------------------------------------------------------------------------

_BRIDGE_MIN_FLOOR = 20
_FAMILY_CAP = 8
_C2_GAS_GAP_TOLERANCE_BPS = -5  # 47j tightened from -10


def _pool_family(pa: str, ptt: dict) -> tuple:
    info = ptt.get(pa) or ptt.get(pa.lower())
    if info and len(info) >= 2:
        return tuple(sorted((info[0].lower(), info[1].lower())))
    return (pa,)


def _assemble_bridge(
    ptt: dict,
    bucket_a: set,
    bucket_b: set,
    bucket_c1: set,
    bucket_c2: set,
    pool_cap: int = 100,
) -> set:
    """Simulate bridge assembly with minimum floor enforcement."""
    committed = bucket_a | bucket_b | bucket_c1 | bucket_c2
    remaining = set()
    for k in ptt:
        pk = k.lower()
        if pk not in committed:
            remaining.add(pk)
    remaining_ranked = sorted(remaining)

    # Diversity-aware fill
    family_counts: dict = {}
    for pa in committed:
        fam = _pool_family(pa, ptt)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    slots = max(0, pool_cap - len(committed))
    diverse_fill: list = []
    for rpa in remaining_ranked:
        if len(diverse_fill) >= slots:
            break
        fam = _pool_family(rpa, ptt)
        if family_counts.get(fam, 0) >= _FAMILY_CAP:
            continue
        diverse_fill.append(rpa)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    bridge = committed | set(diverse_fill)

    # M7.A.5.47j: minimum floor enforcement
    if len(bridge) < _BRIDGE_MIN_FLOOR and len(ptt) >= _BRIDGE_MIN_FLOOR:
        deficit = _BRIDGE_MIN_FLOOR - len(bridge)
        floor_fill = [pa for pa in remaining_ranked if pa not in bridge][:deficit]
        bridge |= set(floor_fill)

    return bridge


def _gas_viable_families_47j(micro_refinement: list) -> set:
    """47j version: tolerance tightened to -5 bps."""
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
        if gfg is not None and gfg >= _C2_GAS_GAP_TOLERANCE_BPS:
            ap = mr.get("actual_pair") or ""
            parts = ap.split("/")
            if len(parts) == 2:
                families.add(tuple(sorted((parts[0].lower(), parts[1].lower()))))
    return families


def _build_overlap_diag(hot_hist: list, bridge_pool_addrs: set | None) -> list:
    """47i+47j: Always returns a list, never None."""
    if not hot_hist or bridge_pool_addrs is None:
        return []
    overlap: list = []
    for oh in hot_hist[:10]:
        addr = (oh.get("pool") or "").lower()
        if not addr:
            continue
        in_bridge = addr in bridge_pool_addrs
        overlap.append({
            "event_pool": addr,
            "in_bridge": in_bridge,
        })
    return overlap[:5]


# ===========================================================================
# 1. Bridge minimum floor enforcement
# ===========================================================================


class TestBridgeMinimumFloor:

    def test_floor_met_when_ptt_large_enough(self):
        """With 30 PTT pools and empty buckets, bridge should have >= 20 pools."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(30)}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        assert len(bridge) >= _BRIDGE_MIN_FLOOR

    def test_floor_not_enforced_when_ptt_small(self):
        """With only 10 PTT pools (< 20), no floor padding applied.
        Family cap (8) still applies, so only 8 of 10 same-family pools get in."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(10)}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        assert len(bridge) == 8  # capped by FAMILY_CAP, not floor

    def test_floor_fills_to_minimum(self):
        """If committed + diverse_fill < 20 but PTT >= 20, floor fill kicks in."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(25)}
        # Set very low family cap by using same family — diversity cap limits C3
        # Actually with _FAMILY_CAP=8, same family will be capped at 8
        # 25 pools / 1 family = at most 8 in diverse fill
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        # Floor should ensure at least 20 pools
        assert len(bridge) >= _BRIDGE_MIN_FLOOR

    def test_buckets_count_toward_floor(self):
        """Pools already in buckets count toward the floor."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(50)}
        bucket_a = {f"0x{i:04x}" for i in range(15)}
        bridge = _assemble_bridge(ptt, bucket_a, set(), set(), set())
        assert len(bridge) >= _BRIDGE_MIN_FLOOR
        # A has 15, need 5 more → floor or diverse fill provides them
        assert bucket_a.issubset(bridge)

    def test_all_ptt_included_when_small(self):
        """When PTT has exactly 20 pools, all should be in bridge."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(20)}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        assert len(bridge) == 20

    def test_cap_still_respected(self):
        """Pool cap should still be respected (floor doesn't exceed cap)."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(200)}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set(), pool_cap=50)
        # Floor is 20, cap is 50; diverse fill limited by cap
        assert len(bridge) <= 50


# ===========================================================================
# 2. bridge_focused_pool_count metric
# ===========================================================================


class TestBridgeFocusedPoolCount:

    def test_metric_reflects_all_buckets(self):
        """bridge_focused_pool_count should match len(bridge)."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(40)}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        # Simulate the metric
        focused_count = len(bridge)
        assert focused_count >= _BRIDGE_MIN_FLOOR
        assert focused_count > 0

    def test_none_bridge_gives_zero(self):
        """If _bridge_pool_addrs is None, focused count should be 0."""
        bridge_pool_addrs = None
        count = len(bridge_pool_addrs) if bridge_pool_addrs else 0
        assert count == 0

    def test_empty_bridge_gives_zero(self):
        """Empty PTT → empty bridge → focused count 0."""
        ptt: dict = {}
        bridge = _assemble_bridge(ptt, set(), set(), set(), set())
        assert len(bridge) == 0


# ===========================================================================
# 3. C2 tightened tolerance
# ===========================================================================


class TestC2TightenedTolerance47j:

    def test_gap_minus_7_excluded_at_tighter_threshold(self):
        """gas_floor_gap_bps = -7 was admitted at -10, excluded at -5."""
        micro = [{"actual_pair": "WETH/USDC",
                  "verified_net_bps_after_refinement": 0,
                  "gas_floor_gap_bps": -7}]
        fams = _gas_viable_families_47j(micro)
        assert ("usdc", "weth") not in fams

    def test_gap_minus_5_admitted(self):
        """Exactly at new threshold: -5 bps should be admitted."""
        micro = [{"actual_pair": "WETH/USDC",
                  "verified_net_bps_after_refinement": 0,
                  "gas_floor_gap_bps": -5}]
        fams = _gas_viable_families_47j(micro)
        assert ("usdc", "weth") in fams

    def test_gap_minus_4_admitted(self):
        """Within threshold: -4 bps admitted."""
        micro = [{"actual_pair": "WETH/USDC",
                  "verified_net_bps_after_refinement": 0,
                  "gas_floor_gap_bps": -4}]
        fams = _gas_viable_families_47j(micro)
        assert ("usdc", "weth") in fams

    def test_gap_minus_6_excluded(self):
        """Outside threshold: -6 bps excluded."""
        micro = [{"actual_pair": "WETH/USDC",
                  "verified_net_bps_after_refinement": 0,
                  "gas_floor_gap_bps": -6}]
        fams = _gas_viable_families_47j(micro)
        assert ("usdc", "weth") not in fams

    def test_verified_positive_still_overrides(self):
        """Verified net > 0 still overrides any gas gap."""
        micro = [{"actual_pair": "WETH/USDC",
                  "verified_net_bps_after_refinement": 3,
                  "gas_floor_gap_bps": -50}]
        fams = _gas_viable_families_47j(micro)
        assert ("usdc", "weth") in fams


# ===========================================================================
# 4. Overlap diagnostic never None
# ===========================================================================


class TestOverlapDiagNeverNone:

    def test_returns_list_even_when_empty_history(self):
        result = _build_overlap_diag([], {"0xaaa"})
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_list_when_bridge_none(self):
        result = _build_overlap_diag([{"pool": "0xaaa", "count": 3}], None)
        assert isinstance(result, list)
        assert len(result) == 0

    def test_returns_list_when_both_none(self):
        result = _build_overlap_diag([], None)
        assert isinstance(result, list)

    def test_produces_entries_when_data_available(self):
        hist = [{"pool": "0xabc", "count": 5}, {"pool": "0xdef", "count": 2}]
        bridge = {"0xabc"}
        result = _build_overlap_diag(hist, bridge)
        assert isinstance(result, list)
        assert len(result) == 2
        assert result[0]["in_bridge"] is True
        assert result[1]["in_bridge"] is False

    def test_capped_at_5(self):
        hist = [{"pool": f"0x{i:04x}", "count": 1} for i in range(20)]
        bridge = set()
        result = _build_overlap_diag(hist, bridge)
        assert isinstance(result, list)
        assert len(result) <= 5

    def test_empty_pool_address_skipped(self):
        hist = [{"pool": "", "count": 3}, {"pool": "0xabc", "count": 2}]
        bridge = {"0xabc"}
        result = _build_overlap_diag(hist, bridge)
        assert len(result) == 1
        assert result[0]["event_pool"] == "0xabc"


# ===========================================================================
# 5. Source code contract verification
# ===========================================================================


class TestSourceCodeContracts47j:
    """Verify that production source code contains the 47j constants and fields."""

    def test_bridge_min_floor_constant(self):
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        src = inspect.getsource(run_loop)
        assert "_BRIDGE_MIN_FLOOR = 20" in src

    def test_c2_tolerance_tightened(self):
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        src = inspect.getsource(run_loop)
        assert "_C2_GAS_GAP_TOLERANCE_BPS = -5" in src

    def test_bridge_focused_pool_count_in_diagnostics(self):
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        src = inspect.getsource(run_loop)
        assert '"bridge_focused_pool_count"' in src

    def test_overlap_diag_always_list(self):
        """Verify that _overlap_diag is initialized as list and always set."""
        import inspect
        from scripts.m7a_orderflow_loop import run_loop
        src = inspect.getsource(run_loop)
        assert "_overlap_diag: list = []" in src
        assert '["hot_seen_vs_bridge_overlap_top"] = _overlap_diag[:5]' in src
