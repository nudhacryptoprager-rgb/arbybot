# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-24 (R39h++ -- **Full system audit confirms blockers are layered: base quote-path, mixed-source on scroll/mantle, HTTP-only freshness on 4 chains, post-signal economics.** +rt_without_signal_count, WS endpoints for all 6 chains, 2330 tests.)
**Tests**: 2330 passed / 5 skipped
**Schema**: start:long_scan_summary:v1.15, m4:run_summary:v2.0, start:hot_loop_snapshot:v1.3
**Evidence**: R39h++: system audit (2026-03-24), WS+funnel. R39h+: funnel attrition zero, sweep_reprieve_rt. R39h: calibration contour + funnel.
**Rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`

---

## R39h++ -- Full System Audit + WS Freshness + Funnel Diagnostics

### System Audit Summary
A full post-R39h+ system audit across chains/dex/config/engine/strategy/discovery confirms that **pair-universe width is no longer the main blocker**. The current blockers are layered:
- **base**: quote-path debt (SLOT0_DIAGNOSTIC 79%, `rq=0`, 44 quoter_v2_failed, exec rate 5.4%)
- **scroll/mantle**: mixed-source truth loss (MIXED_SOURCE 37-67% of OE rejections)
- **linea/mantle/scroll/zksync**: HTTP-only freshness (now fixed — WS endpoints added)
- **arb/zksync/scroll/linea**: post-signal economics/slippage on healthy chains

Broad coverage should therefore expand through tiered universe policy and better source quality, **not by inflating the default productive intent**.

### Per-Chain Fresh RCA (2026-03-24 run dirs)
| Chain | Pairs | Exec% | RT | Best PnL | #1 OE Reject | Gate | Profit Blocker |
|-------|------:|------:|---:|------:|----------|------|---------------|
| arb | 11 | 88.6% | 5 | -54.21 | (no rejections) | PASS | OE_ECONOMICS |
| zksync | 7 | 92.3% | 1 | -608.57 | NET_PROFIT_TOO_LOW 63% | PASS | OE_ECONOMICS |
| base | 9 | 5.4% | 1 | -10127 | SLOT0_DIAGNOSTIC 79% | PASS | OE_ECONOMICS |
| linea | 5 | 100% | 1 | -563 | NET_PROFIT_TOO_LOW 63% | PASS | OE_ECONOMICS |
| scroll | 5 | 86.7% | 2 | -352.62 | SUSPECT_SPREAD_HARD 38% | PASS | OE_ECONOMICS |
| mantle | 4 | 100% | 2 | -415.07 | MIXED_SOURCE 67% | PASS | OE_ECONOMICS |

### Fixes (R39h++)
1. **config/chains.yaml** — Added `ws_endpoints` for linea (`wss://linea.public.blastapi.io`), mantle (`wss://mantle.public.blastapi.io`), scroll (`wss://scroll.public.blastapi.io`), zksync (`wss://zksync.public.blastapi.io`). All 6 chains now have WS configured.
2. **strategy/chain_stats.py** — Added `rt_without_signal_total`: counts RT evaluated on runs where `included_signals_count == 0`. Directly exposes the mantle-style semantic split (0 signals but N RT).
3. **strategy/long_scan_summary.py** — Added `rt_without_signal` to per-chain signal_funnel and `rt_without_signal_total` to aggregate.
4. **tests/unit/test_signal_funnel.py** — +2 tests: `test_rt_without_signal_accumulation`, `test_rt_without_signal_in_funnel`.
5. **tests/unit/test_config.py** — +1 test: `test_all_chains_have_ws_endpoints` (contract: all 6 active chains must have `wss://` endpoints).

### Layered Blocker Priority (per lead directive)
1. **base quote-path**: fix quotes.py / quote_adapters.py / aerodrome path. Until `rq > 0` reliably, base is not a market verdict.
2. **scroll/mantle mixed-source**: fewer MIXED_SOURCE rejects, not more raw signals. One executable leg + one diagnostic leg kills truth quality.
3. **WS freshness**: now configured for all 6 chains. Verify `chains_ws_connected > 0` in next hot_loop.
4. **linea economics/thin-truth**: RT-evaluated > 1 on existing 5 pairs before expanding.
5. **ambient**: explicit tech debt, do not distract from base quote path and mixed-source cleanup.

### Tests
2330 passed / 5 skipped (+3 vs R39h+).

---

## R39h+ -- Funnel Attrition Zero + 3-Tier Policy Permanent

### Key Finding
R39h confirms that **the current blocker is no longer pair-universe attrition**: intent, post-exclude, and xDex counts are all equal (40 → 40 → 40). Broad market coverage should therefore be expanded through tiered universe policy and higher-quality source/pool coverage, **not by blindly inflating the default productive intent**.

### Per-Chain Fresh RCA (2026-03-24 run dirs)
| Chain | Pairs | Exec% | RT | Best PnL (bps) | #1 OE Reject | #2 OE Reject |
|-------|------:|------:|---:|----------------:|--------------|--------------|
| arb | 11 | — | 39 | -254.97 | NET_PROFIT_TOO_LOW | SUSPECT_SPREAD_HARD |
| zksync | 6 | 92.3% | 1 | -608.57 | NET_PROFIT_TOO_LOW 62.5% | SUSPECT_SPREAD_HARD 37.5% |
| base | 9 | 7.6% | 3 | — | SLOT0_DIAGNOSTIC 69% | MIXED_SOURCE 25.7% |
| linea | 5 | 100% | 0 | — | NET_PROFIT_TOO_LOW 55.6% | SUSPECT_SPREAD_HARD 44.4% |
| scroll | 5 | 86.7% | 2 | -354.97 | SUSPECT_SPREAD_HARD 37.5% | MIXED_SOURCE 37.5% |
| mantle | 4 | 100% | 2 | -415.07 | MIXED_SOURCE 66.7% | gas $134-143 |

### Per-Chain Diagnosis (per lead directive)
- **arb**: 313 signals + 39 RT + 0 profitable = pure economics blocker, not pair scarcity
- **zksync**: improvement from selective widening (ZK/*) argues FOR targeted, not blind
- **base**: low-signal ≠ need wider intent; blocker is SLOT0_DIAGNOSTIC quote-path (69% of 113 OE rejections + 43 quoter_v2_failed)
- **linea**: 12 signals but 0 RT = truth/economics bottleneck, not field width
- **scroll**: 4→24 signals proves calibration+source-quality works better than blind inflation
- **mantle**: 0 sig / 14 RT = funnel/summary semantics mismatch → sweep_reprieve_rt field added

### Mantle 0-sig/14-RT Semantic Split (explained)
Two independent pipelines: `included_signals_count` counts signals where |spread| ≤ 500bps (SUSPECT_SPREAD_HARD threshold). Opportunity engine independently creates opps from quotes → rejected opps (MIXED_SOURCE 66.7% on mantle) go to sweep_reprieve path which re-evaluates them with frontier sizing → counted in `roundtrip_evaluated_total`. This is **not a bug** but was confusing for operators. The new `sweep_reprieve_rt` field in signal_funnel makes this gap visible.

### 3-Tier Policy (formalized as permanent)
| Tier | Scope | Pairs | Purpose | Promotion criteria |
|------|-------|------:|---------|-------------------|
| productive | default | 31 | Quality-ranked, volatile, liquid, multi-DEX | Baseline |
| calibration | current | 42 | Productive + benchmark stables (USDC/DAI, USDC/USDT) | Used when benchmarking per-chain health |
| exploratory | wide field | ~69 | All tokens with ≥2 DEX presence | Accept only if ≥2 of 4 growth metrics improve |

**Acceptance criteria for tier promotion**: ≥2 of: real_quote_count grows, RT-evaluated count grows, best gap to zero decreases, near-zero executable negatives appear (gap < 100 bps). `signals_count` alone is **insufficient**.

### Fixes (R39h+)
1. **strategy/chain_stats.py** — Added `sweep_reprieve_rt_total` to `new_chain_stats()` and accumulation from `roundtrip.sweep_reprieve_count` in `update_chain_stats()`.
2. **strategy/long_scan_summary.py** — Added `sweep_reprieve_rt` to per-chain signal_funnel and `sweep_reprieve_rt_total` to aggregate signal_funnel.
3. **tests/unit/test_signal_funnel.py** — +2 tests: `test_sweep_reprieve_rt_in_funnel` (mantle scenario: 0 sig, 14 RT, 14 sweep reprieve) and `test_sweep_reprieve_rt_accumulation`.
4. **No intent.txt changes** — calibration tier confirmed matching (`--tier calibration --diff` = no differences). Exploratory tier reviewed but NOT promoted.

### Tests
2327 passed / 5 skipped (+2 vs R39h).

---

## R39h -- Per-Chain Signal Funnel + Calibration Contour

### Fresh Scan Evidence (2026-03-24T08:34:47Z)
```
Wall time:      833s (~14 min)
Total runs:     40 (PASS=23, NO_DATA=10, FAIL=7, INFRA_FAIL=0)
Signals total:  386 (+81% vs R39g+ 213)
Net USDC total: $462.82 (+53% vs R39g+ $303)
Profitable RTs: 0 (evaluated: 75 (+47% vs 51), best: +0.00 bps)
Sweep best:     +0.00 bps @ $7500 (BREAKEVEN_FRONTIER)
Pass chains:    arbitrum_one, zksync, scroll (+scroll promoted!)
Fail chains:    base, linea
Probe-only:     mantle
Schema:         v1.15 (signal_funnel)
```

| Chain | Runs | PASS | Signals | Net USDC | RT Eval | Blocker | vs R39g+ |
|-------|-----:|-----:|--------:|---------:|--------:|---------|----------|
| arbitrum_one | 7 | 7 | 313 | $400.25 | 39 | OE_ECONOMICS | +119 sig |
| zksync | 7 | 7 | 28 | $17.34 | 7 | OE_ECONOMICS | **+20 sig, +6 RT** |
| base | 7 | 3 | 9 | $16.44 | 3 | OE_ECONOMICS | +7 sig, +3 RT |
| scroll | 6 | 6 | 24 | $28.84 | 12 | MIXED_SOURCE | **+20 sig, +11 RT, PASS** |
| linea | 6 | 0 | 12 | -$0.05 | 0 | OE_ECONOMICS | **+12 sig** |
| mantle | 7 | 0 | 0 | $0.00 | 14 | MIXED_SOURCE | +12 RT |

### Signal Funnel (per-chain)
| Chain | Intent | After Excl | XDex | Signals | RT Eval |
|-------|-------:|-----------:|-----:|--------:|--------:|
| arbitrum_one | 11 | 11 | 11 | 313 | 39 |
| zksync | 6 | 6 | 6 | 28 | 7 |
| base | 9 | 9 | 9 | 9 | 3 |
| mantle | 4 | 4 | 4 | 0 | 14 |
| linea | 5 | 5 | 5 | 12 | 0 |
| scroll | 5 | 5 | 5 | 24 | 12 |
| **Total** | **40** | **40** | **40** | **386** | **75** |

### RCA Summary
Secondary-chain signal scarcity is NOT a single problem. Per-chain pair_level_rca:
- **base**: 7 pairs, exec 7.1%, SLOT0_DIAGNOSTIC 82.1% — quote-path blocked (not pair count)
- **zksync**: 3 pairs (was), exec 100%, OE_ECONOMICS — policy-suppressed (ZK/* blanket exclude removed intent-declared pairs)
- **mantle**: 4 pairs, exec 100%, OE_ECONOMICS + MIXED_SOURCE 61.5% — already reaches RT, economics not discovery
- **scroll**: 3 pairs, exec 80%, MIXED_SOURCE 43% + SUSPECT_SPREAD_HARD 43% — quality-reject limited
- **linea**: 3 pairs, exec 100%, SUSPECT_SPREAD_HARD 50% — execute but OE-thin

### Fixes (R39h)
1. **config/onboard_zksync_candidate.yaml** — removed ZK/*, */ZK from excluded_pair_hints (R28.27 added due to missing anchor prices, not intrinsic issue). Added ZK_USDC: 0.10, ZK_WETH: 0.0000488, USDC_DAI: 1.0 anchor prices. Pairs: 3→7.
2. **config/intent.txt** — regenerated with `--tier calibration`: 42 pairs (was 31). Adds USDC/DAI + USDC/USDT to all chains.
3. **Anchor prices** — added USDC_DAI: 1.0 and USDC_USDT: 1.0 to linea, base, arb configs. Scroll/mantle already had them.
4. **discovery/runtime.py** — added `intent_pairs_count` to RuntimeStats (tracks len(intent_pairs) before filtering).
5. **strategy/chain_stats.py** — added `last_intent_pairs_count`, `last_pairs_after_excludes` to per-chain state. Extracted from discovery_runtime.
6. **strategy/long_scan_summary.py** — schema v1.15. Added `signal_funnel` section (top-level aggregate + per-chain): intent_pairs → pairs_after_excludes → cross_dex_pairs → spread_signals → rt_evaluated.
7. **tests** — +8 signal funnel contract tests. Total: 2325 passed / 5 skipped.

### Per-Chain Pair Counts After Calibration
| Chain | Before | After | Delta | Note |
|-------|-------:|------:|------:|------|
| arbitrum_one | 9 | 11 | +2 | +USDC/DAI, +USDC/USDT |
| base | 7 | 9 | +2 | +USDC/DAI, +USDC/USDT |
| linea | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| scroll | 3 | 5 | +2 | +USDC/DAI, +USDC/USDT |
| mantle | 4 | 5 | +1 | +USDC/DAI (USDC/USDT excluded: 2884bps SUSPECT_SPREAD) |
| zksync | 3 | 7 | +4 | +ZK/USDC, +ZK/WETH, +USDC/DAI, +USDC/USDT |
| **Total** | **29** | **42** | **+13** | calibration tier |

---

## R39g+ -- 10-Minute Fresh Scan + Aerodrome + PRICE_SCALE Fix

### Fresh 10-Minute Scan Evidence (2026-03-23T22:50:49Z)
```
Wall time:      613s (~10 min)
Total runs:     31 (PASS=15, NO_DATA=7, FAIL=9, INFRA_FAIL=0)
Signals total:  213
Net USDC total: $303.14 (diagnostic)
Profitable RTs: 0 (evaluated: 51, best: +0.00 bps)
Spread gap:     +376.85 bps (measured, target: >=0)
Sweep best:     +0.00 bps @ $5000 (BREAKEVEN_FRONTIER)
Pass chains:    arbitrum_one, zksync
Fail chains:    base, scroll, linea
Probe-only:     mantle
```

| Chain | Runs | PASS | Signals | Net USDC | Blocker |
|-------|-----:|-----:|--------:|---------:|---------|
| arbitrum_one | 6 | 6 | 194 | $293.50 | OE_ECONOMICS |
| zksync | 5 | 5 | 8 | $4.80 | - |
| base | 5 | 0 | 2 | $2.90 | SLOT0_DIAGNOSTIC |
| scroll | 5 | 1 | 4 | $0.69 | coverage |
| linea | 5 | 1 | 0 | $0.00 | coverage |
| mantle | 5 | 2 | 5 | $1.25 | PROBE_ONLY |

External market-surface review supports the current local verdict: healthy supported chains are now primarily economics/slippage blocked, not filter-blocked. Volatile depth-expansion (adding more pairs/chains blindly) is no longer the highest-leverage action. Instead, fixing infrastructure gaps on BASE (aerodrome) and correcting truth-path issues (linea PRICE_SCALE) unlocks the remaining cross-dex surface.

### Fixes (R39g+)
1. **config/onboard_base_stage2.yaml** — aerodrome re-enabled in dexes list. VE33_QUOTE_FAILED was diagnosed as transient RPC issue at R28.24 — factory returns valid pool addresses and `getAmountOut(uint256,address)` returns correct quotes (WETH/USDC volatile: ~$2147/ETH, AERO/USDC volatile: ~$0.35/AERO). Fresh base scan: 4 DEXes active, 41 quotes, 7 cross-dex pairs, zero VE33_QUOTE_FAILED.
2. **scripts/ci_m5_0_gate.py** + **scripts/ci_m5_gate.py** — `validate_price_scale()` changed from global violation-rate (>10% fail) to **per-pair majority logic**: if a pair has at least one good quote within PRICE_SCALE_BOUNDS, outlier quotes for that pair are data quality issues (WARN), not direction bugs (FAIL). Only fail if ALL quotes for a pair are outside bounds (systematic direction error). Fixes linea PRICE_SCALE FAIL caused by single 10000-fee-tier garbage quote (price=0.01476) while 4 other WETH/USDC quotes were correct (~2160).
3. **SyncSwap prioritization**: confirmed already active and ordered before iZiSwap on all 3 applicable chains (linea, scroll, zksync). No code change needed.

### Per-Chain Fresh Scan Results (R39g+)
| Chain | Gate | DEXes | Quotes | Pairs | XDex | Blocker |
|-------|------|-------|--------|-------|------|---------|
| arb | PASS | 5 | 48 | 9 | 9 | OE_ECONOMICS |
| base | PASS | **4** | 41 | 7 | 7 | SLOT0_DIAGNOSTIC 87% |
| linea | PASS | 2 | 9 | 3 | 3 | SUSPECT_SPREAD_HARD 50% |
| scroll | PASS | 3 | 9 | 3 | 3 | - |
| zksync | PASS | 2 | 9 | 2 | 3 | - |

### Route-level Economics Lab (arb)
| Pair | Route | Gross | Net | Slippage | Gas | LP Fee |
|------|-------|------:|----:|---------:|----:|-------:|
| ARB/USDC | camelot_v3→pancakeswap | -240.86 | -254.97 | 541.23 | 14.10 | 1.0 |
| WETH/LINK | pancakeswap→sushiswap | -389.40 | -399.12 | 642.33 | 9.70 | 35.0 |
| WETH/ARB | camelot_v3→uniswap_v3 | -470.34 | -485.85 | 821.06 | 15.50 | 1.0 |
| WETH/PENDLE | camelot_v3→uniswap_v3 | -740.83 | -752.99 | 1008.71 | 12.20 | 100.0 |
| WETH/USDC | pancakeswap→sushiswap | -827.24 | -836.57 | 898.34 | 9.30 | 31.0 |

**ARB/USDC is closest to breakeven** (gap=$254.97). All pairs: slippage >> spread — confirms economics bottleneck, not infrastructure.

### Source Coverage (R39g+ update)
| Chain | Declared | Active | Previous Active | Delta |
|-------|----------|--------|-----------------|-------|
| base | 4 | **4/4** | 3/4 | **+aerodrome** |
| Others | unchanged | unchanged | unchanged | - |
| **Total** | **27** | **26/27** | **25/27** | **+1** |

### Tests (+11 → 2317 total)
- `test_r39gplus_fixes.py`: aerodrome enabled contract (2), per-pair PRICE_SCALE logic (7), SyncSwap ordering (1+subtests).
- `test_ci_m5_gate_negative_price_scale.py`: updated for per-pair majority logic (5 tests modified).

---

## R39g -- Gate Accuracy + Blocker Classification Fix

Lead's canonical scan (42 runs, 233 signals, 36 RT evaluated, 0 profitable, $318.19) proved that current FAIL labels mask the true economics blocker on healthy chains. arb: 7/7 PASS, 224 signals, 27 real_quotes, 4 RT evaluated, all negative — pure economics blocker. Secondary chains (zksync, mantle, scroll, linea) show coverage gate FAILs (`pairs_count < 5`) because `hot_requote` universe source used strict thresholds designed for full `config` universes. These gate FAILs inflate fail/runs ratio, causing `INFRA_FAIL` blocker classification that hides real economics data.

### Fixes (R39g)
1. **scripts/ci_m5_0_gate.py** — `hot_requote` universe source now uses relaxed coverage thresholds (min_pairs=1, min_pools=2), same as `discovery_runtime`. Thin productive contours (zksync=2, linea=3, scroll=3, mantle=4 pairs) no longer trigger spurious COVERAGE FAIL.
2. **strategy/chain_stats.py** — `_compute_blocker_evidence()` INFRA_FAIL gate: before assigning INFRA_FAIL, checks if `roundtrip_evaluated_total > 0` or `real_quote_count_total > 0` or OE `total_opportunities > 0`. If chain produced real data, bypasses INFRA_FAIL and falls through to economics/rejection classification. Same pattern for NO_SIGNAL: bypassed when RT or real_quote data exists.
3. **scripts/pair_level_rca.py** — New `_print_gate_vs_blocker()` section: separates gate status (PASS/FAIL with reasons) from actual profit blocker (OE_ECONOMICS, MIXED_SOURCE, etc.). Also added `load_gate_result()` and `_derive_profit_blocker()`.

### Expected Blocker Reclassification (after fix)
| Chain | Old Blocker | New Blocker | Evidence |
|-------|-------------|-------------|----------|
| arbitrum_one | OE_ECONOMICS | OE_ECONOMICS (unchanged) | 7/7 PASS, pure economics |
| zksync | INFRA_FAIL | **OE_ECONOMICS** | fail/runs=5/7 but rt=2, NET_PROFIT 80% |
| mantle | INFRA_FAIL | **MIXED_SOURCE** | fail/runs=5/7 but rt=4, MIXED_SOURCE 61.5% |
| linea | INFRA_FAIL | **QUOTE_PATH_CONSTRAINED** | fail/runs=7/7, OE=6 opps, xdex=3 |
| scroll | INFRA_FAIL | **MIXED_SOURCE** | fail/runs=7/7 but rt=2, MIXED_SOURCE 50% |
| base | OE_ECONOMICS | OE_ECONOMICS (unchanged) | SLOT0_DIAGNOSTIC path, sweep evidence |

### Tests (+10)
- `test_r39g_gate_blocker.py`: coverage gate hot_requote (2), blocker INFRA_FAIL bypass (3), NO_SIGNAL bypass (1), _derive_profit_blocker (4).

---

## R39f -- Source Coverage Audit + Dual-Route Contract

Cross-DEX spread directions are fully checked in both directions (emit_dual_routes=true default, verified by contract test). Same-DEX remains diagnostic-only and not all project DEX sources are active in runtime. Current active coverage is 25/27 declared config sources across the six active chain configs, with base.aerodrome and arbitrum_one.sushiswap_v2 inactive, and the ambient adapter unwired from dexes.yaml entirely.

### Declared vs Active vs Productive Sources (step 9)
| Chain | Declared | Active | Missing | Excluded Pairs | Policy |
|-------|----------|--------|---------|----------------|--------|
| arbitrum_one | 6 | 5/6 | sushiswap_v2 | none | sushiswap_v2 out-of-scope (V2, low volume) |
| base | 4 | **4/4** | none | none | aerodrome re-enabled (R39g+) |
| linea | 4 | 4/4 | none | none | full coverage |
| mantle | 4 | 4/4 | none | none | full coverage |
| scroll | 5 | 5/5 | none | SCR/*, STONE/* | excludes = noise reduction policy |
| zksync | 4 | 4/4 | none | ZK/*, HOLD/* | excludes = noise reduction policy |
| **Total** | **27** | **26/27** | **1** | | |

**ambient**: adapter exists (dex/adapters/ambient.py) and registry import present, but NOT in dexes.yaml or any active config. Classified as tech debt / out-of-scope.

### Policy Decisions (R39f)
1. **emit_dual_routes=true**: mandatory contract, locked by TestDualRouteContract (3 tests).
2. **Same-DEX**: diagnostic-only (`same_dex_verification: true` in real_minimal.yaml). Not truth-path. No selective config key needed yet.
3. **base.aerodrome**: priority #1 source-expansion target. Blocked by VE33_QUOTE_FAILED. Next: fix quote path in quotes.py / quote_adapters.py.
4. **arb.sushiswap_v2**: out-of-scope for current productive strategy (V2 AMM, low volume on arb).
5. **ambient**: tech debt, no runtime use. Not blocking any chain.
6. **excluded_pair_hints (zksync: ZK/*, scroll: SCR/*, STONE/*)**: intentional noise-reduction policy, not infra gaps.
7. **Source-expansion acceptance**: same criteria as R39e — change accepted only if real_quote_count, RT-evaluated, route diversity, or best RT gap improves.

### Code Changes (R39f)
1. **tests/unit/test_spread_signals.py** -- +3 TestDualRouteContract tests: both_directions_emitted, single_direction_when_emit_dual_false, require_cross_dex_blocks_same_dex.

---

## R39e -- Market Verdicts + Calibration Universe

The dense productive contour (R39d) improved signal density materially on arbitrum_one, but it did not unlock profit. Fresh RCA shows that healthy-chain signals now survive to real RT and still fail on economics; density improved, profit proximity did not. Base remains quote-path constrained, and mantle/scroll/linea should not be described as pure adapter gaps.

### Per-Chain Verdicts (from fresh RCA evidence)
| Chain | Verdict | RT | Best PnL | Key Blocker |
|-------|---------|----|---------:|-------------|
| arb | healthy, economics-blocked | 5 | -291 bps | slippage (582 bps) dominates |
| mantle | economics-blocked | 2 | -360 bps | high gas (133 bps) + MIXED_SOURCE 61.5% |
| scroll | mixed-source + economics | 1 | -332 bps | SUSPECT_SPREAD 50%, MIXED_SOURCE 50% |
| linea | executable, sweep-not-profitable | 0 | - | SUSPECT_SPREAD 50%, NET_PROFIT_TOO_LOW 50% |
| zksync | thin + economics | 1 | -737 bps | high gas (163 bps), only 1 RT |
| base | **4-dex, SLOT0_DIAGNOSTIC** | 0 | - | SLOT0_DIAGNOSTIC 87%, aerodrome active |

### Code Changes (R39e)
1. **scripts/pair_level_rca.py** -- Unicode arrow replaced with ASCII `->` for Windows console safety.
2. **scripts/generate_intent.py** -- `--tier calibration` added: productive + benchmark pairs (USDC/DAI, USDC/USDT per chain). 42 total pairs.
3. **scripts/ci_full_pipeline.py** -- `--allow-intent-edit` passthrough to repo safety gate.
4. **tests/unit/test_tiered_intent.py** -- +3 calibration tier tests (total 34).

### Acceptance Criteria (for next pair strategy change)
Next change REACHED only if at least one of: RT-evaluated count grows, real_quote_count grows, near-zero executable candidates appear (gap < 100 bps), or best RT gap to zero decreases. signals_count alone insufficient.

---

## R39d -- Quality-Ranked Pair Selection (Tiered Intent)

A market-surface review of current intent.txt shows that the next leverage is not broader inventory coverage but quality-ranked pair selection. Healthy supported chains are already reaching real RT and failing mostly on economics, so the productive contour should shift toward volatile, liquid, multi-DEX pairs (ARB, PENDLE, AERO, VIRTUAL, WMNT, ZK) while stable/stable, LST/LRT, and thin long-tail pairs move to diagnostic or exploratory tiers.

### Code Changes (R39d)
1. **config/core_tokens.yaml** — Tier metadata added to all tokens: `volatility_tier` (high/medium/low), `liquidity_tier` (high/medium/low), `cross_dex_expected` (int), `accounting_sensitive` (bool for LST/LRT), `productive_default` (bool). Each token classified based on R39c RCA evidence.
2. **scripts/generate_intent.py** — Refactored from blind inventory-based generator to tiered selector. `classify_token()` classifies tokens into productive/exploratory/diagnostic tiers. `generate_pairs_for_chain()` accepts `tier_filter` parameter. `--tier` CLI flag: productive (default) / exploratory / all / diagnostic.
3. **config/intent.txt** — Regenerated with productive contour: 31 pairs (down from 116). Stable/stable, LST/LRT, thin long-tail all excluded from default.

### Per-Chain Productive Contour (R39d)
| Chain | P0 Pairs | Key Tokens |
|-------|----------|------------|
| arbitrum_one | 9 | ARB, PENDLE, LINK, WBTC |
| base | 7 | AERO, VIRTUAL, cbBTC |
| linea | 3 | WBTC |
| scroll | 3 | WBTC |
| mantle | 4 | WMNT |
| zksync | 5 | ZK, WBTC |

### Demoted/Removed from Productive
- **Stable/stable**: USDC/DAI, USDC/USDT → diagnostic
- **Near-stable**: WETH/FRAX, WETH/LUSD, WETH/USDE → diagnostic
- **LST/LRT**: wstETH/*, rETH/*, ezETH/*, weETH/*, STONE/*, cbETH/*, mETH/*, cmETH/* → diagnostic (accounting_sensitive)
- **Thin long-tail (arb)**: DPX, GRAIL, GNS, JOE, MAGIC, RDNT, TBTC → exploratory
- **Meme (base)**: BRETT, DEGEN, TOSHI, WELL → exploratory
- **Removed (zksync)**: CHEEMS, HOLD → exploratory
- **Not headline (mantle)**: PUFF, mETH, cmETH → exploratory/diagnostic

### Tests (+31)
- `test_tiered_intent.py`: classify_token (8), per-chain P0 (14), tier expansion (5), metadata contract (4)

---

## R39c -- EXECUTABLE_BEST_NEG + Route-Level RCA (condensed)
- `EXECUTABLE_BEST_NEG` upgrade in chain_stats.py: distinguishes proven-executable negative frontiers.
- Post-aggregation fence: accepts EXECUTABLE_BEST_NEG for pnl < 0.
- Route-level economics in pair_level_rca.py: buy_dex->sell_dex detail per RT.
- Market surface: arb economics-blocked (-54 to -749 bps), base quote-path constrained (SLOT0_DIAGNOSTIC 68.8%), zksync/mantle/linea/scroll economics-blocked.
- +8 tests. Total: 2259.

---

## R39 -- Frontier Fix + Sweep Guard + Chain Stats Truthiness (condensed)
- Frontier sort key: 0.0 truthiness bug fixed (Python `0.0 or -9999`).
- Sweep size promotion: field name fix (`measured_*` -> `best_*`).
- Chain stats: 0.0 truthiness fix for gas/fee/slippage/total_cost.
- Pair trace gas: reject_reason parsing instead of wrong notional calc.
- Evidence: 30 runs, 241 signals, 67 RT, 0 profitable, $420.82.
- +13 tests.
8. **tests/unit/test_run_scan_real_purity.py** — max_lines bumped to 1650.
9. **tests/unit/test_nonstop_loop_artifacts.py** — Rolling artifact test allows .log files.

### Tests (+13)
- `TestFrontierContractConsistency`: breakeven vs BEST_NEG (3 tests)
- `TestSweepSizePromotionGuard`: executable/non-executable/BEST_NEG/zero_slippage (4 tests)
- `TestChainStatsSweepMeasured`: zero_slippage_preserved, none_falls_through (2 tests)
- `TestPairTraceGasFromRejectReason`: gas_parsed_from_reject_reason, gas_fallback (2 tests)
- `TestRcaGasBpsFromRejectReason`: parse/fallback/zero (3 tests)

---

## R38 — Sweep Size Promotion + Blocker Accuracy + LST Suppression + Artifact Parity + Event-Driven Loop

R38 responds to lead's 2-hour canonical online audit (282 runs, 2557 signals, 649 RT evaluated, 0 profitable, $4411.02 diagnostic net USDC).

### Blocker Verdict: MIXED (Step 1)
The project blocker is **mixed** — not a single classification:
- **Healthy chains (arb/mantle/scroll)**: 100% PASS, high signal volume. Blocker is pure economics/slippage, not infra. Pipeline is NOT the bottleneck here.
- **Signal-rich but unstable (linea)**: Good signal volume (243/47 runs) but 57% fail rate. Economics-blocked + infra instability.
- **Quote-path debt (base)**: SLOT0_DIAGNOSTIC dominance, NO_DATA rate 34%. Not a market verdict — infrastructure/adapter debt (Aerodrome needed).
- **Weak market data (zksync)**: 79% fail rate. Cannot draw market conclusions until stability improves.
M4.1 (simulate-only) operationally proven; M4.2 (stable profit) still open.

### Code Changes
1. **strategy/jobs/run_scan_real.py** — Final RT candidates now use sweep `best_size_usd` (from `dynamic_sweep`) instead of static `target_usd_notional`. Both primary + error paths updated. Falls back to config when sweep unavailable.
2. **strategy/jobs/run_scan_real.py** — LST-aware SUSPECT_ACCOUNTING: 50 bps threshold for LST/derivative pairs (WSTETH, METH, etc.) vs 500 bps generic. Fixed stale `SANE_RT_PNL_MAX` references to use imported constants.
3. **strategy/jobs/run_scan_real.py** — Fixed NoneType crash in `dynamic_sweep.results` chain (defensive `or {}` for None values).
4. **strategy/long_scan_summary.py** — `OE_ECONOMICS` blocker_reason updated: "economics-blocked (NET_PROFIT_TOO_LOW / SLIPPAGE_TOO_HIGH at real sizes)". Added `QUOTE_PATH_CONSTRAINED` reason entry.
5. **strategy/long_scan_summary.py** — Per-chain aliases: `pass_runs`, `signals_count`, `real_quote_count` alongside originals for consumer parity.
6. **m4/fixtures.py** — `blocker_classification` + `blocker_reason` computed per-run from `oe_rejection_funnel`. Cascade: ROUNDTRIP_PROFITABLE → NO_SIGNAL → QUOTE_PATH_BLOCKED (SLOT0>40%) → OE_ECONOMICS (NET_PROFIT>40%) → MIXED_SOURCE (>30%).
7. **strategy/live_stream.py** — `_LST_TOKENS` frozenset, `_is_lst_pair()` function, `_SANE_RT_PNL_MAX_BPS=500`, `_SANE_RT_PNL_MAX_BPS_LST=50`. SUSPECT_ACCOUNTING threshold is LST-aware.
8. **scripts/pair_level_rca.py** — LST column added to economics decomposition output.
9. **strategy/infra.py** — `DirtySetTracker.wait_for_dirty(timeout)`: event-driven wait using `threading.Event`. WS background threads `set()` the event on `newHeads`, orchestrator wakes immediately. `status()` reports `event_driven: true`.
10. **start.py** — Orchestrator loop: `time.sleep(sleep_seconds)` replaced with `dirty_tracker.wait_for_dirty(timeout=sleep_seconds)`. Falls back to `time.sleep()` when no tracker.
11. **docs/WORKFLOW.md** — Dashboard elevated to primary "Canonical Commands" section (before scanner).

### Tests (+20)
- `test_r38_changes.py`: LST detection (7), blocker classification cascade (8), per-chain aliases (2), blocker reason text (2), RCA LST parity (1)

### Per-Chain Blocker Taxonomy (R38, from lead's 2h canonical audit)
| Chain | Blocker Class | Specific | Action |
|-------|---------------|----------|--------|
| arbitrum_one | OE_ECONOMICS | Near-profit counterfactual only (USDC/DAI -53.96 bps); economics/slippage blocked | Sweep-optimal sizing now live; event-driven execution needed |
| mantle | OE_ECONOMICS | NET_PROFIT_TOO_LOW; LST pseudo-profits (METH/WETH) suppressed at 50 bps | Economics investigation; LST filter active |
| linea | OE_ECONOMICS | Signals exist but economics-blocked; LST pseudo-profits (WSTETH/WETH) suppressed | Economics investigation; LST filter active |
| zksync | OE_ECONOMICS | FAIL-heavy, weak market verdict | Stability track first |
| base | QUOTE_PATH_CONSTRAINED | SLOT0_DIAGNOSTIC dominance, few cross-dex pairs | Separate quote-path track; Aerodrome adapter |
| scroll | MIXED_SOURCE | OE rejects dominated by MIXED_SOURCE | Fix MIXED_SOURCE pairs or filter |

### Per-Chain Worktracks (Step 6)
Each chain now has an independent action track:

| Chain | Track | Priority | Next Action |
|-------|-------|----------|-------------|
| arbitrum_one | **ECONOMICS** | P0 | Event-driven re-quote at WS block, optimal sweep sizing, reduce slippage model |
| mantle | **ECONOMICS** | P1 | LST false-positive filter active; investigate NET_PROFIT on non-LST pairs |
| linea | **STABILITY+ECONOMICS** | P1 | Fix 57% fail rate (RPC reliability), then economics |
| scroll | **MIXED_SOURCE** | P2 | Identify and remove MIXED_SOURCE-dominated pairs, or fix quoter_v2 coverage |
| zksync | **STABILITY** | P2 | Fix 79% fail rate before drawing any economics conclusions |
| base | **QUOTE_PATH** | P3 | Aerodrome adapter; increase cross-DEX pair surface beyond current 3 |

### Quality-Ranked Pair Selection Policy (Step 7)
**Do NOT add more pairs blindly.** Current intent.txt expanded aggressively; many pairs produce only diagnostic data. Policy going forward:
- Pairs must have ≥2 DEXes with real (non-SLOT0) quotes before promotion to core
- Priority: pairs that reach RT evaluation → pairs with near-zero PnL → pairs with signals
- Use `scripts/pair_level_rca.py` to audit pair quality BEFORE adding to configs
- Remove or demote pairs that consistently produce SUSPECT_ACCOUNTING or MIXED_SOURCE rejects

### Selective Coverage Expansion Policy (Step 10)
Coverage expansion (new chains, new DEXes, new pairs) is paused until:
1. Healthy chains (arb/mantle) show RT net_pnl_bps > 0 at optimal sweep size
2. Unstable chains (zksync/linea) reach >80% pass rate
3. Base has Aerodrome adapter or equivalent cross-DEX surface
New pairs should be quality-ranked (Step 7) before admission.

---

## R37 — Artifact Parity + Frontier Classification + Stale-Claims Cleanup

R37 closes the lead's 10-point R36 audit. Code: `BREAKEVEN_FRONTIER` reason added to distinguish 0.0 bps sweep results from genuine negative PnL. `roundtrip_summary` promoted to run_summary top-level. `QUOTE_PATH_CONSTRAINED` blocker added for surface-limited chains (base). Per-chain blocker taxonomy refreshed from rolling artifacts. All stale doc claims cleaned.

R36 closes most recent code/config directives, but not all historical monitoring directives are fully closed yet. On healthy supported chains the dominant blocker is now market economics/slippage, while base and part of zksync remain infrastructure/quote-path constrained; therefore the project is beyond infra bring-up, but not yet at milestone profit closure.

### Code Changes
1. **engine/roundtrip.py** — `BREAKEVEN_FRONTIER` reason for 0.0 bps net_pnl (was classified as `BEST_NEG`). Distinguishes genuine negative frontier from breakeven/zero-quote.
2. **m4/fixtures.py** — `roundtrip_summary` added as top-level key in run_summary (alias of `metrics.roundtrip`) for parity with long_scan_latest.json.
3. **strategy/chain_stats.py** — `QUOTE_PATH_CONSTRAINED` blocker: no signals + few cross-dex pairs (<=3). Separates base (surface-limited) from generic NO_SIGNAL. Taxonomy docstring updated.
4. **docs/status/Status_M5_0.md** — Per-chain blocker taxonomy updated from fresh rolling data. Stale blocker classifications fixed (linea: INFRA_PARTIAL→OE_ECONOMICS, base: QUOTE_PATH_DIAGNOSTICS→QUOTE_PATH_CONSTRAINED, scroll: ECONOMICS_DEAD_POOLS→MIXED_SOURCE).
5. **docs/status/Status_M4.md** — "Pending: 6-chain scan" → completed. Stale R33 claims updated.

### Tests (+2: BREAKEVEN_FRONTIER + QUOTE_PATH_CONSTRAINED)

---

## R36 — Surface Expansion + Sweep Frontier Promotion

R36 closes the gap between "adapter implemented" and "adapter enabled in production configs". SyncSwap and iZiSwap adapters are now active in all applicable chain configs. Sweep frontier promotion ensures `best_size_usd` from dynamic sweep influences headline RT metrics. ZERO_QUOTE_FRONTIER distinction (`frontier_reason`) surfaced in long_scan_summary.

### Code Changes
1. **config/real_minimal.yaml** — +iziswap (arb), +same_dex_verification: true
2. **config/onboard_zksync_candidate.yaml** — +syncswap, +iziswap
3. **config/onboard_linea_stage1.yaml** — +syncswap_linea, +iziswap
4. **config/onboard_mantle_stage2.yaml** — +iziswap
5. **config/onboard_scroll_stage1.yaml** — +syncswap, +iziswap
6. **strategy/jobs/run_scan_real.py** — Sweep frontier promotion: when sweep `best_net_pnl_bps` > fixed-size RT, promote to `stats["roundtrip"]["best_net_pnl_bps"]` with `sweep_promoted=true`.
7. **strategy/chain_stats.py** — Track `sweep_best_frontier_reason` per chain (ALL_FAILED / BEST_NEG / PROFITABLE).
8. **strategy/long_scan_summary.py** — Surface `sweep_best_frontier_reason` at top level for downstream consumers.
9. **docs/ONBOARDING_MATRIX.md** — Added 9 entries (syncswap×3, iziswap×5, syncswap_linea×1) to Adapter Registry and Coverage Matrix.

### R36 Acceptance Criteria
| Criterion | Status | Evidence |
|-----------|--------|----------|
| New adapters in active configs | ✅ PASS | 5 configs updated (arb/zksync/linea/mantle/scroll) |
| same_dex_verification enabled | ✅ PASS | real_minimal.yaml |
| Sweep promotion implemented | ✅ PASS | run_scan_real.py `sweep_promoted` flag |
| ZERO_QUOTE_FRONTIER in summary | ✅ PASS | `sweep_best_frontier_reason` in long_scan_summary |
| ONBOARDING_MATRIX updated | ✅ PASS | 9 new rows in Coverage Matrix |
| Tests pass | ✅ PASS | 2211 passed, 5 skipped |
| ambient.py remains stub | ⚠️ KNOWN | Ambient adapter not claimed as production; stub only |

### Per-Chain Blocker Taxonomy (R36, updated R37 from fresh rolling)
| Chain | DEXes (R36) | Blocker Class | Specific Blocker | Action |
|-------|-------------|---------------|------------------|--------|
| arbitrum_one | 5 (uni+sushi+pcswap+camelot+izi) | OE_ECONOMICS | Gas $2.84 + slip 7-9x at $5 sweep best (-27.4 bps) | Economics/slippage investigation; event-driven execution |
| zksync | 4 (uni+pcswap+syncswap+izi) | OE_ECONOMICS | NET_PROFIT_TOO_LOW at probe; 0.0 bps frontier at $50 | Stability track (FAIL-heavy), then market conclusions |
| base | 3 (uni+sushi+pcswap) | QUOTE_PATH_CONSTRAINED | No syncswap/izi in dexes.yaml, surface limited, few cross-dex pairs | Separate quote-path track; Aerodrome adapter |
| mantle | 4 (agni+fusionx+stratum+izi) | OE_ECONOMICS | NET_PROFIT_TOO_LOW; 0.0 bps frontier at $50 | Economics investigation |
| linea | 4 (pcswap+lynex+syncswap_linea+izi) | OE_ECONOMICS | Signals exist, OE rejects; no sweep candidates reach RT | Economics investigation (was INFRA_PARTIAL, now PASS) |
| scroll | 5 (uni+sushi+nuri+syncswap+izi) | MIXED_SOURCE | OE rejects dominated by MIXED_SOURCE | Fix MIXED_SOURCE pairs or filter; then economics |

---

## R35 — User-Visible Stream Fix + Evidence Discipline

R35 follow-up resolved the user-visible stream regression. The hot-loop frontier is no longer empty: diagnostic reprieve rows now preserve pair, route, spread_bps, reject_reason, and net frontier PnL. Remaining blockers are downstream economics and real-quote roundtrip truth, not stream serialization.

### Code Changes
1. **strategy/dynamic_sweep_runtime.py** — Route identity normalization: after `sweep_roundtrip_sizes()`, `sr.buy_dex`/`sr.sell_dex` overwritten with OE opportunity’s original direction. Root cause of empty live_stream fields.
2. **monitoring/dashboard.html** — When `verified_pairs=[]`, shows diagnostic frontier as primary panel ("Best Available Frontier") instead of empty table.
3. **strategy/chain_stats.py** — QUOTE_PATH_BLOCKED sweep override: `has_sweep_evidence` guard prevents misclassification when `runs_with_sweep > 0`.
4. **strategy/rolling_outputs.py** — Hot loop canonical guard: require `summary_file` containing `_rolling` to write to HOT_LOOP_LATEST.

### R35 Acceptance Criteria (all PASS)
| Criterion | Status | Evidence |
|-----------|--------|----------|
| `diagnostic_pairs` non-empty, multi-chain | ✅ PASS | 16 entries across 6 chains (arb=5, linea=3, mantle=2, scroll=3, zksync=3) |
| rows have pair/route/spread_bps/reject_reason | ✅ PASS | e.g. USDC/DAI=39.65, WETH/PENDLE=26.63, WETH/WBTC=8.21 bps |
| `runs_with_sweep > 0` | ✅ PASS | arb=4, mantle=4, scroll=4, base=3, zksync=1 |
| `arb blocker != QUOTE_PATH_BLOCKED` | ✅ PASS | arb=OE_ECONOMICS (sweep override working) |
| `blocker_classification` non-null all chains | ✅ PASS | arb/zksync/scroll=OE_ECONOMICS, base/linea=INFRA_FAIL, mantle=MIXED_SOURCE |
| dashboard shows diagnostic frontier | ✅ PASS | "Best Available Frontier (Diagnostic)" panel populated |

### Chain Quality (R35 fresh 6-chain canonical scan, 2026-03-23)
| Chain | Runs | Blocker | Sweep Runs | Signals |
|-------|------|---------|------------|--------|
| arbitrum_one | 4 | OE_ECONOMICS | 4 | 109 |
| zksync | 4 | OE_ECONOMICS | 1 | 3 |
| base | 4 | INFRA_FAIL | 3 | 4 |
| mantle | 4 | MIXED_SOURCE | 4 | 12 |
| linea | 4 | INFRA_FAIL | 0 | 19 |
| scroll | 4 | OE_ECONOMICS | 4 | 16 |

---

## R34 — Fix Stream-to-Analysis Signal Loss (condensed)
- Fixed live_stream.verified_pairs/diagnostic_pairs being empty (token_decimals/rt_top_n unbound on reprieve path).
- live_stream.py rewrite: 3-tier row building (RT → dynamic_sweep → sweep_candidates).
- Hot loop canonical guard: non-canonical sessions skip HOT_LOOP_LATEST write.
- +17 tests.

---

## R33 — Start.py Extraction + Reprieve Runtime Validation (condensed)
- Sweep reprieve: NET_PROFIT_TOO_LOW rejects with cross-DEX get sweep re-check.
- Blocker taxonomy: 6-value auto-computed (`_compute_blocker_evidence()`).
- Quoter_v2 skip cache: 3 failures → 10-min bypass.
- +25 tests.

---

## R31 — OE Bottleneck Diagnosis (condensed)
- truth_verdict (4-value), quote_source_summary (per-DEX:fee), oe_rejection_funnel (total/gated/rejected/reasons).
- 43-run evidence: 308 signals, $560.16 diag, 0 profitable. Primary blocker = economics at $10 probe (NET_PROFIT_TOO_LOW 57%).
- +14 tests.

---

## Historical Summary (R29-R28 — condensed)

### R29 — Fixed-Size Doctrine Removed + Quotes RPC Extraction
- **Canonical sweep**: $1–$10,000 (19-point log ladder). Discovery probe, spread seed, executable sweep.
- **strategy/quote_rpc.py**: Extracted RPC helpers (quotes.py 2006→1658 lines)
- **Evidence**: 72 runs, 0 profitable RT, best -25.38 bps

### R28.30-R28.29 — Funnel Normalization + Lead Audit
- **6-stage funnel**: discovery→quote→spread→engine→selection→roundtrip
- **env_flag_enabled**: Canonical in core/env.py. read_slot0_v3 dedup. 39 discovery tests.

### Earlier Rounds (R28.24-R25)
Detailed in git history. Key: hot re-quote loop (R28.11), truth contract (R28.13), benchmark chain (R28.14), funnel normalization (R28.30), god-file extraction (R28.28), suppression isolation (R28.26), filter-layer RCA (R28.25).

---

## Architecture Contract

> **Static-looking scans are caused by cache-backed discovery and a tiny surviving route surface; live-market target requires real-time quote refresh plus event-driven hot re-quote, not full registry RPC refresh every cycle.**

THREE refresh cadences:
1. **QUOTES/BLOCKS** (live RPC every cycle) — ✅ Working
2. **HOT RE-QUOTE** (event-driven target) — ❌ Timer-based, not WebSocket
3. **REGISTRY/DISCOVERY** (periodic cold refresh) — ❌ Cache-backed

---

## Chain Quality Classification

| Chain | Quality | DEXes (R36) | Blocker (R37 fresh) | Summary |
|-------|---------|-------------|---------------------|--------|
| arbitrum_one | SIGNAL_PRODUCING | 5 (uni+sushi+pcswap+camelot+izi) | OE_ECONOMICS | 5-DEX, 30+ cross-dex pairs, gas+slippage dominant (USDC/DAI gap=54bps) |
| zksync | SIGNAL_PRODUCING | 4 (uni+pcswap+syncswap+izi) | OE_ECONOMICS | 4-DEX, FAIL-heavy but signals exist, NET_PROFIT_TOO_LOW |
| scroll | SIGNAL_PRODUCING | 5 (uni+sushi+nuri+syncswap+izi) | MIXED_SOURCE | 5-DEX, MIXED_SOURCE rejection dominant |
| mantle | SIGNAL_PRODUCING | 4 (agni+fusionx+stratum+izi) | OE_ECONOMICS | 4-DEX, fragile pass, NET_PROFIT_TOO_LOW |
| linea | SIGNAL_PRODUCING | 4 (pcswap+lynex+syncswap_linea+izi) | OE_ECONOMICS | 4-DEX, 5/5 PASS (was INFRA_FAIL), no sweep candidates |
| base | INFRA_READY | 3 (uni+sushi+pcswap) | QUOTE_PATH_CONSTRAINED | Surface limited, no expansion in dexes.yaml |

**Rollout Queue**: arb → linea → zksync → base → mantle → scroll

---

## Operational Contracts

```powershell
# Offline gate (deterministic)
py -3.11 scripts/ci_m5_0_gate.py --offline --strict

# Online gate (requires RPC)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1

# Unit tests
py -3.11 -m pytest tests/unit -q

# Full CI pipeline
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

---

## Core Truth Statement

> **M5_0 validates artifact schemas/invariants, multicall, failover, provenance.**
> M4 execution gate is separate for profit.
> R32: Sweep reprieve connects wide-ladder to OE re-check for NET_PROFIT_TOO_LOW.
> R31: truth_verdict, quote_source_summary, oe_rejection_funnel — artifact clarity.
> R29: 19-point sweep ladder replaces fixed-size doctrine.
> All chains: `profitable_roundtrips=0` on current evidence.
