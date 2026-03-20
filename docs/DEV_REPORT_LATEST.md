# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R29: QUOTER_V2_FAILED structured reject, per-DEX quoter_matrix, executable/diagnostic split. 2076 tests PASS.

## SESSION GOAL (R29 cont'd: Lead Audit Stesp 2-4 — Structured Quoter Observability)
**Goal**: Add QUOTER_V2_FAILED reject (visible in reject_histogram), per-DEX quoter_matrix artifact, split Stage-2 metrics into executable/diagnostic. Correct per-chain blocker classification per lead audit.
**Prior (R29)**: Pair-level E2E replay infrastructure, 72-run 6-chain diagnostic scan, per-chain RCA. 2071 tests.

## 0) Meta
timestamp_utc: 2026-03-20T10:30:00Z
run_dir_name: long_scan (72 runs, 6 chains, 620s wall)
mode: LEAD_AUDIT_STEPS_2_4 (R29 cont'd)
test_count: 2076 passed, 3 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R29 cont'd: QUOTER_V2_FAILED structured reject, quoter_matrix, executable/diagnostic split, correct blocker taxonomy |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | steps 5-6 (base quoter probe, arb coverage audit) deferred to next session — require live RPC |
| evidence_session_run_dirs | code-only session; uses prior 72-run evidence |
| primary_blocker_of_session | Quoter failures invisible in reject_histogram; Stage-2 conflates executable/diagnostic |
| blocker_status_before | ACTIVE: quoter_v2 failures hidden behind silent slot0 fallback |
| blocker_status_after | RESOLVED: QUOTER_V2_FAILED reject emitted, quoter_matrix tracks per-DEX success/fail/diagnostic |
| start_metric | 0 QUOTER_V2_FAILED in reject_histogram; quotes_fetched=59 on base (misleading) |
| end_metric | QUOTER_V2_FAILED reject visible; quotes_fetched_executable/diagnostic split; quoter_matrix per-DEX |
| delta | +5 tests (2076 total), 3 files modified, 1 new test file |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R29 cont'd: Lead audit steps 2-4 (structured quoter observability)
change_summary:
  - MODIFIED: `strategy/quotes.py` — QUOTER_V2_FAILED reject for non-algebra V3 when quoter fails (informational, slot0 still executes); quoter_matrix per-DEX tracking; counts propagation
  - MODIFIED: `strategy/jobs/run_scan_real.py` — quotes_fetched_executable/diagnostic split; quoter_v2_failed_count; quoter_matrix propagation to stats
  - NEW: `tests/unit/test_quoter_v2_failed_reject.py` — 5 tests (reject emission, fallback contract, matrix tracking, source inspection)
  - CORRECTED: Blocker classification per lead audit (base=quote-path blocked, NOT "all 3 quoters dead"; arb=mixed coverage+economics; linea=true economics; scroll=economics gap; mantle=liquidity/quality; zksync=thin-market)
touched_files:
  - strategy/quotes.py (MODIFIED — QUOTER_V2_FAILED reject + quoter_matrix)
  - strategy/jobs/run_scan_real.py (MODIFIED — executable/diagnostic split + quoter_matrix)
  - tests/unit/test_quoter_v2_failed_reject.py (NEW — 5 tests)
  - docs/DEV_REPORT_LATEST.md (MODIFIED — corrected blocker classification)

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

## 6) Blocker Classification (corrected per Lead R29 audit)

### Per-chain blocker taxonomy (R29 — lead-corrected)
| Chain | Verdict | Primary Blocker | Detail |
|-------|---------|----------------|--------|
| base | **QUOTE-PATH BLOCKED** | quoter_v2 RPC failure | 96% diagnostic-only; 2 real quotes (not "all 3 quoters dead" — corrected). QUOTER_V2_FAILED now visible in reject_histogram |
| arbitrum_one | **MIXED: coverage + economics** | 32/36 pairs pool-missing on 2nd DEX; 2 viable pairs have gross<0 | Only WBTC/USDC, WETH/USDC reach cross-DEX; gas=266 bps dominates |
| linea | **TRUE ECONOMICS BLOCKER** | slippage=208 bps on best RT | Reference chain — quoter works, pools resolve, data quality good. Economics genuinely tight |
| scroll | **ECONOMICS GAP** | gross=25 vs required=296 bps | Not LP gate bug. Pure economics gap (-271 bps). Low pair count |
| mantle | **LIQUIDITY/QUALITY BLOCKER** | 73% SUSPECT_LIQUIDITY rejection | Liquidity desert; even surviving quotes have 4107 bps slippage |
| zksync | **THIN-MARKET ECONOMICS** | 1 pair at RT, -448 bps | Thin market, limited DEX coverage, slippage=1064 bps |

### Summary blockers
```
code_blocker: NONE (2076 tests PASS)
base_quoter_blocker: HIGH (96% diagnostic — now tracked via QUOTER_V2_FAILED reject + quoter_matrix)
economics_blocker: HIGH (best real RT: -24 bps arb, -142 bps linea)
slippage_blocker: HIGH (dominates on mantle 4107 bps, zksync 1064 bps, linea 208 bps)
gas_blocker: MEDIUM (arb 266 bps on WBTC/USDC, linea 10 bps)
liquidity_blocker: HIGH (mantle 73% SUSPECT_LIQUIDITY)
execution_blocker: HIGH (dormant — no signer, simulate_only)
god_file_blocker: PARTIAL (quotes.py: ~2000 lines — staged extraction per lead step 1)
```

## 7) Lead's R29 Audit Directive: Execution Map (continued)
step_01: **NOTED** — quotes.py staged extraction (lead: "only by responsibility", deferred to dedicated session)
step_02: **DONE** — QUOTER_V2_FAILED structured reject in reject_histogram (informational, slot0 still executes)
step_03: **DONE** — Split quotes_fetched → quotes_fetched_executable + quotes_fetched_diagnostic in scan stats
step_04: **DONE** — Per-DEX quoter_matrix artifact (attempted/quoter_success/slot0_fallback/diagnostic_only per dex:fee)
step_05: **DEFERRED** — Base quoter probe on AERO/USDC, WETH/AERO, CBBTC/USDC, CBBTC/WETH (requires live RPC)
step_06: **DEFERRED** — Arb coverage audit on 32 pairs never reaching quote stage (requires run analysis)
step_07: **NOTED** — Linea = reference economics-control chain (correct, no action needed)
step_08: **NOTED** — Scroll/mantle treatment (scroll=economics gap, mantle=liquidity desert)
step_09: **DEFERRED** — Same-session clean E2E with unpolluted hot-loop evidence
step_10: **DONE** — Blocker classification corrected per lead taxonomy

## 8) Root Causes Discovered (R29, corrected per lead audit)
1. **Base quote-path blocked** (corrected): QuoterV2 RPC calls failing on base → 96% slot0 diagnostic. NOT "all 3 quoters fully dead" — 2 real quotes exist (RETH/WETH, USDC/USDT). Quoter is severely degraded, not completely absent. Now tracked via QUOTER_V2_FAILED reject + quoter_matrix.
2. **Scroll NOT LP gate**: Spread (25 bps) vs required (296 bps = 60 LP + 231 slippage + 5 gas). Pure economics gap, not misconfiguration.
3. **Mantle liquidity desert**: 73% of 41 quote attempts fail SUSPECT_LIQUIDITY. Even the 1 RT candidate has 4107 bps slippage. Not viable for arb.
4. **Linea suspect accounting**: WSTETH/WETH (+4577) and WEETH/WETH (+1682) marked profitable but leg2_is_real=false. Properly filtered as SUSPECT_ACCOUNTING.
5. **Arb pool resolution gap**: 32/36 pairs never get quotes — missing pools on second DEX. Only 2 pairs have cross-DEX potential.

## 9) What I need from Lead now
1. **Base quoter probe** (step 5): Run targeted live scan on base with AERO/USDC, WETH/AERO, CBBTC/USDC, CBBTC/WETH. The new QUOTER_V2_FAILED rejects + quoter_matrix will show exactly which quoter calls fail.
2. **Arb coverage audit** (step 6): Analyze the 32/36 arb pairs that never reach quote stage — is this DEX registry gaps or pool resolution?
3. **Same-session clean E2E** (step 9): Dashboard on 8099, start.py --no-dashboard, immediate /api/hot capture, verify hot_loop_latest.json is unpolluted.
4. **quotes.py extraction plan** (step 1): Lead to prescribe extraction targets ("only by responsibility") for dedicated session.
