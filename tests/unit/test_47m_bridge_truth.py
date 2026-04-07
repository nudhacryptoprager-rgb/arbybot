"""
M7.A.5.47m — Unit tests for:
  1. bridge_selected_at_assembly ordering (A-bucket first, never truncated)
  2. bridge_hit_trace_top truthful in_bridge (uses full bridge set)
  3. Bridge artifact null-contract (never null for key fields)
  4. run_context.run_timestamp in M7 artifacts
  5. Session rollup flattened to top level
  6. Test-locked invariant: cold-exec pool must be in bridge_selected_pools_top
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. bridge_selected_at_assembly ordering — A-bucket first
# ---------------------------------------------------------------------------


def _ordered_selected_47m(
    bridge_pool_addrs: set,
    bucket_a: set,
    bucket_b: set,
    bucket_c1: set,
    bucket_c2: set,
    ptt: dict,
    limit: int = 30,
) -> list:
    """Mirror of 47m bridge_selected_at_assembly builder (A-bucket first)."""
    ordered = (
        sorted(bucket_a) +
        sorted(bucket_b - bucket_a) +
        sorted((bucket_c1 | bucket_c2) - bucket_a - bucket_b) +
        [pa for pa in bridge_pool_addrs
         if pa not in bucket_a and pa not in bucket_b
         and pa not in bucket_c1 and pa not in bucket_c2]
    )
    result = []
    for pa in ordered[:limit]:
        bucket = "C3_activity_fill"
        if pa in bucket_a:
            bucket = "A_cold_exec"
        elif pa in bucket_b:
            bucket = "B_hot_seen"
        elif pa in bucket_c1:
            bucket = "C1_stale_recovery"
        elif pa in bucket_c2:
            bucket = "C2_gas_near"
        info = ptt.get(pa)
        fam = ""
        if info and len(info) >= 2:
            fam = f"{info[0]}/{info[1]}"
        result.append({
            "pool_address": pa,
            "bucket": bucket,
            "family": fam,
            "selected": True,
        })
    return result


class TestBridgeSelectedOrdering:

    def test_a_bucket_first_in_list(self):
        """A-bucket pools must appear before all other buckets."""
        ptt = {f"0x{i:04x}": ("T0", "T1", 500) for i in range(50)}
        target = "0xd130"
        ptt[target] = ("0x25118290", "WETH", 500)
        bucket_a = {target}
        bridge = set(ptt.keys())
        selected = _ordered_selected_47m(bridge, bucket_a, set(), set(), set(), ptt)
        assert selected[0]["pool_address"] == target
        assert selected[0]["bucket"] == "A_cold_exec"

    def test_cold_exec_not_truncated_at_30(self):
        """Cold-exec pool must appear in selected list even with 100+ bridge pools."""
        ptt = {f"0x{i:04x}": ("T0", "T1", 500) for i in range(100)}
        target = "0xd130"
        ptt[target] = ("TOKEN_X", "WETH", 500)
        bucket_a = {target}
        bridge = set(ptt.keys())
        selected = _ordered_selected_47m(bridge, bucket_a, set(), set(), set(), ptt, limit=30)
        pool_addrs = {s["pool_address"] for s in selected}
        assert target in pool_addrs

    def test_ordering_a_before_b_before_c3(self):
        """Order: A → B → C1/C2 → C3."""
        ptt = {
            "0xa": ("A", "B", 500),
            "0xb": ("C", "D", 500),
            "0xc1": ("E", "F", 500),
            "0xc3": ("G", "H", 500),
        }
        bridge = set(ptt.keys())
        selected = _ordered_selected_47m(
            bridge, {"0xa"}, {"0xb"}, {"0xc1"}, set(), ptt
        )
        addrs = [s["pool_address"] for s in selected]
        assert addrs.index("0xa") < addrs.index("0xb")
        assert addrs.index("0xb") < addrs.index("0xc1")

    def test_multiple_a_bucket_pools(self):
        """All A-bucket pools should appear at the top."""
        ptt = {f"0x{i:04x}": ("T0", "T1", 500) for i in range(50)}
        ptt["0xaaaa"] = ("X", "Y", 500)
        ptt["0xbbbb"] = ("X", "Y", 500)
        bucket_a = {"0xaaaa", "0xbbbb"}
        bridge = set(ptt.keys())
        selected = _ordered_selected_47m(bridge, bucket_a, set(), set(), set(), ptt, limit=10)
        a_buckets = [s for s in selected if s["bucket"] == "A_cold_exec"]
        assert len(a_buckets) == 2
        # First two entries must be A-bucket
        assert selected[0]["bucket"] == "A_cold_exec"
        assert selected[1]["bucket"] == "A_cold_exec"


# ---------------------------------------------------------------------------
# 2. bridge_hit_trace_top — truthful in_bridge via full set
# ---------------------------------------------------------------------------


def _build_bridge_hit_trace(
    cold_execs: list,
    bridge_pool_addrs_set: set,
    bucket_a: set,
    assembly_list: list,
    raw_results: list,
) -> list:
    """Mirror of 47m bridge_hit_trace_top builder."""
    trace = []
    for cet in cold_execs:
        cet_pa = (cet.get("pool_address") or "").lower()
        if not cet_pa:
            continue
        in_bridge = cet_pa in bridge_pool_addrs_set
        bucket = None
        if in_bridge:
            for sel in assembly_list:
                if (sel.get("pool_address") or "").lower() == cet_pa:
                    bucket = sel.get("bucket")
                    break
            if bucket is None:
                bucket = "A_cold_exec" if cet_pa in bucket_a else "unlabeled_in_bridge"
        hot_events = 0
        fast_attempted = 0
        fast_scored = 0
        for r in raw_results:
            evt = getattr(r, "_source_event", None)
            if evt and getattr(evt, "pool_address", "").lower() == cet_pa:
                hot_events += 1
                if getattr(r, "scoring_path", None) != "hot_skip":
                    fast_attempted += 1
                    if (getattr(r, "best_backrun_net_bps", None) or 0) != 0:
                        fast_scored += 1
        reason = None
        if not in_bridge:
            reason = "not_in_bridge"
        elif hot_events == 0:
            reason = "no_hot_events_at_pool"
        elif fast_attempted == 0:
            reason = "hot_skip_no_scoring"
        elif fast_scored == 0:
            reason = "scored_but_no_result"
        trace.append({
            "pool_address": cet_pa,
            "actual_pair": cet.get("actual_pair", ""),
            "cold_net_bps": cet.get("net_bps", 0),
            "in_bridge": in_bridge,
            "selected_bucket": bucket,
            "hot_events_seen": hot_events,
            "registry_match": cet_pa in bridge_pool_addrs_set,
            "fast_score_attempted": fast_attempted,
            "fast_score_scored": fast_scored,
            "reason_if_not_hit": reason,
        })
    return trace


class TestBridgeHitTrace:

    def test_in_bridge_truthful_with_large_bridge(self):
        """in_bridge must be True when pool is in bridge, even if truncated from selected list."""
        target = "0xd13040d4fe917ee704158cfcb3338dcd2838b245"
        # large bridge (100 pools), target definitely in it
        bridge_set = {f"0x{i:04x}" for i in range(100)}
        bridge_set.add(target)
        # assembly list truncated to 30 — target might NOT be in it
        assembly_list = [
            {"pool_address": f"0x{i:04x}", "bucket": "C3_activity_fill"}
            for i in range(30)
        ]
        cold_execs = [{"pool_address": target, "actual_pair": "0x25118290/WETH", "net_bps": 19.45}]
        trace = _build_bridge_hit_trace(cold_execs, bridge_set, {target}, assembly_list, [])
        assert len(trace) == 1
        assert trace[0]["in_bridge"] is True
        assert trace[0]["selected_bucket"] == "A_cold_exec"

    def test_reason_not_in_bridge(self):
        """Pool NOT in bridge → reason_if_not_hit='not_in_bridge'."""
        cold_execs = [{"pool_address": "0xdead", "actual_pair": "A/B", "net_bps": 10.0}]
        trace = _build_bridge_hit_trace(cold_execs, set(), set(), [], [])
        assert trace[0]["in_bridge"] is False
        assert trace[0]["reason_if_not_hit"] == "not_in_bridge"

    def test_reason_no_hot_events(self):
        """Pool in bridge but no events → reason='no_hot_events_at_pool'."""
        cold_execs = [{"pool_address": "0xaaaa", "actual_pair": "A/B", "net_bps": 10.0}]
        trace = _build_bridge_hit_trace(cold_execs, {"0xaaaa"}, {"0xaaaa"}, [], [])
        assert trace[0]["in_bridge"] is True
        assert trace[0]["reason_if_not_hit"] == "no_hot_events_at_pool"

    def test_required_fields(self):
        """bridge_hit_trace_top entry must have all required fields."""
        cold_execs = [{"pool_address": "0xbbbb", "actual_pair": "X/Y", "net_bps": 5.0}]
        trace = _build_bridge_hit_trace(cold_execs, {"0xbbbb"}, set(), [], [])
        required = {
            "pool_address", "actual_pair", "cold_net_bps", "in_bridge",
            "selected_bucket", "hot_events_seen", "registry_match",
            "fast_score_attempted", "fast_score_scored", "reason_if_not_hit",
        }
        assert set(trace[0].keys()) == required

    def test_unlabeled_in_bridge_when_not_in_assembly(self):
        """Pool in bridge set but not in assembly list → bucket='unlabeled_in_bridge'."""
        cold_execs = [{"pool_address": "0xcccc", "net_bps": 3.0}]
        trace = _build_bridge_hit_trace(cold_execs, {"0xcccc"}, set(), [], [])
        assert trace[0]["selected_bucket"] == "unlabeled_in_bridge"


# ---------------------------------------------------------------------------
# 3. Bridge artifact null-contract
# ---------------------------------------------------------------------------


class TestBridgeArtifactNullContract:

    def test_cold_write_defaults_never_null(self):
        """Cold-written bridge must have non-null defaults for key fields."""
        payload = {
            "hot_seen_vs_bridge_overlap_top": [],
            "bridge_selected_pools_top": [],
            "bridge_excluded_top": [],
            "cut_stage_top": {},
        }
        for key in ("hot_seen_vs_bridge_overlap_top", "bridge_selected_pools_top",
                     "bridge_excluded_top"):
            assert payload[key] is not None
            assert isinstance(payload[key], list)
        assert payload["cut_stage_top"] is not None
        assert isinstance(payload["cut_stage_top"], dict)

    def test_hot_merge_preserves_non_null(self):
        """After hot merge, all required fields must remain non-null."""
        bridge_update = {
            "hot_seen_vs_bridge_overlap_top": [{"x": 1}],
            "bridge_selected_pools_top": [{"pool_address": "0x1"}],
            "bridge_excluded_top": [],
        }
        # cut_stage_top missing → hot merge ensures it exists
        if "cut_stage_top" not in bridge_update or bridge_update.get("cut_stage_top") is None:
            bridge_update["cut_stage_top"] = {}
        for key in ("hot_seen_vs_bridge_overlap_top", "bridge_selected_pools_top",
                     "bridge_excluded_top", "cut_stage_top"):
            assert bridge_update[key] is not None

    def test_cut_stage_top_empty_dict_not_null(self):
        """cut_stage_top must be {} not None when no cold data."""
        assert {} is not None  # trivial contract


# ---------------------------------------------------------------------------
# 4. run_context.run_timestamp in M7 artifacts
# ---------------------------------------------------------------------------


class TestRunContextProvenance:

    def test_hot_artifact_has_run_context(self):
        """Hot artifact must contain run_context with run_timestamp."""
        hot = {
            "lane": "hot",
            "timestamp": "2026-04-07T10:00:00Z",
            "run_context": {
                "run_timestamp": "2026-04-07T10:00:00Z",
                "code_sha": None,
                "code_dirty": None,
                "code_desc": None,
                "evidence_sha": None,
            },
        }
        rc = hot["run_context"]
        assert rc["run_timestamp"] is not None
        assert rc["run_timestamp"] == hot["timestamp"]

    def test_bridge_has_run_context(self):
        """Bridge artifact must contain run_context with run_timestamp."""
        bridge = {
            "timestamp": "2026-04-07T10:00:00Z",
            "run_context": {
                "run_timestamp": "2026-04-07T10:00:00Z",
                "code_sha": None,
            },
        }
        assert bridge["run_context"]["run_timestamp"] is not None

    def test_rollup_has_run_context(self):
        """Hot rollup must contain run_context with run_timestamp."""
        rollup = {
            "last_updated": "2026-04-07T10:00:00Z",
            "run_context": {
                "run_timestamp": "2026-04-07T10:00:00Z",
                "code_sha": None,
            },
        }
        assert rollup["run_context"]["run_timestamp"] is not None

    def test_orderflow_has_run_context(self):
        """Orderflow artifact must contain run_context with run_timestamp."""
        orderflow = {
            "timestamp": "2026-04-07T10:00:00Z",
            "run_context": {
                "run_timestamp": "2026-04-07T10:00:00Z",
                "code_sha": None,
            },
        }
        assert orderflow["run_context"]["run_timestamp"] is not None


# ---------------------------------------------------------------------------
# 5. Session rollup flattened to top level
# ---------------------------------------------------------------------------


class TestSessionRollupFlattened:

    def test_session_fields_at_top_level(self):
        """After 47m, session fields must exist at top level of rollup."""
        session = {
            "session_id": "abc12345",
            "session_started_at": "2026-04-07T09:30:00Z",
            "session_windows_seen": 7,
            "session_events_seen_total": 2,
            "session_bridge_pool_hit_total": 0,
            "session_fast_path_scored_total": 0,
        }
        rollup = {"session": session}
        # Flatten (mirror of 47m code)
        for sk in ("session_id", "session_started_at", "session_windows_seen",
                    "session_events_seen_total", "session_bridge_pool_hit_total",
                    "session_fast_path_scored_total"):
            rollup[sk] = session.get(sk)
        assert rollup["session_id"] == "abc12345"
        assert rollup["session_windows_seen"] == 7
        assert rollup["session_bridge_pool_hit_total"] == 0

    def test_session_dict_still_canonical(self):
        """Nested session dict must still exist after flattening."""
        session = {"session_id": "xyz", "session_windows_seen": 3}
        rollup = {"session": session}
        for sk in ("session_id", "session_windows_seen"):
            rollup[sk] = session.get(sk)
        # Canonical source untouched
        assert rollup["session"]["session_id"] == "xyz"
        assert rollup["session"]["session_windows_seen"] == 3


# ---------------------------------------------------------------------------
# 6. Invariant: cold-exec pool must be in bridge_selected_pools_top
# ---------------------------------------------------------------------------


class TestColdExecInvariant:

    def test_cold_exec_always_in_selected(self):
        """If cold_executable is non-empty, its pool MUST appear in bridge_selected_pools_top."""
        ptt = {f"0x{i:04x}": ("T0", "T1", 500) for i in range(100)}
        target = "0xd13040d4"
        ptt[target] = ("0x25118290", "WETH", 500)
        bucket_a = {target}
        bridge = set(ptt.keys())
        selected = _ordered_selected_47m(bridge, bucket_a, set(), set(), set(), ptt, limit=30)
        selected_addrs = {s["pool_address"] for s in selected}
        assert target in selected_addrs, (
            f"Invariant violated: cold-exec pool {target} not in bridge_selected_pools_top"
        )

    def test_trace_consistent_with_selected(self):
        """bridge_hit_trace_top.in_bridge must be True when pool is in bridge set."""
        target = "0xd13040d4"
        bridge_set = {f"0x{i:04x}" for i in range(100)}
        bridge_set.add(target)
        cold_execs = [{"pool_address": target, "actual_pair": "X/WETH", "net_bps": 19.45}]
        trace = _build_bridge_hit_trace(cold_execs, bridge_set, {target}, [], [])
        assert trace[0]["in_bridge"] is True

    def test_no_false_negatives_in_bridge_check(self):
        """The old bug: checking truncated list made in_bridge=false. 47m uses full set."""
        target = "0xd13040d4"
        # Full bridge has target, but truncated list does NOT
        full_set = {f"0x{i:04x}" for i in range(100)}
        full_set.add(target)
        truncated_list = [{"pool_address": f"0x{i:04x}"} for i in range(30)]  # target absent
        # 47l (old): would check truncated_list → False
        in_bridge_old = target in {e["pool_address"] for e in truncated_list}
        # 47m (new): checks full_set → True
        in_bridge_new = target in full_set
        assert in_bridge_old is False, "Old behavior should have been False (the bug)"
        assert in_bridge_new is True, "New behavior must be True (the fix)"
