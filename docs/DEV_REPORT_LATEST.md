# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 4 Round 27.1)
**Goal**: R27.1 — Fix narrative consistency (scroll/nuri_v3, camelot_v3 in matrix), align docs with current rolling, add narrative consistency tests, run online arb candidate + scroll stage1 verification.

## 0) Meta
timestamp_utc: 2026-03-14T09:20:54Z
rolling_provenance: 2026-03-14T09:20:54Z (scroll COVERAGE, rolling updated)
mode: ONLINE (arb candidate + scroll stage1 verification runs)
test_count: 1791 passed, 2 skipped (+53 total from R26: 48 adapter readiness + 5 narrative consistency)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R27.1: narrative consistency fixes + online verification (arb candidate 4-DEX + scroll stage1 nuri_v3) |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (primary); ADAPTER: ve33 not implemented (base/aerodrome, mantle/stratum) |
| evidence_session_run_dirs | ci_m5_gate_20260314_101735 (arb 4-DEX, PASS, 14 signals, $14.61), ci_m5_gate_20260314_102036 (scroll 2-DEX, PASS, 3 signals, $0.14) |
| primary_blocker_of_session | stale narrative (docs said nuri_v3 EXCLUDED, camelot_v3 EXCLUDED while configs enabled them); no online proof for R27 config changes |
| blocker_status_before | R27: ONBOARDING_MATRIX said nuri_v3 EXCLUDED/mismatch and camelot_v3 EXCLUDED; no online verification; docs used stale rolling numbers |
| blocker_status_after | RESOLVED. Matrix aligned with configs; 5 narrative consistency tests lock alignment; online proof: arb 4-DEX=14 signals, scroll 2-DEX=3 signals |
| start_metric | R27: 1786 tests, stale narrative, no online proof |
| end_metric | R27.1: 1791 tests, narrative locked by tests, arb + scroll online PASS |
| delta | +5 narrative tests, 4 files modified (matrix, scroll config, 2 status docs), 2 online runs |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 infrastructure — narrative consistency + online verification (per lead R27.1 audit)
change_summary:
  - `docs/ONBOARDING_MATRIX.md`: MODIFIED — scroll/nuri_v3 RE-ENABLED (was EXCLUDED), camelot_v3 CANDIDATE (was EXCLUDED)
  - `config/coverage_intent_scroll.yaml`: MODIFIED — blocker text aligned with R27 (removed algebra-incompatible claims)
  - `tests/unit/test_adapter_readiness.py`: MODIFIED — +5 narrative consistency tests (TestNarrativeConsistency)
  - `docs/status/Status_M5_0.md`: R27.1 refresh with online evidence
  - `docs/status/Status_M4.md`: R27.1 refresh with online evidence
  - `docs/DEV_REPORT_LATEST.md`: full refresh with fresh run_timestamps
touched_files:
  - docs/ONBOARDING_MATRIX.md
  - config/coverage_intent_scroll.yaml
  - tests/unit/test_adapter_readiness.py
  - docs/status/Status_M5_0.md
  - docs/status/Status_M4.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1791 passed, 2 skipped, 1 warning, 30.16s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (ALL REQUIRED GATES PASSED)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_arbitrum_one_candidate.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_101735, 4 DEXes, 14 signals, $14.61)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260314_101735: **PASS**
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_scroll_stage1.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_102036, 2 DEXes, 3 signals, $0.14)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260314_102036: **PASS**

## 3) Artifacts Attached (шляхи)
rolling (updated by online runs):
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T09:20:54Z)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs=200)
  - data/runs/_rolling/long_scan_latest.json (schema v1.7, from R26: 15 runs, 46 signals, $36.35)
run_dir_bundle (R27.1 ONLINE):
  - data/runs/ci_m5_gate_20260314_101735/reports (arb candidate, 4 DEXes)
  - data/runs/ci_m5_gate_20260314_102036/reports (scroll stage1, 2 DEXes)

## 4) Key Results (числа з артефактів)

```
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: PASS
  data_run_rate: 0.935
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.signals_count: 3
  metrics.total_net_usdc: 0.1419
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  run_timestamp: 2026-03-14T09:20:54.909278Z
  code_identity: ts:2026-03-14T09:20:54.909278Z
  inputs.run_mode: REGISTRY_REAL
  inputs.run_dir_name: ci_m5_gate_20260314_102036
stability_agg:
  schema_version: m4:stability_agg:v2.0
  agg_status: PASS
  agg_reasons: []
  runs_since_timestamp.runs_count: 200
  runs_since_timestamp.data_runs_count: 187
  quick_stats.unique_pairs: 13
  quick_stats.unique_routes: 6
  quick_stats.low_sample_rate: 0.05
  quick_stats.data_run_rate: 0.935
  quick_stats.total_net_usdc: 1304.9818
long_scan_latest (pinned to last multi-chain scan, NOT refreshed this session):
  schema: start:long_scan_summary:v1.7
  generated_at: 2026-03-13T22:14:53Z
  total_runs: 15 (PASS chains)
  total_included_signals: 46
  total_net_usdc: $36.35
  run_context.run_timestamp: 2026-03-13T22:14:53Z
onboard_verification (R27.1, fresh):
  arb_candidate: ci_m5_gate_20260314_101735, PASS, 14 signals, $14.61, dexes_active=4, cross_dex=27
  scroll_stage1: ci_m5_gate_20260314_102036, PASS, 3 signals, $0.14, dexes_active=2, cross_dex=8
```

## 4.1) Theoretical Net Profit (cost-aware reporting)

```
theoretical_net_profit:
  mode: paper_simulated
  arb_candidate: $14.61 (1 run, 4 DEXes, 14 signals)
  scroll_stage1: $0.14 (1 run, 2 DEXes, 3 signals)
  long_scan_latest: $36.35 (15 runs, 5 chains, pinned to 2026-03-13)
  cost_breakdown: per-signal in truth_reports (gas+slippage+L1 cost model)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — _latest, run_summary, m4_stability_agg, long_scan_latest
- v2.x provenance contract: OK (run_timestamp, code_identity=ts:ISO, no runs_by_code_sha)
- runtime artifacts not committed: OK
- schema version: **v1.7** (unchanged from R26)
- test delta: +53 tests (1738 → 1791)
- narrative consistency: OK (5 tests lock config/docs alignment)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1791 PASS, CI green, safety PASS)
data_collection_blocker: LOW (data_run_rate=0.935, low_sample_rate=0.05, unique_pairs=13)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary chain arb)
adapter_blocker: MEDIUM (ve33 not implemented — affects base/aerodrome, mantle/stratum)
```

### Per-Chain Blocker Classification (R27.1 — with fresh online evidence)

| Chain | Classification | Route Health | Gap bps | Signals | Stage Config | Evidence |
|-------|---------------|-------------|---------|---------|--------------|----------|
| arbitrum_one | NONE | 1.00 | 8.41 | 14 (4-DEX) | onboard_arbitrum_one_candidate.yaml | ci_m5_gate_20260314_101735 PASS |
| zksync | MIXED | 1.00 | 0.0 | 4 | onboard_zksync_candidate.yaml | rolling frontier |
| base | MIXED + ve33 gap | 1.00 | 90.73 | 31 | onboard_base_stage1.yaml | long_scan frontier |
| mantle | STRUCTURAL + ve33 gap | 1.00 | n/a | 6 | onboard_mantle_stage1.yaml | long_scan frontier |
| linea | STRUCTURAL | 1.00 | n/a | 9 | onboard_linea_stage1.yaml | long_scan frontier |
| scroll | CROSS_DEX_UNVERIFIED→**VERIFIED** | 1.00 | n/a | 3 (2-DEX) | onboard_scroll_stage1.yaml | ci_m5_gate_20260314_102036 PASS |

### Rollout Queue (R27 — additive model, per lead directive)

| Priority | Chain | Stage Config | Condition |
|----------|-------|--------------|-----------|
| 1 | arbitrum_one (NORMAL) | onboard_arbitrum_one_candidate.yaml | Exit gate, then 4-DEX additive |
| 2 | zksync | onboard_zksync_candidate.yaml | drift < 0.25 |
| 3 | base | onboard_base_stage1.yaml | ve33 adapter (aerodrome) needed |
| 4 | mantle | onboard_mantle_stage1.yaml | ve33 adapter (stratum) needed |
| 5 | linea | onboard_linea_stage1.yaml | lynex_v3 algebra stability |
| 6 | scroll | onboard_scroll_stage1.yaml | nuri_v3 quoter_v2 verification |

## 6.1) Blockers / Risks (max 5)
- **MARKET**: roundtrip_profitable=0 on arbitrum_one (primary) — gap=8.41 bps (improved from 20.5)
- **ADAPTER**: ve33 not implemented — blocks base/aerodrome, mantle/stratum full coverage
- **SCROLL**: nuri_v3 quoter_v2 CONFIRMED working (3 cross-DEX signals); single PASS is evidence, NOT exit from ECOSYSTEM_BLOCKED
- **STRUCTURAL**: mantle/linea stage1 configs exclude ve33 DEXes (adapter gap)
- **NOTE**: base roundtrip_profitable=2 is COVERAGE evidence, NOT promotion evidence

## 7) Lead's R27.1 10 Steps: Execution Map
step_01: **DONE** — ONBOARDING_MATRIX.md scroll/nuri_v3 fixed: RE-ENABLED (was EXCLUDED/mismatch). Evidence: matrix file, test_matrix_scroll_nuri_not_excluded PASS.
step_02: **DONE** — coverage_intent_scroll.yaml blocker text updated: removed "algebra-incompatible", now says "cross_dex_unverified". Evidence: test_scroll_blocker_text_no_algebra_incompatible PASS.
step_03: **DONE** — camelot_v3 narrative aligned: matrix says CANDIDATE (was EXCLUDED). Evidence: test_matrix_camelot_not_excluded_if_in_candidate PASS.
step_04: **DONE** — DEV_REPORT REACHED vs PENDING resolved: R27 offline scope = REACHED, online was R27.1 scope. Now R27.1 done.
step_05: **DONE** — Docs pinned to current rolling: run_timestamp=2026-03-14T09:20:54Z, run_dir=ci_m5_gate_20260314_102036.
step_06: **DONE** — 5 narrative consistency tests added: scroll nuri config, blocker text, matrix scroll, matrix camelot, stage-config-matrix alignment. Evidence: 53 total tests PASS.
step_07: **DONE** — Matrix-to-stage-config alignment test: test_stage_config_dexes_match_matrix_entries PASS.
step_08: **DONE** — Online scope defined: arb candidate (4-DEX test) + scroll stage1 (nuri_v3 quoter_v2 proof).
step_09: **DONE** — Online runs completed: arb=ci_m5_gate_20260314_101735 (PASS, 14 signals, $14.61, 4 DEXes), scroll=ci_m5_gate_20260314_102036 (PASS, 3 signals, $0.14, 2 DEXes).
step_10: **DONE** — Docs refreshed last: DEV_REPORT, Status_M5_0, Status_M4 all updated with fresh run_timestamps from step 9.

## 8) Що потрібно від ліда
1. Scroll: single PASS ≠ exit from ECOSYSTEM_BLOCKED — потрібна стійка evidence (2+ consecutive runs with signals)
2. Arb candidate 4-DEX: 14 signals / $14.61 — чи достатньо для exit gate, чи потрібно 5 consecutive runs?
3. ve33 adapter implementation priority (base/aerodrome vs mantle/stratum)
4. Чи потрібно long_scan refresh (current pinned to 2026-03-13, 15 runs / $36.35)?
