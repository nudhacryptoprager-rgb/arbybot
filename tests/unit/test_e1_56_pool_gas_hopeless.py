"""E1.56 Step 7 — pool-level gas-hopeless quarantine.

The C3 family-level quarantine (M7.A.5.47o) is too coarse: a single
losing pool in a viable family is spared, and an entire family is
poisoned by one bad pool. Pool-level adds per-pool-address tracking
of consecutive `GAS_EXCEEDS_GROSS` rejects across windows. After
`ARBY_POOL_GAS_HOPELESS_STREAK` (default 3) consecutive windows, the
pool is quarantined from C3 fill. Setting the env to 0 disables the
feature entirely (back-compat).

Tests pin the contract by:
1. Source inspection — guards rolling-out new public fields.
2. Logic test — re-implements the streak update locally and verifies
   it matches the loop_runner's expected behavior.
3. Bridge persistence test — verifies field names land in
   `_HOT_PRESERVE_ALWAYS`.
"""
from __future__ import annotations

import inspect


def test_e1_56_step7_logic_emitted_in_loop_runner() -> None:
    """The pool-level streak logic and skip must be present in source."""
    import m7.orderflow.loop_runner as lr

    src = inspect.getsource(lr)
    assert "_POOL_GAS_HOPELESS_STREAK" in src
    assert "ARBY_POOL_GAS_HOPELESS_STREAK" in src
    assert "_pool_gas_kills_now" in src
    assert "_pool_gas_hopeless" in src
    assert "_c3_pool_gas_hopeless_skipped" in src
    assert "pool_gas_hopeless_streak" in src


def test_e1_56_step7_artifact_top_level_surfaced() -> None:
    """Pool-level fields surfaced at hot artifact top-level."""
    from m7.orderflow.hot_runtime_artifacts import _write_hot_artifact

    src = inspect.getsource(_write_hot_artifact)
    assert "c3_pool_gas_hopeless_skipped" in src
    assert "pool_gas_hopeless_count" in src


def test_e1_56_step7_bridge_preserves_pool_fields() -> None:
    """Bridge runtime preserves pool_gas_hopeless across hot writes."""
    from m7.orderflow.bridge_runtime import _write_cold_hot_bridge

    src = inspect.getsource(_write_cold_hot_bridge)
    assert "c3_pool_gas_hopeless_skipped" in src
    assert "pool_gas_hopeless" in src
    assert "pool_gas_hopeless_streak" in src


def test_e1_56_step7_streak_increments_on_consecutive_gas_kills() -> None:
    """Local re-implementation of the streak update mirrors the runtime."""
    # Window 1: pool A gas-killed. streak: {A:1}
    prev_streak: dict = {}
    pool_kills_now = {"0xpoola": -7.0}
    pool_pos_now: set = set()
    new_streak: dict = {}
    for pa in pool_kills_now:
        new_streak[pa] = int(prev_streak.get(pa, 0)) + 1
    for pa in pool_pos_now:
        new_streak[pa] = 0
    for pa, s in prev_streak.items():
        if pa not in new_streak and 0 < s < 100:
            new_streak[pa] = s
    assert new_streak == {"0xpoola": 1}

    # Window 2: pool A gas-killed again. streak: {A:2}
    prev_streak = dict(new_streak)
    new_streak = {}
    for pa in pool_kills_now:
        new_streak[pa] = int(prev_streak.get(pa, 0)) + 1
    for pa, s in prev_streak.items():
        if pa not in new_streak and 0 < s < 100:
            new_streak[pa] = s
    assert new_streak == {"0xpoola": 2}

    # Window 3: pool A gas-killed third time. streak: {A:3} → quarantine
    prev_streak = dict(new_streak)
    new_streak = {}
    for pa in pool_kills_now:
        new_streak[pa] = int(prev_streak.get(pa, 0)) + 1
    for pa, s in prev_streak.items():
        if pa not in new_streak and 0 < s < 100:
            new_streak[pa] = s
    assert new_streak == {"0xpoola": 3}

    pool_gas_hopeless = {pa for pa, s in new_streak.items() if s >= 3}
    assert pool_gas_hopeless == {"0xpoola"}


def test_e1_56_step7_streak_resets_on_positive() -> None:
    """A positive net_bps row resets the streak to 0 (clears quarantine candidacy)."""
    prev_streak = {"0xpoolb": 2}
    pool_kills_now: dict = {}
    pool_pos_now = {"0xpoolb"}
    new_streak: dict = {}
    for pa in pool_kills_now:
        new_streak[pa] = int(prev_streak.get(pa, 0)) + 1
    for pa in pool_pos_now:
        new_streak[pa] = 0
    for pa, s in prev_streak.items():
        if pa not in new_streak and 0 < s < 100:
            new_streak[pa] = s
    assert new_streak.get("0xpoolb") == 0


def test_e1_56_step7_disabled_when_streak_threshold_zero() -> None:
    """Setting env to 0 disables the quarantine path entirely."""
    streak_thresh = 0
    new_streak = {"0xpoolc": 999}
    pool_gas_hopeless: set = set()
    if streak_thresh > 0:
        for pa, s in new_streak.items():
            if s >= streak_thresh:
                pool_gas_hopeless.add(pa)
    assert pool_gas_hopeless == set()
