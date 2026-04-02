# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a_533_session
mode: OFFLINE (code changes + unit tests + CI pipeline)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.33 — profit guard fix, hot-mode fast path, per-stage timing, integrated profit guard
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z

## Session Completion
session_goal: M7.A.5.33 — first profit_guard-passed hot candidate under unified nonstop runtime and <250ms hot-path budget
goal_status: BLOCKED (offline code session — profit_guard bug fixed, hot-mode fast path wired, stage timing added, but no fresh online runtime to prove first profit_guard pass)
close_allowed: true
remaining_blockers: (1) Must run hot loop online to validate profit_guard actually passes with corrected field derivation; (2) Pipeline latency still ~1940ms in cold lane (hot-mode fast path bypasses this but needs live measurement); (3) viable_count still 0 (needs live run)
evidence_session_run_dirs: [tests/unit (3172 passed), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED), scripts/check_repo_safety.py (PASS 0 warnings)]
primary_blocker_of_session: (1) profit_guard dead code — best_buy/sell_amount_wei fields don't exist; (2) Hot lane still routes through slow pipeline; (3) DEV_REPORT provenance misaligned; (4) Status_M7.md over 300-line limit
blocker_status_before: ACTIVE (profit_guard can never pass due to missing fields; hot lane ~1940ms; repo safety FAIL)
blocker_status_after: RESOLVED (profit_guard field derivation fixed; hot-mode scores via zero-RPC fast path; stage timing instrumented; repo safety PASS 0 warnings; 3172/3172 tests pass)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.33 — profit guard fix + hot-mode fast path + per-stage timing + integrated profit guard
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): Fixed critical bug in _run_profit_guard_on_results() — was reading non-existent best_buy/sell_amount_wei fields; enhanced _write_hot_artifact() with profit_guard_passed count and stage_timings aggregate
  - m7/orderflow/mode_ws_live.py (MODIFIED): Added hot-mode fast path — when external_registry provided, tries score_backrun_fast() first (zero-RPC), falls back to full pipeline only when fast path returns None
  - m7/orderflow/scoring_parallel.py (MODIFIED): Enhanced score_backrun_fast() with per-stage timing (_registry_lookup_ms, _pool_state_ms, _local_math_ms, _profit_guard_ms, _tx_build_ms) and integrated profit_guard check for positive-net results
  - m7/orderflow/contracts.py (MODIFIED): Added profit_guard_passed: Optional[bool] = None field (66→67 fields)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Fixed mock data (removed non-existent fields), added 9 tests in 4 classes for profit guard fix, BackrunResult field, stage timings, hot-mode fast path
  - tests/unit/test_orderflow_contracts_core.py (MODIFIED): Field count assertion 66→67
  - tests/unit/test_orderflow_status_metrics.py (MODIFIED): 6x field count assertion 66→67
  - docs/status/Status_M7.md (MODIFIED): Compressed 346→227 lines, reordered chronologically, added M7.A.5.33 section
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.33)
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - m7/orderflow/scoring_parallel.py (MODIFIED)
  - m7/orderflow/contracts.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - tests/unit/test_orderflow_contracts_core.py (MODIFIED)
  - tests/unit/test_orderflow_status_metrics.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3172 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED, 79.0s)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 errors, 0 warnings)

## 3) Artifacts Attached

No new runtime artifacts (offline code session). Rolling artifacts unchanged from M7.A.5.31.

## 4) Key Results — M7.A.5.33

### Critical Bug Fix: profit_guard Dead Code

`_run_profit_guard_on_results()` in m7a_orderflow_loop.py read `best_buy_amount_wei` / `best_sell_amount_wei` — fields that do not exist on BackrunResult. This caused profit_guard_passed_count to be permanently 0 across all prior sessions.

**Fix**: Derives buy/sell from fields that exist:
- `buy = amount_in_wei` (the backrun size)
- `sell = amount_in_wei + gross_pnl_wei` (size + gross profit)

### Hot-Mode Fast Path in mode_ws_live

When `external_registry` is provided (hot lane), the scoring loop now:
1. Tries `score_backrun_fast()` first (zero-RPC, O(1) registry lookup)
2. Falls back to full `score_backrun_live_parallel()` only if fast path returns None
3. Attaches `_source_event` to result for downstream re-scoring

This eliminates the ~832ms `preload_pair()` call from the per-event hot path.

### Per-Stage Timing in score_backrun_fast()

Enhanced with 5-stage instrumented timing:
1. `_registry_lookup_ms` — O(1) cache hit (budget: 25ms)
2. `_pool_state_ms` — cached entry building (budget: 50ms)
3. `_local_math_ms` — attempt_local_pricing (budget: 10ms)
4. `_profit_guard_ms` — integrated check_profit_guard for positive-net results
5. `_tx_build_ms` — placeholder for future calldata/sign prep

All stage timings aggregated into `pipeline_stage_latency_ms` dict on BackrunResult. Hard abort at 250ms total unchanged.

### Integrated Profit Guard in Fast Path

Stage 4 of score_backrun_fast() now calls `check_profit_guard()` directly for results with positive net_pnl_wei. Sets `profit_guard_passed` field on BackrunResult. Hot artifact reports profit_guard_passed count in fast_path section.

### BackrunResult Field Addition

Added `profit_guard_passed: Optional[bool] = None` — 67 total fields. All test assertions updated.

### Status_M7.md Compression

Compressed 346→227 lines (limit 300). Grouped verbose M7.A.5.20-5.25 sections into compact blocks. Reordered sections to correct chronological order (5.31/5.32 had been placed before 5.23-5.25).

## 5) Strategic Reading

1. **Critical correctness bug found and fixed**: profit_guard was dead code due to non-existent field reads. This explains why profit_guard_passed_count=0 across ALL prior sessions — it was not a market/data issue, it was a field-name bug.
2. **Hot-mode fast path eliminates ~832ms preload**: mode_ws_live now uses score_backrun_fast() as primary path when registry is available, bypassing per-event preload_pair(). Full pipeline is fallback only.
3. **Stage timing enables budget monitoring**: Each stage in score_backrun_fast() is individually timed. Hot artifact aggregates mean/max per stage key for runtime analysis.
4. **Still needs live validation**: profit_guard field derivation is algebraically correct (buy=size, sell=size+gross), but must demonstrate actual passes in live hot loop.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline: OK (canonical files in _rolling)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ≤ 1300 lines)
test file size constraint: OK (test_orderflow_artifacts.py — approaching limit)
Status_M7.md size constraint: OK (227 lines ≤ 300)

## 5.2) Blockers / Risks
- PRIMARY: profit_guard bug fixed but needs live validation (must see profit_guard_passed_count > 0 in hot artifact)
- PRIMARY: Hot-mode fast path untested online (actual pipeline_ms unknown; target ≤250ms)
- SECONDARY: test_orderflow_artifacts.py approaching size limit — may need split
- RESOLVED (this session): profit_guard dead code (field derivation fixed)
- RESOLVED (this session): Hot lane routed through slow full pipeline (now uses score_backrun_fast first)
- RESOLVED (this session): No per-stage timing (5-stage instrumentation added)
- RESOLVED (this session): DEV_REPORT provenance misaligned (timestamp_utc, rolling_run_dir_name, rolling_run_timestamp fixed)
- RESOLVED (this session): Status_M7.md over 300-line limit (346→227)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Run hot loop online, (b) Verify profit_guard_passed_count > 0, (c) Measure stage timings, (d) If passes occur, evaluate tx-build readiness
