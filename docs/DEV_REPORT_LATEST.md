# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 6 Round 28.1)
**Goal**: R28.1 — Honesty correction. Roll back overclaimed R28 REACHED (no online evidence). Fix ONBOARDING_MATRIX lies, close net_pnl_bps TODO, align Status files to reality.
**Prior (R28)**: Architecture audit — removed strategy/execution/ stubs, extracted core/gate_helpers.py+repo_checks.py. Valid work, but overclaimed "REACHED" without online evidence and "economics debt closed" while net_pnl_bps=None TODO remained.

## 0) Meta
timestamp_utc: 2026-03-14T21:35:57Z
rolling_provenance: 2026-03-14T21:35:57Z (arbitrum_one NORMAL — FRESH R28.1 evidence, ci_m5_gate_20260314_223513)
mode: HONESTY_CORRECTION (doc/code fixes + online runs)
test_count: 1812 passed, 3 skipped (+9 new tests: 4 net_pnl_bps, 5 doc-contract)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R28.1: Honesty correction — roll back overclaims, fix ONBOARDING_MATRIX, close economics TODO, fresh online evidence |
| goal_status | **IN_PROGRESS** |
| close_allowed | false |
| remaining_blockers | MARKET: gap_to_zero≈23 bps on arb; ZKSYNC: drift, PROBE_SLIPPAGE: artifact integration pending |
| evidence_session_run_dirs | ci_m5_gate_20260314_222606 (arb, PASS), ci_m5_gate_20260314_222708 (zksync, PASS), ci_m5_gate_20260314_222846 (base, PASS, **ROUNDTRIP_PROFITABLE=1**), ci_m5_gate_20260314_223010 (mantle, PASS) |
| primary_blocker_of_session | R28 overclaimed; ONBOARDING_MATRIX lies; net_pnl_bps=None → FIXED; Status contradictions → FIXED |
| blocker_status_before | DEV_REPORT=REACHED (invalid), ve33=NOT_IMPLEMENTED (lie), net_pnl_bps=None, Status contradictions |
| blocker_status_after | DEV_REPORT=IN_PROGRESS (honest), ve33=IMPLEMENTED (true), net_pnl_bps=computed, Status aligned, FRESH evidence from 4 chains |
| start_metric | R28: 1803 tests, docs overclaimed, economics TODO open, no same-session online evidence |
| end_metric | R28.1: 1812 tests (+9), 4 chain scans (arb+zksync+base+mantle), base ROUNDTRIP_PROFITABLE=1 |
| delta | +9 tests, +1 roundtrip profitable (base), docs honesty restored, net_pnl_bps implemented |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 — honesty correction for R28 overclaims (R28.1 lead directive)
change_summary:
  - R28 valid work: `strategy/execution/` DELETED, `core/gate_helpers.py` + `core/repo_checks.py` extracted, preflight renamed, discovery formalized
  - R28 overclaims corrected:
    - DEV_REPORT goal_status REACHED → IN_PROGRESS (no same-session online evidence, violates WORKFLOW.md)
    - "economics debt closed" → FALSE (net_pnl_bps=None TODO still open in artifacts.py)
    - ONBOARDING_MATRIX ve33=NOT_IMPLEMENTED → IMPLEMENTED (was true since R27.4)
    - Status_M4 line 31 "economics debt closed" contradicts line 217 "[TODO] probe_slippage() ready, artifact integration pending"
  - R28.1 code fixes:
    - `strategy/artifacts.py`: net_pnl_bps computed from net_pnl_usdc / paper_size_usd * 10000
    - `docs/ONBOARDING_MATRIX.md`: ve33 → IMPLEMENTED, base/mantle → adapter-ready (online-unverified)
    - Status_M5_0.md: header bumped to R28.1, honest descriptions
    - Status_M4.md: "economics debt closed" removed, contradiction fixed
touched_files: DEV_REPORT_LATEST.md, ONBOARDING_MATRIX.md, Status_M5_0.md, Status_M4.md, strategy/artifacts.py

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1812 passed, 3 skipped, 1 warning)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 3 --refresh-rolling: **PASS** (arb primary, m4_sim_net_usdc=$5.52)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_zksync_candidate.yaml --cycles 3: **PASS** (cross_dex=10)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_base_stage1.yaml --cycles 2: **PASS** (ROUNDTRIP_PROFITABLE=1) 🎉
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_mantle_stage1.yaml --cycles 2: **PASS** (same-dex only)

## 3) Artifacts Attached (шляхи)
rolling (FRESH — R28.1 online evidence):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T21:35:57Z)
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json
  - data/runs/_rolling/last_roundtrip_profitable.json (NEW — from base ROUNDTRIP_PROFITABLE=1)

session_run_dirs:
  - ci_m5_gate_20260314_222606 (arb primary, NORMAL, PASS)
  - ci_m5_gate_20260314_222708 (zksync candidate, COVERAGE, PASS)
  - ci_m5_gate_20260314_222846 (base stage1, COVERAGE, PASS, ROUNDTRIP_PROFITABLE=1)
  - ci_m5_gate_20260314_223010 (mantle stage1, COVERAGE, PASS)

## 4) Key Results (числа з артефактів)

```
docs_honesty_fixes: ONBOARDING_MATRIX ve33 corrected, Status contradictions fixed
net_pnl_bps: IMPLEMENTED (was None/TODO) — 4 new tests added
doc_contract_tests: 5 new tests (verify adapter claims match code)
economics_debt: PARTIALLY_CLOSED (net_pnl_bps done, probe_slippage artifact integration still pending)
architecture_debt: PARTIALLY_RESOLVED (R28 removed stubs; god-files documented in TECH_DEBT.md)
execution_skeletons: ACKNOWLEDGED (simulator.py + dex_dex_executor.py are skeletons — expected for M4.1)
test_count: 1812 (+9 from R28.1)
online_chains_verified: 4 (arb, zksync, base, mantle)
roundtrip_profitable: 1 (base stage1 — first ROUNDTRIP_PROFITABLE since R27!)
```

## 5) Contract Checks
- status/reasons consistency: FIXED (R28 had contradictions in Status_M4 line 31 vs 217)
- rolling discipline (3+1 canonical files): OK — preserved from R27.4
- execution layer: CANONICAL — execution/ is sole layer, strategy/execution/ deleted (R28)
- god-files: PARTIALLY SPLIT — core/gate_helpers.py + core/repo_checks.py extracted (R28), but ci_m5_0_gate.py=1887 lines, check_repo_safety.py=1596, quotes.py=1722, run_scan_real.py=1346
- economics: PARTIALLY CLOSED — net_pnl_bps computed (R28.1), probe_slippage artifact integration still TODO
- ONBOARDING_MATRIX: FIXED — ve33 corrected to IMPLEMENTED
- execution skeletons: HONEST — simulator.py and dex_dex_executor.py are declared skeletons (expected for M4.1)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1812 PASS, CI gates green)
data_collection_blocker: RESOLVED (fresh online evidence from 4 chains)
market_window_blocker: HIGH (arb: roundtrip_profitable=0, gap≈23 bps; base: roundtrip_profitable=1 🎉)
adapter_blocker: PARTIALLY_VERIFIED (ve33 implemented R27.4; base tested with uniswap_v3+sushi+pancake, stratum not in stage1 config)
architecture_debt: DOCUMENTED (god-files tracked in TECH_DEBT.md)
economics_debt: PARTIAL (net_pnl_bps done, probe_slippage pending)
docs_honesty: FIXED (R28.1 corrected overclaims)
```

## 7) R28.1 Session Summary
- **Honesty corrections**: DEV_REPORT rolled back from REACHED, ONBOARDING_MATRIX ve33 fixed, Status contradictions resolved
- **Code improvements**: net_pnl_bps implemented, doc-contract tests added (5 tests prevent future lies)
- **Online verification**: 4 chains scanned with fresh evidence
- **Key achievement**: Base chain ROUNDTRIP_PROFITABLE=1 — first profitable roundtrip since R27
- **Remaining blockers**: arb gap≈23 bps (market), probe_slippage integration (code), zksync drift (market)

## 8) Що потрібно від ліда
1. ✅ Online runs completed: arb, zksync, base, mantle verified with fresh evidence
2. ✅ Base ROUNDTRIP_PROFITABLE=1: First profitable roundtrip, but on base not arb primary
3. Arb primary still market-blocked: gap≈23 bps, roundtrip_profitable=0
4. probe_slippage: artifact integration still pending (Status_M4 line 217)
5. God-file splitting: documented in TECH_DEBT.md as ongoing work
