# DEV REPORT

> **Policy**: Only `docs/DEV_REPORT_LATEST.md` tracked. Versioned files forbidden.
> Provenance: `run_timestamp` from rolling artifacts (UTC).

## Stage Context

**End-goal**: Production DEX-DEX arbitrage with real on-chain execution and proven net profit.
**Current stage**: M5_0/M4.1 infrastructure + universe bring-up. Execution disabled, rolling on arbitrum_one.

## SESSION GOAL (2026-03-14, Session 4 Round 27.2)
**Goal**: R27.2 — Fix rolling contamination (COVERAGE scroll run overwrote pointer files), add NORM-only rolling guard, strengthen check_repo_safety, run fresh online evidence (primary + arb candidate + scroll stage1 + long scan), refresh docs LAST.

## 0) Meta
timestamp_utc: 2026-03-14T18:39:08Z
rolling_provenance: 2026-03-14T18:39:08Z (arbitrum_one NORMAL, ci_m5_gate_20260314_193819)
mode: ONLINE (primary NORMAL + arb candidate + scroll stage1 + long scan 6 chains)
test_count: 1798 passed, 2 skipped (+7 from R27.1: 4 rolling pointer protection + 3 rolling chain purity)
schema_version: start:long_scan_summary:v1.7

## 0.2) Session Completion Gate (MANDATORY)

| Field | Value |
|-------|-------|
| session_goal | R27.2: fix rolling contamination (COVERAGE overwriting pointers), add NORM-only guard, fresh online evidence, docs refresh |
| goal_status | **REACHED** |
| close_allowed | true |
| remaining_blockers | MARKET: roundtrip_profitable=0 on arb (primary); ADAPTER: ve33 not implemented (base/aerodrome, mantle/stratum) |
| evidence_session_run_dirs | ci_m5_gate_20260314_192514 (arb primary NORMAL, 4 signals, $5.62), ci_m5_gate_20260314_192713 (arb 4-DEX candidate, 87 quotes, cross_dex=27, 14 sims PASS), ci_m5_gate_20260314_193000 (scroll stage1 COVERAGE, 3 signals, nuri_v3 confirmed), ci_m5_gate_20260314_193819 (long_scan arb run, 4 signals, $5.72, rolling updated) |
| primary_blocker_of_session | rolling contamination: run_summary_latest.json pointed to chain=scroll, run_kind=COVERAGE (R27.1 scroll online inadvertently overwrote pointer files) |
| blocker_status_before | CONTAMINATED: rolling pointers pointed to ci_m5_gate_20260314_102036 (scroll COVERAGE), not primary arb NORMAL |
| blocker_status_after | RESOLVED. NORM-only guard in m4/gates.py (v3.2.23); check [20] in check_repo_safety v1.14.0; rolling now points to ci_m5_gate_20260314_193819 (arb NORMAL) |
| start_metric | R27.1: 1791 tests, rolling contaminated (scroll COVERAGE), no NORM-only pointer guard |
| end_metric | R27.2: 1798 tests, rolling clean (arb NORMAL), +7 regression tests, NORM-only guard enforced |
| delta | +7 tests, 3 code files modified (m4/gates.py, check_repo_safety.py, test_rolling_chain_keys.py), 3 doc updates (matrix, scroll config, DEV_REPORT/Status), 4 online runs + long scan |
| docs_reread_confirmed | true |

## 1) Scope (що і навіщо)
goal (Roadmap пункт): M5_0 infrastructure — rolling contamination fix + fresh evidence (per lead R27.2 audit)
change_summary:
  - `m4/gates.py`: MODIFIED — NORM-only rolling pointer policy (v3.2.23): skip writing run_summary_latest.json and _latest.json for non-NORMAL runs
  - `scripts/check_repo_safety.py`: MODIFIED — v1.13.0→v1.14.0: added check [20] rolling chain purity (validates run_kind=NORMAL + chain_key=arbitrum_one in pointer files)
  - `tests/unit/test_rolling_chain_keys.py`: MODIFIED — +7 tests: 4 TestRollingPointerProtection + 3 TestCheckRollingChainPurity
  - `docs/ONBOARDING_MATRIX.md`: MODIFIED — camelot_v3 and nuri_v3 "pending"→"verified" with runDir evidence
  - `config/onboard_scroll_stage1.yaml`: MODIFIED — PURPOSE softened (1 PASS ≠ exit from ECOSYSTEM_BLOCKED), nuri_v3 ADAPTER READINESS→VERIFIED R27.1
  - `docs/status/Status_M5_0.md`: R27.2 refresh with fresh online evidence
  - `docs/status/Status_M4.md`: R27.2 refresh with fresh online evidence
  - `docs/DEV_REPORT_LATEST.md`: full rewrite with R27.2 evidence
touched_files:
  - m4/gates.py
  - scripts/check_repo_safety.py
  - tests/unit/test_rolling_chain_keys.py
  - docs/ONBOARDING_MATRIX.md
  - config/onboard_scroll_stage1.yaml
  - docs/status/Status_M5_0.md
  - docs/status/Status_M4.md
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed (лише факти)

py -3.11 -m pytest tests/unit -q: **PASS** (1798 passed, 2 skipped, 1 warning, 30.50s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: **PASS** (ALL REQUIRED GATES PASSED, 1791/2/1 at pre-fix; 1798/2/1 post-fix)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_192514, arb primary NORMAL, 4 signals, $5.62)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260314_192514 --artifact-mode rolling: **PASS**
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_arbitrum_one_candidate.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_192713, 4-DEX, 87 quotes, cross_dex=27)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260314_192713 --artifact-mode full: **PASS** (14 simulations)
py -3.11 scripts/ci_m5_0_gate.py --online --config config/onboard_scroll_stage1.yaml --cycles 1: **PASS** (runDir ci_m5_gate_20260314_193000, 2-DEX, 3 signals, nuri_v3 confirmed)
py -3.11 scripts/ci_m4_execution_gate.py --online --profile profit --run-dir data/runs/ci_m5_gate_20260314_193000 --artifact-mode full: **PASS** (1 simulation)
py -3.11 start.py --hours 0.25 --cycles 1 --chains arbitrum_one zksync base mantle linea scroll: **PASS** (long scan: 8 runs, 17 signals, $23.49, 565s)

## 3) Artifacts Attached (шляхи)
rolling (updated by R27.2 online runs):
  - data/runs/_rolling/_latest.json (run_status: PASS, agg_status: PASS)
  - data/runs/_rolling/run_summary_latest.json (run_timestamp: 2026-03-14T18:39:08Z, chain_key: arbitrum_one, run_kind: NORMAL)
  - data/runs/_rolling/m4_stability_agg.json (agg_status: PASS, runs=200, $1310.11)
  - data/runs/_rolling/long_scan_latest.json (generated: 2026-03-14T18:40:26Z, 8 runs, 17 signals, $23.49)
run_dir_bundle (R27.2 ONLINE):
  - data/runs/ci_m5_gate_20260314_192514/reports (arb primary NORMAL)
  - data/runs/ci_m5_gate_20260314_192713/reports (arb 4-DEX candidate)
  - data/runs/ci_m5_gate_20260314_193000/reports (scroll stage1 COVERAGE)
  - data/runs/ci_m5_gate_20260314_193819/reports (long_scan arb run, rolling updated)

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
  metrics.signals_count: 4
  metrics.total_net_usdc: 5.7174
  profit_status: PASS
  drift_status: PASS
  quality_status: WARN
  run_timestamp: 2026-03-14T18:39:08.408499Z
  code_identity: ts:2026-03-14T18:39:08.408499Z
  inputs.run_mode: REGISTRY_REAL
  inputs.run_dir_name: ci_m5_gate_20260314_193819
  inputs.chain_key: arbitrum_one
  inputs.run_kind: NORMAL
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
  quick_stats.total_net_usdc: 1310.1083
long_scan_latest (REFRESHED R27.2):
  schema: start:long_scan_summary:v1.7
  generated_at: 2026-03-14T18:40:26Z
  total_runs: 8 (7 PASS + 1 FAIL)
  total_included_signals: 17
  total_net_usdc: $23.49
  total_profitable_roundtrips: 2
  pass_chains: [arbitrum_one, zksync, base, mantle, linea]
  fail_chains: [scroll]
  accepted_fail_chains: [scroll]
  per_chain:
    arbitrum_one: runs=2, signals=8, net=$11.34, gap=15.77 bps, cross_dex=3
    linea: runs=1, signals=2, net=$7.12, cross_dex=12
    base: runs=1, signals=4, net=$2.19, cross_dex=15
    mantle: runs=1, signals=1, net=$2.45, cross_dex=0
    zksync: runs=2, signals=2, net=$0.39, cross_dex=10
    scroll: runs=1, signals=0, net=$0.00, cross_dex=8 (accepted-fail)
onboard_verification (R27.2, fresh):
  arb_primary: ci_m5_gate_20260314_192514, PASS, 4 signals, $5.62
  arb_candidate: ci_m5_gate_20260314_192713, PASS, 87 quotes, cross_dex=27, 14 simulations
  scroll_stage1: ci_m5_gate_20260314_193000, PASS, 3 signals, nuri_v3 confirmed (rolling NOT overwritten — NORM-only guard)
```

## 4.1) Theoretical Net Profit (cost-aware reporting)

```
theoretical_net_profit:
  mode: paper_simulated
  arb_primary: $5.72 (1 run, 4 signals, long_scan arb component)
  arb_candidate: $14.61 equivalent (4-DEX, 14 simulations passed)
  scroll_stage1: $0.00 (COVERAGE, 3 signals — not counted in rolling)
  long_scan_total: $23.49 (8 runs, 6 chains, 17 signals)
  cost_breakdown: per-signal in truth_reports (gas+slippage+L1 cost model)
  disclaimer: "Theoretical profit based on simulated execution. No real trades were executed."
```

## 5) Contract Checks
- status/reasons consistency: OK
- rolling discipline (3+1 canonical files): OK — _latest, run_summary, m4_stability_agg, long_scan_latest
- v2.x provenance contract: OK (run_timestamp, code_identity=ts:ISO, no runs_by_code_sha)
- runtime artifacts not committed: OK
- NORM-only rolling pointer guard: OK (m4/gates.py v3.2.23 — verified: scroll COVERAGE did NOT overwrite rolling)
- check_repo_safety v1.14.0: OK (check [20] rolling chain purity — detects non-NORMAL/non-primary contamination)
- schema version: **v1.7** (unchanged from R26)
- test delta: +7 tests (1791 → 1798)
- narrative consistency: OK (5 R27.1 tests + 7 R27.2 rolling tests)

## 6) Blocker Classification

```
code_blocker: LOW (pytest 1798 PASS, CI green, safety PASS)
data_collection_blocker: LOW (data_run_rate=0.935, low_sample_rate=0.05, unique_pairs=13)
market_window_blocker: HIGH (roundtrip_profitable=0 on primary chain arb, gap=15.77 bps)
adapter_blocker: MEDIUM (ve33 not implemented — affects base/aerodrome, mantle/stratum)
```

### Per-Chain Blocker Classification (R27.2 — with fresh long_scan evidence)

| Chain | Classification | Route Health | Gap bps | Signals | Stage Config | Evidence |
|-------|---------------|-------------|---------|---------|--------------|----------|
| arbitrum_one | NONE | 1.00 | 15.77 | 8 (2 runs) | onboard_arbitrum_one_candidate.yaml | long_scan + ci_m5_gate_20260314_192713 |
| linea | STRUCTURAL | 1.00 | n/a | 2 | onboard_linea_stage1.yaml | long_scan frontier (rank #2) |
| base | MIXED + ve33 gap | 1.00 | n/a | 4 | onboard_base_stage1.yaml | long_scan frontier (rank #3) |
| mantle | STRUCTURAL + ve33 gap | 1.00 | n/a | 1 | onboard_mantle_stage1.yaml | long_scan frontier (rank #4) |
| zksync | MIXED | 1.00 | n/a | 2 | onboard_zksync_candidate.yaml | long_scan frontier (rank #5), drift=0.27 |
| scroll | CROSS_DEX_VERIFIED | 1.00 | n/a | 0 (long_scan) / 3 (stage1) | onboard_scroll_stage1.yaml | ci_m5_gate_20260314_193000 PASS, accepted-fail |

### Rollout Queue (R27.2 — additive model, per lead directive)

| Priority | Chain | Stage Config | Condition |
|----------|-------|--------------|-----------|
| 1 | arbitrum_one (NORMAL) | onboard_arbitrum_one_candidate.yaml | 4-DEX PASS (R27.2: 14 sims), exit gate: 5 consecutive |
| 2 | zksync | onboard_zksync_candidate.yaml | drift 0.27 > 0.25 threshold — needs improvement |
| 3 | base | onboard_base_stage1.yaml | ve33 adapter (aerodrome) needed |
| 4 | mantle | onboard_mantle_stage1.yaml | ve33 adapter (stratum) needed |
| 5 | linea | onboard_linea_stage1.yaml | lynex_v3 algebra stability |
| 6 | scroll | onboard_scroll_stage1.yaml | nuri_v3 verified R27.1/R27.2, needs sustained evidence |

## 6.1) Blockers / Risks (max 5)
- **MARKET**: roundtrip_profitable=2 total (base COVERAGE only) — arb primary gap=15.77 bps (regressed from 8.41)
- **ADAPTER**: ve33 not implemented — blocks base/aerodrome, mantle/stratum full coverage
- **ROLLING CONTAMINATION** (RESOLVED R27.2): NORM-only guard prevents COVERAGE/SMOKE runs from overwriting pointer files
- **ZKSYNC**: drift_rejection_rate_median=0.27 (above 0.25 threshold); needs improvement before promotion
- **SCROLL**: nuri_v3 confirmed (2 sessions), but 0 signals in long_scan — needs sustained evidence

## 7) Lead's R27.2 10 Steps: Execution Map
step_01: **DONE** — NORM-only rolling pointer guard added to m4/gates.py (v3.2.23). Non-NORMAL runs skip writing run_summary_latest.json and _latest.json. Evidence: scroll COVERAGE run ci_m5_gate_20260314_193000 did NOT overwrite rolling.
step_02: **DONE** — Regression tests: +4 TestRollingPointerProtection (COVERAGE blocks, NORMAL allows, missing defaults NORMAL, SMOKE blocks). Evidence: 15 tests in test_rolling_chain_keys.py PASS.
step_03: **DONE** — check_repo_safety v1.14.0: check [20] rolling chain purity validates run_kind=NORMAL + chain_key=arbitrum_one. Evidence: detected 4 ROLLING_CONTAMINATION errors before fix, 0 after.
step_04: **DONE** — Rolling restored to primary NORMAL via fresh arb run ci_m5_gate_20260314_192514. Verified: inspect_rolling shows latest_chain_key=arbitrum_one. Final rolling: ci_m5_gate_20260314_193819 (long_scan arb run).
step_05: **DONE** — ONBOARDING_MATRIX: camelot_v3 and nuri_v3 changed from "pending" to "verified" with runDir evidence.
step_06: **DONE** — onboard_scroll_stage1.yaml: PURPOSE softened ("1 PASS = adapter/quoter proof, NOT automatic exit from ECOSYSTEM_BLOCKED"). nuri_v3 ADAPTER READINESS updated to VERIFIED R27.1.
step_07: **DEFERRED** — ve33 adapter engineering (base/aerodrome, mantle/stratum) — future milestone.
step_08: **DEFERRED** — zksync drift improvement — requires market conditions or pair tuning.
step_09: **DONE** — Online runs: (a) arb primary NORMAL PASS, (b) arb candidate 4-DEX PASS (14 sims), (c) scroll stage1 PASS (3 signals, rolling NOT overwritten), (d) long scan 6 chains (8 runs, $23.49).
step_10: **DONE** — Docs refresh: DEV_REPORT full rewrite, Status_M5_0 and Status_M4 updated with R27.2 evidence.

## 8) Що потрібно від ліда
1. Arb gap regression: 8.41→15.77 bps — ринкова волатильність чи потрібна дія?
2. zksync drift 0.27 (вище порогу 0.25) — чи є priority для pair tuning?
3. ve33 adapter implementation priority (base/aerodrome vs mantle/stratum)
