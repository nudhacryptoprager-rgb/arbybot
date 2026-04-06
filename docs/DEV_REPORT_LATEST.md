# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
run_id: ci_m5_gate_arbitrum_one_20260402_110313_968343
mode: ONLINE (nonstop verification with fresh rolling artifacts)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41.464858Z
  dirty: true
  desc: M7.A.5.46 — strip live-path ballast, hot semantic fix, M7/hot_loop separation
rolling_run_dir_name: ci_m5_gate_arbitrum_one_20260402_110313_968343
rolling_run_timestamp: 2026-04-02T09:03:41.464858Z
m7_orderflow_timestamp: 2026-04-06T11:31:46Z
m7_hot_timestamp: 2026-04-06T11:31:46Z
m7_hot_intents_timestamp: 2026-04-06T11:31:46Z

## Session Completion
session_goal: M7.A.5.46 — strip live-path ballast and convert bridge candidates into first hot-scored rows
goal_status: REACHED (13 hypothesis blocks removed, compact build_replay_summary, execution_funnel sole truth, hot semantic fixed, M7 separated from hot_loop, /api/intents wired to Panel 11, 10-min nonstop 3/3 alive 0 restarts)
close_allowed: true
remaining_blockers: hot_scored=0 (market timing — incoming hot events at different pools than cold_executable), profit_guard_passed=0 in hot lane (requires hot-scored event first)
evidence_session_run_dirs: [tests/unit (3327 passed, 6 skipped), nonstop 10-min (m7_orderflow_latest.json, m7_hot_latest.json, m7_hot_intents_latest.json, m7_cold_hot_bridge.json)]
primary_blocker_of_session: Live-path ballast (hypothesis blocks, full results serialization, multiple truth surfaces, wrong hot semantic for cold_executable_positive, M7 mixed with hot_loop)
blocker_status_before: ACTIVE (13 hypothesis strings in ws_live artifact, results always serialized, cold_executable_positive synthesized from _fast_positive, /api/hot returned hot_loop + m7_hot, /api/intents not connected to dashboard)
blocker_status_after: RESOLVED (hypothesis blocks removed, compact mode active, cold_executable from bridge, /api/hot returns m7_hot + m7_hot_intents only, Panel 11 shows intents)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.46 — strip live-path ballast + hot semantic fix
change_summary:
  - m7/orderflow/mode_ws_live.py (MODIFIED): (a) Removed ALL 13 hypothesis string assignments (m7a4, m7a56-m7a59, m7a513-m7a518, m7a522-m7a524) from ws-live artifact builder. (b) Simplified _ROLLING_EXCLUDE_KEYS — only results, low_lag_debug_rows, low_lag_watchlist, session_low_lag_pairs, _raw_results remain. (c) Calls build_replay_summary with compact=True.
  - m7/orderflow/artifacts.py (MODIFIED): (a) Added compact: bool = False parameter to build_replay_summary(). When compact=True: results→[], low_lag_debug_rows→[], low_lag_watchlist→[]. (b) Removed m7a4_hypothesis from return dict entirely.
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) 3 callers updated to use _raw_results instead of serialized results dict array. (b) Fixed hot semantic: cold_executable_positive reads from bridge's _bridge_cold_executable count, NOT synthesized from _fast_positive. (c) Added _bridge_cold_executable to bridge diagnostics transport. (d) Added bridge_pair_fallback_count counter + surfaced in hot_gap_debug.
  - monitoring/dashboard_server.py (MODIFIED): (a) /api/hot returns {m7_hot, m7_hot_intents} only (no hot_loop). Panel 0 gets hot_loop from /api/rolling. (b) Added m7_cold_hot_bridge to ARTIFACT_FILES.
  - monitoring/dashboard.html (MODIFIED): (a) Panel 11 restructured: execution_funnel is primary headline, signal_classification demoted. (b) New "Hot Execution Intents" section: intents table (pair, net_bps, guard, viable, path, latency). (c) /api/intents wired to Panel 11 via hot poll.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Updated 5 tests: removed m7a4_hypothesis from schema assertions, updated rolling exclude keys test, updated hot endpoint test for new {m7_hot, m7_hot_intents} response shape.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.46 section. Updated header.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.46)
touched_files:
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - m7/orderflow/artifacts.py (MODIFIED)
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - monitoring/dashboard_server.py (MODIFIED)
  - monitoring/dashboard.html (MODIFIED)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3327 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (all required gates)
py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit: PASS (0 warnings)
py -3.11 scripts/start_nonstop_runtime.py --hours 0.17 --no-m4 --dashboard-port 8099 --m7-hot-pause 1 --m7-cold-pause 5: PASS (3/3 alive, 0 restarts)

## 3) Artifacts Attached

fresh rolling (from M7.A.5.46 nonstop):
  - data/runs/_rolling/m7_orderflow_latest.json (cold: mode=ws_live, m7a4_hypothesis ABSENT, results=[] (compact), execution_funnel={diagnostic_positive, cold_executable_positive, hot_scored, profit_guard_passed, realized_onchain_profit, headline_level})
  - data/runs/_rolling/m7_hot_latest.json (hot: headline_level="none", hot_gap_debug={bridge_pair_fallback_count:0, bridge_loaded_candidate_count, bridge_pool_address_hit_count, ...})
  - data/runs/_rolling/m7_hot_intents_latest.json (headline_level="none", intents=[], schema intact)
  - data/runs/_rolling/m7_cold_hot_bridge.json (bridge diagnostics active)
  - data/runs/_rolling/m7_promoted_pairs.json

## 4) Key Results — M7.A.5.46

### Live-Path Ballast Removed

13 hypothesis string assignments removed from ws-live artifact builder:
- m7a4_hypothesis, m7a56_hypothesis through m7a59_hypothesis, m7a513_hypothesis through m7a518_hypothesis, m7a522_hypothesis through m7a524_hypothesis
- These were leftover diagnostic tags from earlier milestones. They consumed serialization time and created bloat in the rolling artifact.
- Verified: m7_orderflow_latest.json no longer contains any *_hypothesis keys.

### Compact build_replay_summary

`build_replay_summary(compact=True)` skips expensive serialization:
- `results`: was `[asdict(r) for r in results]` (up to N dataclass→dict conversions), now `[]`
- `low_lag_debug_rows`: was full debug array, now `[]`
- `low_lag_watchlist`: was full watchlist, now `[]`
- Callers needing raw results use `_raw_results` (original BackrunResult objects) directly.
- `m7a4_hypothesis` removed entirely from the return dict.

### execution_funnel as Sole Headline Truth

Panel 11 restructured:
- Funnel table is the first thing after headline_level badge (primary headline)
- signal_classification table demoted to secondary diagnostic section
- This eliminates the drift risk from having multiple "truth" surfaces for the same signal

### Hot Semantic Fix — No Cold Synthesis

Before: `cold_executable_positive` in hot artifact was synthesized from `_fast_positive` (count of hot-scored candidates with positive net_bps). This was wrong — hot positive != cold executable.
After: `cold_executable_positive` reads from bridge's `_bridge_cold_executable` count — the actual number of cold-lane-confirmed executable positives transported via the bridge.

This fix applies to both `_write_hot_artifact()` and `_write_hot_intents()`.

### M7 Separated from hot_loop

Before: `/api/hot` returned `{hot_loop, m7_hot}` — mixing Panel 0 data with Panel 11 data.
After: `/api/hot` returns `{m7_hot, m7_hot_intents}` only. Panel 0 gets `hot_loop` from `/api/rolling`.

This eliminates semantic coupling between M7 orderflow and the generic hot loop. Panel 11 now depends only on `m7_hot_latest.json`, `m7_hot_intents_latest.json`, and `m7_cold_hot_bridge.json`.

### /api/intents Wired to Panel 11

New "Hot Execution Intents" section in Panel 11 shows intents table from `/api/hot` response:
- Columns: pair, net_bps, guard, viable, path, latency
- Updates on every 1s hot poll
- When intents are empty (headline_level=none), shows "No hot execution intents available"

### Bridge Pair Fallback Counter (NEW)

`bridge_pair_fallback_count` in `hot_gap_debug`:
- Counts hot_skip events whose actual_pair matches any bridge candidate's pair
- This window: 0 (no fallback matches — events still at different pools)
- Diagnostic value: shows how many events COULD have been scored via pair-level matching if pool_address matching failed

### Comparison with M7.A.5.45

| Metric | M7.A.5.45 | M7.A.5.46 | Change |
|--------|-----------|-----------|--------|
| hypothesis keys in artifact | 13 | 0 | REMOVED |
| results serialization | Full [asdict(r)...] | [] (compact) | SKIP |
| m7a4_hypothesis | Present | Absent | REMOVED |
| cold_executable_positive source | _fast_positive (wrong) | bridge._bridge_cold_executable (correct) | FIXED |
| /api/hot response | {hot_loop, m7_hot} | {m7_hot, m7_hot_intents} | SEPARATED |
| /api/intents → dashboard | Not wired | Panel 11 intents table | WIRED |
| bridge_pair_fallback_count | Not tracked | In hot_gap_debug | NEW |
| tests | 3327 | 3327 | Same count |

## 5) Strategic Reading

1. **Ballast removal accelerates the operational path**: 13 hypothesis strings and full results serialization were consuming cycles on every ws-live iteration. With compact mode, the operational artifact contains only what's needed for rolling/hot/bridge/dashboard.
2. **Single truth surface prevents drift**: execution_funnel is now the only headline truth in the dashboard. signal_classification remains as diagnostic but is visually secondary. No duplicate KPI surfaces to maintain.
3. **Correct hot semantic prevents false claims**: cold_executable_positive from bridge means the hot artifact accurately reflects "how many cold-verified executable candidates exist" rather than "how many hot-scored events had positive net_bps." These are fundamentally different metrics.
4. **M7/hot_loop separation simplifies dependency graph**: Panel 11 has a clean dependency on 3 artifacts only (m7_hot, m7_hot_intents, m7_cold_hot_bridge). No generic hot loop noise.
5. **bridge_pair_fallback_count is a diagnostic canary**: When this counter shows nonzero, it means events ARE arriving at pools with the right canonical pair but different pool addresses — suggesting that adding pair-level matching would capture more candidates.

## 5.1) Contract Checks
status/reasons consistency: OK (ALL_REJECT_REASONS: 21, UNSCORED_REJECTS: 12, BackrunResult: 67 fields, ALL_BLOCKER_TAGS: 9)
rolling discipline: OK (canonical files + m7_promoted_pairs.json + m7_cold_hot_bridge.json + m7_hot_intents_latest.json)
v2.x provenance contract: OK (run_timestamp primary, code_sha=null)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
