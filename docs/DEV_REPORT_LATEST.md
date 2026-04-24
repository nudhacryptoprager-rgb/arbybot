# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
soak_started_at_utc: 2026-04-24T06:04:00Z
soak_ended_at_utc: 2026-04-24T06:34:13Z
run_id: M7.E1.34m-soak7
mode: ONLINE (Base, 30m, strict provider policy, session persistence,
  exit-reason diagnostics, dashboard actualization).
artifact_mode: rolling
config: Base, PROD=tenderly / DISC=rpc_fork, strict provider + archive
run_dir reference (unchanged rolling pointer):
  ci_m5_gate_arbitrum_one_20260417_145636_478653
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — soak3 logging + soak4 seed/mapping + soak5 Slipstream ts
         + soak6 supervisor per-window caps + soak7 session persistence
         + WS exit_reason diagnostic + dashboard actualization.

## 1) Scope — M7.E1.34m (soak7)
The user approved the 4 queued fixes from soak6 §9 plus a live 30-min
validation and dashboard refresh:
  1. Persist `session_id` across clean-exits so reviewer counters
     survive supervisor restarts within the same soak.
  2. Wire per-pool Slipstream tickSpacing + token addresses so
     SLIPSTREAM_SIM_READY_TOKENS_MISSING becomes reachable.
  3. Fix the internal `run_live_scan` early-exit that kept each
     subprocess to 20–170 s regardless of supervisor `--ws-timeout=600`.
  4. Make `reviewer_soak_summary.py` aggregate across a rolling
     30-min window without requiring identical session_id.
  5. Dashboard actualization with session + exit-reason surfaces.
  6. Pytest + repo safety + 30-min soak7 to confirm or refute.

## 2) Change summary (code actually shipped this cycle)
- `m7/orderflow/runtime_io.py`:
  - `_resolve_session_id()` reads/writes
    `data/runs/_rolling/m7_session_state.json` (TTL 900 s, disable via
    `ARBY_SESSION_PERSIST=0`). All 5 lanes now share the same
    `session_id`, so reviewer session-scoped fields accumulate across
    clean-exit restarts within a soak.
- `m7/orderflow/mode_ws_live.py`:
  - Added `_exit_reason` tracking at each WS-loop exit path (timeout,
    recv error, recv timeout, max_events, ws_blocks exhausted,
    exception, 429). Surfaced in `ws_live_stats.exit_reason` so the
    supervisor's rc=0 clean exits stop being opaque.
- `m7/orderflow/hot_runtime_artifacts.py`:
  - Rollup session now carries `session_exit_reason_histogram` and
    `last_exit_reason`, enabling operators to distinguish benign
    `recv_timeout` from pathological `ws_429` / `loop_not_entered`.
- `monitoring/dashboard_server.py` + `monitoring/dashboard.html`:
  - `/api/summary` adds `session_state` (file contents),
    `current_session_id`, `last_exit_reason`, `exit_reason_histogram`.
  - Monitoring Summary panel renders a PERSISTED/ROTATED badge plus an
    exit-reason table. No breaking JSON changes (additive only).

Items intentionally NOT shipped this cycle (with explicit reason):
- `set_slipstream_pool_ts()` wiring inside `scoring_parallel.py`:
  pool-inspection hot path was not touched because soak7 first
  uncovered an upstream root cause (see §3) that makes the Slipstream
  bucket unreachable regardless of ts publication. Wiring is parked
  for soak8 after the recv-error root cause is resolved.
- `--rolling-window` flag on `reviewer_soak_summary.py`: the reviewer
  already compares totals-deltas (events_seen_total, fast_path_scored
  _total, etc.) which are cumulative — not session-scoped — so the
  existing command already honours a rolling window once session_id is
  persisted. Adding a redundant flag was deferred.
- `SystemExit → retry` in `run_live_scan`: soak7 evidence (see §3)
  shows the exits are `recv_error`, NOT SystemExit. Rewriting those 4
  sites would not change behaviour; a targeted reconnect loop is the
  correct fix and is scheduled for soak8.

## 3) Soak7 evidence
Supervisor end: 2026-04-24T06:34:13Z
Supervisor tail metrics:
  - 5/5 lanes alive at termination.
  - crash_restarts 0/100 for every subprocess.
  - cycles_completed: m7_hot=22, m7_cold=18, m7_hot_discovery=22,
    m7_cold_discovery=8 (70 cycles total across 30 min).
  - restarts (clean exits + respawns): 69.

Session persistence — confirmed working:
  - `data/runs/_rolling/m7_session_state.json` ==
    `{"session_id": "45482710", "updated_at_epoch": 1777012441}`
  - `m7_hot_rollup_latest.json.session.session_id` == "45482710"
  - `m7_hot_rollup_latest_discovery.json.session.session_id` ==
    "45482710"
  - Both rollups share the SAME session_id — prior cycles had
    divergent ids per lane, which blocked reviewer session-scoped
    accumulation.

Exit-reason histogram — the single most important soak7 finding:
  - production lane: `{"recv_error": 9}`
  - discovery  lane: `{"recv_error": 10}`
  - 100% of WS-loop exits were `recv_error`. NOT `ws_timeout` (which
    would imply quiet market), NOT `max_events_reached` (which would
    imply structural cap), NOT `ws_429` (which would imply rate
    limiting). This is the peer (Alchemy WS) closing the stream
    mid-session, typically 50–120 s in — exactly the window the
    supervisor log shows as "Clean cycle exit rc=0 after Ns".
  - Operational consequence: `args.ws_timeout=600` has zero effect
    because `ws_conn.recv()` returns an exception LONG before the
    timeout guard fires. The "ghost timeout" was a misdiagnosis; the
    true problem is WS keep-alive / provider-side idle disconnects.

Reviewer verdict (baseline = soak6 end, current = soak7 end):
  - events_seen_total: +14 PROD / +15 DISC
  - fast_path_scored_total: +0 / +0
  - sim_attempted_total: +0 / +0
  - roundtrip_attempted_total: +0 / +0
  - strict_provider_breaches_total: +0 / +0
  - BlockOutOfRangeError: +0 / +0
  - OVERALL_ACCEPTANCE: FAIL for both lanes because fast_path_scored
    did not advance.

## 4) Interpretation
Soak7 fixed the infrastructure surfaces (session, diagnostics,
dashboard) as promised, but did NOT produce a funnel breakthrough.
That is not a regression — it is the first soak in this series where
the scanner subprocess ran stably for 30 min without any crash,
while the rollup unambiguously tells us where the work is being lost:

  - Events arrive but fast_path_scored stays flat: +14 events /
    +0 scored. The bottleneck is between normalize_swap_log and
    score_backrun_fast, not in the supervisor, not in ws_timeout,
    not in max_events, not in session_id.
  - `recv_error` dominates: the WS subprocess cannot sustain a
    long-lived newHeads subscription under strict_provider_policy,
    so each lane averages ~65 s of wall time per subprocess instance
    and then respawns. Even if the funnel worked, the lane reopens
    bridge/PTT state every ~70 s, paying a cold-start tax before any
    scoring can occur.

## 5) What soak8 must do (unchanged from soak7's deferred list, now
   with a measured root cause)
1. Replace the `ws_conn.recv()` implicit-exit path with an explicit
   reconnect loop: on `recv_error`, close the connection, back off
   (exponential 1 s → 8 s capped), re-subscribe `newHeads`, continue
   the same scoring session. Only break on `ws_blocks` exhaustion or
   `ws_timeout` actually reached. This turns 22 × ~65 s disposable
   windows into a continuous stream.
2. Publish Slipstream tickSpacing + token addresses inside
   `scoring_parallel.py` so SIM_READY_TOKENS_MISSING becomes a
   reachable bucket once the funnel is alive.
3. If reconnect fix unlocks fast_path_scored > 0, re-run reviewer
   with default thresholds; otherwise keep
   `ARBY_REVIEWER_QUIET_OK=1` as an escape hatch.

## 6) Validation gates
- pytest: `py -3.11 -m pytest tests/unit -q` → 4252 passed, 6 skipped
  (identical to soak6 baseline; no new tests introduced, no existing
  tests broken by session persistence or exit_reason changes).
- repo safety: `py -3.11 scripts\check_repo_safety.py` → PASS, 0
  warnings (all 20 gates including DEV_REPORT_LATEST timestamp anchor
  and docs bloat limit).
- dashboard: `/api/summary` JSON extended with `session_state`,
  `current_session_id`, `last_exit_reason`, `exit_reason_histogram`
  (additive only).

## 7) Prompt-injection / async output surveillance
No prompt-injection attempts detected in async supervisor output or
subprocess logs for soak7 (reviewed full 30-min tail). Only expected
strings: PID lines, "Clean cycle exit", "[supervisor] N/5 alive".

## 8) File-level audit trail for soak7
- `m7/orderflow/runtime_io.py`: added `_resolve_session_id()` and
  state-file I/O.
- `m7/orderflow/mode_ws_live.py`: `_exit_reason` initialisation +
  branch-wise assignments + exposure in `ws_live_stats.exit_reason`.
- `m7/orderflow/hot_runtime_artifacts.py`: session rollup now carries
  `session_exit_reason_histogram` + `last_exit_reason`.
- `monitoring/dashboard_server.py`: `/api/summary` adds 4 fields.
- `monitoring/dashboard.html`: Monitoring Summary panel renders
  session badge + exit-reason table.
- `data/runs/_rolling/m7_session_state.json`: new runtime artifact.

## 9) Queued for soak8 (in priority order)
1. WS `recv_error` → reconnect-in-place loop (the actual blocker).
2. Slipstream tickSpacing + token-address publication in
   `scoring_parallel.py` (now unblocked by fix #1).
3. Optional `--rolling-window` flag on reviewer (cosmetic).

run_dir reference kept intact: ci_m5_gate_arbitrum_one_20260417_145636_478653
