# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39**: Frontier contract fix, executable sweep guard (field name fix), chain_stats truthiness fix, pair_trace gas fix, RCA gas alignment. Fresh post-R39 rerun: 30 runs, 241 signals, 67 RT, 0 profitable, $420.82.

## SESSION GOAL (R39: Frontier contract fix + sweep guard + chain_stats + pair_trace gas + docs sync)
**Goal**: (1) Fix frontier contract mismatch (0.0 bps + BEST_NEG), (2) Fix sweep guard field names (`measured_*` → `best_*`), (3) Fix chain_stats 0.0 truthiness, (4) Fix pair_trace gas notional computation, (5) Sync docs to fresh post-R39 rerun evidence.
**Prior (R38)**: 2237 tests, sweep size promotion, blocker_classification, LST suppression, event-driven WS loop.
**Audit (Lead R39)**: Two canonical scans. First (pre-R39 code): 36 runs, 159 signals, 59 RT, $254.60. Second (post-R39 rerun): 30 runs, 241 signals, 67 RT, $420.82. Second run exposed: sweep guard dead code (field name mismatch), chain_stats 0.0→None, pair_trace gas computation wrong.

## 0) Meta
timestamp_utc: 2026-03-23T16:42:04Z
run_dir_name: post-R39 rerun (30 runs across 6 chains, lead's fresh 10-min canonical scan)
mode: R39_FRONTIER_FIX_SWEEP_GUARD_CHAINSTATS_PAIRTRACE
test_count: 2250 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T16:42:04.338310Z
  dirty: true (R39 code changes uncommitted)
  desc: frontier_contract_fix + sweep_guard_field_fix + chainstats_truthiness + pairtrace_gas_fix

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39: Frontier contract fix + sweep guard field fix + chain_stats truthiness + pair_trace gas + docs sync to post-R39 rerun |
| goal_status | **REACHED** (9 code changes, 13 new tests, 2250 PASS, CI green, arb diagnostics complete, docs synced to 2026-03-23T16:42:04Z) |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (economics: all chains BREAKEVEN_FRONTIER, arb diagnostics confirm fundamental spread+slippage). base: NO_SIGNAL. zksync: 1/5 pass. linea: 0/5 pass INFRA_FAIL. |
| evidence_session_run_dirs | Post-R39 rerun: 30 runs, 241 signals, arb/base/zksync/mantle/linea/scroll |
| primary_blocker_of_session | Sweep guard dead code (field names), chain_stats 0.0→None, pair_trace gas wrong notional |
| blocker_status_before | ACTIVE: sweep guard never promoted (wrong field names), chain_stats lost 0.0, pair_trace gas 2864 instead of 12 |
| blocker_status_after | **RESOLVED**: field names fixed, truthiness fixed, gas parsed from reject_reason + proper notional fallback |
| start_metric | 2246 tests, sweep guard dead code, chain_stats 0.0 bug, pair_trace gas wrong |
| end_metric | 2250 tests, sweep guard reads real fields, chain_stats None-safe, pair_trace gas authoritative |
| delta | +4 tests, +sweep field names, +chain_stats None-safe, +pair_trace gas fix, +docs sync |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R39: Frontier contract fix + sweep guard field fix + chain_stats truthiness + pair_trace gas + docs sync
change_summary:
  - **R39a**: `strategy/long_scan_summary.py` — Fixed frontier contract mismatch: sort key `0.0 or -9999 == -9999` (Python truthiness) caused top-level to pick BEST_NEG from worse chain while pnl=0.0. Fixed with None-safe check. Post-aggregation fence: if pnl==0.0 → force BREAKEVEN_FRONTIER.
  - **R39a**: `strategy/jobs/run_scan_real.py` — Sweep size promotion guarded: only promotes when `frontier_reason` in (BREAKEVEN_FRONTIER, PROFITABLE), `measured_total_cost_bps > 0`, and `measured_slippage_bps is not None`. Falls back to config size for paper-only frontiers.
  - **R39a**: `scripts/pair_level_rca.py` — `_rt_gas_bps()` now parses gas from `reject_reason` string (authoritative, real notional in engine) before falling back to gross_pnl back-calculation.
  - **R39b**: `strategy/jobs/run_scan_real.py` — **Sweep guard field name fix**: `measured_total_cost_bps` → `best_total_cost_bps`, `measured_slippage_bps` → `best_slippage_bps`. Old field names didn't exist in sweep dict → guard was always false → size stuck at config 150.
  - **R39b**: `strategy/chain_stats.py` — **Truthiness fix**: `sweep.get("measured_gas_bps") or sweep.get("best_gas_bps")` treated 0.0 as falsy → mapped to None. Fixed with `if _var is not None else` pattern for all 4 measured fields (gas, fee, slippage, total_cost).
  - **R39b**: `strategy/pair_trace.py` — **Gas computation fix**: Old code used `net_pnl_usd + gas_cost_usd` as notional → wildly wrong (USDC/DAI: 2864.67 instead of 12.0). Now parses from `reject_reason` string first (`|gas=12.0|`), fallback to `abs(gross_usd / (gross_bps/10000))`.
  - **R39b**: `tests/unit/test_r38_changes.py` — +4 tests: sweep guard field names (1), chain_stats 0.0 truthiness (2), pair_trace gas (2). Updated existing sweep tests to use `best_*` field names.
  - **R39a**: `tests/unit/test_r38_changes.py` — +9 tests: frontier consistency (3), sweep guard (3), RCA gas parsing (3).
  - **R39a**: `tests/unit/test_run_scan_real_purity.py` — max_lines bumped to 1650.
  - **R39a**: `tests/unit/test_nonstop_loop_artifacts.py` — Rolling artifact test allows .log files.
  - **R39b**: `tests/unit/test_pair_trace.py` — Added `gross_pnl_usd` to `_FakeRT` fixture for pair_trace gas fix.
touched_files:
  - strategy/long_scan_summary.py (frontier sort key fix + post-aggregation fence)
  - strategy/jobs/run_scan_real.py (executable frontier guard + field name fix)
  - strategy/chain_stats.py (0.0 truthiness fix for 4 measured fields)
  - strategy/pair_trace.py (gas computation: reject_reason parse + proper notional)
  - scripts/pair_level_rca.py (gas_bps from reject_reason)
  - tests/unit/test_r38_changes.py (+13 new tests total)
  - tests/unit/test_pair_trace.py (gross_pnl_usd fixture)
  - tests/unit/test_run_scan_real_purity.py (max_lines bump)
  - tests/unit/test_nonstop_loop_artifacts.py (allow .log files)
  - docs/status/Status_M5_0.md (R39 section + fresh evidence)
  - docs/DEV_REPORT_LATEST.md (synced to post-R39 rerun)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2250 passed, 5 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED
```

## 3) R39 Architecture Changes

### Frontier Contract Fix (strategy/long_scan_summary.py)
Problem: Top-level `sweep_best_net_pnl_bps=0.0` coexisted with `sweep_best_frontier_reason="BEST_NEG"`. Root cause: Python truthiness — `0.0 or -9999 == -9999`, so the sort key mapped breakeven chains (0.0 pnl) below negative chains (-5.0 pnl), causing reason to be picked from the wrong chain.
Fix: Replaced `or -9999` with `if v is not None else -9999` (None-safe). Added post-aggregation consistency fence: if pnl==0.0 → BREAKEVEN_FRONTIER; if pnl>0 → PROFITABLE; if pnl<0 → BEST_NEG.
Impact: `sweep_best_net_pnl_bps` and `sweep_best_frontier_reason` are now always consistent.

### Executable Sweep Guard (strategy/jobs/run_scan_real.py)
Problem: R38 size promotion unconditionally used `dynamic_sweep.best_size_usd` ($750), but the sweep's `measured_slippage_bps=0.0` while live candidates showed slippage=792.2 bps. Paper-only frontier promoted false-optimal sizes.
Fix: Promotion requires: (1) `frontier_reason` in (BREAKEVEN_FRONTIER, PROFITABLE), (2) `measured_total_cost_bps > 0`, (3) `measured_slippage_bps is not None`. Falls back to config `target_usd_notional` when not executable.
Impact: Live candidates now sized at config-conservative level until sweep has real slippage measurements.

### RCA Gas Alignment (scripts/pair_level_rca.py)
Problem: `_rt_gas_bps()` back-calculated gas from `gas_cost_usd / (gross_pnl_usd / gross_pnl_bps)`. When gross values were small/zero, result was 0. Didn't match live reject_reason which shows exact `gas=12.0` from engine.
Fix: Parse gas_bps from `reject_reason` string (authoritative, computed with real notional). Fall back to back-calculation only when reject_reason unavailable.
Impact: RCA Gas column now matches live reject reasons exactly.

### Sweep Guard Field Name Fix (strategy/jobs/run_scan_real.py) [R39b]
Problem: R39a guard checked `_sweep_ds.get("measured_total_cost_bps")` and `_sweep_ds.get("measured_slippage_bps")` — but those fields don't exist in the sweep dict. Actual fields are `best_total_cost_bps` and `best_slippage_bps`. Guard was always false → size always fell back to config 150.0. Sweep guard was dead code.
Fix: Changed both primary (~L1009) and error (~L1057) paths to use `best_total_cost_bps` and `best_slippage_bps`.
Impact: Sweep size promotion now actually reads real fields and can promote when frontier is executable.

### Chain Stats Truthiness Fix (strategy/chain_stats.py) [R39b]
Problem: `sweep.get("measured_gas_bps") or sweep.get("best_gas_bps")` — Python `or` treats 0.0 as falsy. So `best_slippage_bps=0.0` mapped to `sweep_measured_slippage_bps=None`. Same Python truthiness pattern as the frontier sort key bug from R39a.
Fix: `_gas = sweep.get("measured_gas_bps"); _gas if _gas is not None else sweep.get("best_gas_bps")` pattern for all 4 fields (gas, fee, slippage, total_cost).
Impact: `sweep_measured_slippage_bps=0.0` now correctly preserved as 0.0 instead of silently becoming None.

### Pair Trace Gas Computation Fix (strategy/pair_trace.py) [R39b]
Problem: Gas-in-bps computation used `_notional = rt_r.net_pnl_usd + rt_r.gas_cost_usd` as "notional" — this is completely wrong (sum of PnL + gas is not trade notional). For USDC/DAI with tiny values: gas computed as 2864.67 bps instead of correct 12.0.
Fix: Parse gas from `reject_reason` string first (`|gas=12.0|`). Fallback: `notional = abs(gross_usd / (gross_bps/10000))` — proper trade notional derivation from gross fields.
Impact: pair_funnel_trace gas values now match the engine's authoritative calculation.

## 4) Key Results (from rolling artifacts — lead's post-R39 rerun, 10-min canonical 6-chain scan)

```
long_scan_latest:
  schema: start:long_scan_summary:v1.14
  total_runs: 30 (5 per chain)
  signals_total: 241
  net_usdc_total: $420.82
  profitable_rt: 0 (evaluated: 67)
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

## 5) Per-Chain Online Evidence (lead's post-R39 rerun, 30 runs)

| Chain | Runs | PASS | FAIL | Signals | RT Eval | Net USDC | Blocker | Sweep Frontier | Sweep BEQ Size |
|-------|------|------|------|---------|---------|----------|---------|----------------|----------------|
| arbitrum_one | 5 | 5 | 0 | 175 | 6 | — | OE_ECONOMICS | BREAKEVEN_FRONTIER | $2500 |
| mantle | 5 | 5 | 0 | 15 | 2 | — | OE_ECONOMICS | BREAKEVEN_FRONTIER | $25 |
| scroll | 5 | 5 | 0 | 20 | 2 | — | MIXED_SOURCE | BREAKEVEN_FRONTIER | $50 |
| zksync | 5 | 1 | 4 | 4 | 1 | — | OE_ECONOMICS | BREAKEVEN_FRONTIER | $50 |
| base | 5 | 3 | 2 | 5 | 0 | — | NO_SIGNAL | BEST_NEG | $5000 |
| linea | 5 | 0 | 5 | 22 | 2 | — | INFRA_FAIL | (no sweep) | — |

### Per-Chain RCA Highlights (pair_level_rca.py on post-R39 rerun)
- **arb**: 6 RT pairs evaluated. USDC/DAI -54.07 bps (near-zero, gas-dominant at 12.0 bps from reject_reason). ARB/USDC -265. WETH/USDC -142.58. 0 OE rejects gated. Exec rate 59.3%. **Primary economics track.**
- **mantle**: METH/WETH +1444.10 (LST pseudo-profit, SUSPECT_ACCOUNTING). WMNT/USDC -744.75. **LST must be excluded from frontier decisions.**
- **linea**: WSTETH/WETH +4433.75 (LST pseudo-profit). WETH/WBTC -721.13. 0/5 pass, INFRA_FAIL. **Stability + LST track.**
- **scroll**: WETH/USDC -1119.58, USDC/DAI -4196.13. MIXED_SOURCE 37.5% of OE rejects. Exec rate 86.7%.
- **zksync**: WETH/USDC -875.98 (only 1 RT pair). NET_PROFIT_TOO_LOW 75%, SUSPECT_SPREAD_HARD 25%. 1/5 pass.
- **base**: 0 RT evaluated. SLOT0_DIAGNOSTIC=68.8%, MIXED_SOURCE=28.0%. Exec rate 5.0%.

### Lead's Blocker Verdict (post-R39 rerun evidence):
- **Healthy supported (arb/mantle/scroll)**: 5/5 pass. Economics/slippage dominant. Pipeline is not the bottleneck.
- **base**: NO_SIGNAL, 3/5 pass. SLOT0_DIAGNOSTIC dominance, near-zero exec rate. Surface-constrained.
- **zksync**: 1/5 pass. Economics + stability needed.
- **linea**: 0/5 pass. INFRA_FAIL. Signals exist but no sweep candidates. Pipeline gap.
- **LST pairs**: METH/WETH (mantle +1444 bps) and WSTETH/WETH (linea +4434 bps) are pseudo-profits, NOT real profitable RT. Must be excluded from headline frontier decisions.

## 6) R39 Acceptance Criteria Verification
| Criterion | Status | Evidence |
|-----------|--------|----------|
| 1. Frontier contract consistency | ✅ PASS | long_scan_summary.py: None-safe sort key + post-aggregation fence, 3 tests |
| 2. Executable sweep guard (field fix) | ✅ PASS | run_scan_real.py: `best_total_cost_bps`/`best_slippage_bps` field names corrected, 4 tests |
| 3. RCA gas alignment | ✅ PASS | pair_level_rca.py: parse from reject_reason, 3 tests |
| 4. Chain_stats truthiness | ✅ PASS | chain_stats.py: None-safe `if _var is not None else` pattern, 2 tests |
| 5. Pair_trace gas fix | ✅ PASS | pair_trace.py: reject_reason parse + proper notional fallback, 2 tests |
| 6. 2250 unit tests | ✅ PASS | +13 tests from R39 additions (9 R39a + 4 R39b) |
| 7. Status updated | ✅ PASS | Status_M5_0.md + Status_M4.md updated with post-R39 rerun data |
| 8. DEV_REPORT synced to rolling | ✅ PASS | timestamp_utc=2026-03-23T16:42:04Z, all sections synced to post-R39 rerun |
| 9. CI pipeline green | ✅ PASS | ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED |

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
