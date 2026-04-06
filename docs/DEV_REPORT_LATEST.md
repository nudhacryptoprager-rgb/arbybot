# DEV_REPORT_LATEST.md

## 0) Meta
timestamp_utc: 2026-04-02T09:03:41Z
mode: OFFLINE (CI + unit tests verified)
artifact_mode: rolling
config: config/real_minimal.yaml (arbitrum_one, NORMAL)
code_identity:
  primary: ts:2026-04-02T09:03:41Z
  dirty: true
  desc: M7.A.5.47e — hot-rollup semantic correctness, atomic writes, disentangled counters

## Session Completion
session_goal: M7.A.5.47e — fix hot-rollup counter semantics, dominant_hot_miss_reason reliability, first_window_at, atomic writes, adaptive bridge_hit_deficit logic
goal_status: REACHED (all 9 code changes landed, 17 new tests pass, 3344 total tests pass, ALL CI GATES PASS)
close_allowed: true
remaining_blockers: bridge_pool_hit_total=0 — unchanged; 47e fixes observability/correctness, not the structural gap
evidence_session_run_dirs: [tests/unit (3344 passed, 6 skipped), CI full pipeline PASS]
primary_blocker_of_session: counter semantics broken (watchlist_match_count aliased to fast_scored, fast_score_attempted counted scored not admitted, dominant_hot_miss_reason unreliable, first_window_at missing, non-atomic writes)
blocker_status_before: ACTIVE (counters lie, dashboard shows ?Z, miss classification duplicated keys)
blocker_status_after: RESOLVED (counters truthful, first_window_at written, 6-class per-window classification, atomic writes)
docs_reread_confirmed: true

## 1) Scope

goal (Roadmap): M7.A.5.47e — hot-rollup semantic correctness + atomic writes
change_summary:
  - scripts/m7a_orderflow_loop.py (MODIFIED): (a) _atomic_json_write() helper (tmpfile → os.replace) for all 5 rolling artifact writes. (b) hot_gap_debug counter disentanglement: watchlist_match_count = bridge_pool_address_hit_count (was fast_attempted); new admitted_to_scoring = events − hot_skip; renamed fast_path_attempted → fast_path_scored; new fast_score_scored field. (c) Rollup fast_score_attempted_total = admission count (events − hot_skip), not len(_fast). (d) first_window_at via setdefault(). (e) dominant_hot_miss_reason: per-window 6-class mutually-exclusive classification with window_miss_classes dict. (f) bridge_hit_deficit flag passed to run_ws_live().
  - m7/orderflow/mode_ws_live.py (MODIFIED): (a) Added bridge_hit_deficit param. (b) Adaptive broad uses bridge_hit_deficit OR intra-window deficit.
  - monitoring/dashboard_server.py (MODIFIED): Removed dead /api/intents (redundant with /api/hot).
  - tests/unit/test_hot_rollup_semantics.py (NEW): 17 tests covering first_window_at, counter disentanglement, per-window classification, atomic write contract, hot_gap_debug counters.
  - tests/unit/test_orderflow_artifacts.py (MODIFIED): Updated test for /api/intents removal.
  - docs/status/Status_M7.md (MODIFIED): Added M7.A.5.47e section, compressed 47b/47c/47d.
  - docs/DEV_REPORT_LATEST.md (this file, rewritten for M7.A.5.47e)
touched_files:
  - scripts/m7a_orderflow_loop.py (MODIFIED)
  - m7/orderflow/mode_ws_live.py (MODIFIED)
  - monitoring/dashboard_server.py (MODIFIED)
  - tests/unit/test_hot_rollup_semantics.py (NEW)
  - tests/unit/test_orderflow_artifacts.py (MODIFIED)
  - docs/status/Status_M7.md (MODIFIED)
  - docs/DEV_REPORT_LATEST.md (this file)

## 2) Commands Executed

py -3.11 -m pytest tests/unit -q: PASS (3344 passed, 6 skipped)
py -3.11 scripts/ci_full_pipeline.py --mode ci: PASS (ALL REQUIRED GATES PASSED)

## 3) Artifacts Attached

No new rolling artifacts (offline session). Rolling artifacts unchanged from M7.A.5.47d.

## 4) Key Results — M7.A.5.47e

### Counter Disentanglement

| Field | Before (47d) | After (47e) | Fix |
|-------|-------------|-------------|-----|
| watchlist_match_count | = fast_attempted (wrong) | = bridge_pool_address_hit_count | From bridge diagnostics |
| fast_score_attempted | = len(_fast) (scored) | = events − hot_skip (admitted) | Admission not scored |
| fast_path_scored_count | missing | = scoring_path=="registry_fast" | New field |
| fast_score_scored | missing | = scoring_path=="registry_fast" | New field |
| admitted_to_scoring | missing | = events − hot_skip | New field |

### Per-Window Miss Classification

6 mutually-exclusive classes per window, accumulated in `window_miss_classes` dict:
1. `no_events_in_window` — zero events received
2. `events_but_no_bridge_hit` — events but bridge_pool_address_hit_count=0
3. `bridge_hit_but_not_scored` — bridge hit but no fast results
4. `scored_but_rejected_economics` — scored but all net_bps ≤ 0
5. `positive_but_no_guard_pass` — positive but profit_guard failed
6. `guard_passed` — success (excluded from dominant)

`dominant_hot_miss_reason` = max window count excluding `guard_passed`.

### Atomic Writes

All 5 rolling artifact writes (`_PROMOTED_PAIRS_PATH`, `_COLD_HOT_BRIDGE_PATH`, `_HOT_ARTIFACT_PATH`, `_HOT_INTENTS_PATH`, `_HOT_ROLLUP_PATH`) now use `_atomic_json_write()` (tmpfile → `os.replace()`). Prevents cross-process readers from seeing truncated JSON.

## 5) Strategic Reading

1. **Observability layer is now truthful**: counters disentangled, miss classification auditable, first_window_at written.
2. **bridge_pool_hit_total=0 root cause is unchanged**: this session fixed the measurement layer, not the structural gap. Next step requires online verification with corrected counters to determine true miss distribution.
3. **Atomic writes eliminate cross-process truncation risk**: all rolling artifacts now safe for concurrent hot/cold/dashboard reads.
4. **Next justified step**: 10-min online nonstop with corrected counters → read `window_miss_classes` to determine true dominant miss class and plan targeted fix.

## 5.1) Contract Checks
status/reasons consistency: OK
rolling discipline: OK (canonical rolling files unchanged)
runtime artifacts not committed: OK (data/runs/** and data/tmp/** not in git)
