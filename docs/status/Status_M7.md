# Status: M7 (Triangular Feasibility)

**Status**: **VERDICT READY — NO-GRADUATE** (M7.A through M7.A.5.37 + M7.R1 + M7.T1 — all scopes produce no-graduate verdicts. M7.A.5.37 fixes critical hot artifact observability gap (fast_path + hot_skip_count always emitted, even when empty), adds process-level resolve caching (pool token data immutable), oracle block-proximity cache (50 blocks), persistent cold registry via warm_registry parameter. Hot artifact contract locked: p50/p90/hot_skip_count always visible. Cold pipeline latency trending down via caching (total_pipeline mean 1195→1062ms on iteration 2+). 3219 tests pass, all CI gates green. `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`. M7.B closed.)  
**Updated**: 2026-04-04  
**Scope**: M7.A only — runtime graph sourcing, measured scoring, same-state provenance, bounded size sweep ($1-$10K), 9 canonical blocker tags, temporal repeatability, verdict summary, universe profiles (`narrow_7|expanded_10`), orderflow-driven backrun replay, live block-event scoring, ws-triggered streaming replay, two-stage multicall pruning, actual-pair token resolution, coverage decomposition, bounded enrichment, oracle sanity, local-sim state, subgraph seed (blocked), gas decomposition, stale/low-lag split, low-lag reject decomposition, low-lag debug diagnostic, pool-class truth, V2 direct resolve, low-lag watchlist, blocker tags, local-state-first pricing, factory-driven pool registry, adapter-complete pricing, gas-floor prefilter, registry activation in ws-live, low-lag registry-direct scoring bridge, pipeline latency optimization, detection-time low-lag truth, anomaly-clean headlines, wall-clock budget abort, Timeboost feasibility, profit guard fix + hot-mode fast path + stage timing, hot-lane no-fallback + execution-readiness timing, cold/hot artifact isolation + promoted watchlist + stale KPI fix. M7.B remains closed.

---

## M7.A: Triangular Feasibility — Consolidated Evidence

Steps 1-8 done. Verdict: `recommend_open_m7b: false`, `recommend_freeze_current_m7a_scope: true`.

### Evidence Summary (M7.A through M7.A.3)

| Sub-step | Scope | Runs | Best Net (bps) | Two-leg baseline | Verdict |
|----------|-------|------|----------------|------------------|---------|
| M7.A narrow_7 | 5 temporal + 10×19 sweep | 5+4 | -9.56 to -31.19 | -3.51 bps | NO-GRADUATE |
| M7.A.2 expanded_10 | +DAI/GMX/UNI → 8 nodes | 3 | -11.00 to -20.91 | -3.51 bps | NO-GRADUATE |
| M7.A.3 temporal regime | medium_activity regime | 3 | -14.16 to -26.46 | -3.51 bps | NO-GRADUATE |

**Key findings**: All cycles negative at all sizes. U-shaped cost curves (gas dominates small, slippage dominates large). 6/6 blockers stable, 0 flapping. All top cycles ARB→USDC→WETH→ARB (concentration=1.0). Route failure rate 33% (VE33/Ramses). Gross sometimes positive (+2.25 bps) but gas+fees always push net negative.

**Blocker tags** (all stable): `GROSS_NEGATIVE_CORE`, `GAS_DOMINANT_SMALL`, `SLIPPAGE_DOMINANT_LARGE`, `THIRD_LEG_FEE_BINDING`, `SINGLE_TRIPLE_CONCENTRATION`, `QUOTE_FAILURE_BREADTH_LIMIT`.

Artifacts: `data/tmp/m7a_verdict.json`, `m7a_expanded_verdict.json`, `m7a_regime_repeatability.json`.

### Caveats

Market is not static — bounded-scope verdicts do not prove absence of edge on all surfaces, chains, or regimes. L1 gas is static estimate; artifacts are `data/tmp/` provenance.

### Modules

- `engine/triangular_graph.py` — PoolEdge, PoolGraph, graph builders, universe filters
- `engine/triangular_cycles.py` — cycle discovery, `score_cycle_measured`, `classify_same_state`, SizeSweepResult
- `scripts/m7a_enumerate_cycles.py` — CLI: `--source`, `--score`, `--sweep-top`, `--universe`, `--repeatability`, `--verdict`, `--regime-repeatability`
- `scripts/m7a_orderflow_replay.py` — M7.A.4/M7.A.5 event-driven replay: `--offline`, `--replay`, `--online`, `--live-blocks N`, `--ws-live`, `--intent-scout`
- Tests: 152 in `test_triangular_*.py` (3 files), 369 in `test_orderflow_*.py` (8 files + conftest.py)

---

## M7.A.4: Orderflow-Driven Backrun/Replay Hypothesis

**Hypothesis**: Edge may emerge from event-driven replay (backrun after user trades) rather than from static AMM triangular state.

**Infrastructure**: `OrderflowEvent` (15 fields), `BackrunResult` (23 fields), `IntentSurfaceAssessment` (16 fields). 5 fixture events, offline scoring, intent scout (4 surfaces).

**Offline evidence**: 5 events, best_net=-1.55 bps (better than triangular -14.16, worse than two-leg -3.51). Intent scout: `block_event_backrun` = highest feasibility surface.

**M7.A.4 is a closed bounded baseline** for offline-estimated backrun replay.

---

## M7.A.5: Live Block-Event Backrun Replay

**Hypothesis**: `block_event_backrun` on arbitrum_one may produce viable edge with real block events and live quotes.

**Infrastructure**: `fetch_recent_swap_events()` (chunked `eth_getLogs`), `normalize_swap_log()`, `score_backrun_live()` (two-pass buy/sell via `read_quoter_v2`). `--live-blocks N` CLI.

**Evidence — M7.A.5.1 (public RPC)**: 2 runs (100/500 blocks), best_net=-18.36 bps, 0 viable, all stale (mean_lag=218), GAS_EXCEEDS_GROSS on 15/15.

**Evidence — M7.A.5.2 (Alchemy RPC)**: 100 blocks, 20 events, best_net=-19.49 bps, 0 viable, all stale (mean_lag=59.55), 0 low-lag events. Alchemy resolves correctly but sequential pipeline bakes in lag.

**M7.A.5 combined verdict**: Surface NOT VIABLE via either public or Alchemy RPC. Bottleneck is sequential block-polling architecture, not RPC provider latency.

**CI gates**: 2821 passed, 6 skipped. 85 tests in `test_orderflow_contracts.py`.

---

## M7.A.5.3–5.5: WebSocket Streaming, Multicall Pruning, Actual-Pair Resolution (CLOSED)

**M7.A.5.3** (WebSocket-Triggered Same-Block Replay): ws-live streaming architecture NOT VIABLE. Quote pipeline ~2.3s per event, 9x over 250ms block budget. All events stale. CI: 2849 passed, 113 orderflow tests.

**M7.A.5.4** (Two-Stage Multicall Pruning): NOT VIABLE. Per-call RPC latency ~400ms irreducible; closes all public RPC paths. CI: 2869 passed.

**M7.A.5.5** (Actual-Pair Token Resolution): CONFIRMED but IMMATERIAL. 100% pairs resolved but most tokens outside narrow_7. CI: 2887 passed.

---

## M7.A.5.6–5.7: Coverage Decomposition + Enrichment Infrastructure (CLOSED)

**M7.A.5.6**: 80% events rejected at `TOKEN_NOT_ADMITTED`. 5 new reject reasons (13 total), 5 new fields (42 total). CI: 2923 passed.

**M7.A.5.7**: On-chain ERC-20 enrichment, Chainlink oracle, V3 pool-state for local-sim. 3 new fields (45 total). CI: 2950 passed.

---

## M7.A.5.8: Subgraph Seed + Gas Decomposition (CLOSED)

Subgraph BLOCKED (403). Gas decomposition: L1 data ~80%, L2 exec ~20%. GAS_EXCEEDS_GROSS dominant. 4 new fields (49 total). CI: 2961 passed.

---

## M7.A.5.9–5.11: Decimal Fix + Stale Gate + Active-Liquidity Coverage (CORRECTIVE, CLOSED)

**M7.A.5.9** (Token-Decimal-Aware Size & Gas Fix): Fixed 2 bugs: decimal-aware size bounds + gas denomination. 4 new fields (53 total). CI: 2988 passed.

**M7.A.5.10** (Stale-Gate + Zero-Liq + Provenance Fix): Fixed stale-positive false viability, zero-liq pools, provenance misattribution. Added REJECT_STALE_POSITIVE, REJECT_ZERO_LIQUIDITY. CI: 3011 passed.

**M7.A.5.11** (Active-Liquidity-Aware Coverage): Active vs inactive pool distinction. Added REJECT_NO_ACTIVE_COUNTER_POOL, REJECT_ALL_POOLS_ZERO_LIQUIDITY (17 rejects). CI: 3036 passed.

---

## M7.A.5.12: Byte-Parsing Fix + Unified Coverage/Local-Sim Truth (BREAKTHROUGH)

**Root cause**: `batch_full_pool_data()` byte-parsing bug: `d1[0:16]` → `d1[0:32]`. Sole cause of scored_results=0 in M7.A.5.8-5.11. Unified pool state source. 2 new rejects (19 total). Evidence: 300b, **26 scored** (was 0), all stale. CI: 3059 passed.

---

## M7.A.5.13–5.15: Stale/Low-Lag Split + Reject Decomposition + Debug Diagnostic (DIAGNOSTIC, CLOSED)

**M7.A.5.13** (Stale vs Low-Lag Split): Fixed block_lag=0 falsy trap, low-lag counting, UNSCORED_REJECTS scope. Evidence: 300b 16 scored, best_net_bps_stale=-2.20 (beats M4). 0 low-lag scored. CI: 3077 passed.

**M7.A.5.14** (Low-Lag Reject Decomposition): 100% low-lag rejected at pre-econ stage. Multi-causal: TOKEN_PAIR_UNRESOLVED + NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE. CI: 3092 passed.

**M7.A.5.15** (Low-Lag Debug Diagnostic): Added `pair_unresolved_detail`, `low_lag_debug_rows`, `low_lag_coverage_truth`. Evidence: 300b 6 low-lag 0 scored. All `pool_read_failed`. Multi-causal blocker stack confirmed. CI: 3110 passed.

---

## M7.A.5.16–5.17: Pool-Class Truth + V2 Direct Resolve (DIAGNOSTIC + FIX, CLOSED)

**M7.A.5.16** (Pool-Class Truth): Classified low-lag pools into 3 structural classes: unsupported ABI (V2-like on V3 path), no counter-pool, inactive. Added `pool_contract_truth` field (55 total), `dex_family_guess`, 5 fine-grained `pair_unresolved_detail` causes. Evidence: multi-causal blockers (V2 ABI mismatch + NO_COUNTER_POOL + INACTIVE). CI: 3132 passed.

**M7.A.5.17** (V2 Direct Resolve): Added `pool_state_read_path` field (56 total), V2 `getReserves()` fallback bypassing `batch_token_info()` fee() revert. Evidence: V2 path implemented but 0 V2 pool events in sample windows — all low-lag hit NO_COUNTER_POOL via V3. Low-lag blocker unstable across windows. CI: 3151 passed.

---

## M7.A.5.18–5.19: Low-lag Watchlist + Blocker Tags + Quote-Fail Provenance + File Splits (DIAGNOSTIC + STRUCTURAL, CLOSED)

**M7.A.5.18** (Cross-Window Truth): Session-persistent `low_lag_watchlist` (per-pool entries across events), `blocker_tags` artifact block with 8 canonical tags. Evidence: blocker tags correctly vary per window (LOW_LAG_NONE_THIS_WINDOW in empty windows, NO_COUNTER_POOL/INACTIVE_POOL in others). 0 low-lag events scored. Still 56 fields, 19 rejects. CI: 3180 passed.

**M7.A.5.19** (Provenance + Splits): Quote-fail provenance (`quote_fail_stage/venue/exception_short` in `stage_latency`). CLI split: `cli.py` (340 lines) + `mode_ws_live.py` (854 lines). Test file split: `test_orderflow_contracts.py` → 9 files (≤995 lines), `test_triangular_contracts.py` → 3 files (≤932 lines). Still 56 fields, 19 rejects, 8 blocker tags. CI: 3183 passed.

---

## M7.A.5.20–5.22: Local Pricing + Pool Registry + Registry Activation (INFRASTRUCTURE, CLOSED)

**M7.A.5.20** (Local-State-First Pricing): `v3_math.py` — V3/V2/Algebra local swap math. First positive net observed (+18.20 bps stale). Pipeline latency halved. 3 new fields (59 total). CI: 3212 passed.

**M7.A.5.21** (Factory-Driven Pool Registry): `pool_registry.py` — factory-driven persistent cache. `preload_pair()`/`lookup_pair()` O(1). Gas-floor prefilter (2.0 bps). 6 new fields (65 total), 1 new reject (20 total). CI: 3245 passed.

**M7.A.5.22** (Registry Activation in ws-live): Session-scoped `PoolRegistry()` in pipeline. Registry 65–77 pools discovered, NO_COUNTER_POOL=0. Gas-floor operational filter. CI: 3267 passed.

---

## M7.A.5.23–5.24: Registry-Direct Scoring + Pipeline Slim (SCORING, CLOSED)

**M7.A.5.23** (Registry-Direct Scoring Bridge): Low-lag fast path bypasses coverage scan → direct local pricing from registry entries. 100% scoring rate via registry_direct. Positive net detected (9/100, +18–43 bps) but all STALE_POSITIVE. 1 new field `scoring_path` (66 total). CI: 3286 passed.

**M7.A.5.24** (Pipeline Latency Optimization): Skip Stage A multicall for registry_direct. Mid-pipeline lag abort. Session prewarm (6 core pairs). Two-queue priority. Still 66 fields. CI: 3310 passed.

---

## M7.A.5.25: Detection-Time Low-Lag Truth + PRICING_ANOMALY (CORRECTIVE, CLOSED)

Fixed low-lag accounting (detection-time vs final). +REJECT_PRICING_ANOMALY (21 total). Hidden latency telemetry: registry_preload ~372ms, oracle ~101ms. 100% same-block detection confirmed. CI: 3317 passed.

---

## M7.R1: Structural Refactor — Extract m7/ Package (COMPLETED)

Extracted all M7 logic into `m7/` package: `m7/shared/constants.py`, `m7/orderflow/` (8 modules), `m7/triangular/` (5 modules). 8th blocker tag `LOW_LAG_RPC_QUOTE_FAIL`. CI: 3180 passed.

---

## M7.T1: Test Suite Consolidation (COMPLETED)

Consolidated 14 session-specific test files into 8 stable layer-based suites + `conftest.py`. Removed 213 duplicate assertions. 368 unique orderflow tests. CI: 3104 passed.

---

## M7.A.5.26: Coverage Bug Fix (CORRECTIVE, CLOSED)

Fixed `UnboundLocalError` in zero-active-pools path. PRICING_ANOMALY gap found (47322 bps outlier). CI: 3105 passed.

---

## M7.A.5.27: Anomaly-Clean Headlines + Executable Lane Hardening (CLOSED)

`best_net_bps` excludes PRICING_ANOMALY. Wall-clock budget abort replaces RPC mid-pipeline check. New KPIs: `best_net_bps_clean`, `positive_net_count_clean`. Timeboost constants added. Evidence: 300b 6/30 positive clean (37.08 bps), 1000b 15/100 positive clean (416.7 bps), viable_count=0, 100% mid_pipeline_abort. CI: 3113 passed.

---

## M7.A.5.28–5.29: Rolling Artifact + Continuous Loop (INFRASTRUCTURE, CLOSED)

**M7.A.5.28** (KPI Contract Fix + Rolling): Unified `_is_stale()`. Canonical `m7_orderflow_latest.json`. Dashboard Panel 11. CI: 3120 passed.

**M7.A.5.29** (Continuous Loop): `m7a_orderflow_loop.py` — endless/restartable loop. Anti-bad-overwrite. Hot/cold lane split. `BLOCKER_LOW_LAG_COMPLETION_LATENCY` tag. CI: 3124 passed.

---

## M7.A.5.30: Hot Execution Lane + Latency Telemetry + Profit Guard (CLOSED)

Fixed `last_nonempty_timestamp` + `BLOCKER_LOW_LAG_REMOTE_QUOTER_LATENCY` semantics. Added `resolve_ms`/`enrichment_ms` timers + `m7a530_latency_breakdown`. Hot/cold lane split: `--lane cold` (full diagnostic) vs `--lane hot` (tight window, m7_hot_latest.json). Created `m7/orderflow/profit_guard.py` (Flashbots simple-blind-arb pattern). +11 tests. CI: 3140 passed.

---

## M7.A.5.31: Hot Lane to Decision + Profit Guard + Timeboost Eligibility (CLOSED)

Dashboard Panel 11 reads both cold + m7_hot. Discovery solved (registry_direct=30/30), viable_count=0 due to completion latency ~1544ms vs 250ms. Fixed `last_nonempty_timestamp` and `REMOTE_QUOTER_LATENCY` bugs. Latency: resolve_ms≈935, registry_preload_ms≈449, oracle_ms≈117. `run_ws_live()` accepts `external_registry` for hot lane prewarm. CI: 3155 passed.

---

## M7.A.5.32: Unified Nonstop Runtime + Rolling Retention + Hot-Path Slimming

**Hypothesis**: M7.A.5.32 = unified nonstop supervisor, rolling-only retention, hot-path reduction toward first profit_guard pass under 250ms.

**Changes**: (1) `start_nonstop_runtime.py` — unified supervisor (dashboard + start.py + M7 hot/cold). (2) `prune_tmp_artifacts.py` — retention tool for `data/tmp`. (3) Hot lane fast-path via `score_backrun_fast()` with 250ms stage budgets, zero subgraph/oracle/enrichment. (4) `score_backrun_fast()` in scoring_parallel.py: registry O(1) → cached state → local pricing → economics → BackrunResult `scoring_path="registry_fast"`. (5) HOT_BUDGET_* constants, HOT_WATCHLIST_PAIRS (3 pairs). (6) `_rolling/` cleaned to canonical 9 files. (7) +14 tests.

CI: 3163 passed, 6 skipped. Safety: PASS. ALL REQUIRED GATES PASSED.

---

## M7.A.5.33: Profit Guard Fix + Hot-Mode Fast Path + Stage Timing

**Hypothesis**: M7.A.5.33 = first profit_guard-passed hot candidate under unified nonstop runtime and <250ms hot-path budget. Discovery solved (registry_direct=29/29). Primary blocker is latency: mean_pipeline_latency_ms=1940ms vs 250ms budget. No new discovery branch.

**Critical bug fixed**: `_run_profit_guard_on_results()` read `best_buy_amount_wei`/`best_sell_amount_wei` — fields that don't exist on BackrunResult (removed in M7.A.5.32). Profit guard was dead code (`profit_guard_passed_count=0` always). Fix: derive `buy=amount_in_wei`, `sell=amount_in_wei+gross_pnl_wei` from existing fields.

**Changes**: (1) Fixed profit_guard field derivation in `m7a_orderflow_loop.py`. (2) `mode_ws_live.py`: hot-mode fast path — when `external_registry` provided, scores events via `score_backrun_fast()` first (zero-RPC), falls back to full pipeline only if pair not in registry. (3) `score_backrun_fast()`: added per-stage timing (`registry_lookup_ms`, `pool_state_ms`, `local_math_ms`, `profit_guard_ms`, `tx_build_ms`) in `pipeline_stage_latency_ms`. Integrated profit_guard directly — `profit_guard_passed` field on BackrunResult (67 total). (4) Hot artifact now reports `stage_timings` aggregate + `profit_guard_passed` count. (5) +9 tests in 4 classes. (6) DEV_REPORT provenance fixed (timestamp_utc aligned with rolling truth). (7) Status_M7.md compressed from 346→215 lines, sections reordered chronologically.

CI: 3172 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.34: Hot Lane No-Fallback + PRICING_ANOMALY Exclusion + Execution Timing

**Hypothesis**: M7.A.5.34 = first profit_guard-passed hot candidate on a tiny prewarmed watchlist under the 250ms budget. Discovery is not the primary blocker; completion latency and zero profit_guard passes are.

**Architectural change**: Hot mode in `mode_ws_live.py` no longer falls back to `score_backrun_live_parallel()` when `score_backrun_fast()` returns None. Events not in the prewarmed registry get a lightweight `hot_skip` result (~0ms) instead of the ~1330ms parallel pipeline. This cleanly separates hot lane (fast, O(1) only) from cold lane (full diagnostic).

**Changes**: (1) `mode_ws_live.py`: hot mode creates `BackrunResult(scoring_path="hot_skip", reject_reason="REJECT_NOT_IN_HOT_REGISTRY")` when fast path misses — no parallel fallback. Stores `_raw_results` in artifact for downstream. (2) `scoring_parallel.py`: PRICING_ANOMALY hard-exclude (|net_bps|>10000) in fast path. Stage 5 split into `tx_build_ms`, `calldata_ms`, `sign_or_bundle_prep_ms` (7 total stage timing keys). (3) `m7a_orderflow_loop.py`: profit guard + hot headline skip PRICING_ANOMALY. Removed redundant second fast-path re-scoring — extracts fast results from `_raw_results` directly. (4) `constants.py`: added `HOT_BUDGET_CALLDATA_MS=20`, `HOT_BUDGET_SIGN_OR_BUNDLE_PREP_MS=30`. (5) DEV_REPORT blocker-tag count 8→9. (6) +7 tests in 4 classes.

**Online evidence**: Hot loop 30 iterations (events_count=2-4, profit_guard_passed=0, viable=0) — events not in watchlist correctly skipped via hot_skip. Cold loop 3 iterations (events=22, scored=21, positive_clean=2, viable=0, best_clean=46.20 bps, latency_mean=1331ms). Cold confirms resolve_ms=643, registry_preload_ms=484 — exactly the bottleneck hot lane now bypasses entirely.

CI: 3179 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.35: Cold/Hot Artifact Isolation + Promoted Watchlist + Stale KPI Fix

**Hypothesis**: M7.A.5.35 = first profit_guard-passed hot candidate on a promoted watchlist under 250ms budget during a true 1h nonstop runtime.

**Critical bug fixed**: `run_ws_live()` unconditionally called `_write_rolling_m7()` at function end, so hot lane overwrote `m7_orderflow_latest.json` with `hot_skip` results — cold rolling artifact appeared corrupted (all events `hot_skip`, `lane=None`). Fix: `_write_rolling_m7()` only runs when `external_registry is None` (cold lane). Hot lane writes its own `m7_hot_latest.json` via outer loop.

**Changes**: (1) `mode_ws_live.py`: conditional rolling write — only cold lane writes `m7_orderflow_latest.json` internally; hot lane writes only via `_write_hot_artifact()`. (2) `m7a_orderflow_loop.py`: promoted watchlist system — `_promote_pairs_from_cold()` analyzes cold results for pairs with `size_valid_for_token=true`, `reject_reason != PRICING_ANOMALY`, and `events_with_registry > 0`; promoted pairs prewarm hot registry. (3) `artifacts.py`: added `stale_positive_count_clean` — counts stale positives that are also `size_valid_for_token=true` and not PRICING_ANOMALY; fixes KPI inconsistency (stale_pos=6 but best_stale_clean=-60 was logically incoherent). (4) `constants.py`: `PROMOTED_WATCHLIST_MIN_EVENTS=2`, `PROMOTED_WATCHLIST_MAX_PAIRS=10`. (5) +7 tests in 3 classes.

**Online evidence**: 1h nonstop runtime (3/4 processes alive — m4_scan restarts expected). Fresh cold: 28 events, 28 `registry_direct`, `stale_pos=6`, `stale_pos_clean=0`, `GAS_EXCEEDS_GROSS=22`, `STALE_POSITIVE=6`, `mid_abort=28`. No `hot_skip` contamination. Hot: `events=1`, `viable=0`, `profit_guard_passed=0`, promoted watchlist seed_only (no cold→hot promotion yet in 1st iteration).

CI: 3186 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.36: Per-Stage Hard Budget Abort + Promotion Rules + p50/p90 Tracking

**Hypothesis**: M7.A.5.36 = hot p50 ≤ 250ms, p90 ≤ 400ms on a real promoted watchlist. Speed-first: stop diagnostic work, start cutting latency numbers.

**Changes**: (1) `scoring_parallel.py`: per-stage hard budget abort in `score_backrun_fast()` — 4 individual stage aborts (registry≤25ms, pool_state≤50ms, local_math≤10ms, profit_guard≤40ms). Candidate aborted immediately on budget breach. (2) `constants.py`: zero-RPC hot path target constants (HOT_TARGET_RESOLVE_MS=0, HOT_TARGET_ORACLE_MS=0, HOT_TARGET_ENRICHMENT_MS=0, HOT_TARGET_REGISTRY_PRELOAD_MS=0). (3) `m7a_orderflow_loop.py`: p50/p90 latency tracking in hot artifact fast_path block. (4) `m7a_orderflow_loop.py`: strengthened `_promote_pairs_from_cold()` — PROMOTED_MIN_COLD_APPEARANCES=2, PROMOTED_MIN_NET_BPS=-50, anomaly hard exclude. (5) +14 tests.

**Online evidence**: 1h nonstop. Hot: profit_guard_passed=0, viable=0. Cold: mean_latency=1565ms (5.4x over 250ms budget). Breakdown: resolve_ms≈788, registry_preload_ms≈621, oracle_ms≈104, enrichment_ms≈51. Hot artifact MISSING fast_path/p50/p90 entirely (critical observability gap — gated by `if fast_results:` which was always falsy). Promoted watchlist still seed_only.

CI: 3200 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.A.5.37: Hot Artifact Always-Emit + Resolve/Oracle Caching + Persistent Cold Registry

**Hypothesis**: M7.A.5.37 = hot p50 ≤ 250ms and hot p90 ≤ 400ms on a real promoted watchlist before chasing first profit_guard pass.

**Critical bug fixed**: `_write_hot_artifact()` gated `fast_path` block behind `if fast_results:` — when empty, NO fast_path/p50/p90/hot_skip_count emitted. This was a critical observability gap: hot artifact appeared to lack speed metrics entirely. Fix: always emit `fast_path` block (zeros/nulls when empty) + always emit `hot_skip_count`.

**Changes**: (1) `m7a_orderflow_loop.py`: `_write_hot_artifact()` always emits `fast_path` block with all required keys (scored, positive, viable, profit_guard_passed, mean/max/p50/p90_latency_ms, best_net_bps, scoring_paths, stage_timings) even when fast_results is empty. Always emits `hot_skip_count` from `_raw_results`. (2) `m7a_orderflow_loop.py`: persistent cold registry `_cold_registry` — lazy-init `PoolRegistry()` on first cold iteration, passed as `warm_registry` (not `external_registry`) to avoid triggering hot mode. Registry cache survives across iterations. (3) `m7/orderflow/resolve.py`: process-level `_pool_token_cache` for pool→(token0, token1, fee) resolution. Pool tokens are immutable contract data — safe to cache forever. Cache hit skips multicall entirely (~788ms→0ms for repeated pools). (4) `m7/orderflow/pricing.py`: block-proximity `_oracle_cache` for `check_oracle_sanity()`. Cache key is token pair, stale threshold 50 blocks (~12.5s on Arbitrum). Cache hit returns copy (~104ms→0ms for repeated pairs within window). (5) `mode_ws_live.py`: `run_ws_live()` accepts `warm_registry` parameter (persistent cold mode, does NOT trigger hot mode). `_prewarm_count = -2` skips redundant prewarm. (6) +19 tests in 6 classes covering all changes.

**Online evidence**: 1h nonstop `--no-m4`. Hot: fast_path block ALWAYS present with p50/p90/hot_skip_count visible (observability gap fixed). Hot iteration 13: events=0-1, hot_skip_count=0-1, promoted watchlist seed_only. Cold: iteration 1 total_pipeline=1196ms (resolve=374, registry_preload=427, oracle=257, enrichment=138). Iteration 2 total_pipeline=1063ms (registry_preload=354, improving with warm cache). Cache benefit strongest within-iteration (repeated pools). Cross-iteration resolve cache effective for recurring pools; oracle cache stale threshold (50 blocks) too narrow for cross-iteration benefit (future: increase threshold).

CI: 3219 passed, 6 skipped. Safety: PASS (0 warnings). ALL REQUIRED GATES PASSED.

---

## M7.B: Atomic Multi-hop Execution (NOT STARTED)

Per `docs/step_M7.md`: M7.B is the execution phase, closed by default. Opens only if M7.A proves a repeatable measured edge better than two-leg thesis.
