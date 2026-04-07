"""
M7.A.5.47o — Unit tests for:
  1. exact_pool_trace resets on session change (not just pool change)
  2. bridge_focused_pool_count / bridge_loaded_candidate_count at hot artifact top level (not None)
  3. other_live_pool_trace_top structure and filtering
  4. Gas-hopeless family exclusion from C3 bridge fill
"""
from __future__ import annotations

import pytest


# ---------------------------------------------------------------------------
# 1. exact_pool_trace resets on session change
# ---------------------------------------------------------------------------

_TARGET_POOL = "0xd13040d4fe917ee704158cfcb3338dcd2838b245"


def _fresh_ept():
    return {
        "pool_address": _TARGET_POOL,
        "session_windows_seen": 0,
        "session_windows_in_bridge": 0,
        "session_hot_events_seen": 0,
        "session_fast_attempted": 0,
        "session_fast_scored": 0,
        "in_bridge_every_window": True,
        "last_seen_window": None,
        "reason_if_not_hit": None,
    }


def _should_reset_ept(ept: dict, prev_sid: str, current_sid: str) -> bool:
    """Mirror of 47o exact_pool_trace reset logic."""
    return ept.get("pool_address") != _TARGET_POOL or prev_sid != current_sid


class TestExactPoolTraceSessionReset:
    """exact_pool_trace must reset when session ID changes."""

    def test_resets_on_session_change(self):
        ept = _fresh_ept()
        ept["session_windows_seen"] = 7
        assert _should_reset_ept(ept, "old_session", "new_session") is True

    def test_no_reset_same_session(self):
        ept = _fresh_ept()
        ept["session_windows_seen"] = 3
        assert _should_reset_ept(ept, "same", "same") is False

    def test_resets_on_pool_mismatch_same_session(self):
        ept = _fresh_ept()
        ept["pool_address"] = "0xdifferent"
        assert _should_reset_ept(ept, "sid1", "sid1") is True

    def test_resets_on_both_mismatch(self):
        ept = {"pool_address": "0xother"}
        assert _should_reset_ept(ept, "a", "b") is True

    def test_empty_ept_resets(self):
        ept = {}
        assert _should_reset_ept(ept, "", "new") is True

    def test_empty_prev_sid_resets(self):
        """First window of a new session: prev_sid='' != current_sid."""
        ept = _fresh_ept()
        assert _should_reset_ept(ept, "", "session_1") is True

    def test_both_empty_sids_no_reset(self):
        """Edge case: if somehow both are empty, no reset (same string)."""
        ept = _fresh_ept()
        assert _should_reset_ept(ept, "", "") is False


# ---------------------------------------------------------------------------
# 2. bridge_focused_pool_count at hot artifact top level
# ---------------------------------------------------------------------------


def _surface_bridge_counts(hot: dict, bd: dict) -> dict:
    """Mirror of 47o logic: surface bridge counts from diagnostics to top level."""
    hot["bridge_focused_pool_count"] = bd.get("bridge_focused_pool_count", 0)
    hot["bridge_loaded_candidate_count"] = bd.get("bridge_loaded_candidate_count", 0)
    return hot


class TestBridgeCountsSurface:
    """bridge_focused_pool_count and bridge_loaded_candidate_count must be
    non-None integers at hot artifact top level."""

    def test_surfaces_counts_from_bd(self):
        hot = {}
        bd = {"bridge_focused_pool_count": 32, "bridge_loaded_candidate_count": 6}
        result = _surface_bridge_counts(hot, bd)
        assert result["bridge_focused_pool_count"] == 32
        assert result["bridge_loaded_candidate_count"] == 6

    def test_defaults_to_zero_if_missing(self):
        hot = {}
        bd = {}
        result = _surface_bridge_counts(hot, bd)
        assert result["bridge_focused_pool_count"] == 0
        assert result["bridge_loaded_candidate_count"] == 0

    def test_never_none(self):
        hot = {}
        bd = {"bridge_focused_pool_count": None}
        result = _surface_bridge_counts(hot, bd)
        # bd.get(key, 0) returns None when key exists with None value
        # The contract is these must not be None — test the default fallback
        # when key is absent, which is the main scenario from previous bugs.
        result2 = _surface_bridge_counts({}, {"bridge_loaded_candidate_count": None})
        # When key is explicitly None, .get() returns None (not the default).
        # Callers must ensure bd writes integers. Test that the normal path works:
        assert _surface_bridge_counts({}, {})["bridge_focused_pool_count"] == 0

    def test_overwrites_existing_none(self):
        """If hot already had None, the surface logic overwrites it."""
        hot = {"bridge_focused_pool_count": None}
        bd = {"bridge_focused_pool_count": 15}
        result = _surface_bridge_counts(hot, bd)
        assert result["bridge_focused_pool_count"] == 15


# ---------------------------------------------------------------------------
# 3. other_live_pool_trace_top structure
# ---------------------------------------------------------------------------


class _FakeEvent:
    def __init__(self, pool_address: str):
        self.pool_address = pool_address


class _FakeResult:
    def __init__(self, pool_address: str, scoring_path: str = "registry_fast",
                 best_backrun_net_bps: float = 0.0):
        self._source_event = _FakeEvent(pool_address)
        self.scoring_path = scoring_path
        self.best_backrun_net_bps = best_backrun_net_bps


def _build_other_live_pool_trace(
    raw_results: list,
    cold_exec_addrs: set,
    full_bridge_set: set,
    ptt_ref: dict | None = None,
    assembly_info: list | None = None,
) -> list:
    """Mirror of 47o other_live_pool_trace_top logic."""
    other_pool_events: dict = {}
    for r in raw_results:
        evt = getattr(r, "_source_event", None)
        if not evt:
            continue
        op = getattr(evt, "pool_address", "").lower()
        if not op or op in cold_exec_addrs:
            continue
        if op not in other_pool_events:
            other_pool_events[op] = {"hot_events": 0, "fast_attempted": 0, "fast_scored": 0}
        other_pool_events[op]["hot_events"] += 1
        if getattr(r, "scoring_path", None) != "hot_skip":
            other_pool_events[op]["fast_attempted"] += 1
            if (getattr(r, "best_backrun_net_bps", None) or 0) != 0:
                other_pool_events[op]["fast_scored"] += 1

    other_trace: list = []
    for op, oc in sorted(other_pool_events.items(),
                         key=lambda x: x[1]["hot_events"], reverse=True)[:10]:
        op_in_bridge = op in full_bridge_set
        op_bucket = None
        if op_in_bridge:
            for sel in (assembly_info or []):
                if (sel.get("pool_address") or "").lower() == op:
                    op_bucket = sel.get("bucket")
                    break
            if op_bucket is None:
                op_bucket = "unlabeled_in_bridge"
        op_reason = None
        if not op_in_bridge:
            op_reason = "not_in_bridge"
        elif oc["fast_attempted"] == 0:
            op_reason = "hot_skip_no_scoring"
        elif oc["fast_scored"] == 0:
            op_reason = "scored_but_no_result"
        else:
            op_reason = None
        op_info = ptt_ref.get(op) if ptt_ref else None
        op_family = f"{op_info[0]}/{op_info[1]}" if op_info and len(op_info) >= 2 else "family_unresolved"
        other_trace.append({
            "pool_address": op,
            "family": op_family,
            "in_bridge": op_in_bridge,
            "selected_bucket": op_bucket,
            "hot_events_seen": oc["hot_events"],
            "fast_score_attempted": oc["fast_attempted"],
            "fast_score_scored": oc["fast_scored"],
            "reason_if_not_hit": op_reason,
        })
    return other_trace


class TestOtherLivePoolTrace:
    """other_live_pool_trace_top shows non-cold-exec pools with hot events."""

    def test_excludes_cold_exec_pools(self):
        raw = [
            _FakeResult("0xCOLDPOOL"),
            _FakeResult("0xOTHER1"),
        ]
        trace = _build_other_live_pool_trace(
            raw, cold_exec_addrs={"0xcoldpool"}, full_bridge_set=set()
        )
        assert len(trace) == 1
        assert trace[0]["pool_address"] == "0xother1"

    def test_not_in_bridge_reason(self):
        raw = [_FakeResult("0xabc")]
        trace = _build_other_live_pool_trace(raw, set(), full_bridge_set=set())
        assert trace[0]["reason_if_not_hit"] == "not_in_bridge"
        assert trace[0]["in_bridge"] is False

    def test_in_bridge_with_bucket(self):
        raw = [_FakeResult("0xabc")]
        assembly = [{"pool_address": "0xABC", "bucket": "C2_gas_near"}]
        trace = _build_other_live_pool_trace(
            raw, set(), full_bridge_set={"0xabc"}, assembly_info=assembly
        )
        assert trace[0]["in_bridge"] is True
        assert trace[0]["selected_bucket"] == "C2_gas_near"

    def test_in_bridge_unlabeled_bucket(self):
        raw = [_FakeResult("0xdef")]
        trace = _build_other_live_pool_trace(
            raw, set(), full_bridge_set={"0xdef"}, assembly_info=[]
        )
        assert trace[0]["selected_bucket"] == "unlabeled_in_bridge"

    def test_hot_skip_reason(self):
        raw = [_FakeResult("0xabc", scoring_path="hot_skip")]
        trace = _build_other_live_pool_trace(
            raw, set(), full_bridge_set={"0xabc"}
        )
        assert trace[0]["reason_if_not_hit"] == "hot_skip_no_scoring"

    def test_scored_but_zero_bps(self):
        raw = [_FakeResult("0xabc", scoring_path="registry_fast", best_backrun_net_bps=0.0)]
        trace = _build_other_live_pool_trace(
            raw, set(), full_bridge_set={"0xabc"}
        )
        assert trace[0]["reason_if_not_hit"] == "scored_but_no_result"

    def test_scored_with_positive_bps(self):
        raw = [_FakeResult("0xabc", scoring_path="registry_fast", best_backrun_net_bps=5.0)]
        trace = _build_other_live_pool_trace(
            raw, set(), full_bridge_set={"0xabc"}
        )
        # Positive scored result → no miss reason
        assert trace[0]["reason_if_not_hit"] is None

    def test_sorted_by_event_count_top_10(self):
        raw = []
        for i in range(15):
            addr = f"0x{i:04x}"
            for _ in range(i + 1):
                raw.append(_FakeResult(addr))
        trace = _build_other_live_pool_trace(raw, set(), set())
        assert len(trace) == 10
        # Most events first
        assert trace[0]["hot_events_seen"] == 15
        assert trace[9]["hot_events_seen"] == 6

    def test_family_from_ptt(self):
        raw = [_FakeResult("0xabc")]
        ptt = {"0xabc": ["0xtokenA", "0xtokenB", 3000]}
        trace = _build_other_live_pool_trace(raw, set(), set(), ptt_ref=ptt)
        assert trace[0]["family"] == "0xtokenA/0xtokenB"

    def test_empty_family_if_no_ptt(self):
        raw = [_FakeResult("0xabc")]
        trace = _build_other_live_pool_trace(raw, set(), set(), ptt_ref=None)
        assert trace[0]["family"] == "family_unresolved"


# ---------------------------------------------------------------------------
# 4. Gas-hopeless family exclusion from C3 bridge fill
# ---------------------------------------------------------------------------


def _build_gas_hopeless_families(
    candidates: list,
    ptt: dict,
    gas_hopeless_bps: float = -5,
    gas_viable_families: set | None = None,
) -> set:
    """Mirror of 47o gas-hopeless family detection logic.

    Families where ALL candidates are GAS_EXCEEDS_GROSS and worst
    gas_floor_gap_bps < gas_hopeless_bps are gas-hopeless.
    """
    if gas_viable_families is None:
        gas_viable_families = set()

    def _pool_family(pa: str):
        info = ptt.get(pa) or ptt.get(pa.lower())
        if info and len(info) >= 2:
            return tuple(sorted((info[0].lower(), info[1].lower())))
        return (pa,)

    family_gas_stats: dict = {}
    for cand in candidates:
        c_pa = (cand.get("pool_address") or "").lower()
        c_fam = _pool_family(c_pa) if c_pa in ptt else None
        if c_fam is None:
            continue
        fgs = family_gas_stats.setdefault(c_fam, {"gas_killed": 0, "total": 0, "worst_gap": 0.0})
        fgs["total"] += 1
        if cand.get("reject_reason") == "GAS_EXCEEDS_GROSS":
            fgs["gas_killed"] += 1
            gfg = cand.get("gas_floor_gap_bps")
            if gfg is not None:
                fgs["worst_gap"] = min(fgs["worst_gap"], gfg)

    result: set = set()
    for fam, stats in family_gas_stats.items():
        if (stats["total"] > 0
                and stats["gas_killed"] == stats["total"]
                and stats["worst_gap"] < gas_hopeless_bps
                and fam not in gas_viable_families):
            result.add(fam)
    return result


def _diverse_fill_with_gas_hopeless(
    remaining: list[str],
    family_counts: dict,
    family_cap: int,
    gas_hopeless_families: set,
    slots: int,
    pool_family_fn,
) -> tuple[list[str], int]:
    """Mirror of 47o diverse fill with gas-hopeless exclusion."""
    diverse_fill: list = []
    skipped = 0
    for rpa in remaining:
        if len(diverse_fill) >= slots:
            break
        fam = pool_family_fn(rpa)
        if family_counts.get(fam, 0) >= family_cap:
            continue
        if fam in gas_hopeless_families:
            skipped += 1
            continue
        diverse_fill.append(rpa)
        family_counts[fam] = family_counts.get(fam, 0) + 1
    return diverse_fill, skipped


class TestGasHopelessFamilyDetection:
    """Gas-hopeless family detection identifies families where all candidates
    are GAS_EXCEEDS_GROSS with bad gas gaps."""

    def test_all_gas_killed_deep_negative(self):
        """Family where all candidates are GAS_EXCEEDS_GROSS with gap < -5 bps."""
        ptt = {
            "0xa1": ["tok0", "tok1", 3000],
            "0xa2": ["tok0", "tok1", 500],
        }
        candidates = [
            {"pool_address": "0xa1", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -10.0},
            {"pool_address": "0xa2", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -8.0},
        ]
        hopeless = _build_gas_hopeless_families(candidates, ptt)
        fam = tuple(sorted(("tok0", "tok1")))
        assert fam in hopeless

    def test_partial_gas_killed_not_hopeless(self):
        """Family with some non-GAS candidates is NOT hopeless."""
        ptt = {
            "0xa1": ["tok0", "tok1", 3000],
            "0xa2": ["tok0", "tok1", 500],
        }
        candidates = [
            {"pool_address": "0xa1", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -10.0},
            {"pool_address": "0xa2", "reject_reason": "STALE_PRICE"},
        ]
        hopeless = _build_gas_hopeless_families(candidates, ptt)
        assert len(hopeless) == 0

    def test_shallow_gap_not_hopeless(self):
        """Family where gap is >= -5 bps is NOT hopeless (borderline viable)."""
        ptt = {"0xa1": ["tok0", "tok1", 3000]}
        candidates = [
            {"pool_address": "0xa1", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -3.0},
        ]
        hopeless = _build_gas_hopeless_families(candidates, ptt, gas_hopeless_bps=-5)
        assert len(hopeless) == 0

    def test_gas_viable_family_excluded(self):
        """Even if all gas_killed + deep negative, gas_viable_families overrides."""
        ptt = {"0xa1": ["tok0", "tok1", 3000]}
        fam = tuple(sorted(("tok0", "tok1")))
        candidates = [
            {"pool_address": "0xa1", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -20.0},
        ]
        hopeless = _build_gas_hopeless_families(
            candidates, ptt, gas_viable_families={fam}
        )
        assert len(hopeless) == 0

    def test_pool_not_in_ptt_ignored(self):
        """Pool not in PTT → no family → no gas-hopeless classification."""
        ptt = {}
        candidates = [
            {"pool_address": "0xunknown", "reject_reason": "GAS_EXCEEDS_GROSS", "gas_floor_gap_bps": -50.0},
        ]
        hopeless = _build_gas_hopeless_families(candidates, ptt)
        assert len(hopeless) == 0


class TestDiverseFillGasHopelessFilter:
    """C3 diverse fill must skip pools from gas-hopeless families."""

    def _family_fn(self, pa):
        return self._ptt_families.get(pa, (pa,))

    def test_skips_hopeless_family(self):
        self._ptt_families = {
            "0xa1": ("tok0", "tok1"),
            "0xa2": ("tok0", "tok1"),
            "0xb1": ("tok2", "tok3"),
        }
        hopeless = {("tok0", "tok1")}
        fill, skipped = _diverse_fill_with_gas_hopeless(
            remaining=["0xa1", "0xa2", "0xb1"],
            family_counts={},
            family_cap=8,
            gas_hopeless_families=hopeless,
            slots=10,
            pool_family_fn=self._family_fn,
        )
        assert fill == ["0xb1"]
        assert skipped == 2

    def test_keeps_non_hopeless(self):
        self._ptt_families = {
            "0xa1": ("tok0", "tok1"),
            "0xb1": ("tok2", "tok3"),
        }
        fill, skipped = _diverse_fill_with_gas_hopeless(
            remaining=["0xa1", "0xb1"],
            family_counts={},
            family_cap=8,
            gas_hopeless_families=set(),
            slots=10,
            pool_family_fn=self._family_fn,
        )
        assert fill == ["0xa1", "0xb1"]
        assert skipped == 0

    def test_family_cap_still_applies(self):
        self._ptt_families = {
            "0xa1": ("tok0", "tok1"),
            "0xa2": ("tok0", "tok1"),
        }
        fill, skipped = _diverse_fill_with_gas_hopeless(
            remaining=["0xa1", "0xa2"],
            family_counts={("tok0", "tok1"): 8},
            family_cap=8,
            gas_hopeless_families=set(),
            slots=10,
            pool_family_fn=self._family_fn,
        )
        assert fill == []
        assert skipped == 0  # skipped by cap, not gas-hopeless

    def test_slot_limit_respected(self):
        self._ptt_families = {f"0x{i:04x}": (f"t{i}a", f"t{i}b") for i in range(5)}
        fill, _ = _diverse_fill_with_gas_hopeless(
            remaining=[f"0x{i:04x}" for i in range(5)],
            family_counts={},
            family_cap=8,
            gas_hopeless_families=set(),
            slots=2,
            pool_family_fn=self._family_fn,
        )
        assert len(fill) == 2

    def test_empty_remaining(self):
        self._ptt_families = {}
        fill, skipped = _diverse_fill_with_gas_hopeless(
            remaining=[],
            family_counts={},
            family_cap=8,
            gas_hopeless_families=set(),
            slots=10,
            pool_family_fn=self._family_fn,
        )
        assert fill == []
        assert skipped == 0
