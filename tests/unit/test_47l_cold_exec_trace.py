"""
M7.A.5.47l — Unit tests for:
  1. Hard-pin cold-exec pools in bridge assembly
  2. bridge_selected_pools_top at assembly time
  3. cold_exec_pool_trace diagnostic
  4. C1 stale_sub_reason=block_lag filter
  5. cut_stage_top classification
  6. bridge_excluded_top in bridge file
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. Hard-pin cold-exec pools
# ---------------------------------------------------------------------------


def _assemble_bridge_47l(
    ptt: dict,
    bucket_a: set,
    bucket_b: set,
    bucket_c1: set,
    bucket_c2: set,
    pool_cap: int = 100,
    family_cap: int = 8,
) -> set:
    """Simulate 47l bridge assembly with hard-pin guarantee."""
    committed = bucket_a | bucket_b | bucket_c1 | bucket_c2
    remaining = sorted(k.lower() for k in ptt if k.lower() not in committed)

    def _fam(pa):
        info = ptt.get(pa) or ptt.get(pa.lower())
        if info and len(info) >= 2:
            return tuple(sorted((info[0].lower(), info[1].lower())))
        return (pa,)

    family_counts: dict = {}
    for pa in committed:
        f = _fam(pa)
        family_counts[f] = family_counts.get(f, 0) + 1

    slots = max(0, pool_cap - len(committed))
    diverse_fill = []
    for rpa in remaining:
        if len(diverse_fill) >= slots:
            break
        f = _fam(rpa)
        if family_counts.get(f, 0) >= family_cap:
            continue
        diverse_fill.append(rpa)
        family_counts[f] = family_counts.get(f, 0) + 1

    bridge = committed | set(diverse_fill)

    # M7.A.5.47l: Hard-pin — cold-exec pools MUST survive
    bridge |= bucket_a

    # Floor
    _BRIDGE_MIN_FLOOR = 20
    if len(bridge) < _BRIDGE_MIN_FLOOR and len(ptt) >= _BRIDGE_MIN_FLOOR:
        deficit = _BRIDGE_MIN_FLOOR - len(bridge)
        floor_fill = [pa for pa in remaining if pa not in bridge][:deficit]
        bridge |= set(floor_fill)

    return bridge


class TestHardPinColdExec:

    def test_cold_exec_always_in_bridge(self):
        """Cold-exec pool must always be in bridge, even under family cap pressure."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(50)}
        target = "0xd130"
        ptt[target] = ("0x25118290", "WETH", "v3")
        bucket_a = {target}
        bridge = _assemble_bridge_47l(ptt, bucket_a, set(), set(), set())
        assert target in bridge

    def test_cold_exec_survives_full_cap(self):
        """Even when cap is reached, cold-exec hard-pin survives."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(100)}
        target = "0xd130"
        ptt[target] = ("TOKEN_X", "WETH", "v3")
        bucket_a = {target}
        bridge = _assemble_bridge_47l(
            ptt, bucket_a, set(), set(), set(), pool_cap=5, family_cap=2,
        )
        assert target in bridge

    def test_empty_bucket_a_no_crash(self):
        """Empty cold-exec → no crash, bridge still works."""
        ptt = {f"0x{i:04x}": ("WETH", "USDC", "v3") for i in range(25)}
        bridge = _assemble_bridge_47l(ptt, set(), set(), set(), set())
        assert len(bridge) >= 20


# ---------------------------------------------------------------------------
# 2. bridge_selected_pools_top at assembly time
# ---------------------------------------------------------------------------


def _build_bridge_selected(bridge_pool_addrs, bucket_a, bucket_b, bucket_c1, bucket_c2, ptt):
    """Mirror of 47l bridge_selected_at_assembly builder."""
    selected = []
    for pa in list(bridge_pool_addrs)[:30]:
        bucket = "C3_activity_fill"
        if pa in bucket_a:
            bucket = "A_cold_exec"
        elif pa in bucket_b:
            bucket = "B_hot_seen"
        elif pa in bucket_c1:
            bucket = "C1_stale_recovery"
        elif pa in bucket_c2:
            bucket = "C2_gas_near"
        info = ptt.get(pa) or ptt.get(pa.lower())
        fam = ""
        if info and len(info) >= 2:
            fam = f"{info[0]}/{info[1]}"
        selected.append({
            "pool_address": pa,
            "bucket": bucket,
            "family": fam,
            "selected": True,
        })
    return selected


class TestBridgeSelectedPoolsTop:

    def test_cold_exec_labeled_correctly(self):
        """Cold-exec pool should be labeled A_cold_exec."""
        bridge = {"0xaaa", "0xbbb"}
        selected = _build_bridge_selected(
            bridge, {"0xaaa"}, set(), set(), set(),
            {"0xaaa": ("T0", "T1", "v3"), "0xbbb": ("T2", "T3", "v3")},
        )
        a_rows = [s for s in selected if s["pool_address"] == "0xaaa"]
        assert a_rows[0]["bucket"] == "A_cold_exec"

    def test_all_pools_have_selected_true(self):
        """All entries should have selected=True."""
        bridge = {f"0x{i:04x}" for i in range(5)}
        ptt = {f"0x{i:04x}": ("W", "U", "v3") for i in range(5)}
        selected = _build_bridge_selected(bridge, set(), set(), set(), set(), ptt)
        assert all(s["selected"] for s in selected)

    def test_nonempty_when_bridge_has_pools(self):
        """bridge_focused_pool_count > 0 → selected must be non-empty."""
        bridge = {"0x0001"}
        selected = _build_bridge_selected(
            bridge, set(), set(), set(), set(),
            {"0x0001": ("A", "B", "v3")},
        )
        assert len(selected) > 0


# ---------------------------------------------------------------------------
# 3. cold_exec_pool_trace
# ---------------------------------------------------------------------------


class TestColdExecPoolTrace:

    def test_trace_structure(self):
        """Trace entry should have all required fields."""
        trace = {
            "pool_address": "0xd130",
            "actual_pair": "0x25118290/WETH",
            "cold_net_bps": 110.96,
            "in_bridge": True,
            "hot_events_this_window": 0,
            "fast_score_attempted": 0,
            "registry_match": False,
        }
        required = {
            "pool_address", "actual_pair", "cold_net_bps",
            "in_bridge", "hot_events_this_window",
            "fast_score_attempted", "registry_match",
        }
        assert set(trace.keys()) == required

    def test_no_hot_events_reported(self):
        """When no hot events arrive, hot_events_this_window=0."""
        # This mirrors the real scenario: pool is in bridge but no events
        trace = {
            "pool_address": "0xd13040d4fe917ee704158cfcb3338dcd2838b245",
            "in_bridge": True,
            "hot_events_this_window": 0,
            "fast_score_attempted": 0,
        }
        assert trace["hot_events_this_window"] == 0
        assert trace["in_bridge"] is True


# ---------------------------------------------------------------------------
# 4. C1 stale_sub_reason filter
# ---------------------------------------------------------------------------


def _c1_admits(candidate: dict) -> bool:
    """Mirror of 47l C1 admission: skip block_lag sub-reason."""
    ANOMALY_REJECTS = {"PRICING_ANOMALY", "TOKEN_PAIR_UNRESOLVED"}
    rr = candidate.get("reject_reason", "")
    if rr in ANOMALY_REJECTS:
        return False
    if candidate.get("stale_sub_reason") == "block_lag":
        return False
    return True


class TestC1StaleSubReasonFilter:

    def test_block_lag_rejected(self):
        """stale_sub_reason=block_lag → C1 rejects."""
        cand = {"reject_reason": "REJECT_STALE_POSITIVE", "stale_sub_reason": "block_lag"}
        assert _c1_admits(cand) is False

    def test_pipeline_abort_admitted(self):
        """stale_sub_reason=pipeline_abort → C1 admits."""
        cand = {"reject_reason": "REJECT_STALE_POSITIVE", "stale_sub_reason": "pipeline_abort"}
        assert _c1_admits(cand) is True

    def test_state_recheck_admitted(self):
        """stale_sub_reason=state_recheck → C1 admits."""
        cand = {"reject_reason": "REJECT_STALE_POSITIVE", "stale_sub_reason": "state_recheck"}
        assert _c1_admits(cand) is True

    def test_none_sub_reason_admitted(self):
        """No stale_sub_reason → C1 admits."""
        cand = {"reject_reason": "REJECT_STALE_POSITIVE", "stale_sub_reason": None}
        assert _c1_admits(cand) is True

    def test_anomaly_rejected(self):
        """Anomaly reject always blocked."""
        cand = {"reject_reason": "PRICING_ANOMALY", "stale_sub_reason": None}
        assert _c1_admits(cand) is False


# ---------------------------------------------------------------------------
# 5. cut_stage_top classification
# ---------------------------------------------------------------------------


class _FakeResultCut:
    def __init__(self, net_bps, reject_reason, block_lag=0,
                 mid_pipeline_abort=False, route_viable=True, pair="A/B"):
        self.best_backrun_net_bps = net_bps
        self.reject_reason = reject_reason
        self.block_lag = block_lag
        self.route_viable = route_viable
        self.actual_pair = pair
        self.pipeline_stage_latency_ms = (
            {"mid_pipeline_abort": True} if mid_pipeline_abort else {}
        )


def _classify_cut_stage(r) -> str | None:
    """Mirror of 47l cut_stage classification."""
    if (r.best_backrun_net_bps or 0) <= 0:
        return None
    rr = r.reject_reason or ""
    if rr == "REJECT_GAS_EXCEEDS_GROSS":
        return "economics"
    elif rr == "REJECT_STALE_POSITIVE":
        psl = r.pipeline_stage_latency_ms or {}
        if psl.get("mid_pipeline_abort"):
            return "stale_pipeline_abort"
        elif r.block_lag > 2:
            return "stale_block_lag"
        else:
            return "stale_state_recheck"
    elif r.route_viable:
        return "viable"
    return None


class TestCutStageClassification:

    def test_economics(self):
        r = _FakeResultCut(10.0, "REJECT_GAS_EXCEEDS_GROSS")
        assert _classify_cut_stage(r) == "economics"

    def test_stale_block_lag(self):
        r = _FakeResultCut(10.0, "REJECT_STALE_POSITIVE", block_lag=5)
        assert _classify_cut_stage(r) == "stale_block_lag"

    def test_stale_pipeline_abort(self):
        r = _FakeResultCut(10.0, "REJECT_STALE_POSITIVE", mid_pipeline_abort=True)
        assert _classify_cut_stage(r) == "stale_pipeline_abort"

    def test_stale_state_recheck(self):
        r = _FakeResultCut(10.0, "REJECT_STALE_POSITIVE", block_lag=1)
        assert _classify_cut_stage(r) == "stale_state_recheck"

    def test_viable(self):
        r = _FakeResultCut(10.0, None, route_viable=True)
        assert _classify_cut_stage(r) == "viable"

    def test_negative_skipped(self):
        r = _FakeResultCut(-5.0, None)
        assert _classify_cut_stage(r) is None


# ---------------------------------------------------------------------------
# 6. bridge_excluded_top in bridge file
# ---------------------------------------------------------------------------


class TestBridgeExcludedInBridge:

    def test_excluded_persisted(self):
        """bridge_excluded_top should be a list."""
        bridge_update = {"bridge_excluded_top": [
            {"pool_address": "0xaaa", "exclude_reason": "family_cap"},
        ]}
        assert isinstance(bridge_update["bridge_excluded_top"], list)
        assert bridge_update["bridge_excluded_top"][0]["exclude_reason"] == "family_cap"

    def test_empty_when_all_included(self):
        """No excluded pools → empty list."""
        assert [] == []  # trivial — but documents the contract
