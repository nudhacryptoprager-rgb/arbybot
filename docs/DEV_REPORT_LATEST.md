# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-30T21:25:00Z
run_id: M7.E1.50 in-process WS-target refresh bridge — hypothesis live-tested, REFUTED for canary blocker
mode: ONLINE (canary 30m supervisor 2026-04-30T20:49:39Z→21:19:41Z) + OFFLINE (unit + safety)
artifact_mode: rolling
config: code-only changes; canary used `config/intent.txt` v3.6.0 (post-E1.48), no other config changes.
code_identity:
  primary: ts:2026-04-30T21:25:00Z (split/code @ 7b05d2e + targeted dirty diff for E1.49+E1.50)
  dirty: true (m7/orderflow/mode_ws_live.py, m7/orderflow/loop_runner.py, tests/unit/test_e1_50_ws_reuse.py, docs/status/Status_M7.md, docs/TECH_DEBT.md, docs/DEV_REPORT_LATEST.md)
  desc: Implements deferred TD-003 in-process WS-target refresh bridge as 3 surgical patches per CLAUDE.md §1.2 (no large refactor). Live-tested via 30 min canary that REFUTES the hypothesis that the in-process bridge alone unblocks hot-cycle cadence. Diagnosis: the recv-loop body (where all 3 patches live) is never reached when drpc 429 prevents successful `eth_subscribe newHeads`.

## 1) Scope
goal (Roadmap): M7.E1 Base orderflow stabilization, sub-goal: implement TD-003 in-process registry/tier-map refresh bridge and prove or disprove that it lifts hot-cycle cadence above the reviewer floor (`clean_child_exits_delta>=2/30min`).

change_summary:
  - Re-read AGENTS.md, Roadmap.md, Status_M7.md (E1.49 head), DOCS_POLICY.md, WORKFLOW.md, DEV_REPORT_CANONICAL_UA.md, CLAUDE.md, TECH_DEBT.md (TD-003).
  - Patch A — module-level last-working WS endpoint cache (`_LAST_WORKING_WS`) in `m7/orderflow/mode_ws_live.py`. Helpers `_remember_last_working_ws(chain, url, provider)` and `_peek_last_working_ws(chain)`. Stamps the proven endpoint on subscribe success; refuses `public_fallback` to honor strict provider policy. Used at WS resolution time to prefer the proven endpoint over the default chain config (controlled by `ARBY_WS_REUSE_LAST_WORKING`, default `1`).
  - Patch B — mid-recv-loop bridge refresh in `m7/orderflow/mode_ws_live.py` recv loop, hot-lane only. Re-reads cold->hot bridge file every `ARBY_HOT_BRIDGE_REFRESH_S` seconds (default 45s) and warms `_pool_token_cache` so newly-resolved pools become scoreable without restarting the WS subscription. Pure additive: cache writes only; registry mutation stays at iteration boundary per TD-003 risk note (cross-process lock primitives + race-condition audit are out of scope for a surgical patch).
  - Patch C — throttle zero-liquidity refresh in `m7/orderflow/loop_runner.py` to every Nth hot iteration (`ARBY_HOT_ZLR_EVERY_N_ITERS`, default 3). Cuts per-iteration drpc HTTP load (eth.block_number + per-pool state queries) by ~66% to leave headroom for the WS recv loop.
  - Test shield: `tests/unit/test_e1_50_ws_reuse.py` (5 cases) covers remember/peek roundtrip, chain scoping, overwrite-on-success, unknown-chain none, ignore-empty-inputs.
  - Canary: full 30 min supervisor run with all 3 patches live + Alchemy WS fallback enabled. Reviewer post-canary diff classifies the result.

touched_files:
  - m7/orderflow/mode_ws_live.py (module-level `_LAST_WORKING_WS`, helpers `_remember_last_working_ws`/`_peek_last_working_ws`, ws-resolution-time reuse preference, mid-recv-loop bridge refresh block, remember-on-subscribe-success hook)
  - m7/orderflow/loop_runner.py (zero-liq refresh throttling via `ARBY_HOT_ZLR_EVERY_N_ITERS`)
  - tests/unit/test_e1_50_ws_reuse.py (NEW — 5 unit tests for last-working WS cache contract)
  - docs/status/Status_M7.md (E1.50 head section, E1.49 demoted to Prior)
  - docs/DEV_REPORT_LATEST.md (this rewrite)

## 2) Commands Executed (facts only)
py -3.11 -m pytest tests/unit/test_e1_50_ws_reuse.py -q : **PASS 5/5** in 0.19s
py -3.11 -m pytest tests/unit -q : **PASS 4446 / 6 skipped / 1 warning** in 111.16s (+5 vs E1.49 baseline 4441)
py -3.11 scripts/check_repo_safety.py --allow-intent-edit : PASS 0 warnings (20 gates)
Copy-Item data/runs/_rolling/m7_hot_rollup_latest.json data/runs/_rolling/reviewer_soak_baseline_latest.json -Force (baseline snapshot pre-canary at 2026-04-30T20:49:38Z)
py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4 --dashboard-port 8109 --m7-hot-ws-timeout 120 --m7-hot-blocks 300 --m7-hot-max-events 120 --m7-hot-pause 1 --m7-cold-pause 5 with `ARBY_ALCHEMY_WS_FALLBACK=1 ARBY_HOT_HEARTBEAT_INTERVAL_S=30 ARBY_HOT_BRIDGE_REFRESH_S=45 ARBY_HOT_ZLR_EVERY_N_ITERS=3 ARBY_WS_REUSE_LAST_WORKING=1` : supervisor 2026-04-30T20:49:39Z→21:19:41Z, 5/5 alive, crash_restarts=0, cycles_completed=0
py -3.11 scripts/reviewer_soak_summary.py --baseline data/runs/_rolling/reviewer_soak_baseline_latest.json --current data/runs/_rolling/m7_hot_rollup_latest.json --discovery : OVERALL_ACCEPTANCE FAIL (NO_HOT_CYCLE_COMPLETED_DURING_SOAK both lanes, NO_FRESH_SIM_PASSED, NO_FRESH_ROUNDTRIP_ATTEMPTED)

## 3) Artifacts Attached
rolling: `data/runs/_rolling/m7_hot_rollup_latest.json` written through canary; session_id=1e42019a (TTL persisted across canary). Last-updated 2026-04-30T21:19:41Z. Fields: `windows_seen=173` (+11 vs baseline), `events_seen_total=4786` (+168), `fast_path_scored_total=632` (+31), `clean_child_exits_total=9` (delta=+0), `periodic_heartbeats_total=14` (+13 — iteration-boundary cadence telemetry from E1.49 verified working), `session_ws_failed_429_windows=4` (+3 vs E1.49 canary), `last_ws_recv_error="Too many request, try again later, code: 15"`, `last_rpc_provider=drpc`.
DISC sibling: `m7_hot_rollup_latest_discovery.json`, session_id=a9e20745, last-updated 2026-04-30T21:19:41Z. Deltas: events +325, fast_scored +42, clean_child_exits +0, sim_passed +0.
baseline: `data/runs/_rolling/reviewer_soak_baseline_latest.json` snapshotted 2026-04-30T20:49:38Z (immediately pre-canary).
canary stdout: `data/runs/_sessions/canary_E1_50.out.log`.
run_dir_bundle: not produced (rolling-only mode).

## 4) Key Results
e1_50_step_a_last_working_ws:
  module: m7/orderflow/mode_ws_live.py (`_LAST_WORKING_WS` dict + helpers + ws-resolution-time preference + remember-on-subscribe-success)
  shape: Module-level state, pure in-process; reset on process restart. Honors strict_provider_policy by refusing to reuse `public_fallback`. ENV gate `ARBY_WS_REUSE_LAST_WORKING` (default `1`).
  observability: would log `WS reuse last-working endpoint: provider=alchemy host=...` on second iteration if first iteration successfully escalated past drpc 429. In the 30 min canary, the first iteration NEVER reached subscribe success → reuse path never activated → no observable cadence change. Patch is correct in shape, but its leverage requires at least one iteration to succeed first.

e1_50_step_b_mid_loop_bridge_refresh:
  module: m7/orderflow/mode_ws_live.py (recv-loop body, hot-lane only)
  shape: Re-reads `data/runs/_rolling/m7_cold_hot_bridge.json` and warms `_pool_token_cache` every `ARBY_HOT_BRIDGE_REFRESH_S` (default 45s). Pure additive — registry mutation NOT performed mid-loop (cross-process safety contract preserved per TD-003).
  observability: would log `mid-loop bridge refresh: +N ptt entries (refresh #M, total_added=K)` if recv-loop ran ≥45s. In the canary, recv-loop body never entered enough times to trigger a refresh — drpc 429 storms forced repeated re-entry through the WS handshake path.

e1_50_step_c_zlr_throttle:
  module: m7/orderflow/loop_runner.py (hot iteration init block, post-prewarm)
  shape: zero-liquidity CL pool refresh runs only on `iteration % ARBY_HOT_ZLR_EVERY_N_ITERS == 1` (default N=3). Cuts per-iteration drpc HTTP load by ~66%.
  observability: would log `hot-phase: zero-liq refresh throttled (iter X, every_n=3)` on skipped iterations. Reduces upstream pressure on drpc HTTP rate limit so WS rate limit gets relatively more headroom; effect on WS 429 unproven without longer soak (no clean iterations completed during this 30 min).

e1_50_canary_evidence:
  command: `py -3.11 scripts/start_nonstop_runtime.py --chain base --hours 0.5 --with-discovery --no-m4 --dashboard-port 8109 --m7-hot-ws-timeout 120 --m7-hot-blocks 300 --m7-hot-max-events 120 --m7-hot-pause 1 --m7-cold-pause 5`
  env: `ARBY_ALCHEMY_WS_FALLBACK=1 ARBY_HOT_HEARTBEAT_INTERVAL_S=30 ARBY_HOT_BRIDGE_REFRESH_S=45 ARBY_HOT_ZLR_EVERY_N_ITERS=3 ARBY_WS_REUSE_LAST_WORKING=1`
  supervisor: 2026-04-30T20:49:39Z → 21:19:41Z, 5/5 alive, cycles_completed=0, crash_restarts=0, clean_restarts=0
  fresh deltas (PROD): events +168, fast_scored +31, sim_passed +0, roundtrip +0, periodic_heartbeats +13 (E1.49 iteration-boundary telemetry CONFIRMED working), 429w +3
  fresh deltas (DISC): events +325, fast_scored +42, sim_passed +0, roundtrip +0
  conclusion: in-process refresh bridge does NOT lift hot-cycle cadence in the presence of upstream drpc 429 on `eth_subscribe newHeads`. The recv-loop body — where Patch A reuse, Patch B mid-loop bridge refresh, and the E1.49 mid-cycle heartbeat all live — was NEVER reached during this canary because the WS subscribe itself failed to complete in any iteration. The surgical patches deliver leverage only after at least one successful subscribe and recv cycle, which the upstream provider blocked here.

## 5) Verification Outcome
production_lane_ok = False (NO_FRESH_SIM_PASSED, NO_FRESH_ROUNDTRIP_ATTEMPTED, NO_HOT_CYCLE_COMPLETED_DURING_SOAK events_seen_delta=174 clean_child_exits_delta=0)
discovery_lane_ok = False (NO_FRESH_SIM_PASSED, NO_FRESH_ROUNDTRIP_ATTEMPTED)
overall_acceptance = FAIL
fresh_economic_breakthrough = NO (PROD `roundtrip_profitable_total=0` unchanged; DISC cumulative `roundtrip_profitable_total=1` from prior soak preserved, no fresh delta)
unit_suite = PASS 4446/6 skipped/0 failed (E1.49 baseline 4441 + 5 new E1.50 cases)
safety_gate = PASS 0 warnings 20 gates

## 6) Production Readiness Assessment
NOT READY for live capital deployment. Stack of blockers refined this iteration:
1. **Infra (PRIMARY)**: drpc 429 reconnect storm on `eth_subscribe newHeads` blocks the hot lane upstream of every patch landed in E1.49 + E1.50. Both `--m7-hot-ws-timeout 120` (E1.49) and `ARBY_WS_REUSE_LAST_WORKING=1` + mid-loop bridge refresh + zero-liq throttle (E1.50) deliver leverage AFTER the recv-loop runs at least once; they cannot heal a subscribe that never completes.
2. **Economics**: PROD `roundtrip_profitable_total=0` since the start of M7.E1. Universe was widened in E1.48 (51→60 pairs, +memes promoted) — needs a healthy hot lane to surface fresh profitable roundtrips.

Path to acceptance has narrowed to the upstream provider:
  (a) provision premium WS provider for hot lane (premium Alchemy slot or dedicated drpc plan), THEN re-run a 60-90m soak with this E1.49+E1.50 stack already in place.
  (b) the deeper alternative — a custom WS multiplexing layer that opens 2 parallel subscriptions (drpc + alchemy) and reads from whichever survives — is its own iteration with its own pre-conditions; not surgical.

The E1.50 patches REMAIN VALUABLE AS-IS: once any WS provider permits sustained recv-loop activity, the in-process bridge will (1) avoid re-paying the drpc reconnect cost on subsequent iterations, (2) absorb new pool resolutions inside the same iteration window, (3) reduce per-iteration drpc HTTP traffic — all necessary for `clean_child_exits_delta>=2/30min`. They are simply NOT the leverage point for the canary blocker.

## Session Completion
session_goal: Implement step 2 (in-process registry/tier-map refresh bridge) per user request, then run a 30 min canary to confirm or refute progress against `clean_child_exits_delta>0`.
goal_status: IN_PROGRESS
close_allowed: false
remaining_blockers: drpc 429 reconnect storm on `eth_subscribe newHeads` blocks WS subscribe before any recv-loop body code executes; in-process refresh bridge cannot heal upstream provider throttling. Provider switch (premium Alchemy slot or dedicated drpc plan) is the next prerequisite for the surgical work to deliver observable cadence improvement.
evidence_session_run_dirs: data/runs/_sessions/canary_E1_50.out.log; rolling artifacts data/runs/_rolling/m7_hot_rollup_latest.json (last_updated=2026-04-30T21:19:41Z, session_id=1e42019a) + m7_hot_rollup_latest_discovery.json (session_id=a9e20745)
primary_blocker_of_session: hot-lane WS subscribe blocked upstream by drpc 429 → cycles_completed=0/30min on canary baseline AND on E1.49 canary AND now on E1.50 canary.
blocker_status_before: ACTIVE (E1.49 canary 2026-04-30T19:58:48Z→20:28:50Z confirmed cycles_completed=0 with cadence telemetry only)
blocker_status_after: BLOCKED (in-process bridge implemented + unit-shielded + canary-tested, but proves the bottleneck is upstream of the recv-loop body — not the cadence/refresh layer; hypothesis "in-process bridge unblocks the canary" REFUTED for the dominant 429-on-subscribe failure mode)
docs_reread_confirmed: true
