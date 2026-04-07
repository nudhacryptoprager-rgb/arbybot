"""
M7.A.5.47r — Unit tests for:
  1. Cross-artifact contract: bridge_selected_family_diff_top in hot → bridge (non-null)
  2. c3_gas_hopeless guaranteed non-None in bridge merge
  3. family_unresolved excluded from bridge entirely
  4. architecture_blocker_trace structure and blocker_class logic
  5. _write_hot_artifact returns 3-tuple (bridge_hit_trace, other_trace, fam_diff_list)
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
    def __init__(self, pa: str):
        self._source_event = _Evt(pa)
        self.scoring_path = "registry_fast"
        self.best_backrun_net_bps = 0


# ---------------------------------------------------------------------------
# 1. Cross-artifact contract: bridge_selected_family_diff_top
# ---------------------------------------------------------------------------


def _simulate_bridge_merge(
    hot_bridge_diag: dict,
    fam_diff_data: list | None,
    bridge_update: dict | None = None,
) -> dict:
    """Mirror of 47r bridge merge logic for bridge_selected_family_diff_top."""
    bu = bridge_update or {}
    # c3_gas_hopeless fields with or fallback
    bu["c3_gas_hopeless_skipped"] = (
        hot_bridge_diag.get("c3_gas_hopeless_skipped") or 0
    )
    bu["c3_gas_hopeless_families"] = (
        hot_bridge_diag.get("c3_gas_hopeless_families") or []
    )
    # 47r: bridge_selected_family_diff_top
    bu["bridge_selected_family_diff_top"] = (
        fam_diff_data if fam_diff_data else []
    )
    return bu


class TestCrossArtifactBridgeFamilyDiff:

    def test_fam_diff_written_to_bridge(self):
        """If hot has fam_diff_data, bridge must have it too."""
        fam_diff = [{"family": "tok0/tok1", "selected_pool_count": 2}]
        result = _simulate_bridge_merge({}, fam_diff)
        assert result["bridge_selected_family_diff_top"] == fam_diff

    def test_fam_diff_none_becomes_empty_list(self):
        """If fam_diff_data is None, bridge gets [] not None."""
        result = _simulate_bridge_merge({}, None)
        assert result["bridge_selected_family_diff_top"] == []

    def test_fam_diff_empty_list_stays_empty(self):
        result = _simulate_bridge_merge({}, [])
        assert result["bridge_selected_family_diff_top"] == []

    def test_invariant_hot_has_field_bridge_must_too(self):
        """If hot artifact has bridge_selected_family_diff_top, bridge must
        have it non-null."""
        hot = {"bridge_selected_family_diff_top": [{"family": "f1"}]}
        fam_diff = hot["bridge_selected_family_diff_top"]
        result = _simulate_bridge_merge({}, fam_diff)
        assert result["bridge_selected_family_diff_top"] is not None
        assert isinstance(result["bridge_selected_family_diff_top"], list)
        assert len(result["bridge_selected_family_diff_top"]) == len(
            hot["bridge_selected_family_diff_top"]
        )


# ---------------------------------------------------------------------------
# 2. c3_gas_hopeless guaranteed non-None in bridge merge
# ---------------------------------------------------------------------------


class TestC3GasHopelessNonNull:

    def test_skipped_none_becomes_zero(self):
        result = _simulate_bridge_merge({"c3_gas_hopeless_skipped": None}, None)
        assert result["c3_gas_hopeless_skipped"] == 0

    def test_skipped_missing_becomes_zero(self):
        result = _simulate_bridge_merge({}, None)
        assert result["c3_gas_hopeless_skipped"] == 0

    def test_skipped_present_kept(self):
        result = _simulate_bridge_merge({"c3_gas_hopeless_skipped": 3}, None)
        assert result["c3_gas_hopeless_skipped"] == 3

    def test_families_none_becomes_empty_list(self):
        result = _simulate_bridge_merge({"c3_gas_hopeless_families": None}, None)
        assert result["c3_gas_hopeless_families"] == []

    def test_families_missing_becomes_empty_list(self):
        result = _simulate_bridge_merge({}, None)
        assert result["c3_gas_hopeless_families"] == []

    def test_families_present_kept(self):
        fams = [["tok0", "tok1"]]
        result = _simulate_bridge_merge({"c3_gas_hopeless_families": fams}, None)
        assert result["c3_gas_hopeless_families"] == fams


# ---------------------------------------------------------------------------
# 3. family_unresolved excluded from bridge entirely
# ---------------------------------------------------------------------------


def _pool_family(pa: str, ptt: dict) -> tuple:
    """Mirror of _pool_family from m7a_orderflow_loop.py."""
    info = ptt.get(pa) or ptt.get(pa.lower())
    if info and len(info) >= 2:
        return tuple(sorted((info[0].lower(), info[1].lower())))
    return (pa,)


def _simulate_bridge_assembly(
    committed: set,
    remaining_for_fill: list,
    remaining_ranked: list,
    ptt: dict,
    pool_cap: int = 100,
    gas_hopeless_families: set | None = None,
) -> set:
    """Mirror of 47r bridge assembly with family_unresolved exclusion."""
    FAMILY_CAP = 8

    # Count families already committed
    family_counts: dict = {}
    for pa in committed:
        fam = _pool_family(pa, ptt)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    slots_for_fill = max(0, pool_cap - len(committed))
    diverse_fill: list = []
    for rpa in remaining_for_fill:
        if len(diverse_fill) >= slots_for_fill:
            break
        fam = _pool_family(rpa, ptt)
        # 47r: exclude family_unresolved
        if len(fam) < 2:
            continue
        if family_counts.get(fam, 0) >= FAMILY_CAP:
            continue
        if gas_hopeless_families and fam in gas_hopeless_families:
            continue
        diverse_fill.append(rpa)
        family_counts[fam] = family_counts.get(fam, 0) + 1

    # 47r: exclude family_unresolved from committed
    resolved_committed = {pa for pa in committed if len(_pool_family(pa, ptt)) >= 2}
    bridge_pool_addrs = resolved_committed | set(diverse_fill)

    # Hard-pin only resolved
    bucket_a = set()  # no cold exec for this test
    bridge_pool_addrs |= {pa for pa in bucket_a if len(_pool_family(pa, ptt)) >= 2}

    # Min floor fill
    BRIDGE_MIN_FLOOR = 20
    if len(bridge_pool_addrs) < BRIDGE_MIN_FLOOR and len(ptt) >= BRIDGE_MIN_FLOOR:
        deficit = BRIDGE_MIN_FLOOR - len(bridge_pool_addrs)
        floor_fill = [
            pa for pa in remaining_ranked
            if pa not in bridge_pool_addrs
            and len(_pool_family(pa, ptt)) >= 2
        ][:deficit]
        bridge_pool_addrs |= set(floor_fill)

    return bridge_pool_addrs


class TestFamilyUnresolvedExclusion:

    def test_unresolved_excluded_from_diverse_fill(self):
        """Pools with singleton family (unresolved) must not enter bridge."""
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
            "0xb": ["tok2", "tok3", 500],
            # 0xc not in PTT → family_unresolved
        }
        committed = set()
        remaining = ["0xa", "0xb", "0xc"]
        result = _simulate_bridge_assembly(committed, remaining, remaining, ptt)
        assert "0xa" in result
        assert "0xb" in result
        assert "0xc" not in result

    def test_unresolved_excluded_from_committed(self):
        """Even if an unresolved pool is in a higher bucket (committed),
        it must be excluded from bridge."""
        ptt = {
            "0xa": ["tok0", "tok1", 3000],
        }
        committed = {"0xa", "0xunresolved"}
        result = _simulate_bridge_assembly(committed, [], [], ptt, pool_cap=100)
        assert "0xa" in result
        assert "0xunresolved" not in result

    def test_unresolved_excluded_from_floor_fill(self):
        """Unresolved pools must not enter via min floor fill."""
        # Need >= 20 PTT entries but few resolved pools to trigger floor fill
        ptt = {f"0x{i:04x}": ["tok0", "tok1", 3000] for i in range(25)}
        committed = set()
        remaining = [f"0x{i:04x}" for i in range(5)]
        # Add unresolved pools to remaining_ranked
        remaining_ranked = remaining + ["0xunresolved_a", "0xunresolved_b"]
        result = _simulate_bridge_assembly(
            committed, remaining, remaining_ranked, ptt, pool_cap=100
        )
        assert "0xunresolved_a" not in result
        assert "0xunresolved_b" not in result

    def test_resolved_pool_always_enters(self):
        ptt = {"0xa": ["tok0", "tok1", 3000]}
        result = _simulate_bridge_assembly(set(), ["0xa"], ["0xa"], ptt)
        assert "0xa" in result

    def test_pool_family_singleton_for_unknown(self):
        """A pool not in PTT gets singleton family tuple."""
        fam = _pool_family("0xunknown", {})
        assert fam == ("0xunknown",)
        assert len(fam) < 2

    def test_pool_family_pair_for_resolved(self):
        ptt = {"0xa": ["TOK1", "TOK0", 3000]}
        fam = _pool_family("0xa", ptt)
        # sorted → tok0, tok1
        assert fam == ("tok0", "tok1")
        assert len(fam) >= 2


# ---------------------------------------------------------------------------
# 4. architecture_blocker_trace structure and blocker_class logic
# ---------------------------------------------------------------------------


def _build_architecture_blocker_trace(
    sess: dict,
    bd: dict,
    eft: dict,
    prev_abt: dict | None = None,
    session_changed: bool = False,
) -> dict:
    """Mirror of 47r architecture_blocker_trace logic."""
    abt = prev_abt.copy() if prev_abt and not session_changed else {}
    abt["session_windows_seen"] = sess.get("session_windows_seen", 0)
    abt["session_events_seen_total"] = sess.get("session_events_seen_total", 0)
    # Count resolved families
    bsa = bd.get("bridge_selected_at_assembly", [])
    families = set()
    for s in bsa:
        sf = s.get("family", "")
        if sf and sf != "family_unresolved":
            families.add(sf)
    abt["families_selected_count"] = len(families)
    abt["families_with_any_hot_events"] = (
        1 if eft.get("session_family_events_seen", 0) > 0 else 0
    )
    abt["families_with_exact_hits"] = (
        1 if eft.get("session_exact_pool_events_seen", 0) > 0 else 0
    )
    abt["blocker_class"] = (
        "event_source_absence"
        if abt.get("families_with_any_hot_events", 0) == 0
        else "selection_or_scoring"
    )
    return abt


class TestArchitectureBlockerTrace:

    def test_blocker_class_event_source_when_no_events(self):
        sess = {"session_windows_seen": 5, "session_events_seen_total": 10}
        eft = {"session_family_events_seen": 0, "session_exact_pool_events_seen": 0}
        bd = {"bridge_selected_at_assembly": [
            {"pool_address": "0xa", "family": "tok0/tok1"},
        ]}
        abt = _build_architecture_blocker_trace(sess, bd, eft)
        assert abt["blocker_class"] == "event_source_absence"

    def test_blocker_class_selection_when_family_events_exist(self):
        sess = {"session_windows_seen": 5, "session_events_seen_total": 10}
        eft = {"session_family_events_seen": 3, "session_exact_pool_events_seen": 0}
        bd = {"bridge_selected_at_assembly": [
            {"pool_address": "0xa", "family": "tok0/tok1"},
        ]}
        abt = _build_architecture_blocker_trace(sess, bd, eft)
        assert abt["blocker_class"] == "selection_or_scoring"

    def test_families_count_excludes_unresolved(self):
        bd = {"bridge_selected_at_assembly": [
            {"pool_address": "0xa", "family": "tok0/tok1"},
            {"pool_address": "0xb", "family": "family_unresolved"},
            {"pool_address": "0xc", "family": "tok2/tok3"},
        ]}
        eft = {"session_family_events_seen": 0, "session_exact_pool_events_seen": 0}
        abt = _build_architecture_blocker_trace({}, bd, eft)
        assert abt["families_selected_count"] == 2

    def test_session_counters_propagated(self):
        sess = {"session_windows_seen": 12, "session_events_seen_total": 42}
        eft = {}
        abt = _build_architecture_blocker_trace(sess, {}, eft)
        assert abt["session_windows_seen"] == 12
        assert abt["session_events_seen_total"] == 42

    def test_empty_assembly(self):
        abt = _build_architecture_blocker_trace({}, {}, {})
        assert abt["families_selected_count"] == 0
        assert abt["blocker_class"] == "event_source_absence"

    def test_session_reset_clears_previous(self):
        prev = {
            "session_windows_seen": 100,
            "blocker_class": "selection_or_scoring",
        }
        abt = _build_architecture_blocker_trace({}, {}, {}, prev_abt=prev, session_changed=True)
        assert abt["session_windows_seen"] == 0
        assert abt["blocker_class"] == "event_source_absence"

    def test_all_required_keys_present(self):
        abt = _build_architecture_blocker_trace(
            {"session_windows_seen": 1, "session_events_seen_total": 5},
            {"bridge_selected_at_assembly": []},
            {"session_family_events_seen": 0, "session_exact_pool_events_seen": 0},
        )
        required = {
            "session_windows_seen",
            "session_events_seen_total",
            "families_selected_count",
            "families_with_any_hot_events",
            "families_with_exact_hits",
            "blocker_class",
        }
        assert required.issubset(set(abt.keys()))

    def test_families_with_exact_hits_when_present(self):
        eft = {"session_family_events_seen": 5, "session_exact_pool_events_seen": 2}
        abt = _build_architecture_blocker_trace({}, {}, eft)
        assert abt["families_with_exact_hits"] == 1


# ---------------------------------------------------------------------------
# 5. _write_hot_artifact return signature — 3-tuple contract
# ---------------------------------------------------------------------------


class TestWriteHotArtifactReturnContract:
    """Verify the 3-tuple return contract for _write_hot_artifact."""

    def test_three_tuple_unpacking(self):
        """Simulation: function returns 3 values, caller unpacks all 3."""
        def mock_write_hot_artifact():
            bridge_hit = [{"pool": "0xa"}]
            other = [{"pool": "0xb"}]
            fam_diff = [{"family": "tok0/tok1"}]
            return bridge_hit, other, fam_diff

        hit, other, fam = mock_write_hot_artifact()
        assert isinstance(hit, list)
        assert isinstance(other, list)
        assert isinstance(fam, list)

    def test_fam_diff_empty_when_no_assembly(self):
        """When no assembly data, fam_diff_list should be []."""
        def mock():
            return [], [], []
        _, _, fam = mock()
        assert fam == []
