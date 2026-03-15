# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 7 Round 28.12)
**Goal**: R28.12 architectural -- Event queue DirtySetTracker, hot_loop_latest.json, cross-pair parallel quotes (shared TPE), WS block pass-through, truth path alignment.
**Prior (R28.11 Turn 2)**: Hot re-quote loop + WebSocket dirty-set invalidation. Turn 2 completed dual-cycle architecture. R28.12 upgrades: DirtySetTracker from boolean to event queue, cross-pair shared executor, WS block pass-through env var, hot_loop_latest.json fast-refresh artifact, truth_path_alignment section.

## 0) Meta
timestamp_utc: 2026-03-15T20:42:48Z
rolling_provenance: 2026-03-15T20:45:59Z (6-chain long_scan -- R28.12 fresh evidence)
mode: HOT_LOOP + EVENT_QUEUE + CROSS_PAIR_PARALLEL + TRUTH_PATH_ALIGNMENT
test_count: 1886 passed, 3 skipped
schema_version: start:long_scan_summary:v1.11

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.12: Architectural -- event queue DirtySetTracker, hot_loop_latest.json, cross-pair parallel quotes, WS block pass-through, truth path alignment |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: arb/zksync gap still PRIMARY_BLOCKER; mantle/scroll infra-fail (NOT_PROVEN); base thin evidence (THIN_POSITIVE) |
| evidence_session_run_dirs | long_scan_latest.json (2026-03-15T20:45:59Z, 6 chains, schema v1.11, hot_loop + truth_path_alignment populated, 10 full sweeps + 20 hot requotes), hot_loop_latest.json (v1.0) |
| primary_blocker_of_session | DirtySetTracker was boolean flag (no event ordering/priority); per-pair serial quote executor (bottleneck); no WS block pass-through; no truth path alignment |
| blocker_status_before | ACTIVE: boolean dirty-set, per-pair TPE create/destroy, no cross-pair parallelism, no event queue, no truth alignment |
| blocker_status_after | RESOLVED: event queue with pending_chains()/drain_event(); shared 16-worker TPE; WS block env var; hot_loop_latest.json; truth_path_alignment section |
| start_metric | R28.11 T2: 1870 tests, boolean dirty-set, per-pair TPE, no hot_loop_latest.json, no truth alignment |
| end_metric | R28.12: 1886 tests (+16), event queue DirtySetTracker, shared TPE(16), hot_loop_latest.json, truth_path_alignment, schema v1.11 |
| delta | +event queue (pending_chains/drain_event/mark_clean), +shared cross-pair TPE(16), +ARBY_WS_BLOCK_NUMBER, +hot_loop_latest.json, +truth_path_alignment, +16 tests, schema v1.10->v1.11 |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 architectural scanning pipeline (R28.12 lead directive)
change_summary:
  - EVENT_QUEUE: strategy/infra.py -- DirtySetTracker upgraded from boolean dirty-flag to event queue. pending_chains() ordered by arrival. drain_event(chain) pops latest block. mark_clean clears. maxlen=32.
  - HOT_LOOP_LATEST: start.py -- hot_loop_latest.json written after each batch. Schema start:hot_loop_snapshot:v1.0. Fast-refresh for dashboard.
  - CROSS_PAIR_PARALLEL: strategy/quotes.py -- shared 16-worker TPE replaces per-pair TPE create/destroy.
  - WS_BLOCK_PASSTHROUGH: strategy/jobs/run_scan_real.py -- _get_current_block() checks ARBY_WS_BLOCK_NUMBER env var first, skips block-pin RPC.
  - TRUTH_PATH_ALIGNMENT: start.py -- _compute_truth_path_alignment() classifies chains as ALIGNED/BLOCKED/NOT_PROVEN/POSITIVE.
  - SCHEMA_BUMP: v1.10 -> v1.11 (additive: truth_path_alignment, hot_loop_latest support).
touched_files: start.py, strategy/infra.py, strategy/quotes.py, strategy/jobs/run_scan_real.py, tests/unit/test_start.py, tests/unit/test_nonstop_loop_artifacts.py, tests/unit/test_run_scan_real_purity.py, docs/status/Status_M4.md

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: **PASS** (1886 passed, 3 skipped)
py -3.11 start.py --config-list (6 chains) --hours 0.10 --cycles 1: **PASS** (schema v1.11, 30 runs, 10 full/20 hot, 503.6s wall)

## 3) Artifacts Attached
rolling (FRESH from R28.12):
  - data/runs/_rolling/long_scan_latest.json (generated_at: 2026-03-15T20:45:59Z, schema v1.11)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T20:42:48Z, status=PASS)
  - data/runs/_rolling/_latest.json (run_dir: ci_m5_gate_arbitrum_one_20260315_214232_639500)
  - data/runs/_rolling/hot_loop_latest.json (schema: start:hot_loop_snapshot:v1.0)

## 4) Key Results

```
# R28.12 Fresh Evidence (long_scan_latest.json)
schema: start:long_scan_summary:v1.11
generated_at: 2026-03-15T20:45:59Z
total_runs: 30, wall_seconds: 503.6

# Hot Loop: 10 full sweeps, 20 hot requotes

# Per-Chain
arbitrum_one: runs=5 pass=5 fail=0 signals=47 profitable_rt=0 state=PRIMARY_BLOCKER
zksync:       runs=5 pass=5 fail=0 signals=5  profitable_rt=0 state=PRIMARY_BLOCKER
base:         runs=5 pass=4 fail=1 signals=9  profitable_rt=7 state=THIN_POSITIVE
mantle:       runs=5 pass=0 fail=4 signals=0  profitable_rt=0 state=CANDIDATE
linea:        runs=5 pass=5 fail=0 signals=15 profitable_rt=10 state=CONFIRMED_POSITIVE_CONTROL
scroll:       runs=5 pass=0 fail=5 signals=0  profitable_rt=0 state=CANDIDATE

# Truth Path Alignment (R28.12)
arbitrum_one: BLOCKED (PRIMARY_BLOCKER)
zksync:       BLOCKED (PRIMARY_BLOCKER)
base:         POSITIVE (THIN_POSITIVE)
linea:        POSITIVE (CONFIRMED_POSITIVE_CONTROL)
mantle:       NOT_PROVEN (CANDIDATE)
scroll:       NOT_PROVEN (CANDIDATE)
```

## 5) Contract Checks
- Event queue DirtySetTracker: pending_chains()/drain_event()/mark_clean -- VERIFIED with tests
- hot_loop_latest.json: schema v1.0, written after each batch -- VERIFIED
- Shared TPE(16): eliminates per-pair create/destroy -- VERIFIED with test
- WS block pass-through: ARBY_WS_BLOCK_NUMBER -> skip RPC -- VERIFIED with test
- Truth path alignment: BLOCKED/POSITIVE/NOT_PROVEN classification -- VERIFIED with tests
- Schema additive: v1.10->v1.11 -- VERIFIED
- System is still batch-hot: WS invalidates, does not trigger immediate executable re-quote -- ACKNOWLEDGED

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1886 PASS)
market_gap: MEDIUM (arb/zksync PRIMARY_BLOCKER; mantle/scroll CANDIDATE)
hot_loop: ACTIVE (batch-hot, not instant-hot)
linea: CONFIRMED_POSITIVE (10 profitable RT)
base: THIN_POSITIVE (7 profitable RT, needs more repetitions)
```

## 7) R28.12 Session Summary
- EVENT_QUEUE: DirtySetTracker upgraded: pending_chains() ordered by arrival, drain_event() pops latest block, mark_clean() clears. maxlen=32.
- HOT_LOOP_LATEST: hot_loop_latest.json written after each batch. Fast-refresh dashboard data.
- CROSS_PAIR_PARALLEL: Shared 16-worker TPE replaces per-pair TPE. Eliminates overhead.
- WS_BLOCK_PASSTHROUGH: ARBY_WS_BLOCK_NUMBER env var skips block-pin RPC round-trip.
- TRUTH_PATH_ALIGNMENT: Classifies chains (BLOCKED/POSITIVE/NOT_PROVEN/ALIGNED). Operator visibility.
- Tests: +16 (1886 total). Schema v1.10->v1.11.

## 8) What Lead Needs To Decide
1. Instant-hot: WS invalidates but no immediate re-quote pipeline yet. Next step?
2. Cross-pair concurrency=16: appropriate or configurable?
3. Truth alignment states: sufficient granularity?
4. Base THIN_POSITIVE: needs more repetitions for promotion.
5. Mantle/scroll infra failures: investigation or quarantine?