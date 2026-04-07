"""
M7.A.5.47q — Unit tests for:
  1. bridge_selected_family_diff_top — family-level aggregation
  2. exact_family_trace — session-level family trace with sibling discovery
  3. Sibling-pool auto-pin (3 per family, skips already pinned)
  4. stale_sub_reason surfaced in bridge_hit_trace entries
  5. family_unresolved downgrade from A_cold_exec
  6. c3_gas_hopeless in bridge file merge
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

class _Evt:
    def __init__(self, pa: str):
        self.pool_address = pa


class _Res:
    def __init__(self, pa: str, scoring_path: str = "registry_fast"):
        self._source_event = _Evt(pa)
        self.scoring_path = scoring_path


# ---------------------------------------------------------------------------
# 1. bridge_selected_family_diff_top
# ---------------------------------------------------------------------------


def _build_family_diff(assembly: list, raw_results: list) -> list:
    """Mirror of 47q bridge_selected_family_diff_top logic."""
    fam_diff: dict = {}
    for sel in assembly[:30]:
        sel_pa = (sel.get("pool_address") or "").lower()
        sel_fam = sel.get("family") or "family_unresolved"
        if not sel_fam or sel_fam == "":
            sel_fam = "family_unresolved"
        if sel_fam not in fam_diff:
            fam_diff[sel_fam] = {
                "family": sel_fam,
                "selected_pool_count": 0,
                "hot_events_any_pool": 0,
                "exact_hit_count": 0,
                "pools": [],
            }
        fd = fam_diff[sel_fam]
        fd["selected_pool_count"] += 1
        sel_events = 0
        for r in raw_results:
            evt = getattr(r, "_source_event", None)
            if evt and getattr(evt, "pool_address", "").lower() == sel_pa:
                sel_events += 1
        fd["hot_events_any_pool"] += sel_events
        if sel_events > 0:
            fd["exact_hit_count"] += 1
        fd["pools"].append(sel_pa)
    result = []
    for fd in sorted(fam_diff.values(), key=lambda x: x["selected_pool_count"], reverse=True):
        reason_z = None
        if fd["hot_events_any_pool"] == 0:
            reason_z = "no_events_at_any_family_pool"
        elif fd["exact_hit_count"] == 0:
            reason_z = "events_at_family_but_no_exact_match"
        fd["reason_if_zero"] = reason_z
        del fd["pools"]
        result.append(fd)
    return result[:10]


class TestBridgeSelectedFamilyDiff:

    def test_empty_assembly(self):
        result = _build_family_diff([], [])
        assert result == []

    def test_single_family_no_events(self):
        assembly = [
            {"pool_address": "0xA", "family": "tok0/tok1"},
            {"pool_address": "0xB", "family": "tok0/tok1"},
        ]
        result = _build_family_diff(assembly, [])
        assert len(result) == 1
        assert result[0]["family"] == "tok0/tok1"
        assert result[0]["selected_pool_count"] == 2
        assert result[0]["hot_events_any_pool"] == 0
        assert result[0]["reason_if_zero"] == "no_events_at_any_family_pool"

    def test_events_at_one_pool_not_other(self):
        """Events hit pool A but not B → exact_hit=1, events>0, reason None."""
        assembly = [
            {"pool_address": "0xA", "family": "tok0/tok1"},
            {"pool_address": "0xB", "family": "tok0/tok1"},
        ]
        raw = [_Res("0xA")]
        result = _build_family_diff(assembly, raw)
        assert result[0]["hot_events_any_pool"] == 1
        assert result[0]["exact_hit_count"] == 1
        # Family has events, at least one exact hit → reason is None
        assert result[0]["reason_if_zero"] is None

    def test_multiple_families_sorted_by_count(self):
        assembly = [
            {"pool_address": "0xA", "family": "f1"},
            {"pool_address": "0xB", "family": "f1"},
            {"pool_address": "0xC", "family": "f1"},
            {"pool_address": "0xD", "family": "f2"},
        ]
        result = _build_family_diff(assembly, [])
        assert result[0]["family"] == "f1"
        assert result[0]["selected_pool_count"] == 3
        assert result[1]["family"] == "f2"
        assert result[1]["selected_pool_count"] == 1

    def test_family_unresolved_fallback(self):
        """Missing or empty family uses sentinel."""
        assembly = [{"pool_address": "0xA", "family": ""}]
        result = _build_family_diff(assembly, [])
        assert result[0]["family"] == "family_unresolved"

    def test_family_none_fallback(self):
        assembly = [{"pool_address": "0xA", "family": None}]
        result = _build_family_diff(assembly, [])
        assert result[0]["family"] == "family_unresolved"

    def test_truncation_to_10(self):
        assembly = [
            {"pool_address": f"0x{i:04x}", "family": f"fam_{i}"}
            for i in range(15)
        ]
        result = _build_family_diff(assembly, [])
        assert len(result) == 10

    def test_events_at_family_but_no_exact_match_impossible_here(self):
        """events_at_family_but_no_exact_match only possible with
        aggregation across different pool_addresses in the same family
        where only non-assembly pools get events. In practice with this
        function, if hot_events_any_pool > 0 then exact_hit_count > 0."""
        # This reason requires: events counted (>0) but exact_hit_count=0.
        # With the current logic counting events per-pool, this can't
        # happen unless events arrive at a pool counted under family
        # from a different assembly entry. Test the logic path anyway.
        assembly = [
            {"pool_address": "0xA", "family": "f1"},
            {"pool_address": "0xB", "family": "f1"},
        ]
        # Events only at pool 0xC (not in assembly) — won't be counted.
        raw = [_Res("0xC")]
        result = _build_family_diff(assembly, raw)
        assert result[0]["reason_if_zero"] == "no_events_at_any_family_pool"


# ---------------------------------------------------------------------------
# 2. exact_family_trace — session-level family trace
# ---------------------------------------------------------------------------


def _build_exact_family_trace(
    target_pool: str,
    ptt: dict,
    assembly: list,
    fast_results: list,
    prev_trace: dict | None = None,
    session_changed: bool = False,
) -> dict:
    """Mirror of 47q exact_family_trace logic."""
    target_info = ptt.get(target_pool)
    target_family = (
        f"{target_info[0]}/{target_info[1]}"
        if target_info and len(target_info) >= 2
        else "family_unresolved"
    )
    eft = prev_trace.copy() if prev_trace and not session_changed else {}
    if eft.get("family") != target_family or session_changed:
        eft = {
            "family": target_family,
            "selected_pools": [],
            "session_family_events_seen": 0,
            "session_exact_pool_events_seen": 0,
            "reason_if_no_exact_hit": None,
        }
    # Discover siblings
    sibling_pools: list = []
    for sel in assembly:
        sp_fam = sel.get("family", "")
        if sp_fam == target_family or (
            target_info and sp_fam and target_info[0] in sp_fam and target_info[1] in sp_fam
        ):
            sp_pa = (sel.get("pool_address") or "").lower()
            if sp_pa and sp_pa not in eft.get("selected_pools", []):
                eft.setdefault("selected_pools", []).append(sp_pa)
            sibling_pools.append(sp_pa)
    # Count events
    family_events = 0
    exact_events = 0
    for r in fast_results:
        evt = getattr(r, "_source_event", None)
        if not evt:
            continue
        ep = getattr(evt, "pool_address", "").lower()
        if ep == target_pool:
            exact_events += 1
            family_events += 1
        elif ep in sibling_pools:
            family_events += 1
    eft["session_family_events_seen"] = eft.get("session_family_events_seen", 0) + family_events
    eft["session_exact_pool_events_seen"] = eft.get("session_exact_pool_events_seen", 0) + exact_events
    # Reason
    if family_events == 0 and exact_events == 0:
        eft["reason_if_no_exact_hit"] = "no_events_at_any_family_pool"
    elif family_events > 0 and exact_events == 0:
        eft["reason_if_no_exact_hit"] = "events_at_sibling_not_exact_pool"
    else:
        eft["reason_if_no_exact_hit"] = None
    eft["selected_pools"] = eft.get("selected_pools", [])[:20]
    return eft


class TestExactFamilyTrace:

    _TARGET = "0xd130"

    def test_new_session_initializes(self):
        ptt = {self._TARGET: ["tokA", "tokB", 3000]}
        eft = _build_exact_family_trace(self._TARGET, ptt, [], [])
        assert eft["family"] == "tokA/tokB"
        assert eft["session_family_events_seen"] == 0
        assert eft["session_exact_pool_events_seen"] == 0
        assert eft["reason_if_no_exact_hit"] == "no_events_at_any_family_pool"

    def test_no_ptt_gives_unresolved(self):
        eft = _build_exact_family_trace(self._TARGET, {}, [], [])
        assert eft["family"] == "family_unresolved"

    def test_events_at_exact_pool(self):
        ptt = {self._TARGET: ["tokA", "tokB", 3000]}
        assembly = [{"pool_address": self._TARGET, "family": "tokA/tokB"}]
        fast = [_Res(self._TARGET)]
        eft = _build_exact_family_trace(self._TARGET, ptt, assembly, fast)
        assert eft["session_exact_pool_events_seen"] == 1
        assert eft["session_family_events_seen"] == 1
        assert eft["reason_if_no_exact_hit"] is None

    def test_events_at_sibling_not_exact(self):
        ptt = {
            self._TARGET: ["tokA", "tokB", 3000],
            "0xsibling": ["tokA", "tokB", 500],
        }
        assembly = [
            {"pool_address": self._TARGET, "family": "tokA/tokB"},
            {"pool_address": "0xsibling", "family": "tokA/tokB"},
        ]
        fast = [_Res("0xsibling")]
        eft = _build_exact_family_trace(self._TARGET, ptt, assembly, fast)
        assert eft["session_family_events_seen"] == 1
        assert eft["session_exact_pool_events_seen"] == 0
        assert eft["reason_if_no_exact_hit"] == "events_at_sibling_not_exact_pool"

    def test_cumulative_across_windows(self):
        """Session counters accumulate across calls."""
        ptt = {self._TARGET: ["tokA", "tokB", 3000]}
        assembly = [{"pool_address": self._TARGET, "family": "tokA/tokB"}]
        fast1 = [_Res(self._TARGET)]
        eft1 = _build_exact_family_trace(self._TARGET, ptt, assembly, fast1)
        assert eft1["session_exact_pool_events_seen"] == 1
        # Second window
        fast2 = [_Res(self._TARGET), _Res(self._TARGET)]
        eft2 = _build_exact_family_trace(
            self._TARGET, ptt, assembly, fast2, prev_trace=eft1
        )
        assert eft2["session_exact_pool_events_seen"] == 3
        assert eft2["session_family_events_seen"] == 3

    def test_session_change_resets(self):
        ptt = {self._TARGET: ["tokA", "tokB", 3000]}
        prev = {
            "family": "tokA/tokB",
            "selected_pools": [self._TARGET],
            "session_family_events_seen": 99,
            "session_exact_pool_events_seen": 42,
            "reason_if_no_exact_hit": None,
        }
        eft = _build_exact_family_trace(
            self._TARGET, ptt, [], [], prev_trace=prev, session_changed=True,
        )
        assert eft["session_family_events_seen"] == 0
        assert eft["session_exact_pool_events_seen"] == 0

    def test_selected_pools_truncated_to_20(self):
        ptt = {self._TARGET: ["tokA", "tokB", 3000]}
        assembly = [
            {"pool_address": f"0x{i:04x}", "family": "tokA/tokB"}
            for i in range(30)
        ]
        eft = _build_exact_family_trace(self._TARGET, ptt, assembly, [])
        assert len(eft["selected_pools"]) <= 20


# ---------------------------------------------------------------------------
# 3. Sibling-pool auto-pin
# ---------------------------------------------------------------------------


def _sibling_auto_pin(
    bridge_hit_trace: list,
    ptt: dict,
    bridge_pool_addrs: set,
    hot_seen_pin: dict,
    iteration: int,
    ttl: int = 5,
) -> int:
    """Mirror of 47q sibling-pool auto-pin logic."""
    pinned = 0
    cold_families: dict = {}
    for bht in bridge_hit_trace:
        bht_pa = (bht.get("pool_address") or "").lower()
        bht_info = ptt.get(bht_pa)
        if bht_info and len(bht_info) >= 2:
            bht_fam = tuple(sorted((bht_info[0].lower(), bht_info[1].lower())))
            cold_families.setdefault(bht_fam, []).append(bht_pa)
    for sib_fam, _ in cold_families.items():
        sib_candidates = []
        for sib_pa, sib_info in ptt.items():
            if not sib_info or len(sib_info) < 2:
                continue
            sib_pa_low = sib_pa.lower()
            sib_fam_check = tuple(sorted((sib_info[0].lower(), sib_info[1].lower())))
            if (sib_fam_check == sib_fam
                    and sib_pa_low not in bridge_pool_addrs
                    and sib_pa_low not in hot_seen_pin):
                sib_candidates.append(sib_pa_low)
        for sib_c in sib_candidates[:3]:
            hot_seen_pin[sib_c] = {
                "ttl": ttl,
                "last_iter": iteration,
                "source": "family_sibling_pin",
            }
            pinned += 1
    return pinned


class TestSiblingAutoPin:

    def test_pins_siblings_not_in_bridge(self):
        trace = [{"pool_address": "0xA"}]
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
            "0xb": ["tok0", "tok1", 500],
            "0xc": ["tok0", "tok1", 100],
        }
        pin: dict = {}
        count = _sibling_auto_pin(trace, ptt, {"0xa"}, pin, iteration=1)
        assert count == 2  # 0xb and 0xc
        assert "0xb" in pin
        assert "0xc" in pin
        assert pin["0xb"]["source"] == "family_sibling_pin"

    def test_skips_already_pinned(self):
        trace = [{"pool_address": "0xA"}]
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
            "0xb": ["tok0", "tok1", 500],
        }
        pin = {"0xb": {"ttl": 3, "last_iter": 0, "source": "other"}}
        count = _sibling_auto_pin(trace, ptt, {"0xa"}, pin, iteration=1)
        assert count == 0
        assert pin["0xb"]["source"] == "other"  # Not overwritten

    def test_skips_pools_already_in_bridge(self):
        trace = [{"pool_address": "0xA"}]
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
            "0xb": ["tok0", "tok1", 500],
        }
        pin: dict = {}
        count = _sibling_auto_pin(trace, ptt, {"0xa", "0xb"}, pin, iteration=1)
        assert count == 0

    def test_caps_at_3_per_family(self):
        trace = [{"pool_address": "0xA"}]
        ptt = {"0xa": ["tok0", "tok1", 3000]}
        for i in range(10):
            ptt[f"0x{i+10:04x}"] = ["tok0", "tok1", i * 100]
        pin: dict = {}
        count = _sibling_auto_pin(trace, ptt, {"0xa"}, pin, iteration=1)
        assert count == 3

    def test_empty_trace(self):
        pin: dict = {}
        count = _sibling_auto_pin([], {}, set(), pin, iteration=1)
        assert count == 0

    def test_no_ptt_match(self):
        trace = [{"pool_address": "0xA"}]
        ptt = {"0xa": ["tok0", "tok1", 3000]}
        # No siblings in PTT
        pin: dict = {}
        count = _sibling_auto_pin(trace, ptt, {"0xa"}, pin, iteration=1)
        assert count == 0

    def test_multiple_families(self):
        trace = [
            {"pool_address": "0xA"},
            {"pool_address": "0xD"},
        ]
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
            "0xb": ["tok0", "tok1", 500],
            "0xd": ["tok2", "tok3", 3000],
            "0xe": ["tok2", "tok3", 500],
        }
        pin: dict = {}
        count = _sibling_auto_pin(trace, ptt, {"0xa", "0xd"}, pin, iteration=1)
        assert count == 2
        assert "0xb" in pin
        assert "0xe" in pin


# ---------------------------------------------------------------------------
# 4. stale_sub_reason in bridge_hit_trace entries
# ---------------------------------------------------------------------------


def _build_hit_trace_entry(cold_exec: dict) -> dict:
    """Mirror of 47q bridge_hit_trace entry builder (fields only)."""
    return {
        "pool_address": (cold_exec.get("pool_address") or "").lower(),
        "actual_pair": cold_exec.get("actual_pair", ""),
        "cold_net_bps": cold_exec.get("net_bps", 0),
        "stale_sub_reason": cold_exec.get("stale_sub_reason"),
    }


class TestStaleSubReason:

    def test_pipeline_abort_surfaced(self):
        entry = _build_hit_trace_entry({
            "pool_address": "0xABC",
            "actual_pair": "RAIN/WETH",
            "net_bps": 10.5,
            "stale_sub_reason": "pipeline_abort",
        })
        assert entry["stale_sub_reason"] == "pipeline_abort"

    def test_block_lag_surfaced(self):
        entry = _build_hit_trace_entry({
            "pool_address": "0xABC",
            "stale_sub_reason": "block_lag",
        })
        assert entry["stale_sub_reason"] == "block_lag"

    def test_none_when_not_stale(self):
        entry = _build_hit_trace_entry({
            "pool_address": "0xABC",
        })
        assert entry["stale_sub_reason"] is None

    def test_state_recheck_surfaced(self):
        entry = _build_hit_trace_entry({
            "pool_address": "0xABC",
            "stale_sub_reason": "state_recheck",
        })
        assert entry["stale_sub_reason"] == "state_recheck"


# ---------------------------------------------------------------------------
# 5. family_unresolved downgrade from A_cold_exec
# ---------------------------------------------------------------------------


def _apply_bucket_assignment(pool: str, ptt: dict | None, bucket: str) -> tuple[str, str]:
    """Mirror of 47q bucket assignment with family_unresolved downgrade.
    Returns (family, bucket)."""
    info = ptt.get(pool) if ptt else None
    fam = "family_unresolved"
    if info and len(info) >= 2:
        fam = f"{info[0]}/{info[1]}"
    if fam == "family_unresolved" and bucket == "A_cold_exec":
        bucket = "C3_activity_fill"
    return fam, bucket


class TestFamilyUnresolvedDowngrade:

    def test_unresolved_downgraded_from_a(self):
        fam, bucket = _apply_bucket_assignment("0xabc", None, "A_cold_exec")
        assert fam == "family_unresolved"
        assert bucket == "C3_activity_fill"

    def test_resolved_stays_in_a(self):
        ptt = {"0xabc": ["tok0", "tok1", 3000]}
        fam, bucket = _apply_bucket_assignment("0xabc", ptt, "A_cold_exec")
        assert fam == "tok0/tok1"
        assert bucket == "A_cold_exec"

    def test_unresolved_in_b_stays_b(self):
        """Only A_cold_exec is downgraded; other buckets are unaffected."""
        fam, bucket = _apply_bucket_assignment("0xabc", None, "B_hot_seen")
        assert bucket == "B_hot_seen"

    def test_unresolved_in_c1_stays_c1(self):
        fam, bucket = _apply_bucket_assignment("0xabc", None, "C1_stale_recovery")
        assert bucket == "C1_stale_recovery"

    def test_empty_ptt_gives_unresolved(self):
        fam, bucket = _apply_bucket_assignment("0xabc", {}, "A_cold_exec")
        assert fam == "family_unresolved"
        assert bucket == "C3_activity_fill"

    def test_ptt_short_entry_unresolved(self):
        """PTT entry with only 1 element cannot resolve family."""
        ptt = {"0xabc": ["tok0"]}
        fam, bucket = _apply_bucket_assignment("0xabc", ptt, "A_cold_exec")
        assert fam == "family_unresolved"
        assert bucket == "C3_activity_fill"


# ---------------------------------------------------------------------------
# 6. c3_gas_hopeless in bridge file merge
# ---------------------------------------------------------------------------


def _merge_gas_hopeless(bridge_update: dict, diag: dict) -> dict:
    """Mirror of 47q c3_gas_hopeless merge into bridge file."""
    bridge_update["c3_gas_hopeless_skipped"] = diag.get("c3_gas_hopeless_skipped") or 0
    bridge_update["c3_gas_hopeless_families"] = diag.get("c3_gas_hopeless_families") or []
    return bridge_update


class TestGasHopelessInBridge:

    def test_merge_normal(self):
        diag = {"c3_gas_hopeless_skipped": 5, "c3_gas_hopeless_families": ["f1", "f2"]}
        result = _merge_gas_hopeless({}, diag)
        assert result["c3_gas_hopeless_skipped"] == 5
        assert result["c3_gas_hopeless_families"] == ["f1", "f2"]

    def test_merge_missing_keys(self):
        result = _merge_gas_hopeless({}, {})
        assert result["c3_gas_hopeless_skipped"] == 0
        assert result["c3_gas_hopeless_families"] == []

    def test_merge_overwrites_existing(self):
        bridge = {"c3_gas_hopeless_skipped": 99}
        diag = {"c3_gas_hopeless_skipped": 3, "c3_gas_hopeless_families": ["x"]}
        result = _merge_gas_hopeless(bridge, diag)
        assert result["c3_gas_hopeless_skipped"] == 3

    def test_merge_none_becomes_zero(self):
        diag = {"c3_gas_hopeless_skipped": None}
        result = _merge_gas_hopeless({}, diag)
        assert result["c3_gas_hopeless_skipped"] == 0
        assert result["c3_gas_hopeless_families"] == []
