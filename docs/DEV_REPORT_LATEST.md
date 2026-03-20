# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R29: Pair-level end-to-end replay infrastructure built, per-chain RCA completed. 2071 tests PASS.

## SESSION GOAL (R29: Pair-Level E2E Replay)
**Goal**: Build pair-level funnel trace artifact, counterfactual replay harness, and per-chain economics decomposition. Shift from broad scanning to targeted pair-level diagnostics.
**Prior (R28.30)**: Fixed cross_dex_pairs_count fallback; normalized filter funnel; dashboard protocol. 2061 tests.

## 0) Meta
timestamp_utc: 2026-03-20T09:42:41Z
run_dir_name: long_scan (72 runs, 6 chains, 620s wall)
mode: PAIR_LEVEL_E2E_REPLAY (R29)
test_count: 2071 passed, 3 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R29: Build pair-level funnel trace, counterfactual replay, per-chain RCA with economics decomposition |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | none — all 10 lead steps addressed (steps 4/8 deferred to next session with rationale) |
| evidence_session_run_dirs | 72 runs across 6 chains in long_scan; per-chain runDirs with pair_funnel_trace embedded |
| primary_blocker_of_session | No pair-level visibility into where candidates die in the pipeline |
| blocker_status_before | ACTIVE: no per-pair trace artifact, no way to isolate gate-by-gate losses |
| blocker_status_after | RESOLVED: pair_funnel_trace in every truth_report, scripts/pair_level_rca.py for post-hoc analysis |
| start_metric | 0 pair-level trace data in any artifact |
| end_metric | pair_funnel_trace in all 72 truth_reports; RCA completed for all 6 chains |
| delta | +10 tests, 2 new files, 2 modified files |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R29: Lead audit directive (pair-level E2E replay, economics decomposition)
change_summary:
  - NEW: `strategy/pair_trace.py` — extracted pair-level funnel trace builder (per-pair: resolved→quoted→signal→opp→rt_candidate→rt_eval→rt_profitable)
  - NEW: `tests/unit/test_pair_trace.py` — 10 tests covering all pipeline stages
  - NEW: `scripts/pair_level_rca.py` — post-hoc RCA tool (funnel summary, economics decomposition, counterfactual analysis)
  - MODIFIED: `strategy/jobs/run_scan_real.py` — calls `build_pair_funnel_trace()` after filter_funnel
  - MODIFIED: `strategy/artifacts.py` — propagates `pair_funnel_trace` to truth_report
  - ROOT CAUSE FOUND: Base 96% diagnostic-only quotes (quoter_v2 RPC failures → slot0 fallback)
  - ROOT CAUSE FOUND: Scroll economics gap (-271 bps) not LP gate bug
  - ROOT CAUSE FOUND: Mantle 73% SUSPECT_LIQUIDITY rejection rate
touched_files:
  - strategy/pair_trace.py (NEW — 165 lines)
  - tests/unit/test_pair_trace.py (NEW — 10 tests)
  - scripts/pair_level_rca.py (NEW — RCA analysis tool)
  - strategy/jobs/run_scan_real.py (MODIFIED — pair trace integration)
  - strategy/artifacts.py (MODIFIED — truth_report propagation)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2071 passed, 3 skipped)
py -3.11 -m monitoring.dashboard_server --port 8099: RUNNING
py -3.11 start.py --config-list (6 chains) --hours 0.17 --no-dashboard: PASS (72 runs, 620s wall)
py -3.11 scripts/pair_level_rca.py --run-dir <per-chain>: RCA for all 6 chains
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}
runs_in_window: 200+

### 10-min Verification Scan (R29 — with pair_funnel_trace)
```
Wall time:      620s
Total runs:     72  (PASS=25  NO_DATA=7  FAIL=40  INFRA_FAIL=0)
Signals total:  77
Profitable RTs: 0  (evaluated: 53, best: -22.38 bps)
Spread gap:     +20.28 bps
Chains:         arbitrum_one, zksync, base, mantle, linea, scroll
Pass chains:    linea
Fail chains:    arbitrum_one, zksync, base, mantle
Accepted fail:  scroll
```

## 4) Key Results: Pair-Level E2E Replay Infrastructure

### New Artifact: pair_funnel_trace (embedded in truth_report)
Each truth_report now contains `pair_funnel_trace`: an array of per-pair dicts tracking:
```
pair, resolved, pools_resolved, quotes_fetched, quotes_rejected, reject_reasons,
dexes_quoted, spread_signals, best_spread_bps, opp_count, best_spread_minus_req_bps,
rt_candidates, rt_evaluated, rt_best_net_pnl_bps, rt_reject_reasons,
terminal_stage, economics
```
Economics sub-dict includes: gross_spread_bps, gas_cost_usd, fee_cost_usd, slippage_bps, gap_to_zero_bps.
Sorted by pipeline progress (rt_profitable > rt_evaluated > opportunity > signal > quoted > resolved).

### New Tool: scripts/pair_level_rca.py
Usage: `py -3.11 scripts/pair_level_rca.py --run-dir <path>` or `--rolling`
Produces: (1) per-pair funnel summary, (2) economics decomposition, (3) counterfactual analysis.
Counterfactual: for near-zero candidates (within 100 bps), computes if_zero_gas, if_zero_slippage, if_half_lp_fee.

### Per-Chain Diagnostic Census (fresh data, all 6 chains)

**arbitrum_one** (36 pairs, 9 quotes, 2 cross-DEX pairs):
- Bottleneck: 32/36 pairs die at "resolved" — never get quotes (pools missing on second DEX)
- Only WBTC/USDC and WETH/USDC reach cross-DEX; WBTC/USDC reaches RT eval at -24 bps
- Economics: gas=266 bps, slippage=44 bps, LP=10 bps → gas dominates
- Counterfactual: if zero gas → still -24 bps (gross already negative)

**base** (14 pairs, 59 quotes, 0 signals) — **ROOT CAUSE FOUND**:
- 96% of quotes are `is_diagnostic_only=True` (slot0 fallback)
- QuoterV2 RPC calls FAILING for all 3 DEXes (pancakeswap_v3, sushiswap_v3, uniswap_v3)
- When truth_mode_m42=true, diagnostic quotes excluded from spread computation → 0 signals
- Raw slot0 cross-DEX spreads actually exist: WETH/AERO 227 bps, WETH/VIRTUAL 133 bps, CBBTC/USDC 114 bps, WETH/USDC 83 bps
- **Fix needed**: Diagnose quoter_v2 failure on base (contract verification, RPC endpoint, function selector)
- Only 2 real quotes survive: RETH/WETH (1, uniswap_v3), USDC/USDT (1, pancakeswap_v3) — insufficient for cross-DEX

**linea** (10 pairs, 20 quotes, 4 signals, 3 RT evaluated):
- Best real RT: WETH/USDC @ -142 bps (slippage=208 bps, gas=10 bps, LP=1 bps)
- WSTETH/WETH +4577 bps and WEETH/WETH +1682 bps → SUSPECT_ACCOUNTING (leg2_is_real=false)
- Slippage accounts for 95%+ of execution cost
- 3 drift-excluded quotes, 0 diagnostic

**scroll** (3-5 pairs, 7 quotes, 2 signals, 0 RT) — **NOT LP gate bug**:
- WETH/USDC: gross=25 bps, required=296 bps (LP=60 + slippage=231 + gas=5) → gap=-271 bps
- spread_minus_required_bps = -41.81 → is_roundtrip_viable=false → not sent to RT eval
- This is pure economics gap, not a gate misconfiguration

**mantle** (6 pairs, 7 quotes, 0 signals):
- 41 quote attempts, 34 rejected: **30 SUSPECT_LIQUIDITY** (73%), 3 PRICE_SANITY, 1 VE33_QUOTE_FAILED, 4 NOTIONAL_DRIFT
- WMNT/USDT reaches RT eval but rejected: SLIPPAGE_TOO_HIGH (-1940 bps, slippage=4107 bps)
- Mantle is a liquidity desert; quote quality is pathological

**zksync** (3-4 pairs, 7 quotes, 2 signals, 1 RT evaluated):
- WETH/WBTC: RT at -448 bps, slippage=1064 bps dominates
- Thin market, limited DEX coverage

### Diagnostic Ratio by Chain
| Chain | Total Quotes | Diagnostic | Real | Diag % | Cross-DEX Potential |
|-------|-------------|-----------|------|--------|-------------------|
| arbitrum_one | 9 | 0 | 9 | 0% | 2 pairs |
| base | 59 | 57 | 2 | **96%** | 0 pairs |
| linea | 20 | 0 | 20 | 0% | 6 pairs |
| scroll | 7 | 1 | 6 | 14% | 2 pairs |
| mantle | 7 | 0 | 7 | 0% | 2 pairs |
| zksync | 7 | 0 | 7 | 0% | 1 pair |

## 5) Contract Checks
pair_funnel_trace contract: OK — embedded in truth_report, 10 tests pass
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
runtime artifacts not committed: OK

## 6) Blocker Classification

```
code_blocker: NONE (2071 tests PASS)
base_quoter_blocker: HIGH (96% diagnostic — quoter_v2 RPC failing for all 3 base DEXes)
economics_blocker: HIGH (best real RT: -24 bps arb, -142 bps linea)
slippage_blocker: HIGH (dominates on mantle 4107 bps, zksync 1064 bps, linea 208 bps)
gas_blocker: MEDIUM (arb 266 bps on WBTC/USDC, linea 10 bps)
liquidity_blocker: HIGH (mantle 73% SUSPECT_LIQUIDITY)
execution_blocker: HIGH (dormant — no signer, simulate_only)
god_file_blocker: PARTIAL (quotes.py: 1962 lines — deferred)
```

## 7) Lead's R29 Audit Directive: Execution Map
step_01: **DONE** — Same-session diagnostic bundle: 72 runs with embedded pair_funnel_trace
step_02: **DONE** — Pair-level funnel trace artifact: strategy/pair_trace.py + truth_report integration
step_03: **DONE** — Counterfactual replay harness: scripts/pair_level_rca.py
step_04: **DEFERRED** — External truth probe for near-profit pairs (requires separate quoter verification script)
step_05: **DONE** — Base spread-formation audit: ROOT CAUSE = quoter_v2 RPC failure → 96% slot0/diagnostic
step_06: **DONE** — Scroll LP gate replay: NOT a gate bug, economics gap = -271 bps (25 spread vs 296 required)
step_07: **DONE** — Mantle quote-quality census: 73% SUSPECT_LIQUIDITY, 4107 bps slippage on WMNT/USDT
step_08: **DEFERRED** — quotes.py staged extraction (1962 lines → next session)
step_09: **DONE** — Economics decomposition: gas/slippage/LP breakdown per chain
step_10: **DONE** — Docs updated with fresh evidence

## 8) Root Causes Discovered (R29)
1. **Base diagnostic-only quotes**: ALL quoter_v2 RPC calls failing on base → slot0 fallback → truth_mode filters these out → 0 signals. Fix: verify quoter contract addresses on basescan, test with direct eth.call().
2. **Scroll NOT LP gate**: Spread (25 bps) vs required (296 bps = 60 LP + 231 slippage + 5 gas). Pure economics gap, not misconfiguration.
3. **Mantle liquidity desert**: 73% of 41 quote attempts fail SUSPECT_LIQUIDITY. Even the 1 RT candidate has 4107 bps slippage. Not viable for arb.
4. **Linea suspect accounting**: WSTETH/WETH (+4577) and WEETH/WETH (+1682) marked profitable but leg2_is_real=false. Properly filtered as SUSPECT_ACCOUNTING.
5. **Arb pool resolution gap**: 32/36 pairs never get quotes — missing pools on second DEX. Only 2 pairs have cross-DEX potential.

## 9) What I need from Lead now
1. **Base quoter_v2 fix**: Verify 3 quoter contract addresses on basescan. If valid, diagnose RPC failure (function selector? encoding? rate limit?). This is the #1 unblock for base.
2. **Slippage model audit**: Slippage dominates on ALL chains (208-4107 bps). Is the slippage model (`effective_slippage_bps`) overestimating? Or is this market reality?
3. **Arb pair coverage**: Only 4/36 pairs get real quotes. Should we expand DEX registry (camelot, zyberswap) or focus on the 2 viable pairs?
4. **quotes.py extraction plan**: 1962 lines — lead to prescribe extraction targets for next session.
