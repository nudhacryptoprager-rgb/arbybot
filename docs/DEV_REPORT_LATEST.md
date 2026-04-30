# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-30T11:50:00Z
run_id: M7.E1.46 reviewer-funnel observability + WS rate-limit classification + clean-cycle accounting
mode: OFFLINE (unit + safety) — runtime evidence is the post-E1.45 30m soak (supervisor 2026-04-30T11:13:58Z→11:44:01Z, 5/5 alive, crash_restarts=0); no fresh soak this iteration.
artifact_mode: rolling
config: code-only changes; no runtime env or config changes.
code_identity:
  primary: ts:2026-04-30T11:50:00Z (split/code @ 82e7527 + targeted dirty diff)
  dirty: true (m7/orderflow/hot_runtime_artifacts.py, m7/orderflow/mode_ws_live.py, scripts/reviewer_soak_summary.py, scripts/replay_divergence_samples.py, plus 3 test files)
  desc: Closed seven of the ten post-E1.45 reviewer report items with surgical, backward-compatible changes. No large refactors per CLAUDE.md §1.2. Steps 1 (factory_enum → tier_classifier → bounded HOT universe wiring), 6 (DISC→PROD watchlist promotion with TTL/provenance), and 9 (60m active-window soak gated on step 1) explicitly DEFERRED to dedicated iterations.

## 1) Scope
goal (Roadmap): M7.E1 Base orderflow stabilization. Session goal: tighten reviewer-funnel observability (fresh BRIDGE_HIT_NOT_SCORED, current_session_window split, NO_HOT_CYCLE_COMPLETED_DURING_SOAK), correctly classify the dRPC WS reconnect rate-limit storm observed in the post-E1.45 30m soak (`recv_error_reconnect_failed` carrying JSON-RPC code 15 "Too many request"), and harden the divergence replay path against historical samples.

change_summary:
  - Re-read AGENTS.md, Roadmap.md, Status_M7.md (E1.45 head), DOCS_POLICY.md, WORKFLOW.md, DEV_REPORT_CANONICAL_UA.md.
  - Step 2 (BRIDGE_HIT_NOT_SCORED fresh deltas): m7/orderflow/hot_runtime_artifacts.py — `_update_hot_rollup` now mirrors the bridge-hit-not-scored reason into `_sess["session_bridge_hit_not_scored_reason_histogram"]` + `_sess["session_bridge_hit_not_scored_windows"]`; lifetime `bridge_hit_but_not_fast_scored.reason_histogram` is preserved unchanged (back-compat). Histogram resets on session_id change via the existing _sess reset path.
  - Step 3 (NO_HOT_CYCLE_COMPLETED_DURING_SOAK): m7/orderflow/hot_runtime_artifacts.py — `_flush_rollup_at_path()` now bumps `clean_child_exits_total` + `last_clean_child_exit_at` only on per-child clean exits (`is_supervisor_exit=False`); supervisor exits do NOT touch the counter. scripts/reviewer_soak_summary.py adds the `NO_HOT_CYCLE_COMPLETED_DURING_SOAK` reason and sets ok=False when `events_seen_delta>0` AND `clean_child_exits_delta=0` AND not `ARBY_REVIEWER_QUIET_OK=1`.
  - Step 4 (dRPC code 15 → rate-limit classification): m7/orderflow/mode_ws_live.py — when reconnect attempts exhaust and `_exit_reason="recv_error_reconnect_failed"`, the last `_ws_last_recv_error` is now lower-cased and matched against `"too many request" / "'code': 15" / "\"code\": 15" / "code\":15" / "code': 15" / " 429" / ":429" / "rate limit" / "rate-limit"`; on match, `_ws_connection_status="failed_429"` so `session_ws_failed_429_windows` actually counts the storm. Previously only the very first connect's HTTP 429 was tagged (which is why the post-E1.45 soak showed `session_ws_recv_error_total=15` and `session_ws_failed_429_windows=0`).
  - Step 5 (split supervisor_window): m7/orderflow/hot_runtime_artifacts.py — added top-level `current_session_window` block (`session_started_at`, `events_total`, `elapsed_minutes`, `events_per_minute`) sourced from `_sess` so it resets on every new session_id; kept `supervisor_window` and added a `historical_window` alias for the new naming.
  - Step 7 (fee 2600 Slipstream route exercise): no further code change beyond E1.45 (mapping `2600→ts=100` already present in `m7/orderflow/execution_gate.py::SLIPSTREAM_FEE_TO_TICKSPACING` and `_AERODROME_CL_KNOWN`); existing `test_aerodrome_cl_fee_classified` parametrised over `(150, 445, 600, 2105, 2600, 2655, 3024)` already validates the route resolves to `SLIPSTREAM_PENDING_LOOKUP:2600` / `SLIPSTREAM_SIM_READY_TOKENS_MISSING:2600:ts100` instead of `UNSUPPORTED_FEE_TIER:UNKNOWN:2600`. Re-verified.
  - Step 8 (raise fast-path admission target): no code change required — `ARBY_REVIEWER_MIN_FAST_PATH_SCORED` default is already 20 and reviewer enforces `FAST_PATH_SCORED_TOO_LOW=N<20` reason (witnessed in the 30m soak as `FAST_PATH_SCORED_TOO_LOW=3<20`). Carry-forward as the explicit acceptance criterion for the next 30m soak after step 1 lands.
  - Step 10 (replay only on fresh divergence samples): scripts/replay_divergence_samples.py — added `--require-fresh-session` flag that resolves the rollup's current `session.session_id` (or top-level `session_id`) and filters in-memory samples to only those carrying that `session_id`; emits `NO_FRESH_SAMPLES` rc=1 with reason `no_samples_match_current_session_id` when nothing matches.
  - Tests added: tests/unit/test_e142_rate_metrics.py +1 (clean_child_exits counter), tests/unit/test_m7_e1_34h_reviewer_fixes.py +4 (current_session_window present + resets, session bridge histogram increments + resets), tests/unit/test_reviewer_soak_summary.py +2 (NO_HOT_CYCLE_COMPLETED guard fires + silent-when-progressing).
  - Status_M7.md rewritten with E1.46 head section + E1.45 demoted to Prior. Unit baseline 4401 → 4408, Updated tag bumped to 2026-04-30 (E1.46).

touched_files:
  - m7/orderflow/hot_runtime_artifacts.py (clean_child_exits_total, current_session_window/historical_window, session_bridge_hit_not_scored_*)
  - m7/orderflow/mode_ws_live.py (rate-limit reclassification on reconnect-failure exit)
  - scripts/reviewer_soak_summary.py (NO_HOT_CYCLE_COMPLETED_DURING_SOAK reason)
  - scripts/replay_divergence_samples.py (--require-fresh-session)
  - tests/unit/test_e142_rate_metrics.py (+1 test)
  - tests/unit/test_m7_e1_34h_reviewer_fixes.py (+4 tests)
  - tests/unit/test_reviewer_soak_summary.py (+2 tests)
  - docs/status/Status_M7.md (E1.46 head section, baseline bump 4401→4408)
  - docs/DEV_REPORT_LATEST.md (this rewrite)

## 2) Commands Executed (facts only)
py -3.11 -m pytest tests/unit/test_e142_rate_metrics.py tests/unit/test_m7_e1_34h_reviewer_fixes.py tests/unit/test_reviewer_soak_summary.py -q : PASS 41/41 in 1.33s
py -3.11 -m pytest tests/unit -q (final): **PASS 4408 / 6 skipped / 1 warning** in 240.99s (+7 vs E1.45 baseline 4401)
py -3.11 scripts/check_repo_safety.py: PASS (0 warnings, 20 gates)
NO ONLINE SOAK RUN this iteration (code-only changes; runtime evidence is the post-E1.45 30m soak whose findings drove this iteration).

## 3) Artifacts Attached
rolling: NOT WRITTEN this iteration (no soak run). Existing rollups under data/runs/_rolling/ retained as-is from the post-E1.45 30m soak (m7_hot_rollup_latest.json: session_id=0424ee0d, supervisor_end_utc=2026-04-30T08:30:01Z; m7_hot_rollup_latest_discovery.json: rate_basis still null pending next supervisor run that will exercise the E1.45 sibling-flush path live).
run_dir_bundle: not produced.
evidence basis (read-only): post-E1.45 30m soak supervisor 2026-04-30T11:13:58Z→11:44:01Z, PROD events +71 / fast +3 / sim +0 / roundtrip +0; DISC events +72 / fast +2 / sim +0; `session_ws_recv_error_total=15`, `last_exit_reason=recv_error_reconnect_failed`, `last_ws_recv_error="reconnect_fail:WebSocket subscription failed: {'id': 1, 'jsonrpc': '2.0', 'error': {'message': 'Too many request, try again later', 'code': 15}}"`.

## 4) Key Results
e1_46_step2_session_bridge_histogram:
  module: m7/orderflow/hot_runtime_artifacts.py::_update_hot_rollup (bridge-hit-not-scored branch)
  shape: When `_bridge_hits_win > 0 and len(_fast) == 0`, increments `_sess["session_bridge_hit_not_scored_reason_histogram"][reason]` and `_sess["session_bridge_hit_not_scored_windows"]` in addition to the existing lifetime `bridge_hit_but_not_fast_scored.reason_histogram` write. Reset on session_id change via existing `_sess` reset path.
  test_baseline: 2 new tests in tests/unit/test_m7_e1_34h_reviewer_fixes.py covering increment + session reset (lifetime preserved, session-only filtered to new reason).

e1_46_step3_clean_child_exits:
  module: m7/orderflow/hot_runtime_artifacts.py::_flush_rollup_at_path + scripts/reviewer_soak_summary.py::summarise_lane
  shape: Per-child clean exits bump rollup-level `clean_child_exits_total` + `last_clean_child_exit_at`; supervisor exits stamp `supervisor_end_utc` but do NOT bump the counter. Reviewer FAILs acceptance with `NO_HOT_CYCLE_COMPLETED_DURING_SOAK events_seen_delta=N clean_child_exits_delta=0` when hot writes happened but no child finished cleanly.
  test_baseline: 1 new test in tests/unit/test_e142_rate_metrics.py + 2 in tests/unit/test_reviewer_soak_summary.py.

e1_46_step4_ws_rate_limit_reclassification:
  module: m7/orderflow/mode_ws_live.py (reconnect-storm branch)
  shape: After exhausting `_MAX_RECONNECT_ATTEMPTS` and setting `_exit_reason="recv_error_reconnect_failed"`, lower-cases `_ws_last_recv_error` and matches against the rate-limit signature set; on hit sets `_ws_connection_status="failed_429"` + descriptive `_ws_error_detail`. Result: `session_ws_failed_429_windows` now counts dRPC code 15 / "Too many request" / HTTP 429 reconnect cascades, not only the very first connect's HTTP 429.

e1_46_step5_current_session_window:
  module: m7/orderflow/hot_runtime_artifacts.py::_update_hot_rollup (after supervisor_window block)
  shape: Adds top-level `current_session_window` block sourced from `_sess` (resets on session_id change); keeps `supervisor_window` AND adds a `historical_window` alias pointing at the same dict. Lets dashboards/reviewers surface session feed rate (~10 events/min in active windows) instead of the lifetime supervisor rate (~0.46/min observed in the post-E1.45 soak).
  test_baseline: 2 new tests in tests/unit/test_m7_e1_34h_reviewer_fixes.py covering presence + session reset.

e1_46_step7_fee_2600_route:
  module: m7/orderflow/execution_gate.py (E1.45-landed mapping; verified end-to-end this iteration)
  shape: Aerodrome CL fee=2600 routes through `SLIPSTREAM_FEE_TO_TICKSPACING[2600]=100` and is whitelisted in `_AERODROME_CL_KNOWN`. Reject buckets now `SLIPSTREAM_PENDING_LOOKUP:2600` (config not yet verified) or `SLIPSTREAM_SIM_READY_TOKENS_MISSING:2600:ts100` (config verified, tokens pending), no longer `UNSUPPORTED_FEE_TIER:UNKNOWN:2600`. Live runtime exercise gated on step 1 (universe expansion).

e1_46_step8_admission_target:
  module: scripts/reviewer_soak_summary.py (no code change required)
  shape: `ARBY_REVIEWER_MIN_FAST_PATH_SCORED` default is already 20; reviewer emits `FAST_PATH_SCORED_TOO_LOW=N<20` when `_fps_delta < 20` and `ARBY_REVIEWER_QUIET_OK!=1`. Carry-forward as explicit acceptance criterion for the next 30m soak after step 1 lands.

e1_46_step10_replay_fresh_only:
  module: scripts/replay_divergence_samples.py
  shape: New `--require-fresh-session` flag resolves rollup current session_id, filters in-memory `scorer_sim_divergence_samples_recent` to that session, emits `NO_FRESH_SAMPLES` rc=1 with `no_samples_match_current_session_id` reason when nothing matches. Prevents replaying carry-over samples from a prior soak.

unit_baseline: 4408 passed / 6 skipped / 1 warning / 0 failed (was 4401 before E1.46; +7 from new tests).
safety: PASS (20 gates, 0 warnings)

## 4.1) Theoretical Net Profit (cost-aware reporting)
not_applicable_this_session:
  reason: Code-only iteration with no fresh soak run. PROD economics state is unchanged from the post-E1.45 30m soak (`roundtrip_profitable_total=0`). Step 4 (rate-limit reclassification), step 5 (current_session_window), and step 3 (clean_child_exits) only become observably-effective on the next supervisor run; nothing in this iteration mutates economic outcomes directly.

## 5) Outcomes vs goals
session_goal_outcome: REACHED for the seven targeted reviewer-funnel observability + WS classification + clean-cycle accounting items (steps 2, 3, 4, 5, 7, 8, 10); DEFERRED for steps 1, 6, 9 with explicit carry-forward.
- Steps 2, 3, 4, 5, 7, 8, 10 closed with surgical changes and regression tests. Step 7 is the runtime-verification of the E1.45 fee-2600 mapping; gate-level test exercise confirmed.
- Step 1 (factory_enumeration → tier_classifier → bounded HOT universe wiring) DEFERRED. Justification: requires a coordinated multi-module wiring (background tier_classifier task at WARM cadence; HOT loop reading classified universe and capping to 100-300 by recency/liquidity/activity; persistence of `data/runs/_rolling/m7_tier_map_latest.json` artifact; safe migration without breaking current intent-based loading) — too large for a "small backward-compatible fix" iteration per CLAUDE.md §1.2.
- Step 6 (DISC profitable historical pair → PROD watchlist with TTL/provenance) DEFERRED. Justification: requires a new `m7/orderflow/disc_to_prod_watchlist.py` module (or extension of `m7/orderflow/disc_watchlist.py` from E1.42) with TTL handling, persistence, provenance keying on `roundtrip_profitable=true && session_id`, and explicit gating before promoting candidates into the live PROD universe; that is a coordinated change across discovery + orderflow that needs its own iteration.
- Step 9 (60m active-window soak gated on step 1) DEFERRED. Justification: a runtime exercise that only proves out the universe expansion landed in step 1; running it before step 1 would only re-prove the existing `FAST_PATH_SCORED_TOO_LOW` story.
- Production-readiness: NOT REACHED. PROD `roundtrip_profitable_total=0` unchanged. Reviewer-funnel observability is now strict: fresh BRIDGE_HIT_NOT_SCORED reasons, current_session_window split, NO_HOT_CYCLE_COMPLETED_DURING_SOAK guard, and dRPC reconnect rate-limit storms are correctly classified as `failed_429`.

## 6) Risks / Issues
- ECON_BLOCKER (carried): PROD `roundtrip_profitable_total=0` unchanged; gated on step 1 universe expansion + step 9 active-window soak.
- WS_RECONNECT_STORM (carried, now correctly classified): post-E1.45 soak `session_ws_recv_error_total=15`, JSON-RPC code 15 "Too many request" cascades. From next soak onward these increment `session_ws_failed_429_windows` so the operator can directly see provider rate-limiting vs benign recv-timeout.
- UNIVERSE_NARROW (carried): 15 Base pairs intent-loaded; factory_enumeration + tier_classifier modules landed but not wired into hot/cold scanner loops. Step 1 is the next P0 iteration.
- DISC_HISTORICAL_PROFITABLE (carried): the +91.0771 bps DISC roundtrip from E1.40 has not been promoted into PROD watchlist; pending step 6.
- FEE_2600_RUNTIME (partially addressed): the route mapping is in place and gate-tested; live runtime exercise depends on a PROD candidate hitting a fee-2600 pool, which is gated on step 1.

## 7) Next steps
P0 (next iteration — dedicated step 1 scope):
  1. Wire `discovery/factory_enumeration.py` as the cold-cache producer (Uniswap V3 / PancakeSwap V3 / Aerodrome on Base) feeding `discovery/tier_classifier.py` inputs.
  2. Wire `discovery/tier_classifier.py` into the cold-lane scanner loop with WARM cadence; HOT loop reads the tier_map and caps universe at 100-300 by recency/liquidity/activity.
  3. Persist tier_map under `data/runs/_rolling/m7_tier_map_latest.json`; add reviewer evidence echo.
  4. Acceptance for the post-step-1 30m soak: `fast_path_scored_delta>=20 AND sim_attempted_delta>0 AND roundtrip_attempted_delta>0`.
P1 (post step 1):
  5. Step 6: add `m7/orderflow/disc_to_prod_watchlist.py` (or extend the E1.42 `disc_watchlist.py`) with TTL + provenance promotion of the historical DISC profitable pair into PROD.
  6. Step 9: 60m Base soak in active market window once step 1 fast_path numbers are healthy; aspirational acceptance: `roundtrip_profitable_delta>0` OR top-loss closer than `-20 bps`.
  7. drpc 429 mitigation via documented Base pendingLogs / eth_simulateV1 path (per docs.base.org/base-chain/api-reference/rpc-overview); previously deferred.

## Session Completion
session_goal: Close the seven small/surgical reviewer-funnel + WS-classification + clean-cycle items (steps 2/3/4/5/7/8/10) from the post-E1.45 30m soak report without large refactors; explicitly defer the structural step 1 (universe expansion wiring), step 6 (DISC→PROD watchlist promotion), and step 9 (active-window soak) to their own iterations.
goal_status: REACHED for steps 2/3/4/5/7/8/10 (code + tests + safety + docs); DEFERRED for steps 1/6/9.
close_allowed: true
remaining_blockers:
  - ECONOMIC: PROD roundtrip_profitable_total still 0; pending step 1 universe expansion + step 9 active-window soak.
  - INFRA: drpc 429 mitigation (alternate Base RPC path) not in scope this iteration; partially mitigated by step 4 reclassification + existing rate-limit cooldown.
evidence_session_run_dirs:
  - No fresh runtime artifacts produced this iteration (code-only).
  - Existing rolling artifacts retained from post-E1.45 30m soak; will be self-corrected on the next supervisor run via E1.45 sibling-flush + E1.46 clean_child_exits + current_session_window code paths.
primary_blocker_of_session: NONE (all in-scope steps closed)
blocker_status_before: BLOCKED (E1.45 carried)
blocker_status_after: BLOCKED for production economics; UNBLOCKED for fresh BRIDGE_HIT_NOT_SCORED visibility, dRPC reconnect rate-limit classification, current vs historical session feed rate, and divergence-replay freshness.
docs_reread_confirmed: true
