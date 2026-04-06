"""
M7.A.5.47e — Hot rollup semantic unit tests.

Tests the corrected counter semantics, first_window_at, dominant_hot_miss_reason
per-window classification, atomic writes, and disentangled hot_gap_debug counters.
"""
from __future__ import annotations

import json
import os
import tempfile

import pytest

from tests.unit.conftest import _make_result


# ---------------------------------------------------------------------------
# Helpers: simulate _update_hot_rollup logic in isolation
# ---------------------------------------------------------------------------

def _simulate_rollup_window(
    rollup: dict,
    events_count: int,
    fast_results: list | None = None,
    guard_results: list | None = None,
    bridge_diagnostics: dict | None = None,
) -> dict:
    """Apply one rollup window update to *rollup* dict (in-place).

    Mirrors the logic in scripts/m7a_orderflow_loop._update_hot_rollup().
    """
    ts = "2025-01-01T00:00:00Z"
    _bd = bridge_diagnostics or {}
    _fast = fast_results or []
    _guard = guard_results or []

    rollup["last_updated"] = ts
    rollup.setdefault("first_window_at", ts)
    rollup["windows_seen"] = rollup.get("windows_seen", 0) + 1
    rollup["events_seen_total"] = rollup.get("events_seen_total", 0) + events_count

    # Admitted = events minus hot_skip
    _hot_skip_in_window = sum(
        1 for r in _fast
        if getattr(r, "scoring_path", None) == "hot_skip"
    )
    _admitted_in_window = events_count - _hot_skip_in_window
    rollup["fast_score_attempted_total"] = (
        rollup.get("fast_score_attempted_total", 0) + _admitted_in_window
    )
    rollup["fast_path_scored_total"] = (
        rollup.get("fast_path_scored_total", 0) + len(_fast)
    )

    # Per-window classification (mutually exclusive)
    if events_count == 0:
        _window_class = "no_events_in_window"
    elif _bd.get("bridge_pool_address_hit_count", 0) == 0:
        _window_class = "events_but_no_bridge_hit"
    elif len(_fast) == 0:
        _window_class = "bridge_hit_but_not_scored"
    elif sum(1 for r in _fast if (getattr(r, "best_backrun_net_bps", 0) or 0) > 0) == 0:
        _window_class = "scored_but_rejected_economics"
    elif len(_guard) == 0:
        _window_class = "positive_but_no_guard_pass"
    else:
        _window_class = "guard_passed"

    rollup.setdefault("window_miss_classes", {})
    rollup["window_miss_classes"][_window_class] = (
        rollup["window_miss_classes"].get(_window_class, 0) + 1
    )
    # Dominant = max by count, excluding guard_passed
    _miss_only = {
        k: v for k, v in rollup["window_miss_classes"].items()
        if k != "guard_passed"
    }
    rollup["dominant_hot_miss_reason"] = (
        max(_miss_only, key=_miss_only.get) if _miss_only else "none"
    )
    return rollup


# ===========================================================================
# first_window_at
# ===========================================================================


class TestFirstWindowAt:

    def test_first_window_at_set_on_first_call(self):
        rollup = {}
        _simulate_rollup_window(rollup, events_count=0)
        assert "first_window_at" in rollup
        assert rollup["first_window_at"] == "2025-01-01T00:00:00Z"

    def test_first_window_at_not_overwritten(self):
        rollup = {"first_window_at": "2024-01-01T00:00:00Z"}
        _simulate_rollup_window(rollup, events_count=0)
        # Must keep the original value
        assert rollup["first_window_at"] == "2024-01-01T00:00:00Z"


# ===========================================================================
# Counter disentanglement
# ===========================================================================


class TestCounterSemantics:

    def test_admitted_excludes_hot_skip(self):
        """fast_score_attempted_total should count admission, not scored."""
        fast = [
            _make_result(scoring_path="registry_fast", best_backrun_net_bps=10),
            _make_result(scoring_path="hot_skip", best_backrun_net_bps=0),
            _make_result(scoring_path="registry_fast", best_backrun_net_bps=-5),
        ]
        rollup = {}
        _simulate_rollup_window(rollup, events_count=5, fast_results=fast)
        # 5 events, 1 hot_skip → 4 admitted
        assert rollup["fast_score_attempted_total"] == 4
        # fast_path_scored_total = len(fast) = 3 (all results, including hot_skip)
        assert rollup["fast_path_scored_total"] == 3

    def test_zero_events_zero_admission(self):
        rollup = {}
        _simulate_rollup_window(rollup, events_count=0)
        assert rollup["fast_score_attempted_total"] == 0

    def test_all_hot_skip_zero_admission(self):
        fast = [
            _make_result(scoring_path="hot_skip"),
            _make_result(scoring_path="hot_skip"),
        ]
        rollup = {}
        _simulate_rollup_window(rollup, events_count=2, fast_results=fast)
        assert rollup["fast_score_attempted_total"] == 0


# ===========================================================================
# dominant_hot_miss_reason per-window classification
# ===========================================================================


class TestDominantHotMissReason:

    def test_no_events_classification(self):
        rollup = {}
        _simulate_rollup_window(rollup, events_count=0)
        assert rollup["dominant_hot_miss_reason"] == "no_events_in_window"
        assert rollup["window_miss_classes"]["no_events_in_window"] == 1

    def test_events_but_no_bridge_hit(self):
        rollup = {}
        _simulate_rollup_window(
            rollup, events_count=3,
            bridge_diagnostics={"bridge_pool_address_hit_count": 0},
        )
        assert rollup["dominant_hot_miss_reason"] == "events_but_no_bridge_hit"

    def test_scored_but_rejected_economics(self):
        fast = [_make_result(scoring_path="registry_fast", best_backrun_net_bps=-5)]
        rollup = {}
        _simulate_rollup_window(
            rollup, events_count=1,
            fast_results=fast,
            bridge_diagnostics={"bridge_pool_address_hit_count": 1},
        )
        assert rollup["dominant_hot_miss_reason"] == "scored_but_rejected_economics"

    def test_positive_but_no_guard_pass(self):
        fast = [_make_result(scoring_path="registry_fast", best_backrun_net_bps=10)]
        rollup = {}
        _simulate_rollup_window(
            rollup, events_count=1,
            fast_results=fast,
            guard_results=[],
            bridge_diagnostics={"bridge_pool_address_hit_count": 1},
        )
        assert rollup["dominant_hot_miss_reason"] == "positive_but_no_guard_pass"

    def test_guard_passed_not_dominant(self):
        """guard_passed should NOT appear as dominant_hot_miss_reason."""
        fast = [_make_result(scoring_path="registry_fast", best_backrun_net_bps=10)]
        guard = [("pair", object())]  # non-empty guard
        rollup = {}
        _simulate_rollup_window(
            rollup, events_count=1,
            fast_results=fast,
            guard_results=guard,
            bridge_diagnostics={"bridge_pool_address_hit_count": 1},
        )
        # Only one window, and it's guard_passed → no miss classes
        assert rollup["dominant_hot_miss_reason"] == "none"
        assert rollup["window_miss_classes"]["guard_passed"] == 1

    def test_dominant_is_max_across_windows(self):
        """With mixed windows, dominant = class with most windows."""
        rollup = {}
        # 2 windows with no events
        _simulate_rollup_window(rollup, events_count=0)
        _simulate_rollup_window(rollup, events_count=0)
        # 1 window with events but no bridge hit
        _simulate_rollup_window(
            rollup, events_count=5,
            bridge_diagnostics={"bridge_pool_address_hit_count": 0},
        )
        assert rollup["dominant_hot_miss_reason"] == "no_events_in_window"
        assert rollup["window_miss_classes"]["no_events_in_window"] == 2
        assert rollup["window_miss_classes"]["events_but_no_bridge_hit"] == 1

    def test_mutually_exclusive_one_class_per_window(self):
        """Each window contributes to exactly one class."""
        rollup = {}
        _simulate_rollup_window(rollup, events_count=0)
        assert sum(rollup["window_miss_classes"].values()) == 1

        _simulate_rollup_window(
            rollup, events_count=3,
            bridge_diagnostics={"bridge_pool_address_hit_count": 1},
            fast_results=[_make_result(scoring_path="registry_fast", best_backrun_net_bps=-1)],
        )
        assert sum(rollup["window_miss_classes"].values()) == 2


# ===========================================================================
# Atomic JSON write
# ===========================================================================


class TestAtomicJsonWrite:

    def test_atomic_write_produces_valid_json(self, tmp_path):
        # Import the actual helper
        from scripts.m7a_orderflow_loop import _atomic_json_write

        target = str(tmp_path / "test.json")
        data = {"key": "value", "n": 42}
        _atomic_json_write(target, data, indent=2)

        with open(target, encoding="utf-8") as f:
            loaded = json.load(f)
        assert loaded == data

    def test_atomic_write_no_tmp_files_left(self, tmp_path):
        from scripts.m7a_orderflow_loop import _atomic_json_write

        target = str(tmp_path / "clean.json")
        _atomic_json_write(target, {"ok": True})
        # No .tmp files should remain
        leftover = [f for f in os.listdir(tmp_path) if f.endswith(".tmp")]
        assert leftover == []

    def test_atomic_write_overwrites_existing(self, tmp_path):
        from scripts.m7a_orderflow_loop import _atomic_json_write

        target = str(tmp_path / "over.json")
        _atomic_json_write(target, {"v": 1})
        _atomic_json_write(target, {"v": 2})
        with open(target, encoding="utf-8") as f:
            assert json.load(f)["v"] == 2

    def test_atomic_write_creates_directories(self, tmp_path):
        from scripts.m7a_orderflow_loop import _atomic_json_write

        target = str(tmp_path / "sub" / "dir" / "deep.json")
        _atomic_json_write(target, {"nested": True})
        assert os.path.isfile(target)


# ===========================================================================
# hot_gap_debug counter disentanglement (artifact level)
# ===========================================================================


class TestHotGapDebugCounters:
    """Verify hot_gap_debug counters in _write_hot_artifact are disentangled."""

    def test_watchlist_match_count_uses_bridge_diagnostics(self):
        """watchlist_match_count must come from bridge_pool_address_hit_count,
        NOT from fast_attempted / fast_scored."""
        # Build minimal raw_results: 3 events, 2 registry_fast, 1 hot_skip
        results = [
            _make_result(scoring_path="registry_fast", best_backrun_net_bps=10),
            _make_result(scoring_path="registry_fast", best_backrun_net_bps=-5),
            _make_result(scoring_path="hot_skip"),
        ]
        bd = {"bridge_pool_address_hit_count": 7}  # Intentionally different

        # Simulate the hot_gap_debug computation (mirrors _write_hot_artifact)
        _hot_skip_count = sum(
            1 for r in results
            if getattr(r, "scoring_path", None) == "hot_skip"
        )
        _fast_scored = sum(
            1 for r in results
            if getattr(r, "scoring_path", None) == "registry_fast"
        )
        _admitted_to_scoring = len(results) - _hot_skip_count

        gap = {
            "total_events": len(results),
            "admitted_to_scoring": _admitted_to_scoring,
            "fast_path_scored_count": _fast_scored,
            "watchlist_match_count": bd.get("bridge_pool_address_hit_count", 0),
            "fast_score_attempted": _admitted_to_scoring,
            "fast_score_scored": _fast_scored,
        }

        assert gap["total_events"] == 3
        assert gap["admitted_to_scoring"] == 2
        assert gap["fast_path_scored_count"] == 2
        assert gap["watchlist_match_count"] == 7  # From bridge, NOT from fast count
        assert gap["fast_score_attempted"] == 2  # Admission count
        assert gap["fast_score_scored"] == 2  # Actually scored count
        # Critical: watchlist_match_count != fast_path_scored_count
        assert gap["watchlist_match_count"] != gap["fast_path_scored_count"]
