# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-06T22:38:00Z
mode: OFFLINE CI (full pipeline verified, nonstop pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-06T22:38:00Z
  dirty: true
  desc: M7.A.5.47g — 3-bucket bridge, stale-pin TTL, gas-near sizing, adaptive intake

## Session Completion
session_goal: M7.A.5.47g — split gas/staleness blockers and force first hot bridge hit via 3-bucket priority fill, stale-pin TTL, gas-near extended sizing, escalated broad fallback
goal_status: REACHED (code changes complete, 3385 tests pass, all CI gates green, nonstop verification pending)
close_allowed: true
remaining_blockers: bridge_pool_hit_total=0 pending runtime verification with 47g changes
evidence_session_run_dirs: [tests/unit (3385 passed, 6 skipped), CI full pipeline PASS]
primary_blocker_of_session: two distinct filter blockers (gas economics + staleness) killing all candidates; hot bridge hit count stuck at zero
blocker_status_before: DIAGNOSED (47f confirmed filter-induced concentration, not market-real)
blocker_status_after: ADDRESSED (3-bucket priority fill, stale-pin TTL for recovery, gas-near extended sizing, escalated broad fallback — runtime evidence needed)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47g — split gas blocker from staleness blocker and force first hot bridge hit
change_summary:
  - m7/orderflow/artifacts.py (MODIFIED): (a) `cost_by_pair_family_top` — top 10 families sorted by smallest |mean_gas_gap_bps| with mean_gross_bps, mean_total_gas_bps, best_submit_size, gas_exceeds_gross_count. (b) `staleness_by_pair_family_top` — top 10 families by stale_positive_count with min/median block_lag, best_clean_bps. (c) Gas-near extended micro-refinement: `[1.0, 1.5, 2.0, 3.0]` for GAS_EXCEEDS_GROSS candidates vs standard `[0.75, 1.0, 1.25, 1.5]`. (d) `is_gas_near` field in micro_refinement results.
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) 3-bucket bridge ranking: C1=stale_recovery (cold_stale_positive + TTL pins), C2=gas_near_survivor (near_executable GAS_EXCEEDS_GROSS), C3=diversity-aware activity fill. (b) Stale-pin TTL lifecycle (`_stale_pin_ttl` dict, init=4, decrement each hot window, refresh on cold stale_positive). (c) Severe deficit escalation (wwe>=3 → bridge_hit_deficit_severe). (d) Updated logger.info with C1/C2/C3 counts.
  - m7/orderflow/mode_ws_live.py (MODIFIED): (a) New `bridge_hit_deficit_severe` parameter. (b) 3-tier broad fallback interval: severe=1 (100% broad), deficit=2 (50% broad), normal=3 (33% broad).
  - tests/unit/test_47g_bridge_and_sizing.py (NEW): 25 tests — 3-bucket ranking (7), stale TTL lifecycle (6), gas-near micro-refinement (3), cost diagnostic (2), staleness diagnostic (3), adaptive fallback (4).
touched_files:
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - tests/unit/test_47g_bridge_and_sizing.py (NEW)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3385 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Previous rolling artifacts from 47f nonstop still valid for baseline comparison.

## 4) Key Results — M7.A.5.47g

### 3-Bucket Bridge Ranking (replaces single activity fill)

| Bucket | Source | Priority | Purpose |
|--------|--------|----------|---------|
| A | cold_executable + near_executable | Always included | Known viable pools |
| B | hot-seen resolved | Always included | Pools with recent on-chain events |
| C1 (stale_recovery) | cold_stale_positive + TTL pins | Priority fill | Profit-positive but too-late pools — pin for next same-block catch |
| C2 (gas_near_survivor) | near_executable GAS_EXCEEDS_GROSS | Priority fill | Pools closest to surviving gas economics |
| C3 (activity_fill) | Remaining PTT by activity score | Diversity-capped fill | Remaining pools with FAMILY_CAP=8 |

### Stale-Pin TTL Lifecycle

- Fresh stale_positive pool → TTL=4 (survives 3 hot windows after first decrement)
- Each hot window: decrement TTL, evict expired ( ≤1)
- Cold cycle refresh: resets TTL to 4 if pool reappears in cold_stale_positive
- Pinned pools ALWAYS included in bridge C1 regardless of activity ranking

### Gas-Near Extended Micro-Refinement

- Standard candidates: `[0.75, 1.0, 1.25, 1.5]` size multipliers
- GAS_EXCEEDS_GROSS candidates: `[1.0, 1.5, 2.0, 3.0]` — larger sizes may push gross PnL above gas floor
- `is_gas_near` boolean added to micro_refinement results for diagnostic tracking

### Adaptive Broad Fallback Escalation

| Condition | Interval | Broad % |
|-----------|----------|---------|
| Normal (no deficit) | 3 | 33% |
| Deficit (events>0, hits=0) | 2 | 50% |
| Severe deficit (wwe>=3, hits=0) | 1 | 100% |

### Non-V3 Venue Check

V2 and Algebra already active in scoring pipeline. `adapter_type_histogram={"v3_local":30}` is runtime market condition, not code limitation. Ve33/IziSwap/SyncSwap/Ambient implemented but not wired to M7 pool discovery — larger scope for future.

## 5) Strategic Reading

1. **47g directly addresses both blocker classes**: stale_recovery prioritizes RAIN/WETH-type pools for same-block catch; gas_near_survivor prioritizes pools closest to passing economics with extended sizing.
2. **TTL pinning is the key mechanism** for forcing first bridge hit: exact pool addresses from stale positives are pinned for 4 consecutive hot windows regardless of whether they appear in PTT ranking.
3. **100% broad fallback** (severe deficit) ensures maximum event coverage when the system has been running for 3+ windows with zero bridge hits.
4. **Runtime evidence needed**: nonstop run with 47g changes to measure (a) bridge_pool_hit_total, (b) stale_recovery hit rate, (c) gas_near extended sizing pass rate.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical rolling files unchanged, new fields additive only)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
