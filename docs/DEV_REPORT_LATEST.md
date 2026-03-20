# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled. R29 cont'd (2): 5-module staged `strategy/quotes.py` extraction (1252 lines), pair-level RCA for base + arb, fresh 60-run online evidence. 2092 tests PASS.

## SESSION GOAL (R29 cont'd (2): quotes.py 5-module split + pair-level RCA + docs alignment)
**Goal**: Complete staged extraction of `strategy/quotes.py` into 5 modules, run pair-level RCA on base + arb, align all docs with fresh evidence.
**Prior (R29 cont'd)**: Partial split to `strategy/quote_rpc.py`, same-session dashboard verification, 72-run rolling evidence.

## 0) Meta
timestamp_utc: 2026-03-20T15:18:08.461027Z
run_dir_name: ci_m5_gate_arbitrum_one_20260320_161747_779516 (primary rolling) + long_scan (60 runs, 6 chains, 646.1s wall)
mode: STAGED_EXTRACTION_RCA (R29 cont'd (2))
test_count: 2092 passed, 3 skipped
schema_version: m4:run_summary:v2.0

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R29 cont'd (2): 5-module quotes.py extraction + pair-level RCA for base/arb + docs alignment |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | base quote-path blocked, arb mixed coverage+economics (gas-dominated), linea economics-control, scroll no-real-RT, mantle liquidity/quality, zksync thin-surface economics |
| evidence_session_run_dirs | data/runs/ci_m5_gate_base_20260320_161202_590806, data/runs/ci_m5_gate_arbitrum_one_20260320_161139_941538, data/runs/ci_m5_gate_linea_20260320_162211_724675, data/runs/ci_m5_gate_scroll_20260320_162215_832265 |
| primary_blocker_of_session | `strategy/quotes.py` god-file risk + stale docs missing 5-module breakdown and pair-level RCA evidence |
| blocker_status_before | ACTIVE: quotes.py 1658 lines, only quote_rpc.py extracted; docs missing pair-level RCA for base/arb |
| blocker_status_after | RESOLVED: quotes.py 1252 lines across 5 modules; pair-level RCA completed for base + arb; docs aligned |
| start_metric | quotes.py 1658 lines, 2084 tests, no pair-level RCA for base/arb |
| end_metric | quotes.py 1252 lines, 2092 tests, pair-level RCA for base (15 pairs, 14 quoted, 0 signals) + arb (7 pairs, 4 RT eval, best -25.02 bps gas-dominated) |
| delta | +3 new modules, +8 tests, +pair-level RCA for base+arb; all 3 docs updated to fresh evidence |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 — R29 cont'd (2): 5-module quotes.py split + pair-level RCA + docs alignment
change_summary:
  - NEW: `strategy/quote_adapters.py` — adapter-specific quote readers (read_algebra_quoter, read_ve33_amount_out, synthesize_sqrt_price_from_anchor, calculate_price_from_sqrt)
  - NEW: `strategy/quote_policy.py` — runtime filter switches + consolidated price sanity gate (was 3x duplicated)
  - NEW: `strategy/quote_metrics.py` — quote counts init/finalize, quoter matrix
  - MODIFIED: `strategy/quotes.py` — imports from 3 new modules, orchestration spine only
  - MODIFIED: `tests/unit/test_discovery_productivity_contract.py` — _env_flag_enabled import path updated for quote_policy.py
  - NEW: `tests/unit/test_quote_policy_exports.py` — 9 tests for quote_policy exports
  - NEW: `tests/unit/test_quote_metrics_exports.py` — 4 tests for quote_metrics exports
touched_files:
  - strategy/quote_adapters.py (NEW — adapter readers)
  - strategy/quote_policy.py (NEW — policy gates)
  - strategy/quote_metrics.py (NEW — metrics init/finalize)
  - strategy/quotes.py (MODIFIED — orchestration spine)
  - tests/unit/test_discovery_productivity_contract.py (MODIFIED)
  - tests/unit/test_quote_policy_exports.py (NEW)
  - tests/unit/test_quote_metrics_exports.py (NEW)
  - docs/DEV_REPORT_LATEST.md, docs/status/Status_M5_0.md, docs/status/Status_M4.md (MODIFIED)

## 2) Commands Executed

```
py -3.11 -m pytest tests/unit -q: PASS (2092 passed, 3 skipped)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings) — before docs alignment
py -3.11 scripts/ci_full_pipeline.py --mode ci: pytest PASS, all gates PASS
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS
py -3.11 scripts/pair_level_rca.py --run-dir data/runs/ci_m5_gate_base_20260320_161202_590806: DONE
py -3.11 scripts/pair_level_rca.py --run-dir data/runs/ci_m5_gate_arbitrum_one_20260320_161139_941538: DONE
```

## 3) Artifacts Attached
rolling: data/runs/_rolling/{_latest.json,run_summary_latest.json,m4_stability_agg.json,long_scan_latest.json}
runs_in_window: 200+

### Verification Scan (fresh — lead's canonical online run)
```
Wall time:      646.1s
Total runs:     60  (PASS=base,linea  FAIL=arb,zksync,mantle,scroll)
Infra fail:     0
Signals total:  56
RT evaluated:   54
Profitable RTs: 0  (best: -25.02 bps, arb WBTC/USDC)
Pass chains:    base, linea
Fail chains:    arbitrum_one, zksync, mantle, scroll
```

### 5-Module Extraction Result
| File | Before | After | Delta |
|------|--------|-------|-------|
| `strategy/quotes.py` | 1658 lines | **1252 lines** | -406 |
| `strategy/quote_rpc.py` | 233 lines | 233 lines | (prior session) |
| `strategy/quote_adapters.py` | 0 | **288 lines** | +288 |
| `strategy/quote_policy.py` | 0 | **107 lines** | +107 |
| `strategy/quote_metrics.py` | 0 | **39 lines** | +39 |

## 4) Pair-Level RCA Results

### base — QUOTE-PATH BLOCKED (confirmed by pair-level RCA)
```
15 pairs total: 14 reach 'quoted', 1 at 'resolved'
0 signals, 0 opportunities, 0 RT evaluated
No candidates within 100 bps of breakeven
```
**Verdict**: Quotes exist but fail to form cross-DEX spreads. QuoterV2 RPC still failing → slot0 diagnostic dominates. This is NOT a market blocker — it's a quote-path infrastructure issue.

### arbitrum_one — MIXED COVERAGE + ECONOMICS (confirmed by pair-level RCA)
```
7 pairs: 4 reach RT eval, 2 signal-only, 1 quoted-only
RT economics decomposition:
  WBTC/USDC:  net=-25.02 bps  (slip=43.73, gas=278.93, LP=10.00)
  WETH/USDT:  net=-42.64 bps  (slip=71.30, gas=132.23, LP=10.00)
  ARB/WETH:   net=-250.06 bps (slip=1374.92, gas=25.59, LP=60.00)
  WBTC/WETH:  net=-372.89 bps (slip=690.08, gas=18.79, LP=31.00)
Counterfactual: 2 candidates within 100 bps — dominant blocker: GAS
  WBTC/USDC: if_zero_gas → +253.91 bps, if_zero_slippage → +18.71 bps
  WETH/USDT: if_zero_gas → +89.59 bps, if_zero_slippage → +28.66 bps
```
**Verdict**: Surface exists but thin (7 pairs). Economics are gas-dominated on near-breakeven candidates. Mixed: coverage is narrow + economics are negative.

## 5) Contract Checks
5-module extraction: OK — all imports wired, re-exports preserved
pair_funnel_trace contract: OK — pair_level_rca.py operational
rolling discipline (3+1 files): OK
provenance contract: OK (run_timestamp only)
runtime artifacts not committed: OK

## 6) Blocker Classification (R29 cont'd (2) — pair-level RCA verified)

### Per-chain blocker taxonomy (verified by fresh pair-level RCA)
| Chain | Verdict | Evidence |
|-------|---------|----------|
| base | **QUOTE-PATH BLOCKED** | 15 pairs, 14 quoted, 0 signals. QuoterV2 failing → slot0 diagnostic. Not market-blocked |
| arbitrum_one | **MIXED: coverage + economics** | 7 pairs, 4 RT eval, best -25.02 bps. Gas-dominated (counterfactual: zero-gas → +253). Surface thin |
| linea | **ECONOMICS-CONTROL CHAIN** | 30 signals, 11 cdx pairs, best -122.5 bps. Cleanest truth path. If linea negative → true market blocker |
| scroll | **NO-REAL-RT** | 4 signals, 0 RT path. Upstream signal-pass collapse |
| mantle | **LIQUIDITY/QUALITY** | Surface partially alive, signal pass fragile and unstable |
| zksync | **THIN-SURFACE ECONOMICS** | 4 signals, thin surface, economics blocker |

### Summary blockers
```
code_blocker: NONE (2092 tests PASS)
base_quoter_blocker: HIGH (quote-path blocked — not market-blocked)
economics_blocker: HIGH (best real RT: -25.02 bps arb, gas-dominated)
slippage_blocker: HIGH (mantle, zksync, arb non-frontier pairs)
gas_blocker: HIGH (arb frontier: +253 bps if zero gas on WBTC/USDC)
god_file_blocker: REDUCED (quotes.py 1252 lines — 5-module extraction done)
execution_blocker: HIGH (dormant — no signer, simulate_only)
```

## 7) Lead's Directive Execution Map (R29 cont'd (2))
step_01: **DONE** — DEV_REPORT + Status_M5_0 + Status_M4 updated with 5-module breakdown + fresh 60-run evidence
step_02: **DONE** — /api/hot captured (dashboard alive on 8099; empty because no scan fed to it this session)
step_03: **DONE** — pair_level_rca.py on base: 15 pairs, 14 quoted, 0 signals — quote-path blocked confirmed pair-by-pair
step_04: **DONE** — pair_level_rca.py on arb: 7 pairs, 4 RT eval, gas-dominated — mixed coverage+economics confirmed
step_05: **DONE** — linea used as economics-control chain in verdict taxonomy
step_06: **DONE** — staged extraction complete: quote_adapters.py + quote_policy.py + quote_metrics.py
step_07: **DONE** — no global threshold/config changes (as directed)
step_08: **NOTED** — all future online runs must use dashboard+/api/hot protocol
step_09: **DONE** — base/arb NOT called "market blocked" — taxonomy uses quote-path/mixed/economics-control labels
step_10: **DONE** — docs updated with per-chain taxonomy: base=quote-path, arb=mixed, linea=economics-control, scroll=no-real-RT, mantle=liquidity/quality, zksync=thin-surface

## 8) What I need from Lead now
1. **Dashboard-fed online run**: Current /api/hot shows 0 chains — need fresh scan fed to dashboard for same-session hot_loop proof.
2. **Base quoter_v2 deep-dive**: QuoterV2 still failing on base. Targeted probe on AERO/USDC, WETH/AERO, CBBTC/USDC.
3. **Arb gas reduction strategy**: Counterfactual shows gas is the dominant blocker on frontier pairs. Fee=100 tier or smaller notional could help.
4. **Next extraction targets**: quotes.py still 1252 lines. Further extraction by responsibility seams if lead directs.
