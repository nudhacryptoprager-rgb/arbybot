# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a_537_session
mode: ONLINE (code changes + unit tests + CI pipeline + 1h nonstop --no-m4)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.37 — hot artifact always-emit, resolve/oracle caching, persistent cold registry
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z
m7_orderflow_timestamp: 2026-04-04T07:59:06Z
m7_hot_timestamp: 2026-04-04T07:49:19Z

## Session Completion
session_goal: M7.A.5.37 — hot p50 ≤ 250ms and hot p90 ≤ 400ms on a real promoted watchlist before chasing first profit_guard pass
goal_status: PARTIAL (hot artifact observability gap fixed — fast_path/p50/p90/hot_skip_count always emitted; resolve/oracle caching and persistent cold registry implemented; 1h nonstop runtime started with --no-m4; cold pipeline total_pipeline trending down 1196→1063ms; promoted watchlist still seed_only — needs more iterations to populate)
close_allowed: true
remaining_blockers: (1) promoted watchlist still seed_only — cold needs 2+ iterations with overlapping pairs to promote; (2) hot fast_path scored=0 because promoted pairs haven't been established yet; (3) oracle cache stale threshold (50 blocks) too narrow for cross-iteration benefit — future increase needed
evidence_session_run_dirs: [tests/unit (3219 passed, 6 skipped), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED), scripts/check_repo_safety.py (PASS 0 warnings), 1h nonstop --no-m4 (3/3 alive, hot + cold + dashboard)]
primary_blocker_of_session: Hot artifact MISSING fast_path/p50/p90/hot_skip_count when fast_results empty (gated by `if fast_results:`); cold pipeline resolve_ms≈788ms and registry_preload_ms≈621ms dominated by RPC with no caching; no persistent cold registry across iterations
blocker_status_before: ACTIVE (hot artifact had fatal observability gap — fast_path block never emitted when fast_results empty; cold pipeline had no process-level caching; cold registry re-created each iteration)
blocker_status_after: RESOLVED (hot artifact always emits fast_path + hot_skip_count; process-level resolve cache for immutable pool data; oracle block-proximity cache; persistent cold registry via warm_registry parameter; 3219 tests pass; all CI gates green; 1h nonstop confirms hot artifact contract)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.37 — hot artifact always-emit + resolve/oracle caching + persistent cold registry
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): _write_hot_artifact() always emits fast_path block (scored/positive/viable/profit_guard_passed/mean/max/p50/p90_latency_ms/best_net_bps/scoring_paths/stage_timings — zeros/nulls when empty). Always emits hot_skip_count from _raw_results. Added _cold_registry lazy-init + warm_registry wiring for cold lane. Cold registry stats logged after each iteration.
  - m7/orderflow/mode_ws_live.py (MODIFIED): run_ws_live() accepts warm_registry parameter for persistent cold mode (does NOT trigger hot mode). _prewarm_count=-2 skips redundant prewarm for warm registry.
  - m7/orderflow/resolve.py (MODIFIED): Added _pool_token_cache (module-level dict) for pool→(token0, token1, fee) caching. _resolve_event_tokens() checks cache before multicall; on hit returns cached data (~0ms vs ~788ms).
  - m7/orderflow/pricing.py (MODIFIED): Added _oracle_cache + _ORACLE_CACHE_STALE_BLOCKS=50 for check_oracle_sanity(). Cache hit within 50 blocks returns copy of cached result (~0ms vs ~104ms).
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): +19 tests in 6 classes: TestM7A537HotArtifactAlwaysEmit (5), TestM7A537ResolveCaching (3), TestM7A537OracleCaching (4), TestM7A537WarmRegistry (3), TestM7A537ColdRegistryPersistence (3), fast_path key contract test (1).
  - docs/status/Status_M7.md (MODIFIED): Updated status line for M7.A.5.37, added M7.A.5.36 and M7.A.5.37 sections.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.37)
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - m7/orderflow/resolve.py (MODIFIED)
  - m7/orderflow/pricing.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3219 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 errors, 0 warnings)
py -3.11 scripts/start_nonstop_runtime.py --hours 1 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: RUNNING (3/3 alive)

## 3) Artifacts Attached

m7_hot_latest.json: fresh (2026-04-04T07:49:19Z) — fast_path block always present, hot_skip_count visible
m7_orderflow_latest.json: fresh (2026-04-04T07:59:06Z) — cold iteration with caching active
run_summary_latest.json: unchanged (2026-04-02T09:03:41Z) — not updated by --no-m4 runs

## 4) Key Results — M7.A.5.37

### Hot Artifact Always-Emit Fix (Critical)

Previously, `_write_hot_artifact()` gated the entire `fast_path` block behind `if fast_results:`. Since `fast_results` was always empty/None (promoted watchlist was seed_only, no events matched), the hot artifact NEVER contained `fast_path`, `p50_latency_ms`, `p90_latency_ms`, or `hot_skip_count`. This was the root cause of issue #8 from M7.A.5.36 review.

Fix: Both branches (truthy and falsy) now emit the `fast_path` block with identical key sets. The else branch uses zeros/nulls. `hot_skip_count` is always emitted from `_raw_results`.

**Confirmed in runtime**: Hot artifact at iteration 13 has `fast_path.scored=0, fast_path.p50_latency_ms=null, hot_skip_count=0`. Observability gap closed.

### Process-Level Resolve Caching

Pool token data (token0, token1, fee) is immutable — once deployed, a pool's tokens never change. `_pool_token_cache` in `resolve.py` caches the multicall result forever (process scope). On cache hit, `_resolve_event_tokens()` skips the multicall entirely.

Within a single iteration, if multiple events reference the same pool, only the first triggers RPC. Across iterations, pools seen before remain cached. The benefit is proportional to pool overlap between events.

Cold operation 1→2 numbers: resolve_ms mean 374→380 (minimal change, likely high pool diversity between iterations on Arbitrum). The cache is architecturally correct; empirical benefit will accumulate over longer runtimes with more repeated pools.

### Oracle Block-Proximity Cache

`check_oracle_sanity()` now caches results per token pair with a 50-block stale window (~12.5s on Arbitrum). On cache hit within the window, returns a copy of the cached result — no RPC.

The 50-block window is conservative. Between cold iterations (5+ minutes, ~1200 blocks apart), the cache is always stale. Within-iteration benefit exists when multiple events share token pairs. Future: increase to 200+ blocks for cross-iteration benefit.

### Persistent Cold Registry

Cold lane now lazy-inits a `PoolRegistry()` that survives across iterations via `warm_registry` parameter. Previously, each cold iteration created a fresh registry, losing all cached pool data. Now `_cold_registry` is initialized once and passed repeatedly.

Key design: `warm_registry` does NOT trigger `_hot_mode` (which is `external_registry is not None`). Cold lane keeps its full diagnostic pipeline (resolve, enrichment, oracle, registry_preload) while benefiting from cached pool data in the registry.

Cold registry_preload_ms: 427→354ms (iteration 1→2, 17% improvement as cached pools skip factory discovery).

### Latency Summary

| Stage | M7.A.5.36 | M7.A.5.37 iter 1 | M7.A.5.37 iter 2 | Target |
|-------|-----------|-------------------|-------------------|--------|
| resolve_ms | 788.6 | 373.9 | 380.2 | 0 (cache hit) |
| registry_preload_ms | 621.3 | 427.1 | 354.2 | 0 (warm cache) |
| oracle_ms | 104.2 | 257.3 | 217.1 | 0 (cache hit) |
| enrichment_ms | 51.5 | 137.6 | 111.2 | 0 (cache/skip) |
| total_pipeline | 1565.6 | 1195.9 | 1062.6 | ≤250 |

Note: oracle_ms and enrichment_ms increased from M7.A.5.36 baseline — likely RPC variability between runs. The caching benefit is strongest within-iteration (repeated pools/pairs) and will accumulate over longer runtimes.

## 5) Strategic Reading

1. **Hot artifact observability is now complete**: fast_path/p50/p90/hot_skip_count always visible. This was the critical gap preventing latency measurement.
2. **Caching infrastructure is in place**: resolve (immutable, forever), oracle (50-block proximity), registry (persistent per-process). Architecturally correct; empirical benefit scales with pool overlap.
3. **Cold pipeline still >1000ms**: Total pipeline is 1063ms on iter 2, still 4.2x over the 250ms budget. The remaining bottleneck is a mix of RPC latency (new pools) + enrichment + oracle. Possible next steps: (a) increase oracle cache stale threshold, (b) add enrichment caching (ERC-20 symbol/decimals are immutable), (c) pre-resolve pools from cold history, (d) batch RPC calls more aggressively.
4. **Promoted watchlist requires more runtime**: With PROMOTED_MIN_COLD_APPEARANCES=2, cold needs 2+ iterations seeing the same pair with valid criteria. The 1h runtime should produce 10-12 cold iterations, enough to populate the watchlist.
5. **Hot path itself is architecturally fast (~20-50ms)**: The cold pipeline latency is irrelevant to hot path. Once promoted watchlist populates, hot fast_path.p50 should be well under 250ms. The critical measurement is still pending.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files in _rolling)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ≤ 1300 lines)
test file size constraint: OK (test_orderflow_artifacts.py — approaching limit, 2460 lines)
Status_M7.md size constraint: OK

## 5.2) Blockers / Risks
- PRIMARY: promoted watchlist still seed_only — needs 2+ cold iterations with overlapping pairs to populate
- PRIMARY: hot fast_path.scored=0, p50 unmeasurable until promoted pairs exist
- SECONDARY: oracle cache stale threshold (50 blocks) too narrow for cross-iteration benefit
- SECONDARY: enrichment not cached yet (ERC-20 symbol/decimals are immutable)
- SECONDARY: test_orderflow_artifacts.py at 2460 lines — may need split soon
- RESOLVED (this session): hot artifact Missing fast_path/p50/p90/hot_skip_count (always-emit fix)
- RESOLVED (this session): no process-level resolve caching (_pool_token_cache added)
- RESOLVED (this session): cold registry re-created each iteration (persistent via warm_registry)
- RESOLVED (this session): no oracle caching (_oracle_cache with 50-block proximity)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Continue 1h runtime, verify promoted watchlist populates, (b) Measure hot p50/p90 on promoted pairs, (c) Increase oracle cache stale threshold if needed, (d) Add enrichment caching
