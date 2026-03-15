# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-15, Session 6 Round 28.3)
**Goal**: R28.3 — Doc cleanup, claim downgrades (thin not REAL), deprecated pnl pruned, stale section tests, fresh evidence.
**Prior (R28.2)**: Semantics fix (profit_truth requires real_quote_count>0), ve33 stage2 configs created+tested. Base ROUNDTRIP_PROFITABLE=2 but overclaimed as "REAL" when evidence is thin (real_quote_count=1, measured_economics.available=false). Status files had stale R27.x tails, wrong test count format, incorrect gap numbers (used long_scan sweep_best as "arb gap").

## 0) Meta
timestamp_utc: 2026-03-15T09:21:13Z
rolling_provenance: 2026-03-15T09:21:13Z (arbitrum_one NORMAL — FRESH R28.3 evidence, ci_m5_gate_20260315_102028)
mode: DOC_CLEANUP + CLAIM_DOWNGRADE + FRESH_SCANS
test_count: 1822 passed, 3 skipped (+5 new tests: 5 stale-section doc-contract in TestStatusHeaderBodyConsistency)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.3: Doc cleanup, downgrade overclaims (thin not REAL), prune deprecated pnl, add stale-section tests, fresh evidence |
| goal_status | **IN_PROGRESS** |
| close_allowed | false |
| remaining_blockers | MARKET: arb agg gap_median=17.95 bps (best-ever=3.55); BASE_EVIDENCE: thin (real_quote_count=1, needs repetition); PROBE_SLIPPAGE: artifact integration pending |
| evidence_session_run_dirs | ci_m5_gate_20260315_100946 (arb, PASS, 5 signals, $5.60, rolling refresh), ci_m5_gate_20260315_101057 (zksync, PASS, cross_dex=10, 2 signals), ci_m5_gate_20260315_101207 (base stage2, PASS, ROUNDTRIP_PROFITABLE=2 thin), ci_m5_gate_20260315_101358 (mantle stage2, PASS, NO_DATA) |
| primary_blocker_of_session | R28.2 overclaims: base "REAL" when thin, mixed rolling/long_scan numbers, stale R27.x tails in Status, deprecated pnl None fields |
| blocker_status_before | Status files stale (R27.x tails, wrong test count, incorrect gap sources); base overclaimed as REAL; deprecated pnl had None fields confusing readers |
| blocker_status_after | Status cleaned (R28.3 evidence, correct source attribution); base downgraded to "thin"; deprecated pnl pruned; +5 doc-contract tests prevent regression |
| start_metric | R28.2: 1817 tests, base "REAL" claim, gap="17.41" (wrong source), stale R27.2 Next Steps |
| end_metric | R28.3: 1822 tests (+5), base "thin" (honest), agg gap_median=17.95/best-ever=3.55 (correct source), long_scan improved 44 signals/$41.80/5 RT |
| delta | +5 tests, claims downgraded, deprecated pnl pruned, WORKFLOW stage2, Status cleaned, long_scan improved (23→44 signals, $31.37→$41.80, 4→5 RT) |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — doc honesty enforcement + fresh evidence (R28.3 lead directive)
change_summary:
  - DEPRECATED PNL PRUNED: `strategy/artifacts.py` lines 568-574 — removed `gross_pnl_usdc`, `net_pnl_usdc: None`, `net_pnl_bps: None`, `cost_model_available: False` from deprecated `pnl` block (kept `_deprecated`, `_migration`, `signal_pnl_usdc`, `would_execute_pnl_usdc`)
  - WORKFLOW FIX: `docs/WORKFLOW.md` — canonical multi-chain long scan command now uses `onboard_base_stage2.yaml,onboard_mantle_stage2.yaml` (was stage1)
  - STALE-SECTION TESTS: 5 new tests in `tests/unit/test_doc_contracts.py` (TestStatusHeaderBodyConsistency): no stale Next Steps, chain classification tag matches header round, no NEEDS ONLINE TEST when stage2 tested, correct test count format, no None fields in deprecated pnl
  - STATUS CLEANUP: `docs/status/Status_M5_0.md` — fixed test count format, replaced stale "Next Steps (R27.2)" with "Current Blockers (R28.3)", updated chain classification, all evidence lines refreshed
  - STATUS CLEANUP: `docs/status/Status_M4.md` — corrected economics numbers (agg vs long_scan source attribution), fixed rollout table, updated evidence, removed stale claims
  - CLAIM DOWNGRADES: base "REAL" → "thin" throughout (real_quote_count=1, measured_economics.available=false); mantle SIGNAL_PRODUCING → CROSS_DEX_VERIFIED (NO_DATA, 0 signals); arb gap corrected to agg source
touched_files: strategy/artifacts.py, tests/unit/test_doc_contracts.py, docs/WORKFLOW.md, docs/DEV_REPORT_LATEST.md, docs/status/Status_M5_0.md, docs/status/Status_M4.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1822 passed, 3 skipped)
py -3.11 scripts/check_repo_safety.py: **PASS** (0 warnings, 20/20 checks)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **ALL GATES PASS** (pytest, docs_consistency, status_m4_check, m5_0_offline, m4_smoke, m4_profit)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: **PASS** (sims=2, net=$0.50)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 5 --refresh-rolling --refresh-rolling-strict --prune-keep 50: **PASS** (arb, 5 signals, $5.60)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml --cycles 5: **PASS** (cross_dex=10, 2 signals)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage2.yaml --cycles 5: **PASS** (4 DEXes, cross_dex=16, ROUNDTRIP_PROFITABLE=2 thin)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_mantle_stage2.yaml --cycles 5: **PASS** (2 DEXes, cross_dex=5, NO_DATA)
py -3.11 start.py --config-list real_minimal,zksync,base_stage2,mantle_stage2,linea,scroll --hours 0.25: **9 runs** (8 PASS + 1 NO_DATA)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.3 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-15T09:21:13Z, runDir: ci_m5_gate_20260315_102028)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs_in_window: 200, total_net_usdc: $1378.75)
  - data/runs/_rolling/long_scan_latest.json (REFRESHED 2026-03-15T09:24:23Z: 9 runs, 44 signals, $41.80, 5 profitable roundtrips)

session_run_dirs:
  - ci_m5_gate_20260315_100946 (arb primary, NORMAL, PASS, 5 signals, $5.60, rolling refresh)
  - ci_m5_gate_20260315_101057 (zksync candidate, COVERAGE, PASS, cross_dex=10, 2 signals)
  - ci_m5_gate_20260315_101207 (base stage2, COVERAGE, PASS, ROUNDTRIP_PROFITABLE=2 thin, real_quote_count=1, 4 DEXes)
  - ci_m5_gate_20260315_101358 (mantle stage2, COVERAGE, PASS, cross_dex=5, NO_DATA, 2 DEXes)

## 4) Key Results (числа з артефактів)

```
# Rolling agg (arbitrum_one primary only — m4_stability_agg.json)
agg_status: PASS
runs_in_window: 200
total_net_usdc: $1378.75
unique_pairs: 12
unique_routes_cross_dex: 6
sweep_gap_to_zero_min: 3.55 bps (best-ever)
sweep_median_gap_to_zero_bps: 17.95 bps
roundtrip_total_profitable: 0 (arb primary only)
frontier_pair: WETH/USDT

# Long scan (multi-chain — long_scan_latest.json, 2026-03-15T09:24:23Z)
total_runs: 9 (8 PASS + 1 NO_DATA)
total_signals: 44
total_net_usdc: $41.80
total_profitable_roundtrips: 5 (base=3, linea=2)
sweep_best_net_pnl_bps: -12.81 (improved from -17.41)
pass_chains: arbitrum_one, zksync, base, linea, scroll
scroll: 1 signal (first non-zero ever)

# Code changes
deprecated_pnl: pruned (removed None fields from artifacts.py)
doc_contract_tests: +5 (TestStatusHeaderBodyConsistency)
test_count: 1822 (+5 from R28.3)
config_inventory: 18 files (unchanged)
```

## 5) Contract Checks
- deprecated pnl block: PRUNED (no more None fields confusing readers)
- source attribution: FIXED (agg numbers from agg, long_scan numbers from long_scan — no mixing)
- claim honesty: FIXED (base "thin" not "REAL", mantle CROSS_DEX_VERIFIED not SIGNAL_PRODUCING)
- stale-section prevention: 5 new doc-contract tests lock formatting and freshness
- rolling discipline: OK (3+1 canonical files, NORM-only guard active)
- WORKFLOW stage2: FIXED (canonical long scan command uses stage2 configs)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1822 PASS, CI+safety PASS, 0 warnings)
data_collection_blocker: RESOLVED (fresh evidence from 6 chains, 9 long_scan runs)
market_window_blocker: MEDIUM (arb agg gap_median=17.95 bps, best-ever=3.55 — improving but not profitable)
base_evidence: THIN (ROUNDTRIP_PROFITABLE=2 but real_quote_count=1, measured_economics.available=false — needs 2-3 more)
adapter_blocker: RESOLVED (ve33 tested online R28.2, confirmed R28.3)
architecture_debt: DOCUMENTED (god-files tracked in TECH_DEBT.md)
economics_debt: PARTIAL (net_pnl_bps done, probe_slippage pending)
docs_honesty: FIXED (R28.3 cleaned stale claims, correct source attribution, honest labels)
```

## 7) R28.3 Session Summary
- **Doc honesty enforcement**: Downgraded base from "REAL" to "thin" (real_quote_count=1, measured_economics.available=false). Mantle from SIGNAL_PRODUCING to CROSS_DEX_VERIFIED (NO_DATA). Arb gap corrected to use agg source (gap_median=17.95, best-ever=3.55) not long_scan sweep_best.
- **Deprecated pnl pruned**: Removed `net_pnl_usdc: None`, `net_pnl_bps: None`, `cost_model_available: False` from deprecated block in artifacts.py. Only `_deprecated`, `_migration`, `signal_pnl_usdc`, `would_execute_pnl_usdc` remain.
- **Stale-section tests**: +5 tests in TestStatusHeaderBodyConsistency prevent Status drift (no stale Next Steps, correct test count format, no NEEDS ONLINE TEST when tested, chain classification tag freshness, no None in deprecated pnl).
- **Long scan improved**: 9 runs / 44 signals / $41.80 / 5 profitable roundtrips (was 8/23/$31.37/4). Scroll produced first non-zero signal. sweep_best improved -12.81 bps (was -17.41).
- **Remaining blockers**: arb gap_median=17.95 bps (market), base evidence thin (needs repetition), probe_slippage integration (code).

## 8) Що потрібно від ліда
1. R28.3 doc cleanup complete: all claims honest, source attribution correct, stale sections removed.
2. Base ROUNDTRIP_PROFITABLE=2 is THIN (real_quote_count=1, measured_economics.available=false) — needs 2-3 more profitable roundtrips with real_quote_count>1 for promotion.
3. Long scan improved significantly: 44 signals/$41.80/5 RT (was 23/$31.37/4). Scroll first non-zero.
4. Arb primary agg: gap_median=17.95 bps, best-ever=3.55 bps. Still market-blocked (roundtrip_profitable=0).
5. probe_slippage artifact integration still pending.
