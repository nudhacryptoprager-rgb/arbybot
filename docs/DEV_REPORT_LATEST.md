# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-01T13:08:04Z
run_id: m7a_519_300b / m7a_519_300b_b / m7a_519_1000b / m7a_519_triangular
mode: ONLINE (evidence runs + unit tests)
artifact_mode: local evidence (data/tmp/m7a_519_*.json)
config: arbitrum_one narrow_7 universe, same-chain DEX backrun domain
code_identity:
  primary: ts:2026-04-01T13:08:04Z
  dirty: true
  desc: M7.A.5.19 — quote-fail provenance, cli split, test file split
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275

## Session Completion
session_goal: M7.A.5.19 -- quote-fail provenance in scoring_parallel.py; split cli.py <=1000 lines; split test_orderflow_contracts.py and test_triangular_contracts.py into <=1000-line files; fresh evidence runs
goal_status: REACHED (provenance injected + 3 new tests; cli.py split 1181→312 lines; test_orderflow_contracts.py split into 9 files; test_triangular_contracts.py split into 3 files; 3183 tests pass; 4 fresh evidence runs)
close_allowed: true
remaining_blockers: same as M7.A.5.18 — NO_COUNTER_POOL and INACTIVE_POOL dominate low-lag; temporal variance fundamental; no low-lag scored
evidence_session_run_dirs: [data/tmp/m7a_519_300b.json, data/tmp/m7a_519_300b_b.json, data/tmp/m7a_519_1000b.json, data/tmp/m7a_519_triangular.json]
primary_blocker_of_session: diagnostic infrastructure — quote_fail provenance was unpopulated; monolithic files exceeded maintainability limits
blocker_status_before: scoring_parallel.py did not populate quote_fail_* provenance; cli.py at 1181 lines; test_orderflow_contracts.py at 6086 lines; test_triangular_contracts.py at 2247 lines
blocker_status_after: quote_fail provenance injected; cli.py at 312 lines + mode_ws_live.py 799 lines; 9 orderflow test files (max 995 lines); 3 triangular test files (max 932 lines)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.19 -- diagnostic infrastructure improvements (provenance + file splits) before local-state pricing hypothesis
change_summary:
  - `m7/orderflow/scoring_parallel.py`: Added `_buy_fail_info` list to capture (dex_name, exception_class) tuples on quote failure; injected `quote_fail_stage/venue/exception_short` into `stage_latency` dict when `venues_quoted == 0`
  - `m7/orderflow/cli.py`: Extracted ws_live mode handler into `mode_ws_live.py` (1181 → 312 lines)
  - `m7/orderflow/mode_ws_live.py`: NEW file (799 lines) — ws_live mode handler
  - Split `test_orderflow_contracts.py` (6086 lines, 107 classes) → 9 files (max 995 lines)
  - Split `test_triangular_contracts.py` (2247 lines, 21 classes) → 3 files (max 932 lines)
  - Added 3 new tests (TestM7A519QuoteFailProvenance) for provenance injection
  - Updated 4 existing tests (debug row key counts 13→16, blocker tag behavior alignment)
  - No new BackrunResult fields (still 56). No new reject reasons (still 19). ALL_BLOCKER_TAGS still 8.
touched_files:
  - m7/orderflow/scoring_parallel.py (MODIFIED: _buy_fail_info + provenance injection)
  - m7/orderflow/cli.py (MODIFIED: extracted ws_live mode, 1181→312 lines)
  - m7/orderflow/mode_ws_live.py (NEW: 799 lines, ws_live mode handler)
  - tests/unit/test_orderflow_base.py (NEW: 995 lines, 15 classes from split)
  - tests/unit/test_orderflow_scoring.py (NEW: 989 lines, 16 classes)
  - tests/unit/test_orderflow_m7a55_56.py through test_orderflow_m7a518_519.py (NEW: 7 files, 631-992 lines each)
  - tests/unit/test_triangular_base.py (NEW: 932 lines), test_triangular_blockers.py (929), test_triangular_regime.py (537)
  - tests/unit/test_orderflow_contracts.py (DELETED: replaced by 9 split files)
  - tests/unit/test_triangular_contracts.py (DELETED: replaced by 3 split files)
  - docs/status/Status_M7.md (MODIFIED: M7.A.5.19 section added)
  - docs/DEV_REPORT_LATEST.md (this file, rewritten)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3183 passed, 6 skipped in ~54s)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --max-events 30 --output data/tmp/m7a_519_300b.json: PASS (30 events, 3 low-lag)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 300 --max-events 30 --output data/tmp/m7a_519_300b_b.json: PASS (30 events, 1 low-lag)
py -3.11 scripts/m7a_orderflow_replay.py --ws-live --ws-blocks 1000 --max-events 100 --output data/tmp/m7a_519_1000b.json: PASS (38 events, 3 low-lag)
py -3.11 scripts/m7a_enumerate_cycles.py --chain arbitrum_one --source runtime --score measured --max-cycles 500 --max-scored 100 --sweep-top 10 --output data/tmp/m7a_519_triangular.json: PASS (67/100 measured, best_net=-22.74 bps)
## 3) Artifacts Attached

live evidence (this session):
  - data/tmp/m7a_519_300b.json (300-block ws-live, 30 events, 3 low-lag, best_net=-0.54 bps)
  - data/tmp/m7a_519_300b_b.json (300-block ws-live, 30 events, 1 low-lag, best_net=-2.41 bps)
  - data/tmp/m7a_519_1000b.json (1000-block ws-live, 38 events, 3 low-lag, best_net=-2.20 bps)
  - data/tmp/m7a_519_triangular.json (500 cycles, 67 measured, best_net=-22.74 bps)
rolling (pre-session, not regenerated):
  - data/runs/_rolling/_latest.json (run_dir_name: ci_m5_gate_arbitrum_one_20260327_222948_123275)
  - data/runs/_rolling/run_summary_latest.json
  - data/runs/_rolling/m4_stability_agg.json

## 4) Key Results -- M7.A.5.19

### Quote-Fail Provenance

Added `_buy_fail_info` list in `scoring_parallel.py` to capture (dex_name, exception_class) on quote failure. When `venues_quoted == 0`, injects `quote_fail_stage="buy"`, `quote_fail_venue=<comma-sep>`, `quote_fail_exception_short=<comma-sep>` into `stage_latency` dict. In fresh evidence, all 7 low-lag events hit NO_COUNTER_POOL/INACTIVE_POOL (before quoting), so quote_fail provenance is correctly null.

### CLI Split

| File | Lines | Purpose |
|------|-------|---------|
| m7/orderflow/cli.py | 312 | Argument parsing + mode dispatch |
| m7/orderflow/mode_ws_live.py | 799 | ws_live mode handler |

### Test File Split

| File | Lines | Classes |
|------|-------|---------|
| test_orderflow_base.py | 995 | 15 |
| test_orderflow_scoring.py | 989 | 16 |
| test_orderflow_m7a55_56.py | 907 | 14 |
| test_orderflow_m7a57_58.py | 631 | 9 |
| test_orderflow_m7a59_510.py | 737 | 11 |
| test_orderflow_m7a511_512.py | 764 | 14 |
| test_orderflow_m7a513_515.py | 992 | 12 |
| test_orderflow_m7a516_517.py | 959 | 11 |
| test_orderflow_m7a518_519.py | 659 | 5 |
| test_triangular_base.py | 932 | 12 |
| test_triangular_blockers.py | 929 | 6 |
| test_triangular_regime.py | 537 | 3 |

### Evidence: Orderflow (3 runs)

| Run | Events | Scored | Low-lag | Low-lag Scored | best_net_bps |
|-----|--------|--------|---------|----------------|-------------|
| 300b | 30 | 27 | 3 | 0 | -0.54 |
| 300b_b | 30 | 29 | 1 | 0 | -2.41 |
| 1000b | 38 | 35 | 3 | 0 | -2.20 |

Low-lag rejects (combined): NO_COUNTER_POOL=4, ALL_CANDIDATE_POOLS_TRULY_INACTIVE=3.

### Evidence: Triangular

67/100 measured, 0 promoted, best_net=-22.74 bps. Blockers: GROSS_NEGATIVE_CORE=10, GAS_DOMINANT_SMALL=10. universe_profile=narrow_7, regime_bucket=medium_activity.

## 5) Strategic Reading

1. **Diagnostic infrastructure improved**: Quote-fail provenance wired through scoring_parallel → stage_latency → debug_rows. Correctly null when events are rejected before quoting.
2. **File maintainability achieved**: All m7/ modules ≤799 lines, all 12 test files ≤995 lines. Total: 3183 tests.
3. **Low-lag blocker unchanged**: 7/7 low-lag events rejected before quoting (4 NO_COUNTER_POOL, 3 INACTIVE_POOL).
4. **Market consistent with M7.A.5.18**: Stale best_net = -0.54 to -2.20 bps (beats M4 baseline -3.51), no positive-net. Triangular -22.74 bps.
5. **Next step**: Local-state-first pricing + watchlist accumulation to unlock first low-lag scored event.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 19, UNSCORED_REJECTS: 11, BackrunResult: 56 fields, ALL_BLOCKER_TAGS: 8)
rolling discipline (3 files only): OK
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (all m7/ modules ≤ 799 lines, cli.py at 312 lines)
test file size constraint: OK (all M7 test files ≤ 995 lines)

## 5.2) Blockers / Risks
- PRIMARY (unchanged): NO_COUNTER_POOL + ALL_CANDIDATE_POOLS_TRULY_INACTIVE dominate low-lag
- SECONDARY (unchanged): temporal instability — LOW_LAG_NONE_THIS_WINDOW in longer windows
- STRUCTURAL (resolved): cli.py split (1181→312+799); test files split (6086→9, 2247→3)
- DIAGNOSTIC (resolved): quote_fail provenance now populated when events reach quoting
- UNCHANGED: Gas-exceeds-gross dominates stale subset; M4 baseline still negative
