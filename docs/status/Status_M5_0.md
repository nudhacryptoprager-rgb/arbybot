# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-19 (R28.24 — Deep pipeline analysis: phantom spread root cause identified. Filter funnel improvements (config-driven RT caps, quarantine/runtime thresholds). 37-run scan confirms GROSS is negative — slot0 ≠ QuoterV2 executable. 0 profitable RT = market efficiency, not infra bug.)
**Tests**: 1961 passed / 3 skipped
**Schema**: start:long_scan_summary:v1.14, start:hot_loop_snapshot:v1.3
**Evidence runDirs**: 37 runs (6 chains, ~587s)
**Evidence rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`
**Evidence long scan**: long_scan_latest.json @ 2026-03-19T17:17:00Z (37 runs, 587s)
**Evidence per-chain**: arb=ECONOMICS(19 pass/6 no_data/12 fail, 251 signals, gap=15.38bps, gross NEGATIVE), linea=NO_DATA, zksync=NO_DATA, base=NO_DATA, mantle=NO_DATA, scroll=NO_DATA
**Evidence timestamps**: Rolling @ 2026-03-19T17:17:00Z
**Strategy**: Full universe preserved. ROOT CAUSE confirmed: phantom spreads (slot0 price gaps collapse under QuoterV2 roundtrip). Next: expand coverage surface or pivot to intent-based routing.

---

## R28.24 Deep Pipeline Analysis + Filter Funnel

### Code Changes (7 files)
1. **strategy/jobs/run_scan_real.py** — +filter_funnel artifact, config-driven RT caps (max_candidates 20→50, top_n 5→10), +roundtrip_truth_status, +algebra auto-enable quoter_v2
2. **discovery/quarantine.py** — SUSPECT_LIQUIDITY threshold 2→5
3. **strategy/runtime_disabled.py** — per-error failure_threshold_overrides (SUSPECT_LIQUIDITY 3→5)
4. **config/onboard_base_stage2.yaml** — aerodrome ve33 excluded from base
5. **tests/unit/test_run_scan_real_purity.py** — filter_funnel test coverage
6. **tests/unit/test_runtime_disabled.py** — per-error override test coverage

### Root Cause: PHANTOM SPREADS
**Finding**: Slot0 price comparison produces apparent 100-500bps spreads between DEXes. These are NOT executable. QuoterV2 roundtrip re-quote shows GROSS PnL is deeply negative.

**Evidence** (arb truth_report, arb sweep):
- ARB/USDC: Signal=484bps spread → Sweep@$25: gross=-76.6bps, net=-81.2bps (560bps collapse)
- WETH/USDT: Sweep best@$25: net=-15.38bps (signal was positive)
- WETH/RDNT: Sweep @$25: net=-9766.8bps (completely broken pair)
- 47 spread signals generated, 16 with positive spread_minus_required, but 0 survive roundtrip

**On-chain measured costs** (NOT defaults):
- l1_cost_wei = 14,460,000,000 (vs default 60e12) — l1_cost_source=onchain
- gas_price_wei = 20,140,000 (vs default 100M)
- total_cost ≈ 15-25bps (gas=3-5bps, fee=10bps, slippage=0.5-12bps)
- **Gas is NOT the blocker. Gross PnL is negative before costs.**

### Per-Chain Status (R28.24 scan: 37 runs, 587s)
| Chain | pass | fail | no_data | signals | rq | best_rt | blocker |
|-------|------|------|---------|---------|----|---------|---------|
| arb | 19 | 12 | 6 | 251 | 70 | -15.38bps | PHANTOM_SPREAD + MARKET_EFFICIENT |
| linea | — | — | — | — | — | — | NO_DATA (coverage run) |
| zksync | — | — | — | — | — | — | NO_DATA (coverage run) |
| base | — | — | — | — | — | — | NO_DATA (coverage run) |
| mantle | — | — | — | — | — | — | NO_DATA (coverage run) |
| scroll | — | — | — | — | — | — | NO_DATA (coverage run) |

### Pipeline Funnel (arb, single run)
```
235 pool universe
 → 98 quotes fetched (137 failed: slot0 86% fail rate, runtime_disabled=61)
 → 47 spread signals (slot0 comparison)
 → 16 positive spread_minus_required
 → 7 RT candidates (pre-filter: MIN_SPREAD_MINUS=-5.0bps)
 → 0 profitable (LP_FEES_TOO_HIGH=5, NET_PROFIT_TOO_LOW=1, SLIPPAGE_TOO_HIGH=1)
 → 3 sweep routes → 0 viable
```

### Conclusion
The scanner infrastructure works correctly. The zero-profit outcome is NOT a code bug — it reflects market efficiency on mature L2 AMM surface. Slot0-based spread signals are unreliable predictors of executable profitability. Options: (1) expand to less-efficient chains/DEXes, (2) pivot to intent-based or cross-chain arb, (3) accept diagnostic-only mode for current surface.

---

## R28.23 Lead Config Audit + Regeneration

Lead personally audited and regenerated 8 config files from official sources (FusionX Mantle contracts, Scroll ecosystem docs, iZiSwap deployments). Core finding: "config debt was real and partially fixed — Mantle and Scroll were materially unblocked at config layer, but 0 profitable RT remains because the dominant blockers are now chain-specific economics and quote-path defects, not invalid YAML."

### Config Changes (lead-regenerated)
1. **config/dexes.yaml** — Added FusionX V3 for mantle (official contracts), Nuri V3 + verified Uniswap V3 for scroll.
2. **config/onboard_mantle_stage2.yaml** — 3 DEXes (agni_v3, fusionx_v3, stratum), require_cross_dex=true.
3. **config/onboard_scroll_stage1.yaml** — 3 DEXes (uniswap_v3, sushiswap_v3, nuri_v3), suspect_spread_bps_hard=500.
4. **config/onboard_base_stage1.yaml** — 3 DEXes, +VIRTUAL(0.68)/WELL(0.0045) R28.23 on-chain medians.
5. **config/onboard_base_stage2.yaml** — 4 DEXes (with aerodrome), refreshed token prices.
6. **config/onboard_arbitrum_one_candidate.yaml** — 4 DEXes, 17 token anchors with R28.23 on-chain medians.
7. **config/onboard_linea_stage1.yaml** — 2 DEXes (pancakeswap_v3, lynex_v3).
8. **config/onboard_mantle_stage1.yaml** — 1 DEX (agni_v3 only).

### Verification Results (60.5-min bundle, 240 runs)
| Chain | runs | pass | fail | signals | rq | cdx | best_rt_bps | quality | delta |
|-------|------|------|------|---------|----|-----|-------------|---------|-------|
| arb | 40 | 40 | 0 | 1163 | 172 | 8 | -21.19 | SIGNAL_PRODUCING | gap 11.65→10.62 bps |
| linea | 40 | 40 | 0 | 160 | 160 | 4 | -62.96 | SIGNAL_PRODUCING | 100% pass |
| zksync | 40 | 40 | 0 | 40 | 80 | 1 | -130.31 | SIGNAL_PRODUCING | stable |
| base | 40 | 24 | 3 | 50 | 52 | 0 | 0.0 | INFRA_READY | VE33=29 dominant |
| mantle | 40 | 0 | 35 | 35 | 39 | 1 | n/a | **SIGNAL_PRODUCING** | **0→35 signals (FusionX!)** |
| scroll | 40 | 1 | 39 | 80 | 0 | 2 | n/a | SIGNAL_PRODUCING | dead pools block RT |

### Per-Chain Blocker RCA
- **arb** (ECONOMICS): Frontier WETH/ARB @ $25, total_cost=10.38bps, but gross_pnl=-69.8bps. Spread doesn't exist — market efficient.
- **base** (QUOTE_PATH): VE33_QUOTE_FAILED=29 from aerodrome ve33 adapter. Dominant blocker prevents cross-DEX.
- **linea** (ECONOMICS): 100% pass, 4 cdx pairs. ALGEBRA_NEEDS_QUOTER=2 genuine (not config).
- **mantle** (PARTIALLY_UNBLOCKED): FusionX V3 works! agni_v3 works! stratum still broken. 2/3 DEXes active.
- **scroll** (DIAGNOSTIC): LIQUIDITY_ZERO=20, PRICE_SANITY=12. Dead sushi pools. Living pairs produce signals.
- **zksync** (ECONOMICS): Narrow surface, 1 cdx pair. best_rt=-130bps.

---

## R28.22 Live-Stream Truth Contract

R28.21-final live dashboard stream is now runtime-verified: /api/hot is lightweight and carries active chain scans plus verified pair rows. R28.22 splits the primary stream into actionable vs diagnostic/suspect:

1. **is_actionable field** (run_scan_real.py): Each live candidate now carries `is_actionable=True/False`. Actionable = `real_quote=True AND final_result != SUSPECT_ACCOUNTING`.
2. **spread_bps non-null** (run_scan_real.py): Fallback chain: `opp.spread_bps → opp.gross_spread_bps → rt.gross_pnl_bps`. spread always populated when RT data exists.
3. **final_net_pnl_usd** (run_scan_real.py): `(size_usd * net_bps) / 10000`. Operator sees USD impact.
4. **Dashboard split** (dashboard.html): "Actionable Now (Real Quotes)" table + "Diagnostic / Suspect" table. Final USD column added.
5. **_serialize_live_stream split** (start.py): `verified_pairs` = actionable only, `diagnostic_pairs` = suspect/diagnostic. Both capped at 20.

Fresh verification (30 runs, 371s): arb actionable=5/5, linea SUSPECT=2/4 correctly flagged, spread_bps populated everywhere.

---

## R28.22-cont Dashboard Operational Coherence

Lead review of R28.22 identified 10 issues centered on dashboard data contract and operational coherence. Fixes applied:

1. **WORKFLOW.md canonical run contract** (docs/WORKFLOW.md): Formalized the proven mode: external `dashboard_server.py --port 8099` + `start.py --no-dashboard`. Documented key constraints (NORMAL config updates primary rolling, coverage configs update long_scan only, Panel 0 reflects live stream).
2. **Dashboard stale banner** (dashboard.html): When primary rolling date (`run_summary.timestamp`) diverges from long_scan date (`long_scan.generated_at`), a warning banner appears: "PRIMARY ROLLING STALE". Hidden when dates match.
3. **Idle-state messaging** (dashboard.html): When `active_count=0` and no actionable/diagnostic rows or events, Panel 0 shows "No active scan right now. Start a scan to see live stream data here."
4. **Timestamp divergence resolved**: NORMAL config (`real_minimal.yaml`) included in bundle refreshes primary rolling. All 4 rolling artifacts now synchronized at 2026-03-19T10:55Z.
5. **/api/hot coherence verified**: All 6 chains present, hot_loop fresh, live_stream idle state confirmed.

R28.22 split preserved (is_actionable, spread_bps, final_net_pnl_usd, actionable/diagnostic tables).

Fresh bundle: 25 runs, 363s, 192 signals, 51 RT evaluated, 0 profitable, best=-49.56 bps.

---

## R28.22-cont-2 Per-Chain Targeted Fixes

Lead's 10-step directive: per-chain NO_USD_PRICE elimination, zombie quarantine fix, surface expansion. Core insight: "the no-profit state is chain-specific — each chain has a different root cause."

### Code Changes
1. **DEFAULT_TOKEN_USD_PRICES expanded** (strategy/quotes.py): +14 tokens (GRAIL, MAGIC, RDNT, HOLD, BRETT, cbBTC, DEGEN, TOSHI, FRAX, LUSD, USDE, JOE, DPX, WMNT, ZK, SCR, AERO, cbETH).
2. **Per-chain config prices** — arb: +GRAIL/MAGIC/RDNT, base: +cbBTC/BRETT/DEGEN/TOSHI/rETH, zksync: +HOLD/DAI.
3. **Zombie quarantine fix** (strategy/quarantine.py): `load_quarantine_state()` now resets `consecutive_failures` to 0 for records that are NOT actively quarantined. Prevents stale disk-cached failure counts from causing immediate re-quarantine across sessions.
4. **Quarantine cache cleared**: All 7 `data/cache/quarantine_state_*.json` files removed.
5. **Test added**: `test_zombie_quarantine_reset_on_load` locks the fix.

### Per-Chain Impact (FINAL — 97.7 min, 406 runs)
| Chain | Before | After | Delta |
|-------|--------|-------|-------|
| arbitrum_one | 3 NO_USD_PRICE, 50 QUARANTINED | 0 NO_USD_PRICE, 2028 signals, 284 rq, gap=11.65bps | **ECONOMICS** (closest to profit) |
| base | 7 NO_USD_PRICE, 18 QUARANTINED, 0 quotes | 54 signals, 13 rq, 4 DEXes | **CRITICAL: 0→54 signals** |
| zksync | 1 NO_USD_PRICE, 18 QUARANTINED | 68 signals, 128 rq | surface maintained |
| linea | 3 QUARANTINED, 2 ALGEBRA | 272 signals, 135 rq, 68/68 pass (100%) | **BEST chain** |
| scroll | 15 QUARANTINED, 0 rq | 134 signals, 2 cdx pairs | PARTIAL_UNBLOCK |
| mantle | 14 QUARANTINED, 0 signals | 0 signals (68 runs) | **CONFIRMED STRUCTURAL** |

### Remaining Structural Issues
- **mantle**: stratum ve33 genuinely broken — fails even with fresh quarantine. Need 3rd DEX or stratum investigation.
- **scroll**: 10+ PRICE_SANITY_FAILED from dead sushiswap pools (WBTC@6840 vs anchor@68000). Living pairs (WETH/USDC, USDC/USDT) work.
- **arb economics**: slippage 500-9900 bps on $25-150 sizes. Pool depth issue, not config.

---

## R28.21-final Code Fixes

Critical performance fixes based on Lead's post-verification directive:

1. **Multicall Batch Chunking** (core/multicall.py):
   - Problem: arb multicall 100% failure rate (1175 calls batched, all failed → individual RPC fallback → 64.6s).
   - Fix: `MULTICALL_MAX_BATCH=200`, `_execute_multicall()` now chunks and continues on partial failure.
   - Result: arb quote_rpc_ms 64.6s → 32.4s (50% reduction), multicall 0% failure.

2. **Roundtrip Contamination** (strategy/jobs/run_scan_real.py):
   - Problem: best_net_pnl_bps=-10012 bps leaking from diagnostic signals.
   - Fix: (a) symmetric sane filter `SANE_RT_PNL_MIN=-500`, (b) `abs()` in sweep outlier filter, (c) diagnostic-only exclusion in `roundtrip_eligible()`.
   - Result: best_net_pnl_bps now -55.39 bps (clean).

3. **USD Price Anchors** (strategy/quotes.py + config/real_minimal.yaml):
   - Problem: NO_USD_PRICE rejects for GNS, PENDLE, RETH, TBTC, EZETH, STONE.
   - Fix: Added 11 token prices to DEFAULT_TOKEN_USD_PRICES and real_minimal.yaml.

4. **Algebra Quoter Timeout** (strategy/quotes.py):
   - Fix: Reduced timeout 10s → 5s (matches QuoterV2), improves RPC headroom.

---

## Architecture Contract (R28.21 — unchanged)

> **Static-looking scans are caused by cache-backed discovery and a tiny surviving route surface; live-market target requires real-time quote refresh plus event-driven hot re-quote, not full registry RPC refresh every cycle.**

Live scanning operates with THREE refresh cadences:
1. **QUOTES/BLOCKS** (live RPC every cycle) — ✅ Working. `real_quote_count > 0` on signal-producing chains.
2. **HOT RE-QUOTE** (event-driven target) — ❌ Timer-based (`FULL_SWEEP_INTERVAL=5`), not WebSocket event-driven. `ws_connected=0`.
3. **REGISTRY/DISCOVERY** (periodic cold refresh) — ❌ Cache-backed (`pools_from_rpc=0` for all chains), no TTL.

**Artifact visibility (R28.21)**: `last_full_refresh_utc`, `last_hot_requote_utc`, `pools_from_cache`, `pools_from_rpc` now exposed in per_chain stats and hot_loop/long_scan artifacts.

---

## Core Truth Statement

> **M5_0 is mandatory for CI and infra-proof.**
> M5_0 validates artifact schemas/invariants, multicall, failover, provenance.
> M4 execution gate is a separate "core truth" for profit.
> **R28.21**: Lead post-R28.20 audit directive (10 issues, 10 fix steps). (1-3) Architecture contract documentation: quotes=live RPC, hot-requote=timer-based (not event-driven), registry=cache-backed (no TTL). (4) Cache freshness fields added: last_full_refresh_utc, last_hot_requote_utc, pools_from_cache/rpc in per_chain stats + hot_loop + long_scan. (5) real_live_probe.yaml schema fixed: dict-style dexes → string list, base_tokens/quote_tokens → pairs list. 13/13 validate_universe PASS. (6-8) Chain-specific notes documented (linea/zksync/scroll route variation, mantle surface, scroll gating strict). (9-10) Docs updated. Schema bumps: long_scan_summary v1.14, hot_loop_snapshot v1.3. Fresh 36-run scan confirms all chains cache-backed (rpc=0).
> **R28.20**: Lead post-verification directive (10 issues, 10 fix steps). (1) warm_pool_cache: Unicode→ASCII status icons for Windows, multicall batch fallback to per-pool on decode failure. (2) start.py: PermissionError resilience for hot_loop_latest.json writes (try/retry/fallback/pass). (3) strategy/artifacts.py: reject_histogram + reject_samples in truth_data (reason→count dict, top 10 rejects). (4) strategy/artifacts.py: actionable_signals_count excludes is_diagnostic_only signals. (5) ci_m5_0_gate.py: signals_count uses actionable_signals_count with fallback. (6) start.py: last_reject_histogram propagation to per-chain stats → long_scan. (7) mantle config: R28.20 objective (restore signal flow), WETH_WMNT anchor, quarantine clear instructions. (8) scroll config: STRUCTURAL_DEBUG status, truth_mode_m42, execution safety flags. (9) Fresh 54-run online verification: 0 profitable RT confirmed, mantle quarantine cleared → re-accumulated 4 genuine failures (structural confirmed), scroll 18 diagnostic/0 actionable. 1948 tests, CI green.
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

## Chain Quality Classification (R28.20 — fresh 54-run online evidence)

```
arbitrum_one:   SIGNAL_PRODUCING / PRIMARY_BLOCKER (primary, rolling, 7 xdex, rq=37, prt=0/37, best_net=-47.26bps, economics blocker)
                rejects: NOTIONAL_DRIFT_EXCLUDED=31, SUSPECT_LIQUIDITY=21, PRICE_SANITY_FAILED=19
base:           SIGNAL_PRODUCING / PRIMARY_BLOCKER (stage2, rq=1, prt=0/6, 3/9 NO_DATA, QUARANTINED=19)
                rejects: QUARANTINED=19, NO_USD_PRICE=8, VE33_QUOTE_FAILED=3
linea:          SIGNAL_PRODUCING / PRIMARY_BLOCKER (discovery, rq=18, prt=0/36, best_net=-94.81bps, 3 xdex, 100% pass)
                rejects: NO_USD_PRICE=3, QUARANTINED=3, ALGEBRA_NEEDS_QUOTER=2
mantle:         NO_DATA / CANDIDATE (probe-only, rq=0, sig=0, structural: quarantine cleared → re-accumulated 4 genuine failures)
                rejects: QUARANTINED=13, NOTIONAL_DRIFT_EXCLUDED=4
scroll:         FAIL / CANDIDATE (structural-debug, sig=18 diagnostic / 0 actionable, mixed-source gated, 2 xdex)
                rejects: QUARANTINED=16, NOTIONAL_DRIFT_EXCLUDED=2
zksync:         SIGNAL_PRODUCING / PRIMARY_BLOCKER (discovery, rq=9, prt=0/9, best_net=-420.61bps, 1 xdex)
                rejects: QUARANTINED=19, NOTIONAL_DRIFT_EXCLUDED=10, NO_USD_PRICE=1
```

**R28.20 changes**: Fresh 54-run online evidence with R28.20 code fixes (reject histograms, actionable_signals_count, mantle quarantine clear). total_profitable_roundtrips=0 confirmed. Reject histograms now visible per chain in truth artifacts + long_scan. Mantle quarantine cleared → re-accumulated 4 genuine stratum failures (structural confirmed, not stale data). Scroll 18 diagnostic signals correctly excluded from actionable count.

**Rollout Queue (R28.20 — fresh evidence, no chain is positive control)**:
1. **arbitrum_one** (primary contractual) — PRIMARY_BLOCKER. best_net=-47.26 bps, rq=37, prt=0. Economics blocker. gap-to-zero=18.71 bps.
2. **linea** — PRIMARY_BLOCKER. rq=18, prt=0, best_net=-94.81 bps. Strongest signal producer after arb. Clean sane filter result.
3. **zksync** — PRIMARY_BLOCKER. rq=9, prt=0. best_net=-420.61 bps. Deeply negative.
4. **base** — PRIMARY_BLOCKER. rq=1, 3/9 runs NO_DATA, QUARANTINED=19. Thin evidence.
5. **mantle** — CANDIDATE. 0 signals, 0 rq. Structural: quarantine cleared, re-accumulated 4 genuine stratum failures. Needs 3rd DEX or stratum pool health fix.
6. **scroll** — CANDIDATE. 18 diagnostic signals, 0 actionable. Mixed-source gated. QUARANTINED=16. Structural.

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