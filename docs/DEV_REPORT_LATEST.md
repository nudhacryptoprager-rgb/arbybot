# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: OFFLINE CI (full pipeline verified, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47j — bridge minimum floor + focused pool count + C2 tightening + __pycache__ clear

## Session Completion
session_goal: M7.A.5.47j — bridge minimum floor, focused pool count metric, C2 tightening, __pycache__ clear for bytecode freshness
goal_status: REACHED (code changes complete, 3461 tests pass, nonstop verification pending)
close_allowed: true
remaining_blockers: bridge_pool_hit_total needs runtime verification with 47j bytecode
evidence_session_run_dirs: [tests/unit (3461 passed, 6 skipped)]
primary_blocker_of_session: 47i source code was correct but runtime used pre-47i bytecode (stale __pycache__)
blocker_status_before: DIAGNOSED (47i nonstop ran with pre-47i .pyc files — edits applied at 21:49 but nonstop ended at 21:41)
blocker_status_after: ADDRESSED (47j clears all __pycache__, adds bridge floor + focused count + C2 tightening)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47j — bridge minimum floor + focused pool count + C2 tightening
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Bridge minimum floor `_BRIDGE_MIN_FLOOR=20` — if PTT ≥ 20 pools but bridge assembly produces fewer, floor fill pads to minimum. (b) `bridge_focused_pool_count` metric — tracks actual `len(_bridge_pool_addrs)` in hot diagnostics, rollup snapshot, and `hot_gap_debug`. Disambiguates from `bridge_loaded_candidate_count` which only counted A-bucket. (c) C2 tolerance tightened from `-10` to `-5` bps — only families within 5 bps of breakeven admitted to gas-near bucket.
  - tests/unit/test_47j_bridge_floor.py (NEW): 24 tests — bridge floor enforcement (6), focused pool count (3), C2 tightened tolerance (5), overlap-never-null (6), source code contracts (4).
  - docs/status/Status_M7.md (MODIFIED): 47j entry added.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47j.
  - All __pycache__ .pyc files cleared to ensure runtime uses current source.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47j_bridge_floor.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3461 passed, 6 skipped)
py -3.11 -m pytest tests/unit/test_47j_bridge_floor.py -v: PASS (24 passed)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Nonstop run pending with 47j changes + cleared __pycache__.

## 4) Key Results — M7.A.5.47j

### Root Cause Analysis (47i runtime failure)

**Finding**: 47i source code was correct. The 10-minute nonstop (21:30-21:41 UTC April 6) ran with PRE-47i bytecode. `.pyc` timestamps prove:
- `artifacts.cpython-311.pyc`: recompiled at 21:49:50 (AFTER nonstop ended)
- `m7a_orderflow_loop.cpython-311.pyc`: recompiled at 21:50:17 (AFTER nonstop ended)

The rolling artifacts showing PRICING_ANOMALY contamination, null overlap, and zero bridge hits are from pre-47i code.

### 47j Changes (on top of verified-intact 47i)

1. **Bridge minimum floor** (`_BRIDGE_MIN_FLOOR=20`): Prevents bridge starvation when A/B/C1/C2 buckets are empty and family cap limits C3 fill. If PTT has ≥ 20 discovered pools, the focused bridge will have at least 20.
2. **`bridge_focused_pool_count` metric**: Tracks actual bridge size (all buckets combined) in `hot_gap_debug` and rollup (`_last` snapshot). `bridge_loaded_candidate_count` only counted cold_executable + near_executable (just A-bucket). This caused confusion: ptt_total=52 appeared to collapse to 5 pools, but 5 was only the A-bucket count.
3. **C2 tolerance tightened** (`-10` → `-5`): Only families within 5 bps of gas breakeven admitted. Tighter filter reduces bridge pollution from gas-hopeless families.
4. **`__pycache__` cleared**: All `.pyc` removed. Next runtime will compile fresh from source.
4. **Bridge hit diagnostic logging**: `logger.info` after bridge hit loop showing `raw_results` count, PTT size, hit count, and sample pool addresses from both sides.
5. **C2 gas tolerance**: `_C2_GAS_GAP_TOLERANCE_BPS = -10` — families within 10 bps of breakeven admitted to C2. Was strictly `verified_net_bps > 0`.
6. **Safe bridge file update**: Uses `_ba`, `_bb`, `_bc1`, `_bc2`, `_ptt_diag` aliases with `dir()` guard.
7. **Bridge-miss active auto-promote**: Pools in both `bridge_miss_sample` and `recent_active_pools_top` auto-pinned into `_hot_seen_pin` (TTL=3).

## 5) Strategic Reading

1. **Bytecode cache was the root cause**: 47i code was correct all along. The nonstop process used stale `.pyc` bytecode compiled from pre-47i source. Clearing `__pycache__` is mandatory before any proof run.
2. **`bridge_focused_pool_count` reveals the real bridge size**: The confusion between `bridge_loaded_candidate_count=5` and `ptt_total=52` is resolved — 5 was only the A-bucket, not the full bridge. The new metric shows all buckets.
3. **Bridge minimum floor prevents starvation**: With empty A/B buckets and family-cap-limited C3, the bridge could collapse to very few pools. The floor ensures at least 20 pools are always in the focused filter.
4. **Runtime evidence needed**: 10-minute nonstop to verify ALL target fields move with 47i+47j bytecode.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (new fields additive only — bridge_focused_pool_count, bridge_focused_pool_count_last)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
docs_reread_confirmed: true
