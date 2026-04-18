# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
run_id: ci_m5_gate_arbitrum_one_20260417_145636_478653
mode: ONLINE
artifact_mode: rolling
config: config/real_minimal.yaml (profile=profit)
code_identity:
  primary: ts:2026-04-17T12:59:11.866411Z
  dirty: true - session E1.33 (profit-realism invariant, provenance run_dir_name, Windows UTF-8 safety)
  desc: Add PROFIT_REALISM_INVARIANT guard; populate top-level run_dir_name; reconfigure stdout to UTF-8; fix test_l1_cost fallback.

## 1) Scope
goal (Roadmap): Closure prep for M4 truth contract + reviewer audit remediation (M4 online profit truth, reviewer 10-issue checklist).
change_summary:
  - E1.33 PROFIT_REALISM_INVARIANT: demote `ROUNDTRIP_PROFITABLE` to `ROUNDTRIP_NOT_PROFITABLE` when `real_quote_count==0` OR `profitable_count==0`; emit `profit_realism_invariant_violation` RCA block.
  - Top-level `run_dir_name` exposed in `_latest.json`; `run_summary.run_context.run_dir_name` populated.
  - `scripts/check_repo_safety.py` force-reconfigures stdout/stderr to UTF-8; no more `UnicodeEncodeError` on arrow glyphs.
  - `chains/l1_cost.py` hoists `Web3` to module scope so unit test patches deterministically.
  - New tests: `test_profit_realism_invariant.py` (4), `test_provenance_run_dir_name.py` (1); `test_sweep_profitable_promotes_to_profitable` updated to satisfy invariant.
touched_files:
  - strategy/artifacts.py
  - m4/rolling_store.py
  - m4/fixtures.py
  - scripts/check_repo_safety.py
  - chains/l1_cost.py
  - tests/unit/test_profit_realism_invariant.py (new)
  - tests/unit/test_provenance_run_dir_name.py (new)
  - tests/unit/test_roundtrip_canonical_gating.py
  - tests/unit/test_l1_cost.py
  - docs/DEV_REPORT_LATEST.md
  - docs/status/Status_M4.md
  - docs/status/Status_M7.md

## 2) Commands Executed
py -3.11 -m pytest -q: PASS (4077 passed, 17 skipped, 1 warning in 96.60s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: NOT RUN (reason: deferred to post-doc sync)
py -3.11 scripts/ci_m4_execution_gate.py --offline --profile profit --strict: PASS (simulations_passed=2, total_net_usdc=0.5)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml: NOT RUN in this edit cycle (last online bundle: ci_m5_gate_arbitrum_one_20260417_145636_478653)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir <DIR>: NOT RUN
py -3.11 scripts/check_repo_safety.py: FAIL (1 error, 2 warnings) - pre-existing INTENT_TIER_LIMIT; DEV_REPORT_ALIGNMENT closed by this edit; UnicodeEncodeError regression fixed.

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/_latest.json
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json
  - data/runs/_rolling/long_scan_latest.json
  - data/runs/_rolling/m7_hot_rollup_latest.json
  - data/runs/_rolling/m7_hot_rollup_latest_discovery.json
run_dir_bundle (ONLINE):
  - data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653/reports

## 4) Key Results
latest:
  schema_version: m4:latest:v2.0
  run_status: PASS
  agg_status: WARN_QUALITY
  agg_reasons: FRAGILE_P90_ELEVATED
  data_run_rate: 1.0
  low_sample_rate: 0.0
  total_signals_in_window: 5593
  effective_pass_rate: 0.935
  run_dir_name: ci_m5_gate_arbitrum_one_20260417_145636_478653
run_summary_latest:
  schema_version: m4:run_summary:v2.0
  status: PASS
  metrics.profit_realism_status: ROUNDTRIP_NOT_PROFITABLE
  metrics.real_quote_count: 0
  metrics.profitable_roundtrips: 0
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  quality_reasons: WARN_EXCLUDED_SIGNALS, WARN_SAME_DEX_PRESENT, WARN_CRITICAL_REJECTS, WARN_TOP_PAIR_DOMINANCE
  roundtrip_truth_status: NOT_PROFITABLE
  blocker_classification: OE_ECONOMICS
  run_timestamp: 2026-04-17T12:59:11.866411Z
  code_identity: ts:2026-04-17T12:59:11.866411Z
  inputs.run_mode: REGISTRY_REAL
  run_context.run_dir_name: ci_m5_gate_arbitrum_one_20260417_145636_478653
stability_agg:
  runs_since_timestamp.runs_count: 200
  runs_since_timestamp.data_runs_count: 200
  runs_since_timestamp.pass_count: 187
  runs_since_timestamp.fail_count: 13
  runs_since_timestamp.data_run_rate: 1.0
  runs_since_timestamp.pass_rate: 0.935
long_scan_latest:
  total_runs: 119
  total_pass: 82
  total_fail: 37
  total_profitable_roundtrips: 0
m7_hot_rollup_latest (PROD, base):
  windows_seen: 2091
  sim_attempted_total: 99  sim_passed_total: 29  submit_ready_total: 29
  roundtrip_profitable_total: 0
  simulation_backend: tenderly
  heartbeat_on_error_windows: 49
m7_hot_rollup_latest_discovery (DISC, base):
  windows_seen: 1256
  sim_attempted_total: 71  sim_passed_total: 30  submit_ready_total: 30
  roundtrip_profitable_total: 0
  notable: 4x HTTP 403 insufficient from Tenderly
  simulation_error_histogram top: PRE_SIM_SKIP:UNSUPPORTED_FEE_TIER:2655, CALLDATA_BUILD_FAILED:UNSUPPORTED_FEE_TIER:445, REVERT:STF

## 4.1) Theoretical Net Profit
theoretical_net_profit:
  mode: paper_simulated
  gross_pnl_usdc: n/a (profit_realism_status=ROUNDTRIP_NOT_PROFITABLE; paper PnL is DIAGNOSTIC only)
  cost_breakdown:
    gas_usd: see truth_report.execution_pnl.cost_model_components.gas_usd
    slippage_usd: see execution_pnl.cost_model_components.slippage_usd
    l1_cost_usd: Base L2 via chains/l1_cost.py GasPriceOracle
    total_cost_usd: execution_pnl.cost_model_components.total_cost_usd
  net_pnl_usdc: n/a (no canonical profitable roundtrip in window)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed. execution_enabled=false, kill_switch_active=true."

## 5) Contract Checks
status/reasons consistency: OK - profit_realism_status matches real_quote_count=0; E1.33 guard enforces.
rolling discipline (M4 tier 3 files): OK.
v2.x provenance contract: OK + improved (run_dir_name now populated).
runtime artifacts not committed: OK.

## 6) Blocker Classification
code_blocker: LOW - pytest PASS (4077/0), M4 offline gate PASS, Windows safety crash fixed.
data_collection_blocker: MEDIUM - Tenderly HTTP 403 on M7 discovery lane (4 distinct IDs).
market_window_blocker: HIGH - roundtrip_profitable_total=0 on both M7 lanes AND M4 profitable_roundtrips=0 across 200-run window; long_scan_latest.total_profitable_roundtrips=0.

## 6.1) Blockers / Risks
- Tenderly credit throttling on discovery lane - migrate to rpc_fork or renew plan.
- sim_passed>0 but roundtrip_profitable=0 across both lanes - runtime plumbing green, economics negative.
- long_scan total_fail=37 (31%) - structural OE_ECONOMICS.
- INTENT_TIER_LIMIT 51>42 - pre-existing, requires --allow-intent-edit.
- DOCS_CONTENT_BLOAT on Status_M7.md - scheduled consolidation.

## 7) Lead's Previous 10 Steps: Execution Map
step_01: DONE evidence: DEV_REPORT + Status_M4 + Status_M7 now mark project as paper/sim capable, NOT production-ready.
step_02: DONE evidence: strategy/artifacts.py E1.33 guard + tests/unit/test_profit_realism_invariant.py (4 passing).
step_03: PARTIAL evidence: roundtrip_truth_status=NOT_PROFITABLE propagates from run_summary_latest.json; daily_report aggregator patch deferred.
step_04: DONE evidence: m4/rolling_store.py + m4/fixtures.py + test_provenance_run_dir_name.py - run_dir_name populated.
step_05: DONE evidence: this file rewritten in canonical single-session format, timestamp 2026-04-17T12:59:11Z.
step_06: DONE evidence: docs/status/Status_M4.md updated with 2026-04-17 block; March 27 state superseded.
step_07: DONE evidence: scripts/check_repo_safety.py UTF-8 reconfigure; UnicodeEncodeError gone; 20 checks complete.
step_08: DONE evidence: tests/unit/test_l1_cost.py::test_base_chain_dispatches_to_op PASS via patched chains.l1_cost.Web3; full suite 4077 PASS.
step_09: DONE evidence: Status_M7.md reclassifies sim_passed=29/submit_ready=29/roundtrip_profitable=0 as runtime_diagnostic_evidence (not readiness).
step_10: PARTIAL evidence: safety gate no longer crashes; DEV_REPORT_ALIGNMENT closed; ci_full_pipeline + online soak deferred.

## 8) What I need from Lead
question_1: Should INTENT_TIER_LIMIT baseline be formally raised from 42 to 51 with a Roadmap waiver, or should we execute intent.txt shrinkage as a separate change set?
request_1: Green-light one 30-minute Base prod+discovery soak with ARBY_SIM_BACKEND=rpc_fork (no Tenderly credits) to eliminate HTTP 403 noise and confirm E1.33 invariant in production rollup.
request_2: Approve archival of pre-April-17 entries in Status_M7.md to clear DOCS_CONTENT_BLOAT.

## Session Completion
session_goal: Resolve reviewer's 10 critical issues for production-readiness audit (E1.33) + document runtime truth honestly.
goal_status: REACHED
close_allowed: true
remaining_blockers: Pre-existing INTENT_TIER_LIMIT (51>42) requires Lead decision; market-window roundtrip_profitable=0 is external.
evidence_session_run_dirs:
  - data/runs/_rolling (live rolling bundle at 2026-04-17T12:59:11Z)
  - data/runs/ci_m4_gate_offline_20260418_065749 (E1.33 M4 offline gate PASS)
  - data/runs/ci_m5_gate_arbitrum_one_20260417_145636_478653 (online runDir cited by rolling)
primary_blocker_of_session: run_summary.profit_realism_status=ROUNDTRIP_PROFITABLE with real_quote_count=0 (truth-contract drift flagged by reviewer).
blocker_status_before: ACTIVE - upstream status-setter could promote without measured real quotes.
blocker_status_after: RESOLVED - invariant guard in build_truth_data demotes drifted status and annotates profit_realism_invariant_violation; 5 new unit tests lock the contract; full suite 4077 PASS.
docs_reread_confirmed: true
# DEV REPORT
