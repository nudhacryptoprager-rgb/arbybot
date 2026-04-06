# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: m7a541_hot_fix_persist
mode: OFFLINE (CI-only, online evidence pending)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.41 — hot lane token resolution fix, top-candidate persistence
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41Z
m7_orderflow_timestamp: 2026-04-06T07:01:01Z (from prior nonstop run)
m7_hot_timestamp: 2026-04-06T07:01:27Z (from prior nonstop run)

## Session Completion
session_goal: M7.A.5.41 — persist top executable candidates, fix hot lane token resolution bug (fast_path.scored=0), add top_hot_candidates to hot artifact
goal_status: REACHED (code changes complete, tests pass, CI green; online verification pending)
close_allowed: true
remaining_blockers: online nonstop verification needed to confirm hot lane now scores events
evidence_session_run_dirs: [tests/unit (3272 passed, 6 skipped), scripts/ci_full_pipeline.py --mode ci (ALL REQUIRED GATES PASSED)]
primary_blocker_of_session: Hot lane fast_path.scored=0 caused by token resolution bug (direction tags in event.token_in/token_out vs symbol-keyed token_addresses dict). Cold executable positives only persisted as summary counters (viable_count, best_net_bps_executable) — zero per-event detail in rolling artifact.
blocker_status_before: ACTIVE (fast_path.scored=0 since M7.A.5.32; no per-event executable detail in rolling artifact)
blocker_status_after: RESOLVED (score_backrun_fast resolves via _pool_token_cache; top_executable/stale/hot candidates persisted)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.41 — persist top executable candidates + hot lane token resolution fix
change_summary:
  - m7/orderflow/scoring_parallel.py (MODIFIED): (a) Imported _pool_token_cache from resolve.py. (b) Replaced broken token_addresses.get(event.token_out) with _pool_token_cache lookup via event.pool_address + direction tag. (c) Fixed _in_sym decimal detection — uses addr_to_symbol instead of direction tag.
  - m7/orderflow/artifacts.py (MODIFIED): (a) Added top_executable_candidates (top-5 viable, sorted by net_bps desc). (b) Added top_stale_positive_candidates (top-5 stale positive). (c) Compact rows: event_id, actual_pair, net_bps, block_lag, same_state_class, route_viable, size_valid_for_token, scoring_path, profit_guard_passed, pipeline_latency_ms, reject_reason.
  - scripts/m7a_orderflow_loop.py (MODIFIED): Added top_hot_candidates (top-5 fast_results by net_bps) to hot artifact. Always emitted (empty list when no fast results).
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): +14 tests in 3 M7.A.5.41 classes (TestM7A541TopCandidatePersistence, TestM7A541HotLaneTokenResolution, TestM7A541TopHotCandidates).
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.41 section, updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.41)
touched_files:
  - m7/orderflow/scoring_parallel.py (MODIFIED)
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3272 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)

## 3) Artifacts Attached

prior rolling (evidence baseline, from M7.A.5.40 nonstop):
  - data/runs/_rolling/m7_orderflow_latest.json (timestamp: 2026-04-06T07:01:01Z, viable_count=5, best_net_bps_executable=2237.28)
  - data/runs/_rolling/m7_hot_latest.json (timestamp: 2026-04-06T07:01:27Z, fast_path.scored=0)
  - data/runs/_rolling/m7_promoted_pairs.json (20 candidate, 10 execution)
no new runtime artifacts this session (code-only, online verification pending)

## 4) Key Results — M7.A.5.41

### Hot Lane Token Resolution Bug Fix

Root cause: `score_backrun_fast()` did `token_addresses.get(event.token_out)` where `event.token_out` = "token0"/"token1" (direction tag from `normalize_swap_log()`), but `token_addresses` maps `{symbol: address}`. Always returned `""` → always returned None → `fast_path.scored=0` since M7.A.5.32 (9 sessions).

Fix: Lookup `_pool_token_cache[event.pool_address.lower()]` → get `(token0_addr, token1_addr, fee)` → map direction tag to actual addresses. Zero additional RPC. Also fixed `_in_sym` decimal detection: was `event.token_in.upper()` = "TOKEN0_IN" (never matches USDC/USDT), now `addr_to_symbol.get(token_in_addr.lower(), "").upper()`.

Direction convention: cold path after `_resolve_event_tokens("token0_in")` sets `token_in_addr = token0_addr` (victim's in). Hot path fix matches: `if _direction == "token0_in": token_in_addr = _token0_addr`. `attempt_local_pricing` uses `zero_for_one = token_in_addr.lower() < token_out_addr.lower()` — direction determined by address ordering.

### Top-Candidate Persistence

Three new keys in artifacts:
1. `top_executable_candidates` (cold artifact): top-5 viable results sorted by net_bps desc — 11-field compact rows (event_id, actual_pair, net_bps, block_lag, same_state_class, route_viable, size_valid_for_token, scoring_path, profit_guard_passed, pipeline_latency_ms, reject_reason)
2. `top_stale_positive_candidates` (cold artifact): top-5 stale positive results (net_bps > 0 but not route_viable)
3. `top_hot_candidates` (hot artifact): top-5 fast_results by net_bps — 8-field compact rows; always emitted (empty list when no fast results)

All keys survive `_ROLLING_EXCLUDE_KEYS` (only `results`, `low_lag_debug_rows`, `low_lag_watchlist`, `session_low_lag_pairs` stripped).

## 5) Strategic Reading

1. **Hot lane fix is the critical unblock**: `fast_path.scored=0` for 9 sessions was caused by a trivial token resolution mismatch (direction tags vs symbols). Fix uses `_pool_token_cache` — zero-RPC, O(1) lookup. Hot lane should now score events on next nonstop run.
2. **Candidate persistence provides audit trail**: Previously viable_count=5 was a summary counter with no per-event detail. Now top-5 executable and top-5 stale-positive candidates are persisted as compact 11-field rows in the cold artifact, and top-5 hot candidates in the hot artifact.
3. **Cold priming still required**: Hot lane depends on `_pool_token_cache` being populated by prior cold-lane iterations. If cold lane hasn't seen a pool, hot lane returns None for that pool's events. This is correct behavior (cold discovers, hot exploits).
4. **Next step: online nonstop verification**: Must run nonstop to confirm (a) fast_path.scored > 0, (b) top_hot_candidates populated, (c) profit_guard_passed_count > 0 in at least one executable candidate.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files in _rolling: 9 canonical + m7_promoted_pairs.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
module size constraint: OK (scoring_parallel.py ~1320 lines after hot fix additions)
test file size constraint: OK (test_orderflow_artifacts.py ~3050 lines after +14 tests)
Status_M7.md size constraint: OK

## 5.2) Blockers / Risks
- RESOLVED (this session): fast_path.scored=0 since M7.A.5.32 — token resolution via _pool_token_cache instead of broken token_addresses.get()
- RESOLVED (this session): executable candidates not persisted in rolling artifact — top_executable_candidates + top_stale_positive_candidates added
- RESOLVED (this session): _in_sym decimal detection used direction tag string instead of actual symbol — now uses addr_to_symbol
- RESOLVED (this session): hot artifact had no per-event candidate detail — top_hot_candidates added
- PENDING: online nonstop verification to confirm hot lane scores events (fast_path.scored > 0)
- PENDING: profit_guard_passed_count > 0 in at least one executable candidate (requires online run)
- UNCHANGED: M4 ROUNDTRIP_NOT_PROFITABLE; SUBGRAPH_API_KEY_REQUIRED
- NEXT: (a) Run nonstop to verify hot lane fix, (b) Confirm top_hot_candidates populated, (c) Target profit_guard_passed > 0
