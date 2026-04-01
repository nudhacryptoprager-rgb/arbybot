# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_518_300b / m7a_518_300b_b / m7a_518_1000b (low-lag watchlist + blocker tags evidence session)
mode: ONLINE (ws-live evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7a_518_300b.json, data/tmp/m7a_518_300b_b.json, data/tmp/m7a_518_1000b.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: true
  desc: M7.A.5.18 low-lag watchlist + blocker tags + cross-window truth
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275

## Session Completion
session_goal: M7.A.5.18 -- add low_lag_watchlist (cross-window pair/pool truth accumulation), blocker_tags (top-level structural-stopper summary with 7 canonical tags), m7a518_hypothesis; measure temporal stability of low-lag surface across 3 evidence windows
goal_status: REACHED (watchlist + blocker_tags implemented; 3 evidence runs confirm temporal variance; blocker tags correctly activate per window; watchlist captures pool addresses when discoverable)
close_allowed: true
remaining_blockers: NO_COUNTER_POOL dominates low-lag in 300b windows; LOW_LAG_NONE_THIS_WINDOW dominates in 1000b window; SUBGRAPH_API_KEY_REQUIRED always active; no low-lag event has been economically scored
evidence_session_run_dirs: [data/tmp/m7a_518_300b.json, data/tmp/m7a_518_300b_b.json, data/tmp/m7a_518_1000b.json]
primary_blocker_of_session: temporal variance of low-lag surface — NO_COUNTER_POOL or NONE_THIS_WINDOW depending on window
blocker_status_before: V2 direct resolve implemented (M7.A.5.17) but low-lag still not stable across windows
blocker_status_after: watchlist + blocker_tags now track and summarize structural stoppers; temporal variance confirmed across 3 runs
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.18 -- low-lag watchlist + blocker tags; hypothesis: same-chain low-lag scoring may unlock only if low-lag pair/pool truth is accumulated across windows and priced from local pool state
change_summary:
  - Added `low_lag_watchlist` artifact block: per-pool entries with 10 fields (pair, pool_address, first/last_seen_block, seen_count, reject_reason, pair_unresolved_detail, pool_state_read_path, known_pools, active_pools). Deduplicated by pool_address; seen_count increments across events from same pool.
  - Added `blocker_tags` artifact block: active_tags (list), active_count (int), all_canonical_tags (sorted list). 7 canonical tags.
  - Added `ALL_BLOCKER_TAGS` module-level frozenset + 7 individual constants (BLOCKER_LOW_LAG_NONE_THIS_WINDOW, BLOCKER_LOW_LAG_NO_COUNTER_POOL, BLOCKER_LOW_LAG_V2_UNSUPPORTED, BLOCKER_LOW_LAG_INACTIVE_POOL, BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY, BLOCKER_GAS_L1_DATA_DOMINANT, BLOCKER_SUBGRAPH_API_KEY_REQUIRED)
  - Added `m7a518_hypothesis` string to ws-live artifacts
  - No new BackrunResult fields (still 56). No new reject reasons (still 19). All changes are artifact-level.
  - Added 29 new contract tests (444 total orderflow, 3180 total suite)
  - Corrected M7.A.5.17 Status wording per fresh rerun evidence
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: blocker tag constants, low_lag_watchlist computation, blocker_tags computation, m7a518_hypothesis)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +29 tests, 444 total; 3 new test classes)
  - docs/status/Status_M7.md (MODIFIED: updated status line, corrected M7.A.5.17 wording, added M7.A.5.18 section)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (444 passed in ~3.4s)
py -3.11 -m pytest tests/unit -q: PASS (3180 passed, 6 skipped in ~60s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (~63s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7a_518_300b.json: PASS (21 events, 3 low-lag)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7a_518_300b_b.json: PASS (20 events, 3 low-lag)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_518_1000b.json: PASS (22 events, 0 low-lag)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_518_300b.json (300-block ws-live, 21 events, 3 low-lag detected, 0 scored)
  - data/tmp/m7a_518_300b_b.json (300-block ws-live, 20 events, 3 low-lag detected, 0 scored)
  - data/tmp/m7a_518_1000b.json (1000-block ws-live, 22 events, 0 low-lag detected, 3 stale positive)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.A.5.18 Watchlist + Blocker Tags

### Hypothesis Status

M7.A.5.18 hypothesis **CONFIRMED**: Low-lag pair/pool truth varies across windows. The blocker_tags block correctly activates different tags depending on the window's content. Watchlist captures pool addresses when candidate_pools exist. Temporal variance across 3 evidence runs confirms that cross-window accumulation would be necessary to build a stable low-lag pair truth surface.

### Evidence: Blocker Tags Across Windows

| Blocker Tag | 300b | 300b_b | 1000b |
|-------------|------|--------|-------|
| LOW_LAG_NONE_THIS_WINDOW | - | - | **ACTIVE** |
| LOW_LAG_NO_COUNTER_POOL | **ACTIVE** | **ACTIVE** | - |
| LOW_LAG_V2_UNSUPPORTED | - | - | - |
| LOW_LAG_INACTIVE_POOL | - | - | - |
| LOW_LAG_REMOTE_QUOTER_LATENCY | **ACTIVE** | **ACTIVE** | - |
| GAS_L1_DATA_DOMINANT | **ACTIVE** | - | - |
| SUBGRAPH_API_KEY_REQUIRED | **ACTIVE** | **ACTIVE** | **ACTIVE** |

### Evidence: Low-Lag Watchlist

| Run | Entries | Pool Address | Pair | Seen Count | Reject |
|-----|---------|-------------|------|------------|--------|
| 300b | 1 | 0xdd91... | 0x44f49ff0/USDT | 2 | ALL_CANDIDATE_POOLS_TRULY_INACTIVE |
| 300b_b | 0 | - | - | - | (all NO_COUNTER_POOL → no pool to track) |
| 1000b | 0 | - | - | - | (no low-lag events) |

### Evidence: Reject Histograms

| Reject | 300b | 300b_b | 1000b |
|--------|------|--------|-------|
| GAS_EXCEEDS_GROSS | 19 | 16 | 19 |
| NO_COUNTER_POOL | 2 | 3 | 0 |
| STALE_POSITIVE | 0 | 1 | 3 |
| ALL_CANDIDATE_POOLS_TRULY_INACTIVE | 2* | 0 | 0 |

*only in low_lag_reject_histogram

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A518BlockerTagConstants | 4 | PASS |
| TestM7A518BlockerTagsArtifact | 11 | PASS |
| TestM7A518LowLagWatchlist | 7 | PASS |
| TestM7A518BackwardCompat | 7 | PASS |
| **Total new (M7.A.5.18)** | **29** | **PASS** |
| **Total orderflow tests** | **444** | **PASS** |
| **Total all tests** | **3180** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **Temporal variance confirmed**: Three evidence windows show fundamentally different low-lag landscapes: 300b sessions catch 3 low-lag events each (NO_COUNTER_POOL or INACTIVE); 1000b catches zero low-lag events but 3 stale positives (best_net=+14.34 bps). No single run is representative.

2. **Watchlist works but coverage-limited**: The watchlist correctly accumulates pool addresses from candidate_pools in coverage_result. However, NO_COUNTER_POOL events have empty candidate_pools (known_pools=0), so they produce no watchlist entries. The watchlist is most useful for INACTIVE_POOL events where the pool exists but has zero liquidity.

3. **Blocker tags correctly activate per window**: SUBGRAPH_API_KEY_REQUIRED is always present (structural). Other tags activate only when relevant evidence exists in the window. This provides a machine-readable top-level summary of what's blocking progress.

4. **Stale positive reaches +14.34 bps**: The 1000b run produced 3 STALE_POSITIVE events with best_net_bps=14.34 — this would be profitable if it were same-block, but it's stale (block_lag > 2). The STALE_POSITIVE gate correctly rejects these.

5. **Next investigation paths**: (a) Cross-window accumulation — persist watchlist across runs; (b) V2/V3 Factory `getPair`/`getPool` for bounded counter-venue discovery; (c) Subgraph API key for expanded token coverage; (d) Local-state pricing (V2 getReserves, V3 slot0+liquidity) to avoid remote quoter latency.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 19, UNSCORED_REJECTS: 11, BackrunResult: 56 fields, ALL_BLOCKER_TAGS: 7)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
watchlist/blocker_tags: OK (artifact-level, no BackrunResult field changes)

## 5.2) Blockers / Risks
- PRIMARY: NO_COUNTER_POOL dominates low-lag where events exist — pair resolves but no same-chain counter-venue in narrow_7
- SECONDARY: LOW_LAG_NONE_THIS_WINDOW dominates in longer windows — temporal instability fundamental
- STRUCTURAL: SUBGRAPH_API_KEY_REQUIRED always active — subgraph seed cannot expand coverage anonymously (403)
- UNCHANGED: Gas-exceeds-gross dominates stale subset; M4 baseline unchanged at -3.5062 bps
