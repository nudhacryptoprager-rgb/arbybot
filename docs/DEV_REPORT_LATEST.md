# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7a_512_300b (ws-live unified-truth + byte-fix evidence session)
mode: ONLINE (ws-live evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7a_512_30b.json, data/tmp/m7a_512_300b.json)
rolling_run_dir: None (rolling artifacts predate this patch)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14.342304Z
  dirty: true
  desc: M7.A.5.12 byte-parsing fix in batch_full_pool_data + unified coverage/local-sim truth + split blocker rejects + consistency metrics

## Session Completion
session_goal: M7.A.5.12 -- unify coverage/local-sim pool-state truth source and fix byte-parsing bug in batch_full_pool_data that caused 4 sessions of zero scored results
goal_status: REACHED (byte-parsing bug found and fixed; coverage/local-sim unified; 26/28 events scored for first time since M7.A.5.7)
close_allowed: true
remaining_blockers: gas economics -- GAS_EXCEEDS_GROSS dominates (25/28); new blocker after measurement artifact resolved
evidence_session_run_dirs: [data/tmp/m7a_512_30b.json, data/tmp/m7a_512_300b.json]
primary_blocker_of_session: M7.A.5.11 coverage/local-sim inconsistency -- coverage reported active_pools_total>0 but local-sim always showed liquidity=0
blocker_status_before: ACTIVE (scored_results_count=0 for 4 consecutive sessions M7.A.5.8-5.11; byte-parsing bug in batch_full_pool_data read 16 bytes of 32-byte ABI word)
blocker_status_after: RESOLVED -- byte fix restores real liquidity values; 26/28 events reach economic scoring; coverage_local_mismatch_count=0
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.12 -- unify coverage scan and local-sim pool-state sources; fix byte-parsing bug; add split blocker rejects; add consistency metrics
change_summary:
  - Fixed ROOT CAUSE byte-parsing bug in core/multicall.py batch_full_pool_data(): d1[0:16] → d1[0:32] (ABI-encoded uint128 is 32-byte word; reading only first 16 bytes always returns zero)
  - Unified pool state source: _resolve_pool_addresses_multicall() now uses batch_full_pool_data instead of batch_liquidity; returns pool_state per entry for reuse
  - Added REJECT_COVERAGE_LOCAL_MISMATCH ("COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO") and REJECT_ALL_POOLS_TRULY_INACTIVE ("ALL_CANDIDATE_POOLS_TRULY_INACTIVE") (19 rejects total, was 17)
  - Per-pool debug: candidate_pools list in coverage_result with address, dex, fee, liquidity, activity_source, activity_drop_reason
  - Local-sim now built from coverage pool state data (reuses RPC result, eliminates redundant second call)
  - Split zero-liq gate: if coverage says active but local-sim zero → REJECT_COVERAGE_LOCAL_MISMATCH (patches coverage); if both agree zero → REJECT_ALL_POOLS_TRULY_INACTIVE
  - Consistency metrics: coverage_local_mismatch_count, truly_inactive_count, quote_reachability_rate, coverage_complete_no_quote_count
  - Added 23 new contract tests (323 total orderflow, 3059 total suite)
touched_files:
  - core/multicall.py (MODIFIED: byte-parsing fix d1[0:16] → d1[0:32] in batch_full_pool_data)
  - scripts/m7a_orderflow_replay.py (MODIFIED: unified pool state, 2 new rejects, candidate_pools debug, consistency metrics, local-sim reuse)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: +23 tests, 323 total; 7 new test classes)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.12 section, header update, test count 300→323)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py -q: PASS (323 passed in ~2s)
py -3.11 -m pytest tests/unit -q: PASS (3059 passed, 6 skipped in ~53s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (54.8s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 30 --output data/tmp/m7a_512_30b.json: PASS (2 events, 2 scored)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7a_512_300b.json: PASS (28 events, 26 scored)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_512_30b.json (30-block ws-live, 2 events, 2 scored)
  - data/tmp/m7a_512_300b.json (300-block ws-live, 28 events, 26 scored)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.A.5.12 Byte-Fix + Unified Truth

### Root Cause: batch_full_pool_data byte-parsing bug

The ROOT CAUSE of `scored_results_count=0` across M7.A.5.8-5.11 was a byte-parsing bug in `core/multicall.py`:

```python
# BEFORE (always returned 0):
liquidity = int.from_bytes(d1[0:16], "big") if s1 and len(d1) >= 16 else 0

# AFTER (correct ABI decoding):
liquidity = int.from_bytes(d1[0:32], "big") if s1 and len(d1) >= 32 else 0
```

ABI encodes `uint128` as a 32-byte word, left-padded with zeros. Reading only the first 16 bytes reads the zero-padding, always returning 0. The coverage scan used a different function (`batch_liquidity`) that decoded correctly but returned `None` on multicall failure, causing the appearance of "initialized but inactive pools."

### Change #1: Unified Pool State Source

| Aspect | M7.A.5.11 (before) | M7.A.5.12 (after) |
|--------|-------------------|-------------------|
| Coverage scan | `batch_liquidity` (correct bytes, None on failure) | `batch_full_pool_data` (fixed bytes) |
| Local-sim extraction | `batch_full_pool_data` (buggy bytes → always 0) | Reuses coverage pool_state (no second RPC) |
| Data sources | 2 independent, inconsistent | 1 canonical source |
| coverage_local_mismatch_count | N/A | **0** (unified) |

### Change #2: Split Blocker Rejects

| Condition | M7.A.5.11 reject | M7.A.5.12 reject |
|-----------|------------------|------------------|
| Coverage says active, local-sim says zero | ALL_POOLS_ZERO_LIQUIDITY | **COVERAGE_SAYS_ACTIVE_BUT_LOCAL_SIM_ZERO** (patches coverage) |
| Both agree all pools inactive | ALL_POOLS_ZERO_LIQUIDITY | **ALL_CANDIDATE_POOLS_TRULY_INACTIVE** |
| Pools found, all inactive at coverage | NO_ACTIVE_COUNTER_POOL | NO_ACTIVE_COUNTER_POOL (unchanged) |

### Change #3: Per-Pool Debug (candidate_pools)

Each coverage_result now includes `candidate_pools` with per-pool diagnostics:
- `address`, `dex`, `fee`: pool identity
- `liquidity`: actual on-chain value (e.g. `156484833388698295570863`)
- `activity_source`: "multicall_liquidity" or "fallback_assumed_active"
- `activity_drop_reason`: null (active) or specific reason

### Change #4: Consistency Metrics

| Metric | 300b value | Meaning |
|--------|-----------|---------|
| coverage_local_mismatch_count | **0** | No disagreement between coverage and local-sim |
| truly_inactive_count | **1** | 1 event had all pools genuinely inactive |
| quote_reachability_rate | **1.0** | 100% of coverage_complete=True events reached quote stage |
| coverage_complete_no_quote_count | **0** | No events lost between coverage and quoting |

### 300-Block Evidence Comparison (M7.A.5.11 → M7.A.5.12)

| Metric | M7.A.5.11 | M7.A.5.12 | Delta |
|--------|-----------|-----------|-------|
| events_count | 25 | **28** | +3 |
| scored_results_count | **0** | **26** | **+26 (BREAKTHROUGH)** |
| pre_econ_reject_rate | 1.0 | **0.0714** | -93% |
| active_coverage_rate | 0.76 | **0.9286** | +17% |
| scored_results_rate | 0.0 | **0.9286** | +93% |
| ALL_POOLS_ZERO_LIQUIDITY | 19 | 0 | eliminated |
| NO_ACTIVE_COUNTER_POOL | 2 | 0 | eliminated |
| ALL_CANDIDATE_POOLS_TRULY_INACTIVE | N/A | **1** | new (genuine) |
| GAS_EXCEEDS_GROSS | N/A | **25** | new (economics reached!) |
| STALE_POSITIVE | N/A | **1** | +1987 bps (RDNT/WETH, lag=1136) |
| TOKEN_PAIR_UNRESOLVED | 1 | **1** | stable |
| same_block_count | 25 | **2** | varies by run |
| mean_block_lag | 0.0 | **530.86** | varies by run |

### Rolling Artifact State (pre-session, not regenerated)

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 1.0
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 45
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  run_timestamp: 2026-03-27T21:30:14.342304Z
  code_identity: ts:2026-03-27T21:30:14.342304Z
  inputs.run_mode: REGISTRY_REAL
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  runs_since_timestamp.runs_count: 200
  runs_since_timestamp.data_runs_count: 200
  quick_stats.unique_pairs: 7
  quick_stats.unique_routes: 11
  quick_stats.low_sample_rate: 0.0
  quick_stats.total_net_usdc: 8621.0427
```

### Test Summary

| Test Class | Count | Status |
|------------|-------|--------|
| TestM7A512RejectConstants | 4 | PASS |
| TestM7A512CandidatePoolDebug | 3 | PASS |
| TestM7A512CoverageLocalSimInvariant | 3 | PASS |
| TestM7A512QuoteReachabilityInvariant | 3 | PASS |
| TestM7A512ConsistencyMetrics | 3 | PASS |
| TestM7A512UnscoredRejectsExpanded | 1 | PASS |
| TestM7A512BackwardCompat | 6 | PASS |
| **Total new (M7.A.5.12)** | **23** | **PASS** |
| **Total orderflow tests** | **323** | **PASS** |
| **Total all tests** | **3059** | **PASS (6 skipped)** |

## 5) Strategic Reading

1. **The 4-session measurement artifact is explained**: Sessions M7.A.5.8-5.11 all showed `scored_results_count=0` and blamed "inactive pools" or "market structure." The actual cause was a single byte-parsing bug: `batch_full_pool_data` read 16 bytes of a 32-byte ABI word, always returning zero liquidity. Pools on Arbitrum DO have real liquidity (e.g. `156484833388698295570863`). The diagnostic sharpening through those sessions was valuable but was diagnosing a measurement bug, not a market condition.

2. **Blocker has shifted from measurement to economics**: With the byte fix, 26/28 events (93%) now reach full economic scoring. The dominant reject is `GAS_EXCEEDS_GROSS: 25` — real L2 gas costs exceed the gross spread on most opportunities. This is the first time the pipeline produces genuine economic measurements.

3. **One stale positive suggests real opportunity**: RDNT/WETH showed +1987 bps net, but with block_lag=1136 (stale). This means the spread was real at that historical point. Whether such spreads recur at fresh latency is the next question.

4. **Unified truth eliminates a class of bugs**: By using `batch_full_pool_data` as the single source for both coverage and local-sim, and reusing the coverage pool state data (no second RPC call), we eliminated the divergence that caused mismatch-driven false rejects. The `coverage_local_mismatch_count: 0` confirms alignment.

5. **quote_reachability_rate = 1.0 validates the pipeline contract**: Every event where `coverage_complete=True` successfully reached the quote stage. No events were silently dropped between coverage and quoting. This is the first session where this invariant is measurable because events actually pass coverage.

## 5.1) Contract Checks
status/reasons consistency: OK (all reject reasons in ALL_REJECT_REASONS set; UNSCORED covers pre-econ rejects)
rolling discipline (3 files only): OK (_latest.json, run_summary_latest.json, m4_stability_agg.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null, evidence_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)

## 5.2) Blockers / Risks
- GAS_EXCEEDS_GROSS dominates (25/28): L2 gas costs exceed gross spread on narrow_7 pairs; need wider pair surface or lower-gas execution path
- Stale positive at +1987 bps but lag=1136: real spread may not persist at fresh latency
- mean_pipeline_latency_ms=3244: well above 250ms block time; sub-block execution remains out of reach on public RPC
- Rolling artifacts predate byte fix: next online M5 gate run will regenerate rolling with correct pool state

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
| M7.A.5.6 | **COVERAGE DECOMPOSED** (80% TOKEN_NOT_ADMITTED) |
| M7.A.5.7 | **INFRASTRUCTURE BUILT** (enrichment + oracle + local-sim) |
| M7.A.5.8 | **LIVE EVIDENCE: BLOCKER SHIFTED** (admission 100%, GAS_EXCEEDS_GROSS 100%) |
| M7.A.5.9 | **CORRECTIVE: DENOMINATION-CORRECT** (size + gas bugs fixed) |
| M7.A.5.10 | **CORRECTIVE: CONTRACT-CORRECT** (stale-gate + zero-liq + provenance fixed) |
| M7.A.5.11 | **DIAGNOSTIC: ACTIVE-COVERAGE-AWARE** (granular rejects + pre-econ metrics) |
| M7.A.5.12 | **BREAKTHROUGH: BYTE-FIX UNBLOCKS ECONOMICS** (26/28 scored, GAS_EXCEEDS_GROSS dominant) |
| M7.B | NOT STARTED (closed by M7.A verdicts) |
