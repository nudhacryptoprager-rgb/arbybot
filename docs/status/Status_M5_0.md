# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-18 (R28.19 — best_net_pnl_bps sane filter fix, regression tests, reject visibility in truth artifacts. 1948 tests.)
**Tests**: 1948 passed / 3 skipped
**Schema**: see DEV_REPORT_LATEST.md (long_scan_summary + hot_loop_snapshot schemas bumped in R28.17)
**Evidence runDirs**: long_scan 43 runs 6 chains 578s (R28.18 post-fix scan, still canonical)
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`
**Evidence long scan**: `data/runs/_rolling/long_scan_latest.json` (43 runs 578s, total_profitable_roundtrips=0, executable_profitable=0 all chains, signals=288, rq=56)
**Evidence per-chain**: arb=PRIMARY_BLOCKER(rq=28), zksync=PRIMARY_BLOCKER(rq=13), base=PRIMARY_BLOCKER(rq=1), linea=PRIMARY_BLOCKER(rq=14), mantle=CANDIDATE(rq=0), scroll=CANDIDATE(rq=0)
**Strategy**: Full universe preserved, staged chain onboarding via configs/adapters (R27). Config inventory frozen to 19 active files (R28.15: +1 real_live_probe.yaml).

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> **R28.19**: Lead review fixes. (1) best_net_pnl_bps sane filter fix in run_scan_real.py — previously used unfiltered max(roundtrip_results), now uses sane_rts (≤500 bps). If all insane → None. Prevents base 8.2e16 bps contamination. (2) +8 regression tests locking the contract: profitable_count=0 must never coexist with absurd positive best_net_pnl_bps. Tests cover scanner sane filter, start.py secondary guard, classify_chain_profit_state SUSPECT_ACCOUNTING. (3) Reject visibility in truth_report roundtrip_summary: added candidates_total, gated_by_economics, rejected_reasons, suspect_profitable_count. Makes reject pipeline visible in truth artifacts for failing chains. (4) Truth reclassification confirmed: no chain is CONFIRMED_POSITIVE_CONTROL — all are PRIMARY_BLOCKER or CANDIDATE. Classification is purely dynamic, no hardcoded overrides. (5) Scroll quote-truth confirmed structural: 2 DEXes adequate (9/13 cross-dex), but all pools dead or drift-excluded → 0 surviving quotes. Not a code bug. (6) Mantle structural deficit confirmed: 2 DEXes, cross-dex pairs drift-excluded. Needs 3rd DEX or drift fix. 1948 tests, CI green.
> **R28.18**: Code fixes for scroll price-truth blocker + promotion contract enforcement + fresh 10-min online evidence. (1) strategy/quotes.py: slot0 anchor unification — replaced independent lookup_anchor_price_ci() with upstream anchor_price from anchor_manager. Root cause of scroll PRICE_SCALE violations. (2) strategy/quotes.py: slot0 LIQUIDITY_ZERO secondary gate. (3) start.py: promotion contract enforcement (ONE_LEG_ONLY_DIAGNOSTIC/FAIL_QUALITY → capped at THIN_POSITIVE). (4) start.py: logger NameError fix. (5) Configs: scroll/mantle tightened. 1940 tests. 43-run scan: signals=288, rq=56, executable_profitable=0.
> **R28.17**: Truth-quality discipline. SUSPECT_ACCOUNTING state added to classify_chain_profit_state — chains with profitable roundtrips but absurd best_net_pnl_bps (outside ±500 bps) are blocked from CONFIRMED_POSITIVE_CONTROL. Base had best_net_pnl_bps=8e16 (accounting contamination) → will be SUSPECT_ACCOUNTING on fresh scan. Accumulation guard: update_chain_stats rejects insane PnL values. Scanner: suspect_profitable_count tracks filtered roundtrips. 3-tier signal classification in kpi_separation: diagnostic_signals / real_quote_signals / executable_profitable (replaces old 4-tier). COVERAGE truth-path parity: removed lightweight skip for dynamic_sweep + preflight_evidence — all run_kinds now evaluated equally. Rolling protection: hot_loop_snapshot with is_test_session marker. Only linea is true positive control (rq=12, prt=12). +5 tests (1937 total). Schema bumps: long_scan_summary + hot_loop_snapshot (see DEV_REPORT for versions).
> **R28.16**: Phase-level visibility in live stream. Scanner child process (run_scan_real.py) emits structured `ARBY_PHASE:` JSON lines on stdout for 6 phase boundaries (discovery_started/finished, quote_started/finished, preflight_finished, gate_finished). Parent (start.py run_gate_once) parses these and pipes into hot_loop_latest.json live_stream as `phase:*` events. Dashboard badges for phase transitions + severity/reason detail column. Lightweight `/api/hot` endpoint (serves only hot_loop_latest.json vs full /api/rolling). Pair-hot-queue pending count surfaced in live_stream KPIs. +6 tests (1932 total). System remains batch-hot — phases confirm operational visibility within long child runs, not instant-hot trading.
> **R28.15**: Scan stack is productive in simulate-only mode, but live-profit metrics remain blocked because execute_live/simulate_rpc were not yet wired into the operational scanner path until this round. Now wired as dormant probe (gated by config — all production configs keep execution_enabled=false). Real PreTradeSimulator and DexDexExecutor implemented + tested (38 new tests, 1926 total). Live execution probe block in run_scan_real.py: pick best candidate → simulate_rpc() → check signer → log. config/real_live_probe.yaml ready for first live test. Artifacts: truth_data now includes live_execution field, kill_switch_active/execution_enabled are config-driven. The next milestone is realized execution truth — tx submission, receipts, and realized PnL — not further reinterpretation of paper profit.
> R28.14: Benchmark chain formalized — merit-based selection: linea is current benchmark (14 profitable RT, ALIGNED, is_benchmark=true). Unified truth standard: truth_standard_met + is_benchmark per chain. Forbidden version strings removed from Status files. Fresh scan: 42 runs 371s, benchmark_chain=linea. Arb gap=3.25 bps best-ever (approaching breakeven). quote_rpc_ms: arb 5.6s (was 14.6s), linea 8.1s, base 22s. +2 tests (1888). Arbitrum remains contractual primary truth path, but linea is currently the strongest aligned positive control. Next milestone: unified truth-standard across all chains + event-driven hot-loop speed.
> R28.13: Truth contract alignment (ALIGNED vs POSITIVE with quality_healthy — no hidden contradictions). hot_loop_latest.json schema bump with run_context provenance, session link, truth KPIs per chain, micro_requote counters. Truth KPIs surfaced at 4 levels (metrics, frontier_ranking, hot_loop, truth_path_alignment). Dashboard Panel 0 "Hot Loop Live". PairHotQueue: 54 pairs loaded, drain+micro-quote between Phase 1 and Phase 2. Cross-pair parallel quoter prefetch: quote_rpc_ms reduced 8x (base 180s→22s). Schema bumped (additive). Fresh scan: 42 runs 384s, linea ALIGNED/CONFIRMED_POSITIVE_CONTROL (14 profitable RT), base POSITIVE/THIN (3 RT, quality issues).
> R28.12: Event queue DirtySetTracker (pending_chains/drain_event/mark_clean), hot_loop_latest.json (fast-refresh artifact), cross-pair parallel quotes (shared 16-worker TPE), WS block pass-through (ARBY_WS_BLOCK_NUMBER env var skips block-pin RPC), truth_path_alignment section (BLOCKED/POSITIVE/NOT_PROVEN/ALIGNED per chain). System is still batch-hot — WS invalidates but does not yet trigger immediate executable re-quote. Schema bump (additive). +16 tests (1886). Fresh scan: 30 runs, 10 full/20 hot, linea CONFIRMED_POSITIVE_CONTROL (10 profitable RT), base THIN_POSITIVE (7 RT).
> R28.11 Turn 2: Hot re-quote loop + WebSocket dirty-set invalidation. Dual-cycle architecture: every FULL_SWEEP_INTERVAL=5 scans per chain does full discovery, others use cached pairs from `data/cache/hot_pairs_{chain}.json` (reduces RPC calls and latency). `DirtySetTracker` subscribes to WebSocket `eth_subscribe newHeads` — chains only re-scanned when dirty (new block). If WSS not connected, chain is always dirty (safe fallback). Dashboard "Hot Loop" table shows per-chain mode/full_sweeps/hot_requotes. Addresses Lead directive: "Розвести два цикли: full sweep і hot re-quote loop. Використати WebSocket не як 'галочку', а як trigger для dirty-set invalidation."
> R28.11 Turn 1: Pair-level dashboard visibility. _pair_history (5 runs), Delta column for spread_bps changes, Cache Freshness table (pools_from_cache/rpc/rpc_calls), Suppression Counters table (6 types), 2-decimal bps precision. Guardrails: STATIC_PROBE_PATH, ZERO_FEE_DOMINANCE.
> R28.10: Profit truth propagation — real_quote_count + profit_realism_status now flow through full chain: truth_report → run_summary.metrics → rolling_store → long_scan. Chain profit state classification (5 states). KPI separation: signals ≠ exec_candidates ≠ profitable_roundtrips ≠ truth_confirmed. RCA: linea profits from lynex_v3 0-fee pools; arb blocked by 100-3000 bps fee structure + $150 paper_size slippage amplification. **NOTE (R28.19)**: R28.10's claim "CONFIRMED_POSITIVE_CONTROL (linea, base)" is stale — R28.17/R28.18 truth audit reset all chains to non-profitable.
> R28.7: Economics engine correctness — executable_candidates_count KPI (replaces signals_count as primary), min_spread_bps advisory in truth_mode (threshold=0), dynamic_sweep promoted to core decision layer, per_route_breakdown in artifacts (slippage/fee/gas decomposition). ARB/WETH re-enabled (SUSPECT_SPREAD_HARD gates >500bps). Gap narrowed 18→15 bps. Long scan: 42 runs, 109 signals, $123, 21 profitable RT. Linea truth=True (positive control confirmed).
> R28.6: RunDir collision fix — chain-scoped unique dirs (`ci_m5_gate_{chain_key}_{YYYYMMDD}_{HHMMSS}_{microseconds}`) with `exist_ok=False`. 6 pre-fix collisions (zksync 324 + base 8453) → 0 post-fix in parallel stress test (31 runs). Chain_id validation in start.py. Telemetry: report_ms=63 (was 0). Lead: "R28.5 speed gain is provisional until parallel runDir uniqueness/provenance integrity is fixed" → FIXED.
> R28.5: Bounded parallel coverage (`--coverage-workers N` in start.py), expanded phase metrics (8 fields), phase_timers artifact fix (computed before write_artifacts), COVERAGE dynamic_sweep skip. Long scan: 37 runs / 52 signals / $85.88 / 12 profitable roundtrips in 556s wall (~15s/run vs ~27s R28.4).
> R28.4: Scanner performance optimization — shared Web3 cache (`_shared_w3_cache` in quotes.py), parallel quote prefetch (ThreadPoolExecutor, 8-way), COVERAGE lightweight mode (skip daily_report + preflight), inter-chain sleep 20→1s, phase_timers_ms in scan stats, multicall latency accounting fixed. Per-run scan time reduced from ~66s to ~27s (2.5x). Long scan: 21 runs / 43 signals / $68.28 / 9 profitable roundtrips in 563.6s wall.
> R27.4: Config layer audit — 15 stale YAMLs deleted, inventory frozen to 16 active files with TestConfigInventoryGuard. validate_universe.py regression FIXED (is_strict_run used before defined). ve33 adapter IMPLEMENTED (dex/adapters/ve33.py + registry). Fresh online evidence: ci_m5_gate_20260314_211452 (4 signals, $5.55).
> R27.3: Scanner pipeline contract hardening — removed synthetic suspect metrics, strict discovery_runtime, intent forbidden for NORMAL, unified economics, pre-scan validation wired. +7 tests.
> R27.2: Rolling contamination FIXED — NORM-only guard in m4/gates.py prevents COVERAGE/SMOKE runs from overwriting pointer files. check_repo_safety detects contamination (check [20]). +7 regression tests. Fresh online evidence: arb primary + 4-DEX candidate + scroll stage1 + long scan (6 chains, 8 runs, $23.49).
> R27.1: Online proof — arb 4-DEX candidate PASS (14 signals, $14.61, dexes_active=4), scroll stage1 PASS (3 signals, $0.14, nuri_v3 quoter_v2 confirmed).
> R27: Strategy shift — full universe preserved, staged chain onboarding via `onboard_<chain>_stageN.yaml` configs. Scroll nuri_v3 contract mismatch fixed (was incorrectly classified as algebra, actually uniswap_v3/quoter_v2). Coverage matrix: `docs/ONBOARDING_MATRIX.md`.
> R26: `run_context.run_timestamp` added to long_scan; frontier_ranking enriched with triage fields (status, route_health, blocker_reasons).
> R25: `discovery_coverage` now populated from scan_*.json stats; `_warn_missing_chains()` is FATAL.

---

## Chain Quality Classification (R28.18 — fresh evidence)

```
arbitrum_one:   SIGNAL_PRODUCING / PRIMARY_BLOCKER (primary, rolling, 6 pairs, rqc=24, prt=0, best_net=-80.54bps, diag=133, economics blocker)
base:           INFRA_READY / PRIMARY_BLOCKER (stage2, rqc=1, prt=0, NO_DATA, accounting_sane=True on fresh data)
mantle:         NO_DATA / CANDIDATE (probe-only, rqc=0, signals=0, structural cross-DEX deficit: 4/12 pairs, stratum +0, all 4 cdx pairs drift-excluded)
zksync:         SIGNAL_PRODUCING / PRIMARY_BLOCKER (discovery, rqc=10, prt=0, best_net=-191.44bps)
linea:          SIGNAL_PRODUCING / PRIMARY_BLOCKER (discovery, rqc=8, prt=0, best_net_pnl=4576bps SUSPECT — 204x amplification vs spread_gap=22.39bps)
scroll:         FAIL / CANDIDATE (accepted-fail, rqc=0, signals=0, PRICE_SCALE violations: WBTC/USDC + WETH/USDC inverted direction)
```

**R28.18 changes**: Fresh online evidence with R28.17 guards. total_profitable_roundtrips=0 across all chains. Linea reclassified from CONFIRMED_POSITIVE_CONTROL to PRIMARY_BLOCKER (204x accounting amplification caught by SANE_RT_PNL_MAX=500). base accounting clean on fresh data. Per-chain blockers identified: arbitrum/zksync=economics, base=NO_DATA, linea=accounting anomaly, mantle=structural surface, scroll=quote-truth.

**Rollout Queue (R28.19 — truth audit reset, no chain is positive control)**:
1. **arbitrum_one** (primary contractual) — PRIMARY_BLOCKER. best_net=-42.85 bps, rq=28, prt=0. Economics blocker.
2. **linea** — PRIMARY_BLOCKER. rq=14, prt=0. Was "benchmark" in R28.14 — R28.17 SANE_RT_PNL_MAX=500 guard exposed 204x accounting anomaly (best_net_pnl=4576 was unfiltered).
3. **zksync** — PRIMARY_BLOCKER. rq=13, prt=0. best_net=-180.55 bps. Deeply negative.
4. **base** — PRIMARY_BLOCKER. rq=1, 5/7 runs NO_DATA. Thin evidence.
5. **mantle** — CANDIDATE. 0 signals, 0 rq. Structural cross-DEX deficit (4 pairs all drift-excluded). Needs 3rd DEX or drift fix.
6. **scroll** — CANDIDATE. 0 signals, 0 rq. Quote-truth blocker (adequate surface 9/13 cross-dex, but all pools dead/broken). Structural.

**Onboard Stage Configs (R27+R28.2)**:
- `config/onboard_arbitrum_one_candidate.yaml` — 4-DEX additive (uni+sushi+camelot+pancakeswap)
- `config/onboard_zksync_candidate.yaml` — 2-DEX candidate (uni+pancakeswap)
- `config/onboard_base_stage1.yaml` — 3-DEX stage1 (uni+sushi+pancakeswap, aerodrome excluded)
- `config/onboard_base_stage2.yaml` — 4-DEX stage2 (stage1 + aerodrome ve33) [NEW R28.2]
- `config/onboard_mantle_stage1.yaml` — 1-DEX stage1 (agni_v3 only, stratum excluded)
- `config/onboard_mantle_stage2.yaml` — 2-DEX stage2 (agni_v3 + stratum ve33) [NEW R28.2]
- `config/onboard_linea_stage1.yaml` — 2-DEX stage1 (pancakeswap+lynex, algebra stability test)
- `config/onboard_scroll_stage1.yaml` — 2-DEX stage1 (sushi+nuri, cross-DEX test)

**Universe Split (R28 — formalized in docs/WORKFLOW.md)**:
- **config** (production probe): arbitrum_one (real_minimal.yaml, target_for_truth_probe=true)
- **discovery_runtime** (canonical successor): base, linea, mantle, zksync (onboard_*.yaml)
- **monitoring_only**: scroll (nuri_v3 re-enabled R27, accepted-fail=true)

**R27.2 online verification**:
- arb primary: ci_m5_gate_20260314_192514, PASS, 4 signals, $5.62 (NORMAL, rolling refreshed)
- arb candidate: ci_m5_gate_20260314_192713, PASS, 87 quotes, cross_dex=27, 14 simulations (4-DEX)
- scroll stage1: ci_m5_gate_20260314_193000, PASS, 3 signals, nuri_v3 confirmed (rolling NOT overwritten — NORM-only guard)
- long scan: ci_m5_gate_20260314_193819 (arb final), 6 chains, 8 runs, 17 signals, $23.49

**R27.2 code changes**:
- `m4/gates.py`: NORM-only rolling pointer policy — non-NORMAL runs skip writing pointer files
- `check_repo_safety.py`: check [20] rolling chain purity (validates run_kind=NORMAL + chain_key=arbitrum_one)
- `test_rolling_chain_keys.py`: +7 regression tests (4 pointer protection + 3 chain purity)
- ONBOARDING_MATRIX: camelot_v3+nuri_v3 "pending"→"verified" with runDir evidence
- onboard_scroll_stage1.yaml: PURPOSE softened, nuri_v3 VERIFIED

**R27.1 online verification**:
- arb candidate: ci_m5_gate_20260314_101735, PASS, 14 signals, $14.61, dexes_active=4, cross_dex=27
- scroll stage1: ci_m5_gate_20260314_102036, PASS, 3 signals, $0.14, dexes_active=2, cross_dex=8
- nuri_v3 quoter_v2 CONFIRMED: 3 cross-DEX signals on scroll (1 PASS ≠ exit from ECOSYSTEM_BLOCKED)

**R27 key changes**:
- Strategy: full universe preserved, staged onboarding via `onboard_<chain>_stageN.yaml` configs
- Scroll nuri_v3 contract mismatch FIXED (dexes.yaml=uniswap_v3/quoter_v2, was excluded as algebra)
- Coverage matrix: `docs/ONBOARDING_MATRIX.md` — chain/dex/adapter/quoter/blocker
- Adapter readiness tests: +48 tests (per-chain adapter/factory/quoter validation)
- ve33 gap explicitly documented (base/aerodrome, mantle/stratum)
- `base roundtrip_profitable=2` is COVERAGE evidence, NOT promotion evidence

**R27.4 config audit**:
- validate_universe.py: FIXED — is_strict_run/run_kind moved above intent check block (R27.3 regression)
- 15 stale YAMLs deleted: coverage_intent_* (6), real_debug, real_expanded, real_hunting, real_hunting_lowfee, real_nonstop, real_test_coverage, real_minimal_discovery_runtime, real_minimal_intent_forced, real_scan_linea_smoke
- real_m5_0_golden.yaml: MOVED to docs/artifacts/golden/ (golden fixture, not a scanner config)
- Active inventory frozen: 6 registry + 4 primary/probes + 6 onboard = 16 files
- TestConfigInventoryGuard: ALLOWED_YAML_FILES (16 entries) + 2 tests (no unexpected + all exist)
- ve33 adapter: dex/adapters/ve33.py (Ve33Adapter class), registered in dex/registry.py
- All 10 scanner configs pass validate_universe
- Online verification: ci_m5_gate_20260314_211452, PASS, 17 quotes, 4 signals, 3 cross-dex
- Tests: 1803 passed, 3 skipped (-2 net: removed hunting tests, added inventory/adapter tests)

**R27.3 code changes**:
- `strategy/jobs/run_scan_real.py`: removed _compute_sanity_rejects() (synthetic suspect fabrication), replaced with _extract_suspect_from_rejects() (real data only); discovery_runtime strict-by-default; intent/intent_forced forbidden for NORMAL/COVERAGE; strategy_mode/same_dex_only encoded in stats; pre-scan validate_universe wired; paper_slippage_bps passed to opportunity_engine
- `engine/opportunity_engine.py`: paper_slippage_bps parameter (was hardcoded 5.0)
- `scripts/validate_universe.py`: intent forbidden for strict run_kinds, same_dex_mode warning
- `tests/unit/test_suspect_provenance.py`: +7 tests (extract/purity validation)

**Long scan (R28.6)**: REFRESHED — parallel (workers=2): 31 runs / 69 signals / $116.34 / 14 profitable roundtrips (wall_seconds=544). Serial (workers=1): 25 runs / 53 signals / $80.18 / 12 profitable RT (wall_seconds=543). Pass chains: arbitrum_one, zksync, base, linea. **0 runDir collisions** in parallel (was 6 in R28.5).
**Profit truth (R28.19)**: All chains non-profitable under SANE_RT_PNL_MAX=500. executable_profitable=0 across all 6 chains. R28.18 truth audit reset all chains. Linea reclassified from CONFIRMED to PRIMARY_BLOCKER (204x accounting anomaly).

---

## Per-Chain Discovery Coverage (R26)

| Chain | Pairs Evaluated | Pairs Resolved | Cross-DEX | Skipped Excluded |
|-------|-----------------|----------------|-----------|------------------|
| zksync | 15 | 4 | 3 | 11 |
| base | 18 | 10 | 10 | 6 |
| mantle | 14 | 10 | 0 | 3 |
| linea | 17 | 12 | 0 | 0 |
| arbitrum_one | n/a | n/a | n/a | n/a (config) |
| scroll | blocked | blocked | blocked | blocked |

---

## Terminology Contract

| Metric | Source | Meaning |
|--------|--------|---------|
| `quotes_total` | `scan.json stats.quotes_total` | All quote requests attempted |
| `quotes_fetched` | `scan.json stats.quotes_fetched` | Quotes successfully received |
| `infra_gate` | `gate_result.json status` | Artifacts valid, schema OK, quotes_fetched > 0 |
| `run_summary.status` | `run_summary.json status` | Signal flow: NO_DATA/FAIL/PASS |
| `signals_count` | `run_summary.json metrics.signals_count` | Raw spread signals detected |
| `ChainQualityLevel` | `m4/policy.py` | INFRA_READY / SIGNAL_PRODUCING / QUALITY_RAISED |
| `cross_dex_pairs_count` | `gate_result.json` | Unique DEX pairs with buy_dex != sell_dex |

**IMPORTANT**: `infra_gate: PASS` != `run_summary.status: PASS`. Infra gate validates infrastructure; run_summary shows actual opportunity flow.

---

## Rolling Discipline

**PRIMARY_ROLLING_CHAIN**: `arbitrum_one`

| Rule | Behavior |
|------|----------|
| `--refresh-rolling` + non-primary chain | **FAIL** with error |
| Auto-enable `refresh_rolling` + non-primary | **BLOCKED** |
| Non-NORMAL run_kind (COVERAGE/SMOKE) | **SKIP** pointer file writes (R27.2 NORM-only guard, m4/gates.py) |
| check_repo_safety check [20] | **FAIL** if run_kind!=NORMAL or chain_key!=arbitrum_one in pointer files |

Rolling triplet: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json}`

---

## Canonical Commands

```powershell
# Offline gate (deterministic, no secrets)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict

# Online gate (requires RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1

# Online with rolling refresh
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling --refresh-rolling-strict --prune-keep 50

# Unit tests
py -3.11 -m pytest tests/unit -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

---

## Invariants Validated by Gate

| # | Invariant |
|---|-----------|
| 1 | `execution_enabled=false` (always in M5_0) |
| 2 | `current_block` consistent across artifacts |
| 3 | `chain_id` consistent across artifacts |
| 4 | `run_mode` consistent across artifacts |
| 5 | `quotes_total` consistent (scan == truth) |
| 6 | `schema_version` supported |
| 7 | No sentinel blocks (online only) |

---

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | PASS |
| 1 | FAIL validation |
| 2 | FAIL missing artifacts |
| 3 | FAIL scanner error |

---

## Schema Versions

| Artifact | Version | Notes |
|----------|---------|-------|
| scan | `3.2.0` | M5 family |
| truth_report | `3.2.0` | M5 family |
| reject_histogram | `3.2.0` | reject samples (not aggregated counts) |
| long_scan_summary | `LATEST` | R26: run_context provenance + frontier triage fields |

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m5_0_gate.py` | M5_0 acceptance gate |
| `scripts/ci_full_pipeline.py` | Full CI pipeline |
| `core/artifact_invariants.py` | Cross-artifact validation |
| `start.py` | Multi-chain orchestrator |

---

## Relationship to M5/M4

| Milestone | Focus | Gate |
|-----------|-------|------|
| M5_0 | Infrastructure hardening | `ci_m5_0_gate.py` |
| M5 | Production features | `ci_m5_gate.py` |
| M4 | Execution layer | `ci_m4_execution_gate.py` |

---

## Current Blockers (R28.19)

- **All chains**: executable_profitable=0 across all 6 chains. No chain qualifies as positive control.
- **Arb gap**: best_net=-42.85 bps (improved from -80.54). Primary blocker is market economics, not code.
- **Linea**: 14 rq, 0 prt. Was "benchmark" in R28.14 — accounting anomaly (204x amplification) filtered by SANE_RT_PNL_MAX=500.
- **zksync**: 13 rq, 0 prt, best_net=-180.55 bps. Deeply negative economics.
- **Base**: 1 rq, 5/7 NO_DATA. RPC stability or pool coverage issue.
- **Mantle**: 0 signals. Structural cross-DEX deficit — 4 pairs all drift-excluded. Needs 3rd DEX or drift fix.
- **Scroll**: 0 signals. Quote-truth blocker — adequate surface but all pools dead/broken. Structural issue, not code bug.