# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_523_300b / m7a_523_300b_b / m7a_523_1000b
mode: ONLINE (evidence runs + unit tests)
artifact_mode: local evidence (data/tmp/m7a_523_*.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-04-02T12:00:00Z
  dirty: true
  desc: M7.A.5.23 — low-lag registry-direct scoring bridge; 100% scoring rate via local pricing; 19 new tests
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275
rolling_run_timestamp: 2026-03-27T21:30:14Z
note: rolling artifacts predate this session; not regenerated; session evidence is in data/tmp/m7a_523_*

## Session Completion
session_goal: M7.A.5.23 — implement low-lag registry-direct scoring bridge; bypass coverage scan for low-lag events with registry active pools; route into adapter-specific local pricing; KPI: first low-lag scored event
goal_status: REACHED (registry-direct fast path implemented; 99-100% events scored via registry_direct + local pricing; 9/100 positive net_bps; session pair tracking operational; 19 new tests; 3286 pass; 3 evidence runs)
close_allowed: true
remaining_blockers: all positive-net events are STALE_POSITIVE (block_lag > 2 at scoring completion); viable_count=0; scoring latency (34+ blocks) prevents fresh completion; M4 baseline still negative
evidence_session_run_dirs: [data/tmp/m7a_523_300b.json, data/tmp/m7a_523_300b_b.json, data/tmp/m7a_523_1000b.json]
primary_blocker_of_session: coverage scan killed all low-lag events before local pricing (required quoter_v2 which V2 DEXes lack; attempt_local_pricing() can do V2 math without quoter_v2)
blocker_status_before: ACTIVE (events_scored_low_lag=0 in all M7.A.5.22 runs; coverage_complete=False for V2 pools)
blocker_status_after: RESOLVED (100% scoring rate via registry_direct path; coverage scan bypassed; local pricing via V3+V2 adapters)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.23 — low-lag registry-direct scoring bridge
change_summary:
  - `m7/orderflow/scoring_parallel.py` (MODIFIED): Low-lag fast path between registry preload and coverage scan — if preliminary_lag <= 2 AND registry_pools_active > 0, builds synthetic coverage + local_sim from PoolRegistryEntry.to_candidate_pool() / .to_pool_state(), skips coverage scan entirely, goes to local pricing. Non-low-lag events unchanged.
  - `m7/orderflow/contracts.py` (MODIFIED): New field low_lag_scoring_path (66th). Values: None | "registry_direct".
  - `m7/orderflow/mode_ws_live.py` (MODIFIED): Session-persistent _session_low_lag_pairs dict using detection-time lag. session_low_lag_pairs + m7a523_hypothesis in artifact.
  - `m7/orderflow/artifacts.py` (MODIFIED): m7a523_low_lag_fast_path section with low_lag_registry_direct_count + low_lag_registry_direct_scored_count.
  - `tests/unit/test_orderflow_m7a523.py` (NEW, 19 tests): 5 test classes.
  - 10 test files updated for field count 65→66.
touched_files:
  - m7/orderflow/scoring_parallel.py (MODIFIED: +low-lag fast path ~40 lines)
  - m7/orderflow/contracts.py (MODIFIED: +low_lag_scoring_path field)
  - m7/orderflow/mode_ws_live.py (MODIFIED: +session pair tracking, +hypothesis)
  - m7/orderflow/artifacts.py (MODIFIED: +m7a523_low_lag_fast_path metrics)
  - tests/unit/test_orderflow_m7a523.py (NEW: 19 tests in 5 classes)
  - tests/unit/test_orderflow_m7a5{11_512,13_515,16_517,18_519,20,21,22,55_56,57_58,59_510}.py (MODIFIED: field count 65→66)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.23 section)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3286 passed, 6 skipped)
py -3.11 -m m7.orderflow.cli --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_523_300b.json: PASS
py -3.11 -m m7.orderflow.cli --ws-live --ws-blocks 300 --ws-timeout 360 --max-events 30 --output data/tmp/m7a_523_300b_b.json: PASS
py -3.11 -m m7.orderflow.cli --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_523_1000b.json: PASS

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_523_300b.json (300-block ws-live, 30 events, best_net=+43.24 bps, 100% registry_direct)
  - data/tmp/m7a_523_300b_b.json (300-block ws-live, 30 events, best_net=+37.96 bps, 100% registry_direct, 12 session pairs)
  - data/tmp/m7a_523_1000b.json (1000-block ws-live, 100 events, best_net=+32.01 bps, 99% registry_direct, 39 session pairs)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results — M7.A.5.23

### Registry-Direct Scoring Bridge: 100% Scoring Rate

**Before (M7.A.5.22)**: Registry activated, 65-77 pools discovered, but events_scored_low_lag=0. Coverage scan killed all events because `coverage_complete` requires `quoter_v2` which V2 DEXes lack. Local pricing (which can handle V2) was never reached.

**After (M7.A.5.23)**: For low-lag events (preliminary_lag <= 2) with registry active pools, the coverage scan is bypassed entirely. Synthetic coverage and local_sim are built from `PoolRegistryEntry.to_candidate_pool()` / `.to_pool_state()`. `attempt_local_pricing()` receives registry entries for adapter dispatch (V3/V2/Algebra).

| Metric | 300b | 300b_b | 1000b |
|--------|------|--------|-------|
| events_scored | 30/30 (100%) | 30/30 (100%) | 100/100 (100%) |
| scoring_path=registry_direct | 30 (100%) | 30 (100%) | 99 (99%) |
| local_pricing_used | 30 (100%) | 30 (100%) | 99 (99%) |
| positive_net_count | 3 | 5 | 9 |
| best_net_bps | +43.24 | +37.96 | +32.01 |
| viable_count | 0 | 0 | 0 |
| registry_pools_discovered | 116 | n/a | 168 |
| registry_pools_active | 81 | n/a | 123 |
| session_low_lag_pairs | 0 | 12 | 39 |

### Positive Net Events Found — But All Stale

9/100 events in the 1000-block run have positive net_bps (18-43 bps). All are rejected as STALE_POSITIVE because `block_lag > 2` at scoring completion. The events are fresh at detection time (preliminary_lag ≈ 0) but scoring itself takes 34+ blocks of wall time.

### Session Pair Tracking Operational

39 unique pairs tracked across 1000 blocks. WETH/USDC most frequent (26x), RAIN/WETH (10x+8x with direction). All pairs scored via registry_direct with 100% scoring rate.

### Comparison: M7.A.5.23 vs M7.A.5.22

| Metric | M7.A.5.22 | M7.A.5.23 | Delta |
|--------|-----------|-----------|-------|
| events_scored rate | 79-100% (coverage-blocked) | 99-100% (registry-direct) | **+20-100%** |
| low_lag_scoring_path | n/a | registry_direct (99-100%) | **NEW** |
| local_pricing_used | 52-79% | 99-100% | **+20-48%** |
| positive_net_count | 0-1 | 3-9 per run | **+3-9** |
| best_net_bps | -2.20 to +1.53 | +32.01 to +43.24 | **+30-42 bps** |
| viable_count | 0 | 0 | unchanged |
| BackrunResult fields | 65 | 66 | +1 |

## 5) Strategic Reading

1. **Registry-direct path unlocks 100% scoring**: The coverage scan was the death point for 21-100% of events in M7.A.5.22. Bypassing it for events that already have registry-discovered active pools eliminates this bottleneck completely.
2. **Local pricing across adapters works**: V3 (29 events) and V2 (1 event) adapters both produce prices via `attempt_local_pricing()` with registry entries. The adapter dispatch (`_adapter_map` from registry) correctly routes to v3_local / v2_local compute functions.
3. **Positive net events emerge but are not viable**: 9/100 at +18-43 bps. All STALE_POSITIVE because scoring latency (34+ blocks) means `block_lag > 2` at completion. The edge exists at detection time but cannot be captured at current scoring speed.
4. **Next bottleneck is scoring latency**: Events are fresh at ws-detection (preliminary_lag ≈ 0). The fast path saved coverage-scan RPC calls. But the remaining pipeline (enrichment, oracle, pruning, gas computation, local pricing, size sweep) still takes 34+ blocks.
5. **Session pair tracking provides operational visibility**: 39 unique pairs with WETH/USDC dominant (26x). This data can inform pair-caching, pre-warming, and priority scoring in future steps.
6. **Honest assessment**: M7.A.5.23 is a real scoring breakthrough — 0% → 100% scoring rate, positive net events detected. But viable_count=0 and execution-relevant edge remains unproven. The positive signals are stale-state artifacts, not executable opportunities.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 20, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 1100 lines)
test file size constraint: OK (all M7 test files ≤ 995 lines, test_orderflow_m7a523.py ~260 lines)

## 5.2) Blockers / Risks
- PRIMARY (changed): Coverage-scan bottleneck **RESOLVED** by registry-direct path; new primary is **scoring latency** (34+ blocks from detection to completion)
- SECONDARY: All positive-net events are STALE_POSITIVE — edge exists at detection but cannot be captured
- MEASUREMENT: gas_floor_exceeded ~60-80% across runs; GAS_EXCEEDS_GROSS dominates scored rejections (90/100)
- REGISTRY PROVEN: 116-168 pools discovered, 81-123 active; cache hits operational
- UNCHANGED: M4 baseline still negative; SUBGRAPH_API_KEY_REQUIRED persists; viable_count=0
- NEXT: To progress from scoring to viability, need either (a) pipeline latency reduction (skip enrichment/oracle for warm pairs), (b) pre-scored pair caching (score only delta from cached state), or (c) lower-latency RPC infrastructure
