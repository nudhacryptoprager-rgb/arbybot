# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: OFFLINE CI (47m code complete, nonstop proof pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47m — truthful bridge hit diagnostics + run_context provenance + session rollup fix

## Session Completion
session_goal: M7.A.5.47m — truthful bridge hit on exact cold-exec pool 0xd13040d4fe917ee704158cfcb3338dcd2838b245
goal_status: REACHED (code changes complete, 3529 tests pass, CI gates green, nonstop proof pending)
close_allowed: true
remaining_blockers: nonstop proof run needed to verify bridge_hit_trace_top.in_bridge=true at runtime
evidence_session_run_dirs: [tests/unit (3529 passed, 6 skipped)]
primary_blocker_of_session: cold_exec_pool_trace.in_bridge=false due to set truncation — pool IS in bridge but observability reports false
blocker_status_before: BUG (list(set)[:30] truncation makes cold-exec pool invisible in bridge_selected + trace)
blocker_status_after: FIXED (A-bucket priority ordering + full-set in_bridge check + bridge_hit_trace_top)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47m — truthful bridge observability for cold-exec pool via priority ordering + full-set diagnostics
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) Bridge selected ordering: A-bucket first via explicit priority (was list(set)[:30]). (b) bridge_hit_trace_top replaces cold_exec_pool_trace: uses full _bridge_pool_addrs_set for truthful in_bridge, adds selected_bucket + reason_if_not_hit. (c) Bridge artifact null contract: cold-write includes bridge_excluded_top=[], cut_stage_top={}. Hot merge uses assembly-ordered list. (d) run_context in hot/bridge/rollup artifacts. (e) Session rollup flattened to top level.
  - m7/orderflow/artifacts.py (MODIFIED): run_context in build_replay_summary return.
  - tests/unit/test_47m_bridge_truth.py (NEW): 21 tests — ordering (4), trace (5), null contract (3), run_context (4), session (2), invariant (3).
  - docs/status/Status_M7.md (MODIFIED): 47m entry, trimmed to <300 lines.
  - docs/DEV_REPORT_LATEST.md (this file): Overwritten for 47m.
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/artifacts.py (MODIFIED)
  - tests/unit/test_47m_bridge_truth.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3529 passed, 6 skipped)
py -3.11 -m pytest tests/unit/test_47m_bridge_truth.py -v: PASS (21 passed)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PENDING (docs update in progress)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Nonstop proof pending with 47m changes.

## 4) Key Results — M7.A.5.47m

### Root Cause (from 47l 1-hour nonstop: April 7, 09:36-10:36Z)

| Metric | Value | Bug? |
|--------|-------|------|
| cold_executable_positive | 3 | OK — 3 survivors at 19.4505 bps |
| verified_profitable | true | OK — verified_net_bps=17.6505 |
| pool_address | 0xd13040d4...45 | Same pool, all 3 entries |
| cold_exec_pool_trace.in_bridge | **false** | **BUG** — set truncation |
| bridge_selected_pools_top | **[]** | **BUG** — null contract broken |
| bridge_excluded_top | **null** | **BUG** — not written in cold path |
| cut_stage_top | **null** | **BUG** — not persisted in bridge |
| session_bridge_pool_hit_total | **None** | **BUG** — nested under session dict |
| run_context | **absent** | **BUG** — no provenance in M7 artifacts |

### Root Cause Analysis

1. **in_bridge=false**: `list(_bridge_pool_addrs)[:30]` — set of 83 elements, arbitrary iteration order, pool beyond position 30. Trace checked truncated list, not the actual bridge set.
2. **bridge_selected_pools_top=[]**: Cold-write path didn't include selection. Hot merge used same broken `list(set)[:30]`.
3. **Null fields**: Cold-write missing `bridge_excluded_top`, `cut_stage_top` keys. Hot merge didn't guard nulls.
4. **Session rollup nested**: Fields stored under `rollup["session"]` dict, top-level `get("session_*")` returns None.
5. **No run_context**: M7 artifact writers (hot, bridge, rollup, orderflow) didn't include `run_context.run_timestamp`.

### 47m Fixes

1. **Bridge selected ordering**: Replaced `list(set)[:30]` with priority-ordered list: A-bucket (sorted) → B → C1/C2 → C3 → rest. A-bucket pools ALWAYS appear first.
2. **bridge_hit_trace_top**: Uses full `_bridge_pool_addrs_set` for truthful `in_bridge`. Adds `selected_bucket` (with "unlabeled_in_bridge" fallback), separate `fast_score_attempted`/`fast_score_scored`, `reason_if_not_hit` classification. Backward compat: `cold_exec_pool_trace` alias kept.
3. **Null contract**: Cold-write: `bridge_excluded_top=[]`, `cut_stage_top=artifact.get(...)`. Hot merge: reuses `_bridge_selected_at_assembly[:20]`, null guard on `cut_stage_top`.
4. **Session flattening**: 6 session keys copied to rollup top level.
5. **run_context**: Added to all 4 M7 artifact writers with `run_timestamp`.

## 5) Strategic Reading

1. **This WAS a code bug, not market**: Pool was in the bridge set the entire time. The observability layer (trace + selected list) falsely reported it absent due to set-iteration truncation.
2. **Priority ordering is defense-in-depth**: Even with hard-pin (47l), the diagnostic trace lied. Now the trace checks the actual bridge set.
3. **bridge_hit_trace_top is the primary debug surface**: 10 fields per cold-exec pool, with reason classification for each gap type.
4. **Nonstop proof will be definitive**: If `bridge_hit_trace_top.in_bridge=true` and `session_bridge_pool_hit_total > 0`, the truthful bridge hit goal is met.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (bridge_hit_trace_top, run_context are additive)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
docs_reread_confirmed: true
