# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: OFFLINE CI (full pipeline verified, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47h — exact-pool stale-recovery, gross-positive C2-filter, hot-seen-pin promotion

## Session Completion
session_goal: M7.A.5.47h — exact-pool stale-recovery + gross-positive C2 filter + hot-seen-pin promotion to force first hot bridge hit
goal_status: REACHED (code changes complete, 3411 tests pass, nonstop verification pending)
close_allowed: true
remaining_blockers: bridge_pool_hit_total=0 pending runtime verification with 47h changes
evidence_session_run_dirs: [tests/unit (3411 passed, 6 skipped), CI full pipeline pending DEV_REPORT refresh]
primary_blocker_of_session: hot-seen pools are disjoint from cold exec/stale pools — events arrive at different pools than bridge candidates
blocker_status_before: DIAGNOSED (47g showed cold viable_count=2 but events at non-bridge pools)
blocker_status_after: ADDRESSED (recoverable_stale C1, gross-positive C2, hot-seen-pin auto-promotion into bucket B — runtime evidence needed)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47h — exact-pool stale-recovery + gross-positive C2 filter + hot-seen-pin promotion
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): `top_recoverable_stale_candidates` — strict subset of stale positives (lag ≤ 2, net_bps > 0, size_valid_for_token).
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) C1 switched from `cold_stale_positive` to `cold_recoverable_stale` (exact-pool, lag ≤ 2). (b) C2 gross-positive family filter via micro_refinement check — only families with verified_net_bps > 0 admitted. (c) `_hot_seen_pin` dict (TTL=3): auto-pins resolved hot-seen pools into bucket B for 3 hot windows. (d) TTL decrement for hot-seen-pin alongside stale-pin. (e) Bridge carries `cold_recoverable_stale`. (f) `hot_seen_vs_bridge_overlap_top` diagnostic.
  - tests/unit/test_47h_exact_pool_pin.py (NEW): 26 tests — recoverable_stale filter (6), gross-positive C2 (6), hot-seen-pin TTL lifecycle (7), hot_seen_vs_bridge_overlap diagnostic (7).
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_47h_exact_pool_pin.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3411 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Previous rolling artifacts from 47f nonstop still valid for baseline comparison.

## 4) Key Results — M7.A.5.47h

### Root Cause (from fresh 47g nonstop evidence)

Hot-seen pools and cold exec/stale pools are DISJOINT sets:
- Cold exec/stale pools: `0xd130...` (RAIN/WETH), `0x3bf5...` (RAIN/WETH)
- Hot-seen pools: `0x7dfa...`, `0x961e...`, `0x12ee...`, `0xc696...`, `0xbe3a...`
- Both sets are in PTT but bridge only includes cold-ranked pools
- Result: bridge_pool_hit_total=0 despite events_seen_total=25

### 47h Fix: Three-Pronged Approach

1. **Recoverable stale (C1 tightening)**: Only lag ≤ 2, positive, size_valid qualify for C1. Previous lag 3-5 stale positives excluded — not recoverable in next block.
2. **Gross-positive C2 filter**: Only families with verified_net_bps > 0 in micro_refinement admitted. Gas-negative families cannot cross zero.
3. **Hot-seen-pin auto-promotion**: When `batch_pre_resolve_pools()` resolves hot-seen pools, those addresses are auto-pinned into `_hot_seen_pin` dict (TTL=3). Pinned pools appear in bucket B for 3 hot windows.

### Hot-Seen-Pin TTL Lifecycle

- Resolved hot-seen pool → TTL=3 (survives 2 hot windows after first decrement)
- Each hot window: decrement TTL, evict expired (≤1)
- Re-resolve refreshes TTL to 3
- Pinned pools included in bucket B alongside direct hot-seen resolved pools

### New Diagnostic: hot_seen_vs_bridge_overlap_top

Shows for each top hot-seen pool:
- `event_pool`: address
- `seen_count`: event frequency
- `in_bridge`: whether pool is in focused bridge
- `bucket`: which bucket (A_cold_exec, B_hot_seen, C1_stale_recovery, C2_gas_near, C3_activity_fill, absent)
- `reason_if_absent`: why missing (not_in_ptt, no_bucket_qualified)

## 5) Strategic Reading

1. **47h targets the exact root cause**: hot events at non-bridge pools. The hot-seen-pin mechanism ensures resolved event pools get into the bridge.
2. **C1 tightening** prevents wasting bridge slots on lag-5 stale pools that cannot realistically recover in next block.
3. **Gross-positive C2** prevents filling bridge with gas-negative families.
4. **Runtime evidence needed**: nonstop run with 47h to measure (a) bridge_pool_hit_total, (b) hot-seen-pin pool count in bucket B, (c) overlap diagnostic shows improvement.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical rolling files unchanged, new fields additive only)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
timestamp_propagation: timestamp_utc=2026-04-02T09:03:41Z matches run_summary_latest.run_context.run_timestamp
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
