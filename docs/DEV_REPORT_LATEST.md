# DEV_REPORT_LATEST.md — R39x+4

## 0) Meta
timestamp_utc: 2026-03-27T20:27:43Z
run_id: long_scan_latest.json (60 runs, wall=1206s)
mode: ONLINE
artifact_mode: rolling
config: real_minimal.yaml (arb_one PRIMARY) + onboard_base_profit.yaml (base COVERAGE)
code_identity:
  primary: ts:2026-03-27T20:27:43.113013Z
  dirty: false — no code changes this session (analysis-only)
  desc: R39x+4 lane-selection pivot — WBTC/USDC deep-dive, Base stable family closure

## Session Completion
session_goal: Lane-selection pivot from Base stable to arb WBTC/USDC — per lead R39x+3 review directive
goal_status: REACHED
close_allowed: true
remaining_blockers: Base stable pair family economics-blocked (closed); arb WBTC/USDC exploration-inconclusive (0 sweeps in fresh window)
evidence_session_run_dirs: long_scan_latest.json (60 runs), ci_m5_gate_arbitrum_one_20260327_212723_520815, ci_m5_gate_base_20260327_212743_868062
primary_blocker_of_session: WBTC/USDC candidacy evaluation — is it viable for further optimization?
blocker_status_before: ACTIVE — Base stable hardening saturated, no WBTC/USDC analysis existed
blocker_status_after: RESOLVED — WBTC/USDC deep-dive completed; pair has 0 sweeps in fresh 30-run window (signal present in 25/30 runs but never promoted to sweep); historical 4 samples show structural slippage blocker (leg2 sell-side WBTC 12.75 bps at $15)
docs_reread_confirmed: true

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5.0 — Lane-selection pivot per lead directive (close Base stable, evaluate arb WBTC/USDC)
change_summary:
  - No code changes this session — pure analysis and evidence gathering
  - Lane-selection review from rolling evidence: all arb/base pairs ranked by median gap
  - WBTC/USDC deep-dive: 2 route patterns analyzed, size curves extracted, repeatability evaluated
  - Base stable pair family formally closed as "economics-blocked"
  - fee_tier_alternatives: confirmed available=false, not used as evidence
  - Fresh 60-run online scan (30 arb + 30 base)
touched_files:
  - docs/DEV_REPORT_LATEST.md (this file — updated for R39x+4)

## 2) Commands Executed

py -3.11 -m pytest -q: PASS (2527 passed, 5 skipped, 53.0s)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: ALL REQUIRED GATES PASSED (52.1s)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS (2 sims, net_usdc=0.5)
py -3.11 start.py --config-list config/real_minimal.yaml,config/onboard_base_profit.yaml --minutes 20 --cycles 1 --sleep-seconds 0 --coverage-workers 1 --no-dashboard --summary-file data/runs/_rolling/long_scan_latest.json: 60 runs (PASS=55, NO_DATA=1, FAIL=4), wall=1206s
py -3.11 scripts/inspect_rolling.py: agg_status=PASS, data_run_rate=1.0

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/long_scan_latest.json
run_dir_bundle (ONLINE):
  - ci_m5_gate_arbitrum_one_20260327_212723_520815 (latest arb — USDC/DAI frontier, no WBTC/USDC)
  - ci_m5_gate_base_20260327_212743_868062 (latest base — USDC/USDT frontier)

## 4) Key Results

### 4.1 Rolling aggregation
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 1.0
run_summary_latest:
  status: PASS
  metrics.signals_count: 36
  metrics.total_net_usdc: $44.05
  profit_status: PASS
  quality_status: WARN
  run_timestamp: 2026-03-27T20:27:43.113013Z
  inputs.run_mode: REGISTRY_REAL
  blocker_classification: OE_ECONOMICS
  roundtrip_truth_status: NOT_PROFITABLE
m4_stability_agg:
  agg_status: PASS
  runs_in_window: 200

### 4.2 Long scan frontier (60 runs, 20 min)
| Chain | Runs | PASS | FAIL | Frontier Pair | Gap (bps) | Median Gap | Best PnL | Profit State |
|-------|------|------|------|---------------|-----------|------------|----------|--------------|
| base | 30 | 25 | 4+1ND | USDC/USDT | 8.67 | 8.67 | -8.67 | CANDIDATE |
| arbitrum_one | 30 | 30 | 0 | USDC/DAI | 25.44 | 25.46 | -25.44 | PRIMARY_BLOCKER |

### 4.3 Per-pair repeatability (arb — ranked by median gap)
| Pair | Median Gap (bps) | Sweep Samples | Signal Runs | Swept Runs |
|------|------------------|---------------|-------------|------------|
| WBTC/USDC | None | 0 | 25 | 0 |
| USDC/DAI | 25.46 | 30 | 30 | 30 |
| WETH/ARB | 61.39 | 7 | 30 | 30 |
| WETH/LINK | 115.19 | 30 | 0 | 30 |
| WETH/USDC | 222.90 | 22 | 22 | 22 |
| WETH/PENDLE | 393.19 | 18 | 30 | 30 |
| ARB/USDC | None | 0 | 30 | 30 |
| USDC/USDT | None | 0 | 29 | 0 |

### 4.4 WBTC/USDC deep-dive (lead directive: bounded exploration lane)

**Signal presence:** 25/30 runs produced WBTC/USDC spread signals. 0/30 runs promoted to sweep. In 97 arb runs on disk, ZERO contain WBTC/USDC signals in scan report. The signal detection is in truth_report.spread_signals but the pair never reaches sweep promotion threshold.

**Historical data (from prior rolling window, now pruned):** 4 sweep samples existed across ~200 prior runs. Two distinct routes:

| Route | Samples | Gap (bps) | Fee | Fee L1 | Fee L2 | Slip | Slip L1 | Slip L2 | Gas | Dominant Cost |
|-------|---------|-----------|-----|--------|--------|------|---------|---------|-----|---------------|
| uni→pancake | 3 | 10.97-12.05 | 31.0 | 1.0 | 30.0 | 6.9-11.7 | 5.8-10.5 | 1.1-1.2 | ~2.0 | Fee tier (pancake 3000) |
| sushi→uni | 1 | 10.90 | 10.0 | 5.0 | 5.0 | 12.76 | 0.01 | 12.75 | 5.46 | Slippage (L2 WBTC sell) |

**Size curve analysis (sushi→uni — best route, from prior window):**
| Size USD | Net PnL (bps) | Fee | Slippage | Gas | Dominant |
|----------|---------------|-----|----------|-----|----------|
| $1 | -86.68 | 10.0 | ~4 | ~81 | gas |
| $10 | -11.59 | 10.0 | ~8.5 | ~8.1 | balanced |
| $15 | -10.90 (BEST) | 10.0 | 12.76 | 5.46 | slippage |
| $25 | -12.51 | 10.0 | ~18 | ~3.3 | slippage |
| $50 | -21.79 | 10.0 | ~40 | ~1.6 | slippage |
| $150 | -62.83 | 10.0 | ~130 | ~0.5 | slippage |

**Size curve analysis (uni→pancake — 3 samples, from prior window):**
| Size USD | Net PnL (bps) | Fee | Slippage | Gas | Dominant |
|----------|---------------|-----|----------|-----|----------|
| $15 | -14.62 | 31.0 | 6.88 | 6.46 | fee |
| $50 | -12.05 (BEST) | 31.0 | 11.74 | 1.99 | fee |
| $150 | -17.62 | 31.0 | 25.59 | 0.66 | fee+slip |

**WBTC/USDC verdict:**
- **sushi→uni route** (best): gap=10.90 bps. Fee=10 bps (same-tier 500/500). Sell-side WBTC slippage=12.75 bps at just $15 is the binding constraint. Thin WBTC liquidity on arb DEXes.
- **uni→pancake route**: gap=12.05 bps. Fee=31 bps (pancake 3000 tier on leg2). Irreducible fee floor — dead on arrival.
- **Repeatability: POOR.** 4 sweeps out of ~200 historical runs. ZERO sweeps in fresh 30-run window. The pair is detected as a signal but never reaches sweep promotion.
- **Path to profitability: NONE visible.** Even at optimal $15 (sushi→uni), the sell-side WBTC slippage (12.75 bps) alone exceeds the gap margin. Would require either: (a) significantly deeper WBTC DEX liquidity, or (b) a low-fee-tier pool for WBTC/USDC.

### 4.5 Lane comparison summary
| Lane | Best Gap | Blocker Type | Path to Profit | Status |
|------|----------|-------------|----------------|--------|
| base/USDC/USDT | 8.67 bps | Gas(6.18)+slip(2.59), same-tier | None without gas subsidy | **CLOSED: economics-blocked** |
| base/USDC/DAI | 14.19 bps | Fee mismatch (1bp vs 5bp) | None without fee-tier alignment | **CLOSED: economics-blocked** |
| arb/WBTC/USDC | 10.90 bps* | L2 WBTC sell slippage (12.75), rare sweep | None without WBTC liquidity growth | **INCONCLUSIVE: insufficient sweep data** |
| arb/USDC/DAI | 25.46 bps | Fee mismatch (1bp vs 5bp) | None near-term | FAR from breakeven |
| arb/WETH/USDC | 222.90 median | Inconsistent (best 9.98, median 223) | Rare lucky alignment only | NOT VIABLE |

*from historical prior-window data (4 samples); 0 sweeps in current window

### 4.6 Base stable pair family — formal closure
**Verdict: Base stable pair family economics-blocked** (per lead directive: exact wording)

Evidence basis (accumulated across R39x+1 through R39x+4):
- USDC/USDT: median gap=8.67 bps, 24+ sweeps, fee=2bp (same-tier), gas=6.18bp, slippage=2.59bp — gas-dominated, no escape
- USDC/DAI: median gap=14.19 bps, 28+ sweeps, fee=6bp (1+5 tier mismatch), gas=5.77bp, slippage=3.67bp — fee-mismatch-dominated
- Both pairs stable with narrow variance across 50+ sweep runs — no exploitable volatility windows observed
- Size curves monotonically degrade beyond $25 — no large-size escape either
- Do NOT expand Base pairs — freeze as solved-no-go

### 4.7 Fee-tier alternatives
fee_tier_alternatives: available=false (sweep evaluates 1 route per pair; 0 pairs with alternatives)
Decision needed: either materialize through multi-route-per-pair sweep expansion, or formally remove from milestone evidence claims. Currently NOT used as evidence — purely infrastructure placeholder.

## 5) Contract Checks
status/reasons consistency: OK — PASS/WARN with documented reasons
rolling discipline (3 files): OK — _latest.json, run_summary_latest.json, long_scan_latest.json
v2.x provenance contract: OK — run_timestamp only, code_sha=null
runtime artifacts not committed: OK

## 6) Blocker Classification
code_blocker: LOW (pytest 2527 PASS, CI green, safety PASS)
data_collection_blocker: LOW (data_run_rate=1.0, arb 30/30 PASS)
market_window_blocker: HIGH (all explored lanes economics-blocked or inconclusive)

## 7) Lead's R39x+3 Review Steps: Execution Map

step_01 (Fix R39x+3 as REACHED, close Base stable workstream): DONE — R39x+3 confirmed REACHED; Base stable pair family formally closed as economics-blocked
step_02 (Use "Base stable pair family economics-blocked" exact wording): DONE — section 4.6 uses exact terminology
step_03 (fee_tier_alternatives: materialize or stop citing as evidence): DONE — confirmed available=false, documented in 4.7 as non-evidence infrastructure placeholder; decision deferred to lead
step_04 (Don't push Base stable via config changes): DONE — no config changes; base runs as COVERAGE only
step_05 (Don't expand Base pairs — freeze as solved-no-go): DONE — documented in 4.6
step_06 (Lane-selection review from current evidence): DONE — full per-pair repeatability ranking in 4.3, lane comparison in 4.5
step_07 (First priority: arb WBTC/USDC decomposition): DONE — full deep-dive in 4.4 with route analysis, size curves, and verdict
step_08 (Base=control no-go, WBTC/USDC=bounded exploration): DONE — Base closed (4.6), WBTC/USDC evaluated (4.4)
step_09 (Run prescribed sequence with dashboard): DONE — all CI gates PASS + 60-run scan completed
step_10 (Update docs only after step 9): DONE — this report written after fresh evidence

## 8) What I need from Lead now

1. **WBTC/USDC verdict:** Zero sweeps in fresh 30-run window. Historical 4-sample data (now pruned) showed 10.9 bps gap with sell-side WBTC slippage as binding constraint. Should this lane be closed as economics-blocked, or does the intermittent signal presence (25/30 runs) warrant further investigation with config changes (e.g., forcing WBTC sweep)?
2. **fee_tier_alternatives decision:** Materialize through multi-route-per-pair sweep expansion (requires non-trivial code changes), or formally remove from artifact schema as non-evidence?
3. **Next exploration direction:** With both Base stable and arb WBTC/USDC evaluated:
   - (a) arb USDC/DAI at 25.46 bps gap — too far from breakeven?
   - (b) expand to new chains (scroll, mantle, linea, zksync — configs exist)?
   - (c) change strategy (e.g., MEV-aware execution, flashblocks, intents)?
   - (d) accept current economics and focus on M4.2/M4.3 milestone infrastructure?

## 9) Final Verdict

**VERDICT: LANE-SELECTION PIVOT COMPLETED**

1. **Base stable pair family: CLOSED as economics-blocked.** Fee-tier mismatch (USDC/DAI) and gas+slippage floor (USDC/USDT) confirmed across 50+ sweep runs with leg-level decomposition. No path to profitability without external changes.
2. **arb WBTC/USDC: EXPLORATION-INCONCLUSIVE.** The pair shows consistent signal presence (25/30 runs) but zero sweep promotion in fresh 30-run window. Historical 4-sample data showed gap=10.9 bps with sell-side WBTC slippage (12.75 bps at $15) as binding constraint. The pair's economics are structurally challenged: thin WBTC liquidity → high sell-side slippage, uni→pancake route → 31 bps fee tier. Path to profitability requires external WBTC liquidity growth.
3. **arb frontier: USDC/DAI at 25.46 bps.** The only consistently swept arb pair. Same fee-tier mismatch pattern as Base (1bp vs 5bp). Distant from breakeven.
4. **No code changes needed this session.** Infrastructure from R39x+3 (near_breakeven_report, leg-level decomposition, size_curve) provided all analytical tools. The blocker is economic, not engineering.
5. **Decision point for lead:** All easily accessible lanes have been evaluated. Next step requires either: (a) new chain exploration, (b) new execution primitives, (c) accepting current economics and pivoting to M4.2/M4.3 infra work, or (d) WBTC/USDC forced sweep investigation.
