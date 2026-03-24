# Status: M5_0 (Infrastructure Hardening)

**Status**: [ACTIVE]
**Updated**: 2026-03-24 (R39i — base QUOTE_PATH_BLOCKED fix, Status compression, CI enforcement. R39h++ system audit confirmed layered blockers.)
**Tests**: 2332 passed / 5 skipped
**Schema**: start:long_scan_summary:v1.15, m4:run_summary:v2.0, start:hot_loop_snapshot:v1.3
**Evidence**: R39i: base blocker fix + CI enforcement. R39h++: system audit, WS+funnel. R39h+: funnel attrition zero. R39h: calibration contour + funnel.
**Rolling**: `data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json,hot_loop_latest.json}`

---

## R39i — Base QUOTE_PATH_BLOCKED Fix + Status Compression + CI Enforcement

### Summary
R39h++ partially complete: rt_without_signal implemented/verified, WS endpoints configured on all 6 chains, but runtime WS connectivity still unproven, base still quote-path blocked in practice, and docs bundle was not repo-safety clean. R39i fixes these gaps.

### Fixes (R39i)
1. **strategy/chain_stats.py** — `_compute_blocker_evidence()`: sweep evidence override now requires `rq > 0` (not just `runs_with_sweep > 0`). When SLOT0 dominates (>40%) and `real_quote_count_total=0`, chain is `QUOTE_PATH_BLOCKED` even with diagnostic-only sweep evidence. Directly fixes base misclassification as `OE_ECONOMICS`.
2. **tests/unit/test_blocker_evidence.py** — +2 tests: `test_slot0_with_diagnostic_sweep_still_quote_path_blocked` (base scenario: SLOT0 77.5%, rq=0, sweep=2 → QUOTE_PATH_BLOCKED), `test_slot0_with_real_quotes_falls_through` (SLOT0 50%, rq=5, sweep=3 → OE_ECONOMICS).
3. **docs/status/Status_M5_0.md** — Compressed from 487 → <400 lines. Historical R39c–R38 sections folded into compact table.
4. **docs/DEV_REPORT_LATEST.md** — Aligned with current rolling timestamp/runDir from `run_summary_latest.json`.
5. **WS connectivity**: acknowledged as config-complete but runtime-incomplete. `hot_loop_latest.json` still shows `chains_ws_connected: 0`. Not claiming WS step as finished until verified.
6. **linea framing**: corrected from "coverage fail" to "thin-truth/economics" — fresh rolling shows `signals=20, rt=6, rq=6`.

### Per-Chain Fresh RCA (2026-03-24 run dirs, pair_level_rca evidence)

| Chain | Pairs | Exec% | RT | Best PnL | #1 OE Reject | Blocker (R39i) |
|-------|------:|------:|---:|------:|----------|---------------|
| arb | 11 | 88.6% | 5 | -54.21 | NET_PROFIT_TOO_LOW | OE_ECONOMICS |
| zksync | 7 | 92.3% | 1 | -608.57 | NET_PROFIT_TOO_LOW 63% | OE_ECONOMICS |
| base | 9 | 6.3% | 0 | — | SLOT0_DIAGNOSTIC 77.5% | **QUOTE_PATH_BLOCKED** (R39i fix) |
| linea | 5 | 100% | 1 | -563 | NET_PROFIT_TOO_LOW 63% | OE_ECONOMICS (thin-truth) |
| scroll | 5 | 86.7% | 2 | -369.94 | SUSPECT_SPREAD 37.5% + MIXED_SOURCE 37.5% | MIXED_SOURCE |
| mantle | 4 | 100% | 2 | -415.07 | MIXED_SOURCE 66.7% | MIXED_SOURCE |

### Layered Blocker Priority (formalized)

| Priority | Chain(s) | Blocker | Status |
|----------|----------|---------|--------|
| P0 | base | QUOTE_PATH_BLOCKED (SLOT0 77%, rq=0) | Fix in quotes.py/quote_adapters.py |
| P1 | scroll, mantle | MIXED_SOURCE (38-67% of OE rejections) | Clean quote/truth path |
| P2 | all 6 | WS freshness | Config-complete, runtime-unproven |
| P3 | linea | Thin-truth/economics (signals=20, rt=6, all negative) | Economics investigation |
| P4 | arb | Economics/slippage (best -54bps USDC/DAI) | Sweep sizing + slippage model |
| P5 | — | ambient adapter (tech debt) | Do not distract from P0-P2 |

### Signal Funnel (v1.15 + rt_without_signal, fresh evidence)

| Chain | Intent | Excl | XDex | Signals | RT Eval | RT w/o Sig |
|-------|-------:|-----:|-----:|--------:|--------:|-----------:|
| arb | 11 | 11 | 11 | 226 | 30 | 0 |
| zksync | 7 | 7 | 6 | 24 | 6 | 0 |
| base | 9 | 9 | 9 | 6 | 3 | 1 |
| mantle | 5 | 4 | 4 | 0 | 12 | **12** |
| linea | 5 | 5 | 5 | 20 | 6 | 0 |
| scroll | 5 | 5 | 5 | 24 | 12 | 0 |
| **Total** | **42** | **41** | **40** | **300** | **69** | **13** |

Near-zero universe attrition (42→41→40). Mantle semantic split exposed: rt_without_signal=12.

---

## R39h++ — Full System Audit + WS Freshness + Funnel Diagnostics

### Summary
Full post-R39h+ audit confirms **pair-universe width is no longer the main blocker**. Blockers are layered: base quote-path debt, mixed-source on scroll/mantle, HTTP-only freshness, post-signal economics.

### Fixes (R39h++)
1. **config/chains.yaml** — WS endpoints for linea/mantle/scroll/zksync (BlastAPI public WSS). All 6 chains now have WS configured.
2. **strategy/chain_stats.py** — `rt_without_signal_total`: RT evaluated on runs where `included_signals_count=0`.
3. **strategy/long_scan_summary.py** — `rt_without_signal` in per-chain + aggregate signal_funnel.
4. **tests** — +3 tests (rt_without_signal accumulation/funnel, all-chains-have-ws-endpoints). 2330 passed.

---

## R39h+ — Funnel Attrition Zero + 3-Tier Policy Permanent

### Key Finding
Current blocker is no longer pair-universe attrition: intent, post-exclude, and xDex counts are equal (40→40→40). Expansion should come through tiered universe policy and source quality, not inflating default productive intent.

### 3-Tier Policy (permanent)
| Tier | Pairs | Purpose | Promotion criteria |
|------|------:|---------|-------------------|
| productive | 31 | Quality-ranked volatile/liquid/multi-DEX | Baseline |
| calibration | 42 | + benchmark stables (USDC/DAI, USDC/USDT) | Benchmarking per-chain health |
| exploratory | ~69 | All tokens ≥2 DEX presence | ≥2 of 4 metrics improve |

**Expansion acceptance**: ≥2 of: rq grows, RT-evaluated grows, best gap decreases, near-zero candidates appear (<100bps). signals_count alone insufficient.

### Mantle 0-sig/14-RT Semantic Split
Two independent pipelines: `included_signals_count` uses 500bps threshold; opportunity engine creates opps independently → rejected opps go to sweep_reprieve → counted in `roundtrip_evaluated_total`. Not a bug; `sweep_reprieve_rt` + `rt_without_signal` fields make this visible. 2327 tests.

---

## R39h — Per-Chain Signal Funnel + Calibration Contour

### Key Changes
1. Schema v1.15: `signal_funnel` section (intent→excludes→xdex→signals→RT per-chain + aggregate).
2. ZK/* blanket exclude removed; anchor prices added (ZK_USDC=0.10, ZK_WETH=0.0000488). zksync: 3→7 pairs.
3. `config/intent.txt` regenerated with `--tier calibration`: 42 pairs (was 31).

### Per-Chain Pair Counts After Calibration
| Chain | Before | After | Delta |
|-------|-------:|------:|------:|
| arb | 9 | 11 | +2 |
| base | 7 | 9 | +2 |
| linea | 3 | 5 | +2 |
| scroll | 3 | 5 | +2 |
| mantle | 4 | 5 | +1 |
| zksync | 3 | 7 | +4 |
| **Total** | **29** | **42** | **+13** |

2325 passed / 5 skipped (+8 signal funnel tests).

---

## Historical Summary (R39g+ through R36)

Condensed from full session notes. For detailed per-session evidence, see git log.

| Session | Key Changes | Tests | Total |
|---------|-------------|------:|------:|
| **R39g+** | Aerodrome re-enabled on base (4 DEXes). PRICE_SCALE per-pair majority logic. Base source: 3/4→4/4. | +11 | 2317 |
| **R39g** | Coverage gate relaxed (min_pairs=1). Blocker INFRA_FAIL bypass when chain has real data. pair_level_rca gate vs profit blocker. | +10 | 2306 |
| **R39f** | Source audit: 26/27 active (arb.sushiswap_v2 out-of-scope, ambient=tech debt). Dual-route contract. Same-DEX diagnostic-only. | +3 | 2296 |
| **R39e** | Per-chain verdicts. Calibration tier. Acceptance: ≥2 of 4 metrics. | +3 | 2293 |
| **R39d** | Quality-ranked pairs: 116→31 (productive contour). core_tokens.yaml tiers. generate_intent.py tiered selector. | +31 | 2290 |
| **R39c** | EXECUTABLE_BEST_NEG. Route-level economics in pair_level_rca. | +8 | 2259 |
| **R39** | Frontier 0.0 truthiness fix. Sweep size promotion fix. Chain stats gas/fee 0.0 fix. | +13 | 2251 |
| **R38** | Sweep size promotion. LST-aware SUSPECT_ACCOUNTING (50bps). Event-driven loop (DirtySetTracker). Coverage expansion paused. | +20 | 2238 |
| **R37** | BREAKEVEN_FRONTIER reason. roundtrip_summary top-level. QUOTE_PATH_CONSTRAINED. Stale claims cleanup. | +2 | 2218 |
| **R36** | SyncSwap+iZiSwap in all configs. Sweep frontier promotion. ZERO_QUOTE_FRONTIER. | — | 2216 |

### Per-Chain Blocker Evolution (R36→R39i)

| Chain | R36 | R38 | R39g | R39h++ | R39i |
|-------|-----|-----|------|--------|------|
| arb | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS |
| zksync | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS | OE_ECONOMICS |
| base | QUOTE_PATH_CONSTRAINED | QUOTE_PATH_CONSTRAINED | OE_ECONOMICS | OE_ECONOMICS | **QUOTE_PATH_BLOCKED** |
| linea | OE_ECONOMICS | OE_ECONOMICS | QUOTE_PATH_CONSTRAINED | OE_ECONOMICS | OE_ECONOMICS |
| scroll | MIXED_SOURCE | MIXED_SOURCE | MIXED_SOURCE | MIXED_SOURCE | MIXED_SOURCE |
| mantle | OE_ECONOMICS | OE_ECONOMICS | MIXED_SOURCE | MIXED_SOURCE | MIXED_SOURCE |

### Source Coverage (cumulative)
| Chain | Declared | Active | Missing | Note |
|-------|----------|--------|---------|------|
| arb | 6 | 5/6 | sushiswap_v2 | V2, out-of-scope |
| base | 4 | 4/4 | — | aerodrome re-enabled R39g+ |
| linea | 4 | 4/4 | — | full |
| mantle | 4 | 4/4 | — | full |
| scroll | 5 | 5/5 | — | full |
| zksync | 4 | 4/4 | — | full |
| **Total** | **27** | **26/27** | **1** | ambient=tech debt |

### Policies (permanent, from R38-R39h+)
1. **3-tier universe**: productive/calibration/exploratory. Default=calibration (42 pairs).
2. **Expansion acceptance**: ≥2 of 4 metrics must improve before promotion.
3. **Coverage expansion paused**: until healthy chains show RT net_pnl_bps > 0.
4. **Quality-ranked pairs**: ≥2 DEXes with real quotes before promotion to core.
5. **Same-DEX**: diagnostic-only, not truth-path.
6. **LST suppression**: 50bps threshold for LST/derivative pairs.
7. **emit_dual_routes=true**: mandatory contract.
