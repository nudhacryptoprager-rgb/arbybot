"""
E1.55 — Unit tests for hot-lane cold-start recovery when bridge is empty.

Scenarios tested:
  1. force_reload_persistent_pool_token_cache() bypasses the already-loaded
     guard and loads entries from disk.
  2. When bridge PTT is empty and _pool_token_cache is empty, force-reload
     hydrates the cache so score_backrun_fast can proceed.
  3. force_reload is idempotent when called multiple times with file present.
  4. force_reload returns 0 when file does not exist (no error raised).
  5. E1.55 diagnostic fields surface into hot_gap_debug in the artifact.
  6. Clean-start scenario: persistent_cache_forced_reload_count > 0 when
     bridge is empty but _pool_token_cache.json exists on disk.

Acceptance criteria for E1.55 FIXED (control soak evidence):
  - bridge_ptt_raw_count > 0        (cold bridge file found and read)
  - bridge_pool_address_hit_count > 0  (event pools matched bridge set)
  - admitted_to_scoring > 0           (events reached fast scorer)
  - fast_score_scored > 0             (scoring completed without skip)
  NOTE: bridge_cache_populated may stay 0 (it tracks the legacy
  _bridge_cache_count path); it is NOT the primary acceptance criterion.
"""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch


# ---------------------------------------------------------------------------
# Test 1: force_reload bypasses _PERSISTENT_CACHE_LOADED guard
# ---------------------------------------------------------------------------

def test_force_reload_bypasses_loaded_guard(tmp_path: Path) -> None:
    """force_reload sets _PERSISTENT_CACHE_LOADED=False then reloads."""
    import importlib
    import m7.orderflow.resolve as resolve_mod

    # Build a small cache file with 3 entries
    cache_file = tmp_path / "_pool_token_cache.json"
    entries = {
        "0xpool1": ["0xtok0", "0xtok1", 3000],
        "0xpool2": ["0xtok2", "0xtok3", 500],
        "0xpool3": ["0xtok4", "0xtok5", 100],
    }
    cache_file.write_text(
        json.dumps({"version": 1, "entries": entries, "count": 3}), encoding="utf-8"
    )

    # Patch the module-level path and the already-loaded flag
    original_path = resolve_mod._PERSISTENT_CACHE_PATH
    original_flag = resolve_mod._PERSISTENT_CACHE_LOADED
    original_cache = dict(resolve_mod._pool_token_cache)

    try:
        resolve_mod._PERSISTENT_CACHE_PATH = cache_file
        # Simulate: previous load already ran (flag is True), cache empty
        resolve_mod._PERSISTENT_CACHE_LOADED = True
        resolve_mod._pool_token_cache.clear()

        # Normal load should be a no-op (already loaded)
        count_noop = resolve_mod.load_persistent_pool_token_cache()
        assert count_noop == 0, "load_persistent_pool_token_cache should be a no-op when already loaded"

        # force_reload must bypass the guard and load all 3 entries
        count_forced = resolve_mod.force_reload_persistent_pool_token_cache()
        assert count_forced == 3, f"Expected 3 entries loaded, got {count_forced}"
        assert len(resolve_mod._pool_token_cache) == 3
        assert "0xpool1" in resolve_mod._pool_token_cache
        t0, t1, fee = resolve_mod._pool_token_cache["0xpool1"]
        assert t0 == "0xtok0"
        assert t1 == "0xtok1"
        assert fee == 3000
    finally:
        # Restore state
        resolve_mod._PERSISTENT_CACHE_PATH = original_path
        resolve_mod._PERSISTENT_CACHE_LOADED = original_flag
        resolve_mod._pool_token_cache.clear()
        resolve_mod._pool_token_cache.update(original_cache)


# ---------------------------------------------------------------------------
# Test 2: force_reload returns 0 when file does not exist (no exception)
# ---------------------------------------------------------------------------

def test_force_reload_file_absent_no_error(tmp_path: Path) -> None:
    """force_reload returns 0 gracefully when cache file is absent."""
    import m7.orderflow.resolve as resolve_mod

    missing_path = tmp_path / "_no_such_file.json"
    assert not missing_path.exists()

    original_path = resolve_mod._PERSISTENT_CACHE_PATH
    original_flag = resolve_mod._PERSISTENT_CACHE_LOADED
    original_cache = dict(resolve_mod._pool_token_cache)

    try:
        resolve_mod._PERSISTENT_CACHE_PATH = missing_path
        resolve_mod._PERSISTENT_CACHE_LOADED = True  # simulate already-loaded guard set
        resolve_mod._pool_token_cache.clear()

        count = resolve_mod.force_reload_persistent_pool_token_cache()
        assert count == 0, "Expected 0 when file absent"
        assert len(resolve_mod._pool_token_cache) == 0
    finally:
        resolve_mod._PERSISTENT_CACHE_PATH = original_path
        resolve_mod._PERSISTENT_CACHE_LOADED = original_flag
        resolve_mod._pool_token_cache.clear()
        resolve_mod._pool_token_cache.update(original_cache)


# ---------------------------------------------------------------------------
# Test 3: force_reload is idempotent (second call re-reads same file)
# ---------------------------------------------------------------------------

def test_force_reload_idempotent(tmp_path: Path) -> None:
    """Calling force_reload twice does not duplicate entries (setdefault)."""
    import m7.orderflow.resolve as resolve_mod

    cache_file = tmp_path / "_pool_token_cache.json"
    entries = {
        "0xpoolA": ["0xtokA0", "0xtokA1", 3000],
    }
    cache_file.write_text(
        json.dumps({"version": 1, "entries": entries, "count": 1}), encoding="utf-8"
    )

    original_path = resolve_mod._PERSISTENT_CACHE_PATH
    original_flag = resolve_mod._PERSISTENT_CACHE_LOADED
    original_cache = dict(resolve_mod._pool_token_cache)

    try:
        resolve_mod._PERSISTENT_CACHE_PATH = cache_file
        resolve_mod._PERSISTENT_CACHE_LOADED = True
        resolve_mod._pool_token_cache.clear()

        resolve_mod.force_reload_persistent_pool_token_cache()
        assert len(resolve_mod._pool_token_cache) == 1

        # Second force-reload — should not duplicate
        resolve_mod.force_reload_persistent_pool_token_cache()
        assert len(resolve_mod._pool_token_cache) == 1, "setdefault prevents duplication"
    finally:
        resolve_mod._PERSISTENT_CACHE_PATH = original_path
        resolve_mod._PERSISTENT_CACHE_LOADED = original_flag
        resolve_mod._pool_token_cache.clear()
        resolve_mod._pool_token_cache.update(original_cache)


# ---------------------------------------------------------------------------
# Test 4: Empty bridge PTT → force_reload populates cache
# (integration: _populate_pool_token_cache_from_bridge returns 0 then reload)
# ---------------------------------------------------------------------------

def test_empty_bridge_then_force_reload(tmp_path: Path) -> None:
    """When bridge has no PTT, force_reload recovers scoring from disk cache."""
    import m7.orderflow.resolve as resolve_mod
    from m7.orderflow.bridge_runtime import _populate_pool_token_cache_from_bridge

    cache_file = tmp_path / "_pool_token_cache.json"
    entries = {
        "0xpool10": ["0xtok100", "0xtok101", 500],
        "0xpool11": ["0xtok110", "0xtok111", 3000],
    }
    cache_file.write_text(
        json.dumps({"version": 1, "entries": entries, "count": 2}), encoding="utf-8"
    )

    original_path = resolve_mod._PERSISTENT_CACHE_PATH
    original_flag = resolve_mod._PERSISTENT_CACHE_LOADED
    original_cache = dict(resolve_mod._pool_token_cache)

    try:
        resolve_mod._PERSISTENT_CACHE_PATH = cache_file
        resolve_mod._PERSISTENT_CACHE_LOADED = True
        resolve_mod._pool_token_cache.clear()

        empty_bridge: dict = {}  # cold lane hasn't written bridge yet

        # Step 1: populate from bridge (as hot lane does each iteration)
        populated = _populate_pool_token_cache_from_bridge(empty_bridge)
        assert populated == 0, "Empty bridge should populate 0 entries"
        assert len(resolve_mod._pool_token_cache) == 0

        # Step 2: force-reload from disk (E1.55 fallback)
        reloaded = resolve_mod.force_reload_persistent_pool_token_cache()
        assert reloaded == 2, f"Expected 2 entries from disk, got {reloaded}"

        # Step 3: score_backrun_fast cache check (direct cache lookup simulated)
        assert resolve_mod._pool_token_cache.get("0xpool10") is not None
        t0, t1, fee = resolve_mod._pool_token_cache["0xpool10"]
        assert t0 == "0xtok100"
        assert fee == 500
    finally:
        resolve_mod._PERSISTENT_CACHE_PATH = original_path
        resolve_mod._PERSISTENT_CACHE_LOADED = original_flag
        resolve_mod._pool_token_cache.clear()
        resolve_mod._pool_token_cache.update(original_cache)


def test_hot_gap_debug_surfaces_bridge_reload_diagnostics() -> None:
    """E1.55 diagnostics must survive into the reviewer-facing artifact."""
    import inspect
    from scripts.m7a_orderflow_loop import _write_hot_artifact

    source = inspect.getsource(_write_hot_artifact)
    assert "bridge_file_exists" in source
    assert "bridge_ptt_raw_count" in source
    assert "bridge_mtime_age_s" in source
    assert "persistent_cache_forced_reload_count" in source


# ---------------------------------------------------------------------------
# Test 6: Clean-start scenario — persistent_cache_forced_reload_count > 0
# Simulates: bridge empty at hot startup + cache file DOES exist on disk
# (written by cold lane's first window before bridge is ready).
# This is the most realistic E1.55 recovery path.
# ---------------------------------------------------------------------------

def test_clean_start_persistent_cache_forced_reload_nonzero(tmp_path: Path) -> None:
    """Force-reload path fires and persistent_cache_forced_reload_count>0 when:
    - bridge PTT is empty (cold bridge not yet written)
    - _pool_token_cache is empty (hot just started)
    - persistent cache file EXISTS on disk (cold wrote it in its first window)
    """
    import m7.orderflow.resolve as resolve_mod

    cache_file = tmp_path / "_pool_token_cache.json"
    # Simulate: cold lane wrote cache with 5 entries before producing bridge
    entries = {f"0xpool{i}": [f"0xtok{i}a", f"0xtok{i}b", 3000] for i in range(5)}
    cache_file.write_text(
        json.dumps({"version": 1, "entries": entries, "count": 5}), encoding="utf-8"
    )

    original_path = resolve_mod._PERSISTENT_CACHE_PATH
    original_flag = resolve_mod._PERSISTENT_CACHE_LOADED
    original_cache = dict(resolve_mod._pool_token_cache)

    try:
        resolve_mod._PERSISTENT_CACHE_PATH = cache_file
        # Simulate: hot process just started — flag=True (import-time load ran,
        # file was absent at that moment), cache is empty
        resolve_mod._PERSISTENT_CACHE_LOADED = True
        resolve_mod._pool_token_cache.clear()

        # --- Reproduce hot-startup logic from loop_runner.py (E1.55) ---
        _bridge_cache_count = 0  # bridge PTT empty (cold not yet written)
        _persistent_force_reload_count = 0
        if _bridge_cache_count == 0:
            from m7.orderflow.resolve import (
                force_reload_persistent_pool_token_cache as _frl,
                _pool_token_cache as _ptc_check,
            )
            if not _ptc_check:
                _persistent_force_reload_count = _frl()

        # Verify: force-reload fired and loaded entries
        assert _persistent_force_reload_count == 5, (
            f"Expected persistent_cache_forced_reload_count=5, got {_persistent_force_reload_count}"
        )
        assert len(resolve_mod._pool_token_cache) == 5
    finally:
        resolve_mod._PERSISTENT_CACHE_PATH = original_path
        resolve_mod._PERSISTENT_CACHE_LOADED = original_flag
        resolve_mod._pool_token_cache.clear()
        resolve_mod._pool_token_cache.update(original_cache)
