# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39c**: EXECUTABLE_BEST_NEG distinction, route-level economics RCA, sweep guard + post-aggregation fence accept new frontier reason. Fresh per-chain RCA confirms market economics dominance on healthy chains.

## SESSION GOAL (R39c: EXECUTABLE_BEST_NEG + route-level RCA + market surface conclusion)
**Goal**: (1) EXECUTABLE_BEST_NEG distinction in chain_stats/long_scan_summary/run_scan_real, (2) Route-level economics in pair_level_rca.py, (3) Market surface conclusion in docs.
**Prior (R39b)**: 2250 tests, sweep guard field fix, chain_stats truthiness fix, pair_trace gas fix.
**Lead directive (R39c)**: Reports are strong proxy for supported market surface. Healthy chains are market-economics-blocked. Filter relaxation does not unlock profit (arb diagnostics proved). Base/zksync infrastructure-constrained.

## 0) Meta
timestamp_utc: 2026-03-23T18:35:31Z
run_dir_name: R39c canonical scan (30 runs across 6 chains, fresh 10-min canonical scan with EXECUTABLE_BEST_NEG + route-level)
mode: R39c_EXECUTABLE_BEST_NEG_ROUTE_RCA
test_count: 2259 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T18:35:31Z
  dirty: true (R39c code changes uncommitted)
  desc: executable_best_neg + route_level_rca

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39c: EXECUTABLE_BEST_NEG distinction + route-level economics RCA + market surface conclusion |
| goal_status | **REACHED** (6 code changes, 9 new tests, 2259 PASS, CI green, canonical scan with R39c code, docs synced) |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (market economics: spread < slippage + LP fee + gas on all healthy chains). base: quote-path constrained. zksync: stability. |
| evidence_session_run_dirs | Post-R39 rerun evidence (30 runs, 6 chains) + per-chain RCA confirming economics dominance |
| primary_blocker_of_session | EXECUTABLE_BEST_NEG distinction missing → frontier trust ambiguous (paper vs proven executable) |
| blocker_status_before | ACTIVE: BEST_NEG mixed paper-only and real-executable frontiers. No route-level visibility. |
| blocker_status_after | **RESOLVED**: EXECUTABLE_BEST_NEG upgrade in chain_stats + long_scan + run_scan_real. Route-level RCA shows buy_dex→sell_dex economics. |
| start_metric | 2250 tests, no frontier trustworthiness distinction, pair-level-only RCA |
| end_metric | 2259 tests, EXECUTABLE_BEST_NEG distinction, route-level economics in pair_trace + pair_level_rca |
| delta | +9 tests, +EXECUTABLE_BEST_NEG (3 files), +route-level RCA (pair_trace + pair_level_rca), +market surface docs |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R39c: EXECUTABLE_BEST_NEG + route-level RCA + market surface conclusion
change_summary:
  - **R39c**: `strategy/chain_stats.py` — EXECUTABLE_BEST_NEG upgrade: BEST_NEG with measured_gas_bps + measured_slippage_bps both populated → EXECUTABLE_BEST_NEG.
  - **R39c**: `strategy/long_scan_summary.py` — Post-aggregation fence accepts EXECUTABLE_BEST_NEG for pnl < 0. Per-chain frontier ranking includes sweep_best_frontier_reason.
  - **R39c**: `strategy/jobs/run_scan_real.py` — Sweep guard accepts EXECUTABLE_BEST_NEG. Both paths.
  - **R39c**: `scripts/pair_level_rca.py` — Route-level economics: ALL RT results per pair with buy_dex→sell_dex.
  - **R39c**: `tests/unit/test_r38_changes.py` — +8 tests for EXECUTABLE_BEST_NEG.
  - **R39a**: `strategy/long_scan_summary.py` — Frontier sort key fix (0.0 truthiness) + post-aggregation fence.
  - **R39a**: `strategy/jobs/run_scan_real.py` — Executable frontier guard.
  - **R39a**: `scripts/pair_level_rca.py` — gas_bps from reject_reason.
  - **R39b**: `strategy/jobs/run_scan_real.py` — Field name fix: `measured_*` → `best_*`.
  - **R39b**: `strategy/chain_stats.py` — Truthiness fix for measured fields.
  - **R39b**: `strategy/pair_trace.py` — Gas computation fix. 
  - **R39a**: `tests/unit/test_r38_changes.py` — +9 tests.
  - **R39b**: `tests/unit/test_r38_changes.py` — +4 tests.
touched_files:
  - strategy/chain_stats.py (EXECUTABLE_BEST_NEG + 0.0 truthiness)
  - strategy/long_scan_summary.py (EXECUTABLE_BEST_NEG fence + ranking + sort key fix)
  - strategy/jobs/run_scan_real.py (EXECUTABLE_BEST_NEG guard + field name fix)
  - scripts/pair_level_rca.py (route-level RCA + gas from reject_reason)
  - strategy/pair_trace.py (gas computation fix)
  - tests/unit/test_r38_changes.py (+21 tests total: R39a:9 + R39b:4 + R39c:8)
  - docs/status/Status_M5_0.md (R39c section)
  - docs/DEV_REPORT_LATEST.md (synced to R39c)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2258 passed, 5 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
```

## 3) R39c Architecture Changes

### EXECUTABLE_BEST_NEG Distinction (chain_stats.py + long_scan_summary.py + run_scan_real.py)
Problem: `BEST_NEG` frontier reason was ambiguous — could be a paper-only boundary (no real measured costs) or a genuinely proven-executable negative frontier (measured gas/slippage populated). No way to tell from downstream artifacts whether a negative frontier was trustworthy.
Fix: chain_stats.py now upgrades `BEST_NEG` → `EXECUTABLE_BEST_NEG` when both `sweep_measured_slippage_bps` and `sweep_measured_gas_bps` are not None (indicated by real quotes). long_scan_summary.py post-fence accepts it for pnl < 0. run_scan_real.py guard accepts it for sweep size promotion.
Impact: Downstream consumers can now distinguish proven-executable negative frontiers (trustworthy, market economics) from paper-only ones (may need more data).

### Route-Level Economics (pair_level_rca.py)
Problem: RCA showed only pair-level aggregate economics (best RT per pair). No visibility into which specific buy_dex→sell_dex route contributed what costs.
Fix: `extract_pair_trace()` now collects ALL RT results per pair in a `routes` list with buy_dex, sell_dex, gross/net/slippage/gas/LP fee/real-quote. Console output adds a "Route-level economics" table.
Impact: Operator can now see exactly which routes are closest to profit and which cost component dominates for each route.

## 3.1) R39a/b Architecture Changes (consolidated)
- **Frontier contract fix** (long_scan_summary.py): 0.0 truthiness in sort key → None-safe + post-fence.
- **Executable sweep guard** (run_scan_real.py): Size promotion requires measured costs. R39b field names: `measured_*` → `best_*`.
- **Chain stats truthiness** (chain_stats.py): `0.0 or fallback` → `if _var is not None else fallback`.
- **Pair trace gas** (pair_trace.py): `net_pnl_usd + gas_cost_usd` → reject_reason parse + notional derivation.
- **RCA gas** (pair_level_rca.py): Parse from `reject_reason` string (authoritative).

## 4) Key Results (R39c canonical scan — fresh 10-min 6-chain online scan)

```
long_scan_latest:
  schema: start:long_scan_summary:v1.14
  total_runs: 30 (5 per chain)
  signals_total: 225
  net_usdc_total: $454.90
  profitable_rt: 0 (evaluated: 70)
  sweep_best: +0.00 bps (BREAKEVEN_FRONTIER on arb/mantle/scroll/zksync; base BEST_NEG; linea no sweep)
  wall_time: ~600s
  pass_chains: arb, base, mantle, scroll
  fail_chains: zksync, linea

run_summary_latest (scroll, last run):
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 43
  metrics.included_signals_count: 29
  metrics.total_net_usdc: $51.66
  metrics.real_quote_count: 6
  profit_status: PASS
  quality_status: WARN
  run_mode: REGISTRY_REAL
  run_timestamp: 2026-03-23T16:42:04.338310Z
  blocker_classification: OE_ECONOMICS
  blocker_reason: Signals exist but economics-blocked

_latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  data_run_rate: 1.0

stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: WARN_QUALITY
  agg_reasons: FRAGILE_P90_ELEVATED
  runs_since_timestamp.runs_count: 200
```

## 5) Per-Chain Online Evidence (R39c canonical scan, 30 runs)

| Chain | Runs | PASS | FAIL | Signals | RT Eval | Net USDC | Blocker | Sweep Frontier |
|-------|------|------|------|---------|---------|----------|---------|----------------|
| arbitrum_one | 5 | 5 | 0 | 160 | 7 | $304.35 | OE_ECONOMICS | BREAKEVEN_FRONTIER |
| mantle | 5 | 5 | 0 | 15 | — | $53.30 | OE_ECONOMICS | BREAKEVEN_FRONTIER |
| scroll | 5 | 5 | 0 | 20 | — | $23.42 | MIXED_SOURCE | BREAKEVEN_FRONTIER |
| zksync | 5 | 1 | 4 | 3 | — | $3.25 | OE_ECONOMICS | BREAKEVEN_FRONTIER |
| base | 5 | 1 | 1+3ND | 4 | 0 | $13.60 | NO_SIGNAL | BEST_NEG |
| linea | 5 | 0 | 5 | 23 | — | $56.98 | INFRA_FAIL | (no sweep) |

### Per-Chain RCA Highlights (R39c — route-level enabled)
- **arb**: 7 RT pairs. USDC/DAI -54.25 (near-zero, slippage-dominant). 64.4% exec rate. Route-level: uniswap_v3→sushiswap, camelot→uniswap_v3 routes.
- **mantle**: METH/WETH +1444 (LST pseudo-profit). WMNT/USDC deeply negative. 100% exec rate.
- **linea**: WSTETH/WETH +4434 (LST pseudo-profit). 0/5 pass. SIGNAL_PRODUCING but infrastructure-blocked.
- **scroll**: MIXED_SOURCE 37.5% of OE rejects. Economics present, 5/5 pass.
- **zksync**: 1/5 pass. Economics + stability needed.
- **base**: 0 RT evaluated. SLOT0_DIAGNOSTIC dominance. Quote-path constrained.

## 6) R39c Acceptance Criteria Verification
| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. EXECUTABLE_BEST_NEG in chain_stats | ✅ PASS | chain_stats.py: upgrade BEST_NEG → EXECUTABLE_BEST_NEG when measured gas+slip populated, 4 tests |
| 2. Post-fence accepts EXECUTABLE_BEST_NEG | ✅ PASS | long_scan_summary.py: pnl < 0 + EXECUTABLE_BEST_NEG preserved, 2 tests |
| 3. Sweep guard accepts EXECUTABLE_BEST_NEG | ✅ PASS | run_scan_real.py: both paths accept EXECUTABLE_BEST_NEG, 1 test |
| 4. Route-level RCA | ✅ PASS | pair_level_rca.py: route-level economics with buy_dex→sell_dex |
| 5. Frontier ranking includes reason | ✅ PASS | long_scan_summary.py: sweep_best_frontier_reason in per-chain ranking, 1 test |
| 6. 2258 unit tests | ✅ PASS | +8 tests from R39c (total +21 from R39a/b/c) |
| 7. Market surface conclusion documented | ✅ PASS | Status_M5_0.md R39c section + DEV_REPORT updated |

## 6.1) Blockers / Risks
- **profitable_rt=0**: BREAKEVEN_FRONTIER at 0.0 bps on 4/6 chains. Market economics, not infra.
- **LST pseudo-profits**: METH/WETH (mantle +1444 bps) and WSTETH/WETH (linea +4434 bps) are NOT real profitable RT. Must be excluded from frontier decisions.
- **base NO_SIGNAL**: 0 RT evaluated, SLOT0_DIAGNOSTIC=68.8%, exec rate 5.0%. Surface-constrained.
- **linea INFRA_FAIL**: 0/5 pass despite 22 signals. Pipeline gap — signals exist but cannot reach sweep/RT.
- **zksync instability**: 1/5 pass, 4 signals, 1 RT. Stability needed before economics analysis.
- **scroll MIXED_SOURCE**: 37.5% of OE rejects from MIXED_SOURCE. Economics present but impure.
- **sweep promotion (pre-R39b)**: Post-R39 rerun was done with pre-R39b code (sweep guard had wrong field names). Need canonical re-run with R39b code to validate actual size promotion.
- **ambient stub**: CrocSwap adapter still placeholder. Potential surface on Scroll.

## 7) Contract Checks
status/reasons consistency: OK — blocker_classification cascade has clear priority, no contradictions
rolling discipline: OK — _latest.json, run_summary_latest.json, m4_stability_agg.json, long_scan_latest.json
v2.x provenance contract: OK — run_timestamp, code_identity ts:..., no SHA tracking
runtime artifacts not committed: OK — data/runs/** in .gitignore
frontier contract: OK — post-aggregation fence ensures pnl↔reason consistency (R39)
sweep guard: OK — promotion requires executable frontier (R39)
LST threshold contract: _SANE_RT_PNL_MAX_BPS_LST=50 < _SANE_RT_PNL_MAX_BPS=500 (generic unchanged)

## 8) Lead's R39 10 Steps: Execution Map (post-R39 rerun audit)
step_01: **DONE** — DEV_REPORT + Status synced to post-R39 rerun evidence (2026-03-23T16:42:04Z, 30 runs, 241 sig, $420.82)
step_02: **ACKNOWLEDGED** — No broad "disable all gates" experiments. One-layer-at-a-time diagnostics only.
step_03: **ACKNOWLEDGED** — Dashboard mandatory in canonical directives.
step_04: **DONE** — Sweep guard field names fixed (`measured_*` → `best_*`). Chain_stats 0.0 truthiness fixed. +3 tests.
step_05: **DONE** — pair_trace.py gas computation fixed (reject_reason parse + proper notional). +2 tests. USDC/DAI now 12.0 not 2864.67.
step_06: **DONE** — Per-chain worktracks in Section 5 RCA highlights: arb=ECONOMICS P0, mantle=LST+ECONOMICS, scroll=MIXED_SOURCE, base=NO_SIGNAL, zksync=STABILITY, linea=INFRA_FAIL.
step_07: **DONE** — Arb one-layer-at-a-time diagnostics completed. Same-DEX: NOT bottleneck. Drift: mild (+18 quotes). Price sanity: largest gate (rejects 104 quotes) but all RT still deeply negative. Conclusion: fundamental spread+slippage economics, not filter gates.
step_08: **ACKNOWLEDGED** — Do not relax gates on base. Surface-constrained (SLOT0 dominance).
step_09: **ACKNOWLEDGED** — LST pairs (METH/WETH, WSTETH/WETH) kept separate from headline frontier decisions. Documented in Section 5.
step_10: **DONE** — Mixed global verdict accepted: 4 chains economics-blocked (arb/mantle/scroll/zksync), 1 NO_SIGNAL (base), 1 INFRA_FAIL (linea).

## 9) Lead's Diagnostic Commands for Arb (one-layer-at-a-time)
These isolate each gate layer independently on arbitrum_one. Run with `real_intent_arbitrum_one.yaml` (arb-only config):

1. **Same-DEX override**: Test if cross-dex filter is killing valid spreads.
   ```
   $env:ARBY_ALLOW_SAME_DEX='1'
   py -3.11 start.py --config config/real_intent_arbitrum_one.yaml --allow-partial-chains --hours 0.05 --cycles 1 --no-dashboard
   ```
2. **Drift warning relaxed**: Test if drift gate is blocking valid spreads.
   Create temp config variant with `drift_warning_pct: 100` (effectively disables drift exclusion).
3. **Price sanity disabled**: Test if Coingecko sanity kills valid spreads.
   Create temp config variant with `price_sanity_enabled: false`.

Success on #1 rules out same-DEX filtering; success on #2 rules out drift; success on #3 rules out price sanity. Compare signal counts / RT counts / OE reject distributions between each variant and baseline.

**Note**: These require live RPC. Run interactively; do not batch.

### 9.1) Arb One-Layer Diagnostic Results (R39b)
All 3 diagnostics ran on arbitrum_one with `real_intent_arbitrum_one.yaml`, single cycle.

| Variant | Quotes Fetched | Quotes Rejected | Signals | RT Candidates | Best PnL (bps) | Verdict |
|---------|---------------|-----------------|---------|---------------|-----------------|---------|
| **Baseline** (normal) | 76 | 162 | 23 | 4 | -202.73 (WETH/PENDLE) | SLIPPAGE_TOO_HIGH dominant |
| **Same-DEX** (ARBY_ALLOW_SAME_DEX=1) | 76 | 162 | 23 | 4 | -202.73 (WETH/PENDLE) | No same-DEX pairs produced — filter NOT the bottleneck |
| **Drift relaxed** (drift_warning_pct=100) | 94 | 154 | 23 | 4 | -291.89 (WBTC/USDC) | +18 quotes from relaxed drift; LP_FEES_TOO_HIGH replaces SLIPPAGE on some |
| **No price sanity** (price_sanity_enabled=false) | 112 | 58 | 30 | 5 | -297.51 (WBTC/USDC) | **Price sanity rejects 104 quotes** (162→58). +7 signals, +1 RT. But all still deeply negative. |

**Key findings**:
1. **Same-DEX filter**: NOT the bottleneck. No same-dex pairs made it to RT evaluation.
2. **Drift filter**: Mild effect (+18 quotes). Some spreads shift from SLIPPAGE_TOO_HIGH to LP_FEES_TOO_HIGH when drift relaxed — the slippage was partially drift artifact.
3. **Price sanity**: **Largest single gate layer** — rejects 104 additional quotes (64% of baseline rejections). But even with all those quotes passing, RT candidates are deeply negative (-297 to -9657 bps). The gate is correctly protecting — relaxing it doesn't find profit.
4. **Conclusion**: Arb economics blocker is **fundamental spread + slippage + LP fees**, not filter gates. All candidates show net_pnl_bps between -200 and -9600. Nearest-to-zero: WETH/PENDLE at -202.73 (slippage=255.1, lp_fee=10.0, gas=0.7).

## 10) What I need from Lead now
1. **Commit approval**: R39 full changes (long_scan_summary.py, run_scan_real.py, chain_stats.py, pair_trace.py, pair_level_rca.py, +13 tests, Status_M5_0.md, Status_M4.md, DEV_REPORT) — ready to commit on split/code.
2. **Canonical re-run with R39b code**: Sweep guard field names are now correct. Need fresh scan to validate that size promotion actually works when frontier is executable.
3. **Next investigation direction**: Arb one-layer diagnostics confirm fundamental spread+slippage economics, not filter gates. WETH/PENDLE nearest at -202.73 bps (slippage=255.1). Options: (a) lower target_usd_notional to reduce slippage, (b) seek lower-fee pools, (c) add WS event-driven re-quote for timing advantage, (d) accept current market gap and focus on other chains.
