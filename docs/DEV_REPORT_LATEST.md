# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled.
**R39e**: Dense productive contour improved signal density on arb but did NOT unlock profit. Corrected per-chain verdicts. Added calibration universe. Fixed pair_level_rca.py ASCII output.

## SESSION GOAL (R39e: correct market verdicts + calibration universe)
**Goal**: (1) Document correct per-chain verdicts from fresh R39d RCA, (2) Add calibration universe alongside productive, (3) Fix pair_level_rca.py Windows ASCII issue, (4) Establish acceptance criteria for next pair strategy changes.
**Prior (R39d)**: 2290 tests, 31 productive pairs, tiered intent, fresh scan: 36 runs/203 signals/37 RT/0 profitable.
**Lead directive (R39e)**: Dense intent improved density but not profit proximity. Volatile tokens alone don't help when spread < slippage + LP fee + gas. Chain verdicts must be precise per RCA evidence. Calibration pairs needed alongside productive. Dashboard mandatory for pair experiments.

## 0) Meta
timestamp_utc: 2026-03-23T20:21:48Z
run_dir_name: ci_m5_gate_arbitrum_one_20260323_212120_844201
mode: R39e_MARKET_VERDICTS
test_count: 2293 passed, 5 skipped
schema_version: m4:run_summary:v2.0, start:long_scan_summary:v1.14
code_identity:
  primary: ts:2026-03-23T20:21:48.534187Z
  dirty: true (R39e code changes uncommitted)
  desc: market_verdicts_calibration

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R39e: correct market verdicts + calibration universe + ASCII fix |
| goal_status | **REACHED** (verdicts corrected, calibration tier added, ASCII fix, +3 tests) |
| close_allowed | true |
| remaining_blockers | profitable_rt=0 (market economics on all healthy chains) |
| evidence_session_run_dirs | ci_m5_gate_arbitrum_one_20260323_212120_844201 (fresh R39e scan: 36 runs, 196 signals, 30 RT, 0 profitable) |
| primary_blocker_of_session | Imprecise per-chain verdicts + missing calibration benchmark pairs + broken Windows RCA output |
| blocker_status_before | ACTIVE: docs said "adapter gaps" for mantle/linea/scroll; no calibration pairs; RCA needs PYTHONIOENCODING workaround |
| blocker_status_after | **RESOLVED**: Verdicts corrected per fresh RCA. Calibration tier added. pair_level_rca.py ASCII-safe. |
| start_metric | 2290 tests, imprecise chain verdicts, no calibration tier |
| end_metric | 2293 tests, evidence-based verdicts, calibration tier, ASCII-safe RCA |
| delta | +3 tests, corrected verdicts, calibration tier, pair_level_rca.py -> ASCII |
| docs_reread_confirmed | true |

## 1) Scope
goal (Roadmap): M5_0/M4 -- R39e: correct verdicts + calibration
change_summary:
  - **R39e**: `scripts/pair_level_rca.py` -- replaced Unicode arrow with ASCII `->` for Windows console safety.
  - **R39e**: `scripts/generate_intent.py` -- added `--tier calibration` (productive + USDC/DAI, USDC/USDT, WETH/USDC, WBTC/USDC benchmarks).
  - **R39e**: `tests/unit/test_tiered_intent.py` -- +3 calibration tier tests.
  - **R39e**: `scripts/ci_full_pipeline.py` -- `--allow-intent-edit` passthrough to repo safety gate.
  - **R39e**: `docs/DEV_REPORT_LATEST.md` -- corrected verdicts per fresh RCA.
  - **R39e**: `docs/status/Status_M5_0.md` -- R39e section.

## 2) Per-Chain Market Verdicts (fresh R39e scan, 2026-03-23T20:21:48Z)

| Chain | Verdict | RT | Best PnL | Evidence |
|-------|---------|----|---------:|----------|
| arb | healthy, economics-blocked | 4 RT | -298 bps (ARB/USDC) | 185 sig, 22 real_quotes, 6/6 PASS, slippage dominates |
| mantle | no-signal, economics-blocked | 2 RT | -360 bps (WETH/WMNT) | 0 sig, 4 real_quotes, 0/6 PASS, high gas (133-143 bps) |
| scroll | infra-fail + economics | 1 RT | -343 bps (WETH/USDC) | 0 sig, 2 real_quotes, 0/6 PASS, accepted_fail |
| linea | infra-fail, no RT | 0 RT | - | 0 sig, 0 real_quotes, 0/6 PASS, no PnL data |
| zksync | thin + economics | 1 RT | -737 bps (WETH/USDC) | 6 sig, 2 real_quotes, 2/6 PASS, gas 163 bps |
| base | low-sample, economics-blocked | 0 RT | -376 bps (VIRTUAL/USDC*) | 5 sig, 0 real_quotes, 4/6 PASS, *not real_quote |

**Key insight**: arb signal density stable (185 sig/6 runs). Profit proximity unchanged: best RT -298 bps (ARB/USDC). mantle dropped to NO_SIGNAL. scroll/linea INFRA_FAIL. Dominant blocker: spread < slippage + LP fee + gas.

## 3) Economics Lab (arb, route-level)

| Pair | Route | Net (bps) | Slip | Gas | LP Fee |
|------|-------|----------:|-----:|----:|-------:|
| ARB/USDC | camelotV3->pancakeV3 | -298 | 540 | 14 | 1 |
| WETH/LINK | camelotV3->sushiV3 | -395 | 642 | 12 | 30 |
| WETH/ARB | pancakeV3->uniV3 | -420 | 840 | 17 | 6 |
| WETH/USDC | pancakeV3->sushiV3 | -798 | 898 | 10 | 31 |

No candidates within 100 bps of breakeven on any chain.

## 4) Code Changes (R39e)
1. `scripts/pair_level_rca.py` -- Unicode arrow `->` replaced with ASCII `->`. No more PYTHONIOENCODING workaround needed.
2. `scripts/generate_intent.py` -- `--tier calibration` generates productive + benchmark pairs (USDC/DAI, USDC/USDT per chain where available). Total 42 pairs. Productive remains 31 (default).
3. `scripts/ci_full_pipeline.py` -- `--allow-intent-edit` flag forwarded to repo safety gate for intentional intent.txt changes.
4. `tests/unit/test_tiered_intent.py` -- +3 tests: calibration superset, arb stable pairs, count range.

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline: OK
- v2.x provenance: OK
- frontier contract: OK (EXECUTABLE_BEST_NEG)
- sweep guard: OK
- tiered intent: OK (productive_default drives selection)
- calibration: OK (superset of productive, adds only benchmarks)

## 6) Acceptance Criteria for Next Pair Change (step 10)
Next pair strategy change is REACHED only if at least one of:
- RT-evaluated count increases
- real_quote_count increases
- Near-zero executable candidates appear (gap < 100 bps)
- Best RT gap to zero decreases

signals_count alone is insufficient.

## 7) Blockers / Next Steps
- **profitable_rt=0**: economics blocker (all chains). Not infra except base.
- **arb**: economics lab. Route-level RCA for ARB/USDC, WETH/USDC, WETH/LINK, WETH/ARB, WETH/PENDLE. Do not expand contour.
- **base**: quote-path constrained (SLOT0_DIAGNOSTIC 96.6%). Next: quotes.py, quote_adapters.py, onboard_base_stage2.yaml.
- **zksync**: stability first (2/6 PASS). Keep WETH/USDC, WBTC/USDC, ZK/*. No long-tail.
- **mantle/scroll/linea**: economics + mixed-source, not pure adapter gaps.
- **Dashboard mandatory** for any pair-policy experiment: start dashboard, run scan with --no-dashboard, check /api/hot, then RCA, then docs.
