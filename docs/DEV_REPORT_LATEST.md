# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T14:30:00Z
run_id: m7a_532_session
mode: OFFLINE (code changes + unit tests + CI pipeline)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T14:30:00Z
  dirty: true
  desc: M7.A.5.32 — unified nonstop supervisor, rolling retention, hot-path slimming (score_backrun_fast)
rolling_run_dir_name: N/A (offline session)
rolling_run_timestamp: 2026-04-02T14:30:00Z

## Session Completion
session_goal: M7.A.5.32 — unified nonstop supervisor + rolling-only retention + hot-path reduction toward first profit_guard-passed candidate under 250ms
goal_status: REACHED (supervisor created, retention tool created, _rolling cleaned, score_backrun_fast implemented with 250ms stage budgets, 3163 tests pass, all CI gates green)
close_allowed: true
remaining_blockers: score_backrun_fast needs live runtime evidence (hot loop must run online to measure actual fast-path latency); profit_guard_passed_count still 0 (offline session — no fresh runtime)
evidence_session_run_dirs: [tests/unit (3163 passed), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED)]
primary_blocker_of_session: (1) No unified supervisor; (2) data/tmp bloat (153 files/22MB); (3) _rolling non-canonical files; (4) hot lane pipeline ~1940ms (needs ≤250ms)
blocker_status_before: ACTIVE (hot lane gives 0 profit_guard passes; no supervisor; tmp bloat; _rolling contains archives)
blocker_status_after: PARTIALLY RESOLVED (supervisor built; retention tool built; _rolling cleaned; score_backrun_fast written with 250ms budget — needs live validation)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.32 — unified nonstop runtime + rolling retention + hot-path slimming
change_summary:
  - scripts/start_nonstop_runtime.py (NEW, ~200 lines): Unified supervisor — 4 managed subprocesses (dashboard, M4 scan, M7 hot, M7 cold) with health/restart/signal-handling
  - scripts/prune_tmp_artifacts.py (NEW, ~130 lines): Retention tool for data/tmp with per-prefix rules and --dry-run
  - scripts/m7a_orderflow_loop.py (MODIFIED): Hot lane fast-path scoring via score_backrun_fast() for prewarmed watchlist pairs; _write_hot_artifact() includes fast_path section
  - m7/orderflow/scoring_parallel.py (MODIFIED): Added score_backrun_fast() (~120 lines) — zero-RPC fast path with 250ms hard abort; fixed _normalized_bounds call and removed non-existent BackrunResult fields
  - m7/shared/constants.py (MODIFIED): HOT_BUDGET_* stage constants + HOT_WATCHLIST_PAIRS
  - scripts/m7a_orderflow_replay.py (MODIFIED): Added rolling-first output policy NOTE
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): +14 tests in 5 classes; fixed orphaned test code from ExternalRegistry class
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.32 section with clean changes list
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)
touched_files:
  - scripts/start_nonstop_runtime.py (NEW)
  - scripts/prune_tmp_artifacts.py (NEW)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/scoring_parallel.py (MODIFIED)
  - m7/shared/constants.py (MODIFIED)
  - scripts/m7a_orderflow_replay.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3163 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (pytest OK, docs_consistency OK, status_m4_check OK, m5_0_offline OK, m4_smoke OK, m4_profit OK — ALL REQUIRED GATES PASSED, 76.9s)

## 3) Artifacts Attached

No new runtime artifacts (offline code session). Rolling artifacts unchanged from M7.A.5.31.
Runtime cleanup: 12 non-canonical files moved from data/runs/_rolling/ to data/runs/_archive/.

## 4) Key Results — M7.A.5.32

### Unified Nonstop Supervisor

`scripts/start_nonstop_runtime.py` — standalone supervisor managing 4 processes:
- Dashboard (streamlit)
- M4/M5 scan (start.py)
- M7 hot loop (m7a_orderflow_loop.py --lane hot)
- M7 cold loop (m7a_orderflow_loop.py --lane cold)

Features: auto-restart with configurable delay/max-restarts, graceful signal handling (SIGINT/SIGTERM), periodic status reporting, CLI flags (--hours, --no-m4, --no-m7-cold). Separate from start.py — does not modify M4/M5 logic.

### Retention Tool

`scripts/prune_tmp_artifacts.py` — classifies files in data/tmp by type (m7a:prefix, helper, log, suppression, other) and applies retention limits:
- m7a_* files: keep last 2 per prefix
- helpers: keep last 5
- logs: keep last 3
- >14 days: delete regardless

### Rolling Cleanup

Moved 12 files to data/runs/_archive/:
- 7 m4_stability_agg_archive_*.json
- 4 r3*_scan log files
- 1 last_roundtrip_profitable.json

_rolling/ now contains 9 canonical files only.

### score_backrun_fast() — Zero-RPC Fast Path

New function in scoring_parallel.py (~120 lines) targeting ≤250ms total:
1. Registry O(1) lookup (budget: 25ms)
2. Cached pool state read (budget: 50ms)
3. Decimal-aware bounded size (from pricing._normalized_bounds)
4. attempt_local_pricing() — single adapter-dispatch (budget: 10ms)
5. Economics computation
6. Hard abort if pipeline_ms > HOT_BUDGET_TOTAL_MS (250ms)

Returns BackrunResult with scoring_path="registry_fast" or None (pair not in registry / over budget).

**Bug fixes during implementation**:
- _normalized_bounds was called with (event, token_addresses) instead of (token_decimals) — TypeError in runtime
- best_buy_amount_wei/best_sell_amount_wei fields don't exist on BackrunResult — removed from construction

### Hot Lane Integration

m7a_orderflow_loop.py hot lane now:
1. Prewarms HOT_WATCHLIST_PAIRS on first iteration
2. After run_ws_live(), re-scores events through score_backrun_fast() if registry has preloaded pairs
3. Reports fast-path results in _write_hot_artifact() fast_path section

## 5) Strategic Reading

1. **Infrastructure-only session**: No fresh runtime evidence. All changes are structural — supervisor, retention, fast-path function. Must run online to validate.
2. **score_backrun_fast designed for 250ms budget**: Stage budgets are explicit constants, hard abort enforced. Whether actual execution meets budget depends on registry warm state and local math speed.
3. **Three implementation bugs caught and fixed in tests**: OrderflowEvent constructor (wrong field names), _normalized_bounds call signature, non-existent BackrunResult fields. Tests are load-bearing.
4. **Next session must produce live evidence**: Run hot loop with score_backrun_fast, measure actual pipeline_ms, check if any profit_guard passes occur.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 20, UNSCORED_REJECTS: 12, BackrunResult: 66 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline: OK (9 canonical files in _rolling, 12 non-canonical moved to _archive)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ~1270 lines ≤ 1300)
test file size constraint: OK (test_orderflow_artifacts.py ~1560 lines — note: approaching limit)
Status_M7.md size constraint: OK (~230 lines ≤ 300)

## 5.2) Blockers / Risks
- PRIMARY: score_backrun_fast needs live measurement (actual pipeline_ms unknown; target ≤250ms)
- PRIMARY: profit_guard_passed_count still 0 (no fresh runtime this session)
- SECONDARY: test_orderflow_artifacts.py at ~1560 lines — may need split if more M7.A.5.3x tests added
- RESOLVED (this session): No unified supervisor
- RESOLVED (this session): data/tmp bloat (retention tool created)
- RESOLVED (this session): _rolling non-canonical files (cleaned)
- RESOLVED (this session): Hot lane had no fast-path scoring (score_backrun_fast added)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Run hot loop online with score_backrun_fast, (b) Measure actual fast-path latency, (c) Check for profit_guard passes, (d) Run prune_tmp_artifacts.py --dry-run to validate retention
