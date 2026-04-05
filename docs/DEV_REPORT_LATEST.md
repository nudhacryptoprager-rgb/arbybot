# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a_538_session
mode: ONLINE (code changes + unit tests + CI pipeline + 0.25h nonstop --no-m4)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.38 — session-scoped caching, enrichment cache, latency budget hit rate
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z
m7_orderflow_timestamp: 2026-04-04T09:21:43Z
m7_hot_timestamp: 2026-04-04T09:22:33Z

## Session Completion
session_goal: M7.A.5.38 — latency_budget_hit_rate >= 0.80 in 15-minute nonstop runtime via session-scoped caching
goal_status: PARTIAL (latency_budget_hit_rate peaked at 0.80 on warm-cache iteration, settled to 0.72 as new pairs appeared. Total pipeline mean 866→275-290ms warm. Enrichment fully cached (96→7ms). Oracle cross-iteration caching effective (245→15-55ms). Registry stale refresh eliminated within session. Remaining latency from cold-start new-pair discovery — structural, not cacheable.)
close_allowed: true
remaining_blockers: (1) latency_budget_hit_rate 0.72 < 0.80 target on final iteration (new pair cold-start pulls rate down); (2) promoted watchlist still seed_only; (3) resolve_ms ≈ 94ms for new pools (fallback probe path expensive)
evidence_session_run_dirs: [tests/unit (3228 passed, 6 skipped), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED), scripts/check_repo_safety.py (PASS 0 warnings), 0.25h nonstop --no-m4 (3/3 alive, 0 restarts)]
primary_blocker_of_session: Oracle/registry/enrichment caches too narrow for cross-iteration benefit (50-block oracle, 200-block registry). Cold pipeline 866ms mean. latency_budget_hit_rate 0.19.
blocker_status_before: ACTIVE (oracle 50-block threshold expired between iterations; no enrichment cache; registry_preload refreshed every iteration; total_pipeline 866ms; latency_budget_hit_rate 0.19)
blocker_status_after: RESOLVED (oracle 5000-block threshold covers full 20-min session; enrichment cached forever; registry 5000-block threshold prevents refresh within session; total_pipeline 275-290ms warm; latency_budget_hit_rate 0.72-0.80; 3228 tests pass; all CI gates green)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.38 — session-scoped caching + enrichment cache + latency budget hit rate
change_summary:
  - m7/orderflow/resolve.py (MODIFIED): Added _enrichment_cache (module-level dict) for immutable ERC-20 symbol/decimals data. enrich_tokens_batch() checks cache before RPC multicall; only uncached addresses go to batch_symbol()/batch_decimals(). Successfully enriched entries cached forever.
  - m7/orderflow/pricing.py (MODIFIED): _ORACLE_CACHE_STALE_BLOCKS 50→5000 (5000 blocks ≈ 20 min on Arbitrum). Covers multi-iteration reuse within 0.25h sessions.
  - m7/orderflow/pool_registry.py (MODIFIED): __init__ accepts stale_threshold_blocks parameter (default=10, backward compatible). preload_pair() uses self.stale_threshold_blocks instead of hard-coded 10.
  - scripts/m7a_orderflow_loop.py (MODIFIED): Cold registry init PoolRegistry(stale_threshold_blocks=5000) — diagnostic lane state refresh only after 5000 blocks, effectively never within a 15-min session after initial warmup.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Fixed 2 broken assertions (oracle 50→5000, cold registry init). +9 tests in 4 classes (TestM7A538EnrichmentCaching, TestM7A538OracleThreshold, TestM7A538RegistryStaleThreshold).
  - docs/status/Status_M7.md (MODIFIED): Updated status line for M7.A.5.38, added M7.A.5.38 section.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.38)
touched_files:
  - m7/orderflow/resolve.py (MODIFIED)
  - m7/orderflow/pricing.py (MODIFIED)
  - m7/orderflow/pool_registry.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3228 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 errors, 0 warnings)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.25 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: COMPLETED (3/3 alive, 0 restarts, 15 min wall)

## 3) Artifacts Attached

m7_hot_latest.json: fresh (2026-04-04T09:22:33Z) — loop_iteration=73, events_count=3, promoted_watchlist seed_only
m7_orderflow_latest.json: fresh (2026-04-04T09:21:43Z) — cold iteration 5, events=25, scored=24, latency_budget_hit_rate=0.72
run_summary_latest.json: unchanged (2026-04-02T09:03:41Z) — not updated by --no-m4 runs

## 4) Key Results — M7.A.5.38

### Enrichment Cache (resolve.py)

ERC-20 symbol and decimals are immutable contract data — safe to cache forever. Added `_enrichment_cache: Dict[str, dict]` at module level. `enrich_tokens_batch()` splits input addresses into cached vs uncached; only uncached go to RPC. Successfully enriched entries (symbol not None) stored; failed enrichment not cached (retryable).

**Effect**: enrichment_ms dropped from 96ms (M7.A.5.37) → 7ms (warm iteration 5). On fully-warm iterations: 0ms. Remaining ~7ms from new tokens appearing in later iterations.

### Oracle Session-Scoped Cache (pricing.py)

`_ORACLE_CACHE_STALE_BLOCKS` increased from 50 → 5000 (5000 blocks ≈ 20 min on Arbitrum). Previously, the 50-block window (~12.5s) expired between cold iterations that take 3+ minutes each, meaning every token pair re-queried Chainlink every iteration. With 5000 blocks, the cache covers the entire 15-min session after first warm-up.

Oracle is explicitly "sanity guardrail, not execution truth" — 20-minute staleness is acceptable for a diagnostic lane. Hot lane (when live) uses fresh block state anyway.

**Effect**: oracle_ms dropped from 245ms (M7.A.5.37) → 15ms (warm iteration 3). On iteration 5: 55ms (new pairs appearing). Cross-iteration reuse now effective.

### Configurable Registry Stale Threshold (pool_registry.py + m7a_orderflow_loop.py)

`PoolRegistry` now accepts `stale_threshold_blocks` parameter (default=10, preserving hot lane behavior). Cold lane uses `stale_threshold_blocks=5000` — pool state refresh only after 5000 blocks (~20 min), effectively never within a 15-minute session after the first iteration's cold start.

Previously with the default threshold of 10 blocks (~2.5s), every pair triggered `_refresh_state()` on every iteration because cold iterations span 700+ blocks. With 5000 blocks, the refresh trigger never fires within a session.

**Effect**: registry_preload_ms dropped from 327ms (M7.A.5.37) → 121-133ms (warm iterations). Remaining cost is from NEW pairs not previously queried (factory discovery + first state read).

### Latency Budget Hit Rate

| Metric | M7.A.5.37 | M7.A.5.38 Iter 1 | M7.A.5.38 Iter 3 | M7.A.5.38 Iter 5 |
|--------|-----------|-------------------|-------------------|-------------------|
| total_pipeline.mean (ms) | 866 | 893 | **275** | **290** |
| resolve_ms.mean | 197 | 296 | 109 | **94** |
| enrichment_ms.mean | 96 | 63 | 30 | **7** |
| oracle_ms.mean | 245 | 114 | **15** | 55 |
| registry_preload_ms.mean | 327 | 421 | **121** | 133 |
| latency_budget_hit_rate | **0.19** | 0.36 | **0.80** | **0.72** |

Iteration 1 is always cold-start (all caches empty). Iteration 3 shows peak performance with warm caches (all previously-seen pairs hit cache). Later iterations have slightly higher means as new pairs appear (cold-start cost for discovery).

## 5) Strategic Reading

1. **latency_budget_hit_rate 0.19 → 0.80 (peak), 0.72 (steady)**: The primary session target. Caching infrastructure delivers 3x pipeline speedup for warm-cache pairs. The gap between 0.72 and 0.80 comes from new-pair cold-start cost (factory discovery + first RPC for unknown pools). This is structurally irreducible without pre-warming.
2. **Enrichment fully cached**: 96ms → ~0ms for known tokens. The enrichment cache is the cleanest win — immutable data, no staleness concern, zero ongoing cost after first enrichment.
3. **Oracle and registry now session-scoped**: Both caches now cover the entire session (~20 min window). No cache expiration within a 15-min nonstop run. This eliminates the per-iteration refresh that was the dominant bottleneck in M7.A.5.37.
4. **New-pair discovery is the remaining cost**: resolve_ms (94ms) and registry_preload_ms (133ms) are dominated by RPC calls for pairs NOT seen in previous iterations. Possible mitigation: pre-resolve all intent.txt pairs at session startup, pre-warm pool registry for known pairs.
5. **Promoted watchlist still seed_only**: Zero profit_guard passes, zero hot-path executions. The next session should focus on (a) pre-warming caches at session start for all configured pairs, (b) understanding why cold-to-hot promotion hasn't triggered.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files in _rolling)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ≤ 1300 lines)
test file size constraint: OK (test_orderflow_artifacts.py ≈ 2640 lines, approaching limit)
Status_M7.md size constraint: OK

## 5.2) Blockers / Risks
- PRIMARY: latency_budget_hit_rate 0.72 < 0.80 on steady-state (new pairs pulling rate down)
- PRIMARY: promoted watchlist still seed_only — zero profit_guard passes
- SECONDARY: resolve_ms ≈ 94ms for new pools (fallback probe path expensive, ~579ms max)
- SECONDARY: registry_preload_ms ≈ 133ms for new pairs (factory discovery)
- SECONDARY: test_orderflow_artifacts.py at ~2640 lines — may need split soon
- RESOLVED (this session): enrichment not cached (now fully cached, 96→7ms)
- RESOLVED (this session): oracle cache too narrow (50→5000 blocks, 245→15-55ms)
- RESOLVED (this session): registry refresh every iteration (now 5000-block threshold)
- RESOLVED (previous): hot artifact missing fast_path (always-emit fix)
- RESOLVED (previous): no resolve caching (_pool_token_cache, immutable)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Pre-warm all configured pairs at session startup, (b) Investigate cold-to-hot promotion criteria, (c) Measure latency_budget_hit_rate over longer runtimes
