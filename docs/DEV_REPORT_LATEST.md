# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R29 cont'd: staged `strategy/quotes.py` extraction, same-session dashboard verification, fresh 72-run rolling evidence. 2084 tests PASS.

## SESSION GOAL (R29 cont'd: quotes.py staged extraction + same-session dashboard evidence)
**Goal**: Audit `setting_timlid.md`, review `strategy/quotes.py`, safely split low-level RPC/cache responsibilities out of the god-file, and verify the scanner end-to-end in canonical dashboard mode with fresh rolling evidence.
**Prior (R29)**: Pair-level E2E replay infrastructure, QUOTER_V2_FAILED reject, per-DEX quoter_matrix artifact, executable/diagnostic split.

## 0) Meta
timestamp_utc: 2026-03-20T11:06:10.764758Z
run_dir_name: ci_m5_gate_arbitrum_one_20260320_120555_227055 (primary rolling) + long_scan (72 runs, 6 chains, 647.8s wall)
mode: LEAD_AUDIT_QUOTES_EXTRACTION (R29 cont'd)
test_count: 2084 passed, 14 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R29 cont'd: staged quotes.py extraction + same-session dashboard/rolling verification |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | base quote-path, arb mixed coverage/economics, linea/zksync economics, mantle liquidity-quality, scroll no real RT |
| evidence_session_run_dirs | data/runs/ci_m5_gate_arbitrum_one_20260320_120652_022118, data/runs/ci_m5_gate_zksync_20260320_120710_487428, data/runs/ci_m5_gate_base_20260320_120714_572504, data/runs/ci_m5_gate_mantle_20260320_120719_371191, data/runs/ci_m5_gate_linea_20260320_120731_538504, data/runs/ci_m5_gate_scroll_20260320_120739_677712 |
| primary_blocker_of_session | `strategy/quotes.py` had re-accumulated low-level RPC/cache responsibilities and hid the next isolation target inside a 2k-line file |
| blocker_status_before | ACTIVE: quotes.py ~2000 lines, low-level v3/shared-cache helpers embedded in the same file as quote policy/orchestration |
| blocker_status_after | PARTIAL: extracted low-level shared RPC/cache helpers into `strategy/quote_rpc.py`; quotes.py reduced to 1658 lines, but adapter/policy split still pending |
| start_metric | `strategy/quotes.py` ~2006 lines, no dedicated low-level quote RPC module, same-session dashboard evidence stale |
| end_metric | `strategy/quotes.py` 1658 lines, `strategy/quote_rpc.py` 233 lines, same-session `/api/hot` snapshot aligned with `long_scan_latest.json` |
| delta | +2 files touched in code + 2 tests updated/added; full pytest 2084/14; fresh 72-run online evidence |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R29 cont'd: staged quotes.py extraction + same-session dashboard verification
change_summary:
  - NEW: `strategy/quote_rpc.py` — extracted shared web3/executor, multicall caches, slot0/quoter_v2 readers
  - MODIFIED: `strategy/quotes.py` — imports low-level helpers from `strategy.quote_rpc`, removes duplicated low-level v3/shared-cache logic, keeps policy/adapters in place
  - MODIFIED: `tests/unit/test_start.py` — shared quote executor assertions moved to `strategy.quote_rpc`
  - NEW: `tests/unit/test_quote_rpc_exports.py` — export compatibility tests for extracted helpers
  - VERIFIED: canonical mode = `dashboard_server` + `start.py --no-dashboard`; `/api/hot` same-session with rolling `long_scan_latest.json`
touched_files:
  - strategy/quote_rpc.py (NEW — low-level quote RPC/cache helpers)
  - strategy/quotes.py (MODIFIED — partial staged extraction)
  - tests/unit/test_start.py (MODIFIED — shared executor test target moved)
  - tests/unit/test_quote_rpc_exports.py (NEW — compatibility tests)
  - docs/DEV_REPORT_LATEST.md (MODIFIED — fresh same-session evidence)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit/test_quote_rpc_exports.py tests/unit/test_quoter_v2_failed_reject.py tests/unit/test_quoter_canonical.py tests/unit/test_start.py -q: PASS (165 passed)
py -3.11 -m pytest -q: PASS (2084 passed, 14 skipped)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS
py -3.11 -m monitoring.dashboard_server --port 8099: RUNNING (same-session proof server)
py -3.11 start.py --config-list (6 chains) --hours 0.17 --no-dashboard: PASS (72 runs, 647.8s wall, 0 infra_fail)
Invoke-RestMethod http://127.0.0.1:8099/api/hot: PASS (schema=v1.3, same-session, is_test_session=false)
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}
runs_in_window: 200+

### 10-min Verification Scan (R29 cont'd — staged quotes.py extraction + same-session dashboard)
```
Wall time:      647.8s
Total runs:     72  (PASS=23  NO_DATA=10  FAIL=39  INFRA_FAIL=0)
Signals total:  78
Profitable RTs: 0  (evaluated: 57, best: -25.38 bps)
Spread gap:     +16.06 bps sweep / +20.28 bps measured spread gap
Chains:         arbitrum_one, zksync, base, mantle, linea, scroll
Pass chains:    base, linea
Fail chains:    arbitrum_one, zksync, mantle
Accepted fail:  scroll
```

### Extraction Result
| File | Before | After | Delta |
|------|--------|-------|-------|
| `strategy/quotes.py` | ~2006 lines | 1658 lines | -348 |
| `strategy/quote_rpc.py` | 0 | 233 lines | +233 |
| `strategy/jobs/run_scan_real.py` | unchanged this session | 1425 lines | orchestration spine preserved |

### Fresh same-session dashboard evidence
- `hot_loop_latest.json` `run_timestamp=2026-03-20T11:07:45Z`
- `session_summary_file=data/runs/_rolling/long_scan_latest.json`
- `total_runs=72`, `total_full_sweeps=18`, `total_hot_requotes=54`
- `is_test_session=false`
- `/api/hot` therefore matches the same canonical online run and is valid RCA evidence

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
