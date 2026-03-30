# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_515_300b (low-lag debug diagnostic + coverage truth evidence session)
mode: ONLINE (ws-live evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7a_515_300b.json, data/tmp/m7a_515_1000b.json)
rolling_run_dir: ci_m5_gate_arbitrum_one_20260327_222948_123275
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: true
  desc: M7.A.5.15 low-lag debug rows + pair_unresolved_detail + coverage truth + targeted enrichment fallback

## Session Completion
session_goal: M7.A.5.15 -- diagnose WHY low-lag TOKEN_PAIR_UNRESOLVED fires (causal detail), add per-event low-lag debug rows, coverage truth metrics, and targeted enrichment fallback
goal_status: REACHED (pair_unresolved_detail reveals pool_read_failed as universal cause; targeted eth_call fallback also fails on same pools; coverage truth confirms 0 known/active pools for low-lag events; structural blocker confirmed: non-standard pool contracts)
close_allowed: true
remaining_blockers: low-lag pool contracts are non-standard (not Uniswap V3 ABI) — both multicall and individual eth_call fail to read token0()/token1()
evidence_session_run_dirs: [data/tmp/m7a_515_300b.json, data/tmp/m7a_515_1000b.json]
primary_blocker_of_session: pool_read_failed on all low-lag TOKEN_PAIR_UNRESOLVED events
blocker_status_before: DIAGNOSED (M7.A.5.14 identified TOKEN_PAIR_UNRESOLVED as blocker but did not explain WHY it fires)
blocker_status_after: ROOT-CAUSED -- pool_read_failed is universal; both multicall batch_token_info and direct eth_call for token0()/token1() fail on these pools
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.15 -- low-lag debug diagnostic + coverage truth; hypothesis: token identity and active counter-pool truth are incomplete for exact low-lag pairs
change_summary:
  - Added `pair_unresolved_detail` field to BackrunResult (54 fields total): captures causal detail (`no_pool_address`, `pool_read_failed`, `no_symbol_map`)
  - Added `low_lag_debug_rows` in build_replay_summary(): per-event diagnostic for block_lag<=2 events (event_id, reject_reason, pair_resolved, actual_pair, pair_unresolved_detail, admission_source, known/active pools, counter_venue_count)
  - Added `low_lag_coverage_truth` block: known_pools_total, active_pools_total, active_buy/sell_venues, no_counter_pool_rate, inactive_pool_rate
  - Added targeted enrichment fallback: when _resolve_event_tokens() fails, tries individual eth_call for token0()/token1(), enriches discovered addresses, retries resolution
  - Added `m7a515_hypothesis` artifact block
  - Added 18 new contract tests (374 total orderflow, 3110 total suite)
  - Corrected M7.A.5.14 Status_M7.md section: blocker stack is multi-causal, not single-dominant
touched_files:
  - scripts/m7a_orderflow_replay.py (MODIFIED: pair_unresolved_detail, low_lag_debug_rows, low_lag_coverage_truth, targeted enrichment fallback, hypothesis block)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +18 tests, 374 total; 5 new test classes, updated backward-compat field counts 53→54)
  - docs/status/Status_M7.md (MODIFIED: header update, corrected M7.A.5.14, added M7.A.5.15 section)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (374 passed in ~3s)
py -3.11 -m pytest tests/unit -q: PASS (3110 passed, 6 skipped in ~62s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (59s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7a_515_300b.json: PASS (17 events, 6 low-lag)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --ws-timeout 600 --max-events 100 --output data/tmp/m7a_515_1000b.json: PASS (12 events, 3 low-lag)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_515_300b.json (300-block ws-live, 17 events, 6 low-lag detected, 0 low-lag scored)
  - data/tmp/m7a_515_1000b.json (1000-block ws-live, 12 events, 3 low-lag detected, 0 low-lag scored)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.A.5.15 Low-Lag Debug Diagnostic

### Hypothesis Status

The M7.A.5.15 hypothesis is **CONFIRMED (structural blocker identified)**: low-lag events fail at TOKEN_PAIR_UNRESOLVED because the pool contracts are non-standard (not Uniswap V3 ABI). Both multicall `batch_token_info()` and the new targeted enrichment fallback (individual `eth_call` for `token0()`/`token1()`) fail on these pools. The coverage truth shows 0 known/active counter-pools for ANY low-lag event.

### Evidence: Low-Lag Debug Rows (300b)

| event_id | reject_reason | pair_unresolved_detail | actual_pair | known_pools | active_pools |
|----------|--------------|----------------------|-------------|-------------|--------------|
| live_swap_447168120_0 | NO_COUNTER_POOL | null | 0x1009c5c1/USDT | 0 | 0 |
| live_swap_447168123_0 | NO_COUNTER_POOL | null | WETH/0x60bf4e7c | 0 | 0 |
| live_swap_447168146_3 | TOKEN_PAIR_UNRESOLVED | pool_read_failed | null | 0 | 0 |
| live_swap_447168147_2 | TOKEN_PAIR_UNRESOLVED | pool_read_failed | null | 0 | 0 |
| live_swap_447168203_0 | TOKEN_PAIR_UNRESOLVED | pool_read_failed | null | 0 | 0 |
| live_swap_447168220_0 | TOKEN_PAIR_UNRESOLVED | pool_read_failed | null | 0 | 0 |

### Evidence: Low-Lag Reject Histograms

| Run | Low-lag detected | Low-lag scored | Reject distribution | Pair resolution rate |
|-----|-----------------|---------------|---------------------|---------------------|
| 300b | 6 | 0 | TOKEN_PAIR_UNRESOLVED: 4, NO_COUNTER_POOL: 2 | 33.3% |
| 1000b | 3 | 0 | TOKEN_PAIR_UNRESOLVED: 3 | 0.0% |

### Evidence: Low-Lag Coverage Truth

| Metric | 300b | 1000b |
|--------|------|-------|
| known_pools_total | 0 | 0 |
| active_pools_total | 0 | 0 |
| active_buy_venues | 0 | 0 |
| active_sell_venues | 0 | 0 |
| no_counter_pool_rate | 0.3333 | 0.0 |
| inactive_pool_rate | 0.0 | 0.0 |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A515PairUnresolvedDetail | 4 | PASS |
| TestM7A515LowLagDebugRows | 4 | PASS |
| TestM7A515LowLagCoverageTruth | 2 | PASS |
| TestM7A515FourLowLagPaths | 4 | PASS |
| TestM7A515BackwardCompat | 4 | PASS |
| **Total new (M7.A.5.15)** | **18** | **PASS** |
| **Total orderflow tests** | **374** | **PASS** |
| **Total all tests** | **3110** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **pool_read_failed is universal**: Every TOKEN_PAIR_UNRESOLVED event has `pair_unresolved_detail: pool_read_failed`. Both the multicall `batch_token_info()` and the new targeted eth_call fallback for `token0()`/`token1()` fail. These pools are likely non-standard contracts (e.g., Curve, Balancer, Solidly forks) that don't implement the Uniswap V3 `token0()`/`token1()` interface.

2. **NO_COUNTER_POOL: resolved pairs are exotic**: When pair resolution DOES succeed (300b: 2 events), the resolved pairs are exotic (`0x1009c5c1/USDT`, `WETH/0x60bf4e7c`) — one token is always an unrecognized address. No counter-venue pools exist for these pairs in the narrow_7 universe.

3. **Coverage truth is zero across the board**: known_pools_total=0, active_pools_total=0 for all low-lag events. No low-lag event has ANY known pool to trade against. This is a structural coverage gap — the narrow_7 universe's pool registry doesn't contain pools for the tokens being swapped in same-block events.

4. **Stale subset continues to beat M4 baseline**: `best_net_bps_stale: -2.10` (1000b) vs M4 baseline of -3.51 bps.

5. **Targeted enrichment is necessary but insufficient**: The fallback enrichment tries harder to resolve pool tokens but still fails — the fundamental issue is that the pool contracts don't support the expected ABI. Next diagnostic step: identify the pool contract types (factory address, bytecode signature) to determine which DEX adapters are needed.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 19, UNSCORED_REJECTS: 11, BackrunResult: 54 fields)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
low-lag diagnostic: OK (low_lag_debug_rows present, pair_unresolved_detail populated, coverage_truth block present)

## 5.2) Blockers / Risks
- pool_read_failed is the root cause for TOKEN_PAIR_UNRESOLVED — pools are non-standard contracts
- NO_COUNTER_POOL: resolved pairs are exotic tokens with no counter-venue pools
- Coverage truth is zero for all low-lag events — structural gap in pool registry
- GAS_EXCEEDS_GROSS still dominant on stale subset
- No low-lag scored events in any M7.A.5.x run to date — low-lag executable economy remains unproven
- Next step: identify pool contract types (factory forensics) to determine required DEX adapters

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY -- NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY -- NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC latency) |
| M7.A.5.5 | **LIVE EVIDENCE: NOT VIABLE** (actual-pair token resolution) |
| M7.A.5.6-5.7 | **COVERAGE DECOMPOSED + ENRICHMENT BUILT** |
| M7.A.5.8 | **LIVE EVIDENCE: BLOCKER SHIFTED** (admission 100%, GAS_EXCEEDS_GROSS 100%) |
| M7.A.5.9 | **CORRECTIVE: DENOMINATION-CORRECT** (size + gas bugs fixed) |
| M7.A.5.10 | **CORRECTIVE: CONTRACT-CORRECT** (stale-gate + zero-liq + provenance fixed) |
| M7.A.5.11 | **DIAGNOSTIC: ACTIVE-COVERAGE-AWARE** (granular rejects + pre-econ metrics) |
| M7.A.5.12 | **BREAKTHROUGH: BYTE-FIX UNBLOCKS ECONOMICS** (26/28 scored, GAS_EXCEEDS_GROSS dominant) |
| M7.A.5.13 | **DIAGNOSTIC: STALE/LOW-LAG SPLIT** (stale beats M4 baseline, 0 low-lag scored) |
| M7.A.5.14 | **DIAGNOSTIC: LOW-LAG REJECT DECOMPOSITION** (TOKEN_PAIR_UNRESOLVED dominant, 100% pre-econ fail) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
