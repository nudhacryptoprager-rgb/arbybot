# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-03-27T21:30:14Z
run_id: m7r1_300b_verify / m7r1_triangular_verify (structural refactor evidence session)
mode: ONLINE (evidence runs + unit tests + CI gates)
artifact_mode: local evidence (data/tmp/m7r1_300b_verify.json, data/tmp/m7r1_triangular_verify.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-03-27T21:30:14Z
  dirty: true
  desc: M7.R1 structural refactor — extract m7/ package + 8th blocker tag
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275

## Session Completion
session_goal: M7.R1 -- extract all M7 logic into dedicated m7/ package (orderflow, triangular, shared); preserve CLI flags, artifact schemas, reject codes, milestone semantics; add BLOCKER_LOW_LAG_RPC_QUOTE_FAIL as 8th canonical tag
goal_status: REACHED (m7/ package created with 14 modules; scripts are thin wrappers; engine files are re-export shims; 8th blocker tag added; all tests pass; both CLIs produce valid artifacts)
close_allowed: true
remaining_blockers: same as M7.A.5.18 — NO_COUNTER_POOL dominates low-lag; temporal variance fundamental; no low-lag scored
evidence_session_run_dirs: [data/tmp/m7r1_300b_verify.json, data/tmp/m7r1_triangular_verify.json]
primary_blocker_of_session: structural — monolithic scripts exceeded maintainability threshold
blocker_status_before: scripts/m7a_orderflow_replay.py at 4443 lines, scripts/m7a_enumerate_cycles.py at 1396 lines, no package boundary
blocker_status_after: m7/ package with 14 modules (max 1105 lines), scripts as thin wrappers (94-154 lines), engine files as re-export shims (19-23 lines)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.R1 -- structural refactor; not a market hypothesis but a maintenance session to extract m7/ package
change_summary:
  - Created `m7/` package with 3 subpackages: `shared/`, `orderflow/`, `triangular/`
  - `m7/shared/constants.py` (171 lines): all M7 constants, reject reasons, blocker tags, event types, surfaces, thresholds
  - `m7/orderflow/` (7 modules + cli.py): contracts, events, resolve, coverage, pricing, scoring_parallel, artifacts, cli
  - `m7/triangular/` (4 modules + cli.py): graph, scoring, verdicts, repeatability, cli
  - `scripts/m7a_orderflow_replay.py` reduced from 4443 lines to 154 lines (thin re-export wrapper)
  - `scripts/m7a_enumerate_cycles.py` reduced from 1396 lines to 94 lines (thin re-export wrapper)
  - `engine/triangular_cycles.py` and `engine/triangular_graph.py` converted to re-export shims (19-23 lines)
  - Added `BLOCKER_LOW_LAG_RPC_QUOTE_FAIL` as 8th canonical blocker tag (was missing despite RPC_QUOTE_FAIL dominating in fresh verify runs)
  - Updated backward-compat test: blocker count 7 → 8
  - No new BackrunResult fields (still 56). No new reject reasons (still 19).
touched_files:
  - m7/__init__.py, m7/shared/__init__.py, m7/shared/constants.py (NEW)
  - m7/orderflow/__init__.py, contracts.py, events.py, resolve.py, coverage.py, pricing.py, scoring_parallel.py, artifacts.py, cli.py (NEW)
  - m7/triangular/__init__.py, graph.py, scoring.py, verdicts.py, repeatability.py, cli.py (NEW)
  - scripts/m7a_orderflow_replay.py (REWRITTEN: thin wrapper)
  - scripts/m7a_enumerate_cycles.py (REWRITTEN: thin wrapper)
  - engine/triangular_cycles.py (REWRITTEN: re-export shim)
  - engine/triangular_graph.py (REWRITTEN: re-export shim)
  - tests/unit/test_orderflow_contracts.py (MODIFIED: blocker count 7→8)
  - docs/status/Status_M7.md (MODIFIED: M7.R1 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit/test_orderflow_contracts.py tests/unit/test_triangular_contracts.py -q: PASS (596 passed)
py -3.11 -m pytest tests/unit -q: PASS (3180 passed, 6 skipped in ~56s)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (~55s, ALL REQUIRED GATES PASSED)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --output data/tmp/m7r1_300b_verify.json: PASS (30 events, 1 low-lag)
py -3.11 scripts/m7a_enumerate_cycles.py --chain arbitrum_one --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7r1_triangular_verify.json: PASS (500 cycles, 67 measured)

## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7r1_300b_verify.json (300-block ws-live, 30 events, 1 low-lag, 4 active blocker tags)
  - data/tmp/m7r1_triangular_verify.json (500 cycles, 67/100 measured, best_net=-20.18 bps)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.R1 Structural Refactor

### Package Structure

| Package | Modules | Total Lines | Largest Module |
|---------|---------|-------------|----------------|
| m7/shared/ | 1 | 171 | constants.py (171) |
| m7/orderflow/ | 8 | 4034 | cli.py (1105) |
| m7/triangular/ | 5 | 1828 | cli.py (648) |
| **Total** | **14** | **6033** | |

### Shims (backward-compat)

| File | Lines | Imports From |
|------|-------|-------------|
| scripts/m7a_orderflow_replay.py | 154 | m7.orderflow.* |
| scripts/m7a_enumerate_cycles.py | 94 | m7.triangular.* |
| engine/triangular_cycles.py | 23 | m7.triangular.scoring |
| engine/triangular_graph.py | 19 | m7.triangular.graph |

### Blocker Tag Addition

Added `BLOCKER_LOW_LAG_RPC_QUOTE_FAIL` (`LOW_LAG_RPC_QUOTE_FAIL`) as 8th canonical blocker tag. Now separately tracked from `LOW_LAG_REMOTE_QUOTER_LATENCY`. ALL_BLOCKER_TAGS count: 7 → 8.

### Evidence: Orderflow CLI (post-refactor)

Orderflow 300b verify: 30 events, 1 low-lag detected, 0 scored. Blocker tags: 4 active (LOW_LAG_NO_COUNTER_POOL, LOW_LAG_REMOTE_QUOTER_LATENCY, GAS_L1_DATA_DOMINANT, SUBGRAPH_API_KEY_REQUIRED). best_net=-1.82 bps.

### Evidence: Triangular CLI (post-refactor)

Triangular verify: 500 cycles found (cap hit), 328 viable after fee filter, 67/100 measured, 0 promoted, best_measured_net=-20.18 bps. All 67 same_state_proven. Size sweep: 10 cycles x 19 sizes.

## 5) Strategic Reading

1. **Refactor achieved its goal**: All M7 logic now lives in `m7/` with clear module boundaries. No module exceeds 1105 lines (cli.py orchestrator). Former 4443-line monolith is now 8 focused modules.

2. **Backward compatibility preserved**: All 3180 unit tests pass unchanged (except blocker count 7→8). Both CLI scripts produce identical artifact schemas. Engine re-export shims maintain `from engine.triangular_*` import paths.

3. **8th blocker tag closes a gap**: `LOW_LAG_RPC_QUOTE_FAIL` was observed dominating low-lag in verify runs but had no dedicated tag. Now tracked separately from `LOW_LAG_REMOTE_QUOTER_LATENCY`.

4. **Test files remain monolithic**: test_orderflow_contracts.py (6006 lines) and test_triangular_contracts.py (2247 lines) were not split in this session. This is a follow-up task if review complexity becomes a blocker.

5. **No market hypothesis in this session**: M7.R1 is purely structural. No new reject reasons, no new BackrunResult fields, no new economic insights. The market blockers from M7.A.5.18 remain unchanged.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 19, UNSCORED_REJECTS: 11, BackrunResult: 56 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 1105 lines, cli.py is pure orchestration)

## 5.2) Blockers / Risks
- PRIMARY (unchanged): NO_COUNTER_POOL dominates low-lag — pair resolves but no counter-venue in narrow_7
- SECONDARY (unchanged): temporal instability — LOW_LAG_NONE_THIS_WINDOW in longer windows
- STRUCTURAL (resolved): monolithic scripts extracted to m7/ package
- REMAINING: test files still monolithic (6006 + 2247 lines); follow-up split recommended
- UNCHANGED: Gas-exceeds-gross dominates stale subset; M4 baseline still negative
