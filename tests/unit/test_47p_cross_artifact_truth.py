"""
M7.A.5.47p — Unit tests for:
  1. Conditional cold bridge preserve (stale trace cleared when cold_executable=[])
  2. Cross-artifact truth invariant (hot_latest ↔ bridge file consistency)
  3. bridge_selection_diff_top structure
  4. c3_gas_hopeless guaranteed non-None
  5. Live-miss pool auto-pin from other_live_pool_trace
  6. family_unresolved sentinel (never empty string)
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. Conditional cold bridge preserve
# ---------------------------------------------------------------------------

_HOT_PRESERVE_ALWAYS = ("bridge_selected_pools_top", "bridge_excluded_top")
_HOT_PRESERVE_IF_COLD_EXEC = ("bridge_hit_trace_top", "cold_exec_pool_trace")


def _cold_bridge_preserve_47p(payload: dict, existing: dict) -> dict:
    """Mirror of 47p conditional preserve logic."""
    has_cold_exec = bool(payload.get("cold_executable"))
    for k in _HOT_PRESERVE_ALWAYS:
        existing_val = existing.get(k)
        if existing_val and not payload.get(k):
            payload[k] = existing_val
    if has_cold_exec:
        for k in _HOT_PRESERVE_IF_COLD_EXEC:
            existing_val = existing.get(k)
            if existing_val and not payload.get(k):
                payload[k] = existing_val
    else:
        for k in _HOT_PRESERVE_IF_COLD_EXEC:
            payload[k] = []
    return payload


class TestConditionalColdPreserve:

    def test_clears_trace_when_no_cold_exec(self):
        """When cold_executable=[], stale trace must be cleared."""
        existing = {
            "bridge_hit_trace_top": [{"pool_address": "0xd130", "cold_net_bps": 47.41}],
            "cold_exec_pool_trace": [{"pool_address": "0xd130"}],
            "bridge_selected_pools_top": [{"pool_address": "0xaaa"}],
        }
        payload = {"cold_executable": []}
        result = _cold_bridge_preserve_47p(payload, existing)
        assert result["bridge_hit_trace_top"] == []
        assert result["cold_exec_pool_trace"] == []
        # bridge_selected_pools_top is always-preserved
        assert result["bridge_selected_pools_top"] == [{"pool_address": "0xaaa"}]

    def test_preserves_trace_when_cold_exec_present(self):
        """When cold_executable has entries, trace is preserved."""
        existing = {
            "bridge_hit_trace_top": [{"pool_address": "0xd130"}],
            "cold_exec_pool_trace": [{"pool_address": "0xd130"}],
        }
        payload = {"cold_executable": [{"pool_address": "0xd130"}]}
        result = _cold_bridge_preserve_47p(payload, existing)
        assert result["bridge_hit_trace_top"] == [{"pool_address": "0xd130"}]

    def test_cold_exec_empty_list_clears(self):
        """Empty list [] is falsy — triggers clear."""
        existing = {"bridge_hit_trace_top": [{"p": "0x1"}], "cold_exec_pool_trace": [{"p": "0x1"}]}
        payload = {"cold_executable": []}
        result = _cold_bridge_preserve_47p(payload, existing)
        assert result["bridge_hit_trace_top"] == []

    def test_always_keys_preserved_regardless(self):
        """bridge_selected_pools_top and bridge_excluded_top always preserved."""
        existing = {
            "bridge_selected_pools_top": [{"p": "0x1"}],
            "bridge_excluded_top": [{"p": "0x2"}],
            "bridge_hit_trace_top": [{"p": "0x3"}],
            "cold_exec_pool_trace": [{"p": "0x3"}],
        }
        payload = {"cold_executable": []}
        result = _cold_bridge_preserve_47p(payload, existing)
        assert result["bridge_selected_pools_top"] == [{"p": "0x1"}]
        assert result["bridge_excluded_top"] == [{"p": "0x2"}]
        assert result["bridge_hit_trace_top"] == []
        assert result["cold_exec_pool_trace"] == []


# ---------------------------------------------------------------------------
# 2. Cross-artifact truth invariant
# ---------------------------------------------------------------------------


def _check_cross_artifact_truth(hot_latest: dict, bridge_file: dict) -> list[str]:
    """Check cross-artifact consistency. Returns list of violations."""
    violations = []
    trace_keys = ("bridge_hit_trace_top",)
    for k in trace_keys:
        hot_val = hot_latest.get(k, [])
        bridge_val = bridge_file.get(k, [])
        hot_has = bool(hot_val)
        bridge_has = bool(bridge_val)
        if hot_has != bridge_has:
            violations.append(
                f"{k}: hot_latest={'populated' if hot_has else 'empty'} "
                f"vs bridge={'populated' if bridge_has else 'empty'}"
            )
    return violations


class TestCrossArtifactTruth:

    def test_both_empty_ok(self):
        violations = _check_cross_artifact_truth(
            {"bridge_hit_trace_top": []},
            {"bridge_hit_trace_top": []},
        )
        assert violations == []

    def test_both_populated_ok(self):
        data = [{"pool_address": "0xd130"}]
        violations = _check_cross_artifact_truth(
            {"bridge_hit_trace_top": data},
            {"bridge_hit_trace_top": data},
        )
        assert violations == []

    def test_hot_empty_bridge_populated_violation(self):
        violations = _check_cross_artifact_truth(
            {"bridge_hit_trace_top": []},
            {"bridge_hit_trace_top": [{"pool_address": "0xd130"}]},
        )
        assert len(violations) == 1
        assert "bridge_hit_trace_top" in violations[0]

    def test_hot_populated_bridge_empty_violation(self):
        violations = _check_cross_artifact_truth(
            {"bridge_hit_trace_top": [{"pool_address": "0xd130"}]},
            {"bridge_hit_trace_top": []},
        )
        assert len(violations) == 1


# ---------------------------------------------------------------------------
# 3. bridge_selection_diff_top structure
# ---------------------------------------------------------------------------


class _Evt:
    def __init__(self, pa):
        self.pool_address = pa


class _Res:
    def __init__(self, pa):
        self._source_event = _Evt(pa)


def _build_selection_diff(
    other_trace: list, raw_results: list, assembly: list, ptt_ref: dict | None
) -> dict:
    """Mirror of 47p bridge_selection_diff_top logic."""
    sel_diff = {"hot_seen_not_in_bridge": [], "bridge_selected_but_no_hot_events": []}
    for ot in other_trace:
        if not ot.get("in_bridge"):
            sel_diff["hot_seen_not_in_bridge"].append({
                "pool_address": ot["pool_address"],
                "family": ot["family"],
                "hot_events_seen": ot["hot_events_seen"],
                "reason_if_absent": ot.get("reason_if_not_hit", "not_in_bridge"),
            })
    all_event_pools = set()
    for r in raw_results:
        evt = getattr(r, "_source_event", None)
        if evt:
            ep = getattr(evt, "pool_address", "").lower()
            if ep:
                all_event_pools.add(ep)
    for sel in (assembly or [])[:20]:
        sel_pa = (sel.get("pool_address") or "").lower()
        if sel_pa and sel_pa not in all_event_pools:
            sel_info = ptt_ref.get(sel_pa) if ptt_ref else None
            sel_fam = (
                f"{sel_info[0]}/{sel_info[1]}"
                if sel_info and len(sel_info) >= 2
                else "family_unresolved"
            )
            sel_diff["bridge_selected_but_no_hot_events"].append({
                "pool_address": sel_pa,
                "family": sel_fam,
                "selected_bucket": sel.get("bucket"),
            })
    sel_diff["hot_seen_not_in_bridge"] = sel_diff["hot_seen_not_in_bridge"][:10]
    sel_diff["bridge_selected_but_no_hot_events"] = sel_diff["bridge_selected_but_no_hot_events"][:10]
    return sel_diff


class TestBridgeSelectionDiff:

    def test_hot_seen_not_in_bridge(self):
        other_trace = [
            {"pool_address": "0xabc", "family": "family_unresolved",
             "in_bridge": False, "hot_events_seen": 3, "reason_if_not_hit": "not_in_bridge"},
        ]
        diff = _build_selection_diff(other_trace, [], [], None)
        assert len(diff["hot_seen_not_in_bridge"]) == 1
        assert diff["hot_seen_not_in_bridge"][0]["pool_address"] == "0xabc"

    def test_bridge_selected_no_events(self):
        assembly = [{"pool_address": "0xDEF", "bucket": "C3_activity_fill"}]
        diff = _build_selection_diff([], [], assembly, None)
        assert len(diff["bridge_selected_but_no_hot_events"]) == 1
        assert diff["bridge_selected_but_no_hot_events"][0]["pool_address"] == "0xdef"
        assert diff["bridge_selected_but_no_hot_events"][0]["family"] == "family_unresolved"

    def test_bridge_selected_with_events_excluded(self):
        """Pool in bridge that DID have events should NOT appear in diff."""
        assembly = [{"pool_address": "0xDEF", "bucket": "A_cold_exec"}]
        raw = [_Res("0xDEF")]
        diff = _build_selection_diff([], raw, assembly, None)
        assert diff["bridge_selected_but_no_hot_events"] == []

    def test_in_bridge_pools_excluded_from_hot_seen(self):
        """Pools with in_bridge=True should NOT appear in hot_seen_not_in_bridge."""
        other_trace = [
            {"pool_address": "0xabc", "family": "tok0/tok1",
             "in_bridge": True, "hot_events_seen": 5, "reason_if_not_hit": None},
        ]
        diff = _build_selection_diff(other_trace, [], [], None)
        assert diff["hot_seen_not_in_bridge"] == []

    def test_empty_inputs(self):
        diff = _build_selection_diff([], [], [], None)
        assert diff == {"hot_seen_not_in_bridge": [], "bridge_selected_but_no_hot_events": []}

    def test_truncation_to_10(self):
        other_trace = [
            {"pool_address": f"0x{i:04x}", "family": "f",
             "in_bridge": False, "hot_events_seen": 1, "reason_if_not_hit": "not_in_bridge"}
            for i in range(15)
        ]
        diff = _build_selection_diff(other_trace, [], [], None)
        assert len(diff["hot_seen_not_in_bridge"]) == 10

    def test_family_resolved_from_ptt(self):
        assembly = [{"pool_address": "0xDEF", "bucket": "B"}]
        ptt = {"0xdef": ["tokA", "tokB", 3000]}
        diff = _build_selection_diff([], [], assembly, ptt)
        assert diff["bridge_selected_but_no_hot_events"][0]["family"] == "tokA/tokB"


# ---------------------------------------------------------------------------
# 4. c3_gas_hopeless guaranteed non-None
# ---------------------------------------------------------------------------


def _surface_gas_hopeless(bd: dict) -> dict:
    """Mirror of 47p logic — `or` fallback for explicitly None values."""
    return {
        "c3_gas_hopeless_skipped": bd.get("c3_gas_hopeless_skipped") or 0,
        "c3_gas_hopeless_families": bd.get("c3_gas_hopeless_families") or [],
    }


class TestGasHopelessNonNone:

    def test_explicit_none_becomes_zero(self):
        """When bd has key=None, result must be 0 / []."""
        result = _surface_gas_hopeless({"c3_gas_hopeless_skipped": None, "c3_gas_hopeless_families": None})
        assert result["c3_gas_hopeless_skipped"] == 0
        assert result["c3_gas_hopeless_families"] == []

    def test_missing_key_becomes_zero(self):
        result = _surface_gas_hopeless({})
        assert result["c3_gas_hopeless_skipped"] == 0
        assert result["c3_gas_hopeless_families"] == []

    def test_normal_values_pass_through(self):
        result = _surface_gas_hopeless({"c3_gas_hopeless_skipped": 3, "c3_gas_hopeless_families": ["a"]})
        assert result["c3_gas_hopeless_skipped"] == 3
        assert result["c3_gas_hopeless_families"] == ["a"]

    def test_zero_stays_zero(self):
        """0 is falsy but `or 0` still returns 0."""
        result = _surface_gas_hopeless({"c3_gas_hopeless_skipped": 0})
        assert result["c3_gas_hopeless_skipped"] == 0


# ---------------------------------------------------------------------------
# 5. Live-miss pool auto-pin
# ---------------------------------------------------------------------------


def _live_miss_auto_pin(
    other_live_trace: list, hot_seen_pin: dict, iteration: int, ttl: int = 5
) -> int:
    """Mirror of 47p live-miss auto-pin logic."""
    pinned = 0
    for lmt in (other_live_trace or []):
        if lmt.get("reason_if_not_hit") == "not_in_bridge":
            lm_pa = (lmt.get("pool_address") or "").lower()
            if lm_pa and (lm_pa not in hot_seen_pin
                          or hot_seen_pin[lm_pa].get("ttl", 0) <= 1):
                hot_seen_pin[lm_pa] = {
                    "ttl": ttl,
                    "last_iter": iteration,
                    "source": "live_miss_trace_pin",
                }
                pinned += 1
    return pinned


class TestLiveMissAutoPin:

    def test_pins_not_in_bridge_pool(self):
        pin = {}
        trace = [
            {"pool_address": "0xABC", "reason_if_not_hit": "not_in_bridge"},
        ]
        count = _live_miss_auto_pin(trace, pin, iteration=5)
        assert count == 1
        assert "0xabc" in pin
        assert pin["0xabc"]["source"] == "live_miss_trace_pin"

    def test_skips_in_bridge_pools(self):
        pin = {}
        trace = [
            {"pool_address": "0xABC", "reason_if_not_hit": "scored_but_no_result"},
        ]
        count = _live_miss_auto_pin(trace, pin, iteration=5)
        assert count == 0

    def test_skips_already_pinned_with_ttl(self):
        pin = {"0xabc": {"ttl": 3, "last_iter": 2, "source": "bridge_miss_direct_pin"}}
        trace = [
            {"pool_address": "0xABC", "reason_if_not_hit": "not_in_bridge"},
        ]
        count = _live_miss_auto_pin(trace, pin, iteration=5)
        assert count == 0
        # Original pin preserved
        assert pin["0xabc"]["source"] == "bridge_miss_direct_pin"

    def test_repins_expired_ttl(self):
        pin = {"0xabc": {"ttl": 1, "last_iter": 1, "source": "bridge_miss_direct_pin"}}
        trace = [
            {"pool_address": "0xABC", "reason_if_not_hit": "not_in_bridge"},
        ]
        count = _live_miss_auto_pin(trace, pin, iteration=5)
        assert count == 1
        assert pin["0xabc"]["source"] == "live_miss_trace_pin"

    def test_empty_trace(self):
        pin = {}
        count = _live_miss_auto_pin([], pin, iteration=1)
        assert count == 0

    def test_none_trace(self):
        pin = {}
        count = _live_miss_auto_pin(None, pin, iteration=1)
        assert count == 0


# ---------------------------------------------------------------------------
# 6. family_unresolved sentinel
# ---------------------------------------------------------------------------


class TestFamilyUnresolved:

    def test_no_ptt_gives_unresolved(self):
        """Pool not in PTT must say 'family_unresolved', never empty string."""
        # Use the _build_other_live_pool_trace from test_47o
        from tests.unit.test_47o_overlap_trace import _FakeResult, _build_other_live_pool_trace
        raw = [_FakeResult("0xabc")]
        trace = _build_other_live_pool_trace(raw, set(), set(), ptt_ref=None)
        assert trace[0]["family"] == "family_unresolved"
        assert trace[0]["family"] != ""

    def test_ptt_present_gives_resolved(self):
        from tests.unit.test_47o_overlap_trace import _FakeResult, _build_other_live_pool_trace
        raw = [_FakeResult("0xabc")]
        ptt = {"0xabc": ["0xtokA", "0xtokB", 500]}
        trace = _build_other_live_pool_trace(raw, set(), set(), ptt_ref=ptt)
        assert trace[0]["family"] == "0xtokA/0xtokB"
