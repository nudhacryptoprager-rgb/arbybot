# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-30T00:00:00Z
run_id: m7a5_4_multicall_pruning_evidence
mode: ONLINE (ws-live evidence run on arbitrum_one via Alchemy WSS)
artifact_mode: local_session (data/tmp) + rolling
config: arbitrum_one narrow_7 universe, ws-triggered block-event backrun replay with 2-stage multicall pruning
code_identity:
  primary: ts:2026-03-30T00:00:00Z
  dirty: true
  desc: M7.A.5.4 two-stage multicall pruning pipeline + evidence

## Session Completion
session_goal: M7.A.5.4 — implement two-stage multicall pruning pipeline (Stage A: factory.getPool + liquidity via multicall; Stage B: confirmatory QuoterV2) and generate ws-live evidence to test whether reducing quote_calls_attempted from ~12 to ≤4 makes backrun viable
goal_status: REACHED (evidence produced — multicall pruning measurably works but pipeline latency increased; per-call RPC latency is irreducible bottleneck)
close_allowed: true
remaining_blockers: none (evidence conclusive — quote-fanout-collapse hypothesis closed)
evidence_session_run_dirs:
  - data/tmp/m7a_ws_live_pruned.json (ws-live evidence, 50 blocks, 8 events, 2-stage pruning)
primary_blocker_of_session: M7.A.5.3.1 multicall pruning was a no-op (venues_pruned=0) — need real multicall-based venue pruning to test call-reduction hypothesis
blocker_status_before: ACTIVE (venues_pruned_by_multicall=0 in all prior ws-live runs)
blocker_status_after: RESOLVED (venues_pruned=8, calls reduced 20→16, but pipeline latency increased — hypothesis closed)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.4 — collapse per-event quote count via multicall/local-state prefilter + confirmatory quotes
change_summary:
  - Added `batch_get_pool()` method to MulticallBatcher (batches factory.getPool via multicall)
  - Added `_resolve_pool_addresses_multicall()` — resolves V3 pool addresses via batched factory.getPool + batch_liquidity
  - Rewrote `score_backrun_live_parallel()` as 2-stage pipeline: Stage A (multicall pruning) → Stage B (confirmatory QuoterV2)
  - Added 4 new BackrunResult fields: quote_calls_attempted, quote_calls_after_pruning, prune_reason_histogram, pipeline_stage_latency_ms
  - Added artifact metrics: mean_quote_calls_attempted, mean_quote_calls_after_pruning, prune_reason_histogram, mean_stage_a_ms, mean_stage_b_ms, mean_quote_calls_after_pruning in ws_low_lag_summary
  - Added 20 new contract tests (133 total in test_orderflow_contracts.py)
  - Generated ws-live evidence with 2-stage pruning (50 blocks, 8 events)
touched_files:
  - core/multicall.py (MODIFIED: +batch_get_pool method)
  - scripts/m7a_orderflow_replay.py (MODIFIED: 2-stage pipeline, new fields, _resolve_pool_addresses_multicall)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +20 tests, 133 total)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.4 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (133 passed in 14.54s)
py -3.11 -m pytest tests/unit -q: PASS (2869 passed, 6 skipped in 70.01s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (66.1s)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 50 --ws-timeout 60 --max-events 20 --output data/tmp/m7a_ws_live_pruned.json: COMPLETED (8 events, 50 blocks, 49.11s)

## 3) Artifacts Attached

local_session (R&D evidence, data/tmp):
  - data/tmp/m7a_ws_live_pruned.json (M7.A.5.4 ws-live: 50 blocks, 8 events, 2-stage pruning active)

prior session artifacts (for comparison):
  - data/tmp/m7a_ws_live.json (M7.A.5.3.1: 10 blocks, 6 events, multicall=no-op)

rolling (unchanged):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json (two-leg baseline: -3.5062 bps)

## 4) Key Results — M7.A.5.4 Two-Stage Pruning Evidence

### Core Evidence (Before vs After)

| Metric | M7.A.5.3.1 (before) | M7.A.5.4 (after) | Delta |
|--------|---------------------|-------------------|-------|
| events_scored | 6 | 8 | +33% |
| events_scored_low_lag_ws | 0 | 0 | no change |
| venues_pruned_by_multicall | **0** | **8** | **now measurable** |
| mean_quote_calls_attempted | N/A | 20.0 | new field |
| mean_quote_calls_after_pruning | N/A | 16.0 | 20% reduction |
| prune_reason_histogram | N/A | NO_POOL: 16 | new field |
| mean_stage_a_ms | N/A | 656 | new field |
| mean_stage_b_ms | N/A | 2204 | new field |
| mean_pipeline_latency_ms | 2258 | **2860** | **+27% worse** |
| latency_budget_ms | 250 | 250 | same |
| latency_budget_hit_rate | 0.0 | 0.0 | same |
| sub_block_capable | false | false | same |
| best_net_bps | -20.49 | -19.73 | marginal |

### Two-Stage Pipeline Breakdown

| Stage | Mean Latency | RPC Calls | Purpose |
|-------|-------------|-----------|---------|
| Stage A (multicall) | 656ms | 2 (getPool + liquidity) | Resolve pools, prune dead venues |
| Stage B (QuoterV2) | 2204ms | ~16 parallel | Confirmatory buy/sell quotes |
| Pipeline total | 2860ms | ~18 | vs 250ms budget (11.4× over) |

### Prune Reason Histogram (aggregate across 8 events)

| Reason | Count |
|--------|-------|
| NO_POOL | 16 |
| ZERO_LIQUIDITY | 0 |

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A54BackrunResultFields | 7 | PASS |
| TestM7A54PruneReasonHistogram | 3 | PASS |
| TestM7A54StageLatency | 3 | PASS |
| TestM7A54ArtifactFields | 2 | PASS |
| TestM7A54ResolvePoolAddresses | 2 | PASS |
| TestM7A54BackwardCompat | 3 | PASS |
| TestBatchGetPool | 1 | PASS |
| **Total new (this session)** | **20** (+1 import) | **PASS** |
| **Total orderflow tests** | **133** | **PASS** |
| **Total all tests** | **2869** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **Multicall pruning now measurably works**: `venues_pruned_by_multicall` went from 0 (no-op) to 8. The Stage A pipeline correctly resolves pool addresses via `factory.getPool()` multicall and checks liquidity. Prune reason `NO_POOL=16` shows that many DEX × fee tier combos have no deployed pool for the token pair.

2. **Call reduction is insufficient**: Pruning reduced potential calls from 20 to 16 (20% reduction). This is far below the target of ~12→≤4. Most DEXes that have a quoter also have deployed pools, so multicall can only prune DEXes with missing pools, not reduce calls within active DEXes.

3. **Stage A adds overhead instead of saving time**: The multicall pruning stage costs ~656ms (2 RPC calls: factory.getPool batch + liquidity batch). This is additive to the pipeline, not a replacement. Total pipeline latency increased from 2258ms to 2860ms (+27%).

4. **The irreducible bottleneck is per-call RPC latency (~400ms)**: Even with perfect pruning down to 1 QuoterV2 call, that single call takes ~400ms, which exceeds the 250ms Arbitrum block budget. No amount of call reduction on public RPC infrastructure can achieve sub-block latency.

5. **All public RPC architecture paths are now exhaustively closed**:
   - M7.A.5.1: Public HTTP polling → NOT VIABLE (mean_lag=218)
   - M7.A.5.2: Alchemy HTTP polling → NOT VIABLE (mean_lag=59.55)
   - M7.A.5.3: Alchemy WSS streaming → NOT VIABLE (pipeline 9× over budget)
   - M7.A.5.4: Multicall pruning → NOT VIABLE (pipeline 11× over budget, increased)

6. **The only unexplored theoretical path would require**: co-located node (sub-1ms RPC), on-chain quoter (instead of off-chain RPC), or MEV relay integration. These are outside the bounded M7.A scope per `docs/step_M7.md`.

## 6) Milestone Summary

| Milestone | Status |
|-----------|--------|
| M0-M3 | Completed foundation |
| M4 | Frozen (public-infra economics ceiling) |
| M5_0 | Reached (stable rolling artifacts) |
| M7.A | **VERDICT READY — NO-GRADUATE** (narrow_7) |
| M7.A.2 | **VERDICT READY — NO-GRADUATE** (expanded_10) |
| M7.A.3 | **CLOSED BOUNDED BASELINE** (medium_activity regime) |
| M7.A.4 | **CLOSED BOUNDED BASELINE** (orderflow replay, intent scout) |
| M7.A.5 | **LIVE EVIDENCE: NOT VIABLE** (public RPC) |
| M7.A.5.2 | **LIVE EVIDENCE: NOT VIABLE** (Alchemy RPC) |
| M7.A.5.3 | **LIVE EVIDENCE: NOT VIABLE** (Alchemy WSS — pipeline 9× over budget) |
| M7.A.5.4 | **LIVE EVIDENCE: NOT VIABLE** (multicall pruning — pipeline 11× over budget, per-call latency is irreducible) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
