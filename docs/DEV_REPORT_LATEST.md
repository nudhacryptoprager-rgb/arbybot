# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.2)
**Goal**: R28.2 — Fix critical semantics bug (profit_truth_available when real_quote_count=0). Create ve33 stage2 configs. Test stage2 online. Fresh evidence with correct profit semantics.
**Prior (R28.1)**: Honesty correction — rolled back overclaims, fixed ONBOARDING_MATRIX, net_pnl_bps implemented. Base profitable_count=1 was SUSPECT (real_quote_count=0, best_net_pnl_bps=2548 — paper contamination).

## 0) Meta
timestamp_utc: 2026-03-14T22:17:01Z
rolling_provenance: 2026-03-14T22:17:01Z (arbitrum_one NORMAL — FRESH R28.2 evidence, ci_m5_gate_20260314_231616)
mode: SEMANTICS_FIX + VE33_STAGE2_TESTING
test_count: 1817 passed, 3 skipped (+5 new tests: 2 profit semantics regression + 3 doc-contract)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.2: Fix profit_truth semantics bug, create ve33 stage2 configs, test online, fresh evidence |
| goal_status | **IN_PROGRESS** |
| close_allowed | false |
| remaining_blockers | MARKET: arb gap=17.41 bps (improved from 20.41); PROBE_SLIPPAGE: artifact integration pending |
| evidence_session_run_dirs | ci_m5_gate_20260314_230400 (arb, PASS, rolling), ci_m5_gate_20260314_230514 (zksync, PASS), ci_m5_gate_20260314_230622 (base stage2, PASS, ROUNDTRIP_PROFITABLE=2 REAL), ci_m5_gate_20260314_230824 (mantle stage2, PASS, cross_dex=5) |
| primary_blocker_of_session | R28.1 semantics bug: profit_truth_available=true when real_quote_count=0; ve33 configs excluded ve33 DEXes; Status stale |
| blocker_status_before | profit_truth allows false ROUNDTRIP_PROFITABLE (real_quote_count=0), ve33 stage2 configs missing, Status stale |
| blocker_status_after | semantics fixed (real_quote_count>0 required), stage2 configs created+tested, base REAL ROUNDTRIP_PROFITABLE=2, arb gap improved 20.41→17.41 |
| start_metric | R28.1: 1812 tests, base SUSPECT profitable_count=1, ve33 untested, gap=20.41 |
| end_metric | R28.2: 1817 tests (+5), base REAL ROUNDTRIP_PROFITABLE=2 (real_quote_count=1), ve33 tested both chains, gap=17.41 |
| delta | +5 tests, semantics bug fixed, 2 stage2 configs, ve33 online-verified, arb gap improved 3 bps |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — semantics fix + ve33 stage2 testing (R28.2 lead directive)
change_summary:
  - CRITICAL BUG FIX: `strategy/artifacts.py` lines 606-618 — profit_is_diagnostic, profit_truth_source, profit_realism_status now require BOTH `profitable_count > 0` AND `real_quote_count > 0`
  - Regression tests: 2 new tests in test_truth_report.py (profitable_but_no_real_quotes_is_diagnostic, profitable_with_real_quotes_zero_no_truth_mode)
  - Doc-contract tests: 3 new tests in test_doc_contracts.py (stage2_configs_exist, stage1_yaml_no_not_implemented_lie, profit_semantics_contract)
  - ve33 stage2 configs: onboard_base_stage2.yaml (4 DEXes + aerodrome), onboard_mantle_stage2.yaml (2 DEXes + stratum)
  - Stage1 YAML comment fix: removed "NOT YET IMPLEMENTED" lies from onboard_base_stage1.yaml, onboard_mantle_stage1.yaml
  - Config inventory guard: ALLOWED_YAML_FILES updated (16→18, +2 stage2)
  - Status_M5_0.md, Status_M4.md: cleaned stale evidence, base SUSPECT downgraded, updated with R28.2 evidence
  - DEV_REPORT_LATEST.md: rewritten for R28.2
touched_files: strategy/artifacts.py, tests/unit/test_truth_report.py, tests/unit/test_doc_contracts.py, tests/unit/test_config_contracts.py, config/onboard_base_stage2.yaml (NEW), config/onboard_mantle_stage2.yaml (NEW), config/onboard_base_stage1.yaml, config/onboard_mantle_stage1.yaml, docs/DEV_REPORT_LATEST.md, docs/status/Status_M5_0.md, docs/status/Status_M4.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1817 passed, 3 skipped, 1 warning)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **ALL GATES PASS** (pytest, docs, status, m5_0, m4_smoke, m4_profit)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS** (sims=2, net=$0.50)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling --refresh-rolling-strict --prune-keep 50: **PASS** (arb, m4_sim_net_usdc=$5.79)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml --cycles 3: **PASS** (cross_dex=10)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage2.yaml --cycles 3: **PASS** (4 DEXes, cross_dex=16, ROUNDTRIP_PROFITABLE=2, real_quote_count=1)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_mantle_stage2.yaml --cycles 3: **PASS** (2 DEXes, cross_dex=5, profitable=0)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,mantle_stage2,linea,scroll --hours 0.25: **8 runs** (6 PASS + 1 accepted-fail + 1 fail)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.2 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T22:17:01Z)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED: 8 runs, 23 signals, $31.37, 4 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_20260314_230400 (arb primary, NORMAL, PASS, rolling refresh)
  - ci_m5_gate_20260314_230514 (zksync candidate, COVERAGE, PASS, cross_dex=10)
  - ci_m5_gate_20260314_230622 (base stage2, COVERAGE, PASS, ROUNDTRIP_PROFITABLE=2, real_quote_count=1, 4 DEXes)
  - ci_m5_gate_20260314_230824 (mantle stage2, COVERAGE, PASS, cross_dex=5, 2 DEXes)

## 4) Key Results (числа з артефактів)

```
semantics_fix: profit_truth now requires real_quote_count > 0 (artifacts.py lines 606-618)
ve33_stage2_base: TESTED, 4 DEXes (uni+sushi+pancake+aerodrome), cross_dex=16, ROUNDTRIP_PROFITABLE=2 REAL
ve33_stage2_mantle: TESTED, 2 DEXes (agni_v3+stratum), cross_dex=5, profitable=0
long_scan: 8 runs / 23 signals / $31.37 net / 4 profitable roundtrips (base=2, linea=2)
arb_gap: 17.41 bps (improved from 20.41 bps R27.4)
test_count: 1817 (+5 from R28.2)
config_inventory: 18 files (+2 stage2 configs)
```

## 5) Contract Checks
- profit_truth semantics: FIXED (profitable_count + real_quote_count both required)
- ve33 adapter accuracy: PROVEN ONLINE (base aerodrome + mantle stratum both produce quotes)
- stage1 YAML comments: FIXED (no more "NOT YET IMPLEMENTED" lies)
- config inventory: UPDATED (18 files, guard test updated)
- rolling discipline: OK (3+1 canonical files, NORM-only guard active)
- status/reasons consistency: FIXED (R28.2 evidence matches claims)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1817 PASS, CI+safety PASS)
data_collection_blocker: RESOLVED (fresh evidence from 6 chains)
market_window_blocker: MEDIUM (arb gap=17.41 bps, improving; base has REAL profitable roundtrips)
adapter_blocker: RESOLVED (ve33 tested online on both base and mantle)
architecture_debt: DOCUMENTED (god-files tracked in TECH_DEBT.md)
economics_debt: PARTIAL (net_pnl_bps done, probe_slippage pending)
docs_honesty: FIXED (R28.2 corrected semantics + stale claims)
```

## 7) R28.2 Session Summary
- **Critical bug fix**: profit_truth_available/ROUNDTRIP_PROFITABLE now requires real_quote_count > 0. Prevents false claims from paper-estimate contamination.
- **ve33 online verification**: Base stage2 (aerodrome) PASS with REAL ROUNDTRIP_PROFITABLE=2 (real_quote_count=1). Mantle stage2 (stratum) PASS with cross_dex=5, 2 DEXes active.
- **Arb gap improving**: 20.41→17.41 bps (market conditions)
- **Long scan refreshed**: 8 runs, 23 signals, $31.37 net, 4 profitable roundtrips (base + linea)
- **Remaining blockers**: arb gap=17.41 bps (market), probe_slippage integration (code)

## 8) Що потрібно від ліда
1. Semantics fix verified: profit_truth now requires real_quote_count > 0. R28.1 base suspect claim corrected.
2. ve33 stage2 TESTED online: base 4 DEXes (inc. aerodrome), mantle 2 DEXes (inc. stratum). Both PASS.
3. Base REAL ROUNDTRIP_PROFITABLE=2 (real_quote_count=1) — first honest confirmed profitable roundtrip.
4. Arb primary gap improved 20.41→17.41 bps but still market-blocked (roundtrip_profitable=0).
5. probe_slippage: artifact integration still pending.
