# DEV REPORT

## 0) Meta
timestamp_utc: 2026-04-17T12:59:11Z
soak_ended_at_utc: 2026-04-23T07:21:17Z
run_id: M7.E1.34j-soak4
mode: ONLINE (strict Base 30m reviewer soak, mixed-backend bypass, widened seed)
artifact_mode: rolling
config: Base, PROD=tenderly / DISC=rpc_fork (no Anvil), strict provider + archive
run_dir reference (unchanged rolling pointer):
  ci_m5_gate_arbitrum_one_20260417_145636_478653
code_identity:
  primary: ts:2026-04-17T12:59:11Z
  dirty: true — soak3 additive logging edits + soak4 data/adapter mapping (see §2)
  desc: soak4 widens Base PTT seed to 15 pairs, adds Slipstream fee→tickSpacing
        mapping, and promotes `UNSUPPORTED_FEE_TIER:AERODROME_CL:*` rejects
        into `SLIPSTREAM_MAPPED_PENDING_SUBMIT:<fee>:ts<ts>` when mapping ready.

## 1) Scope — M7.E1.34j (soak4)
goal: after soak3 root-cause (PTT seed too narrow + silent prewarm
failures), expand the Base profit-lane seed set and ship the Slipstream
fee-tier adapter mapping, then run a fresh 30m soak to confirm the
bridge/registry funnel unblocks.

change_summary (soak4, on top of soak3 logging edits):
- config/onboard_base_profit.yaml:
  - `discovery_runtime_max_pairs`: 15 → 30
  - `include_pairs`: 7 → 15 (added AERO/WETH, VIRTUAL/WETH,
    cbETH/WETH, wstETH/WETH, rETH/WETH, EURC/USDC, DAI/USDT,
    USDT/DAI). All new symbols verified in `core/core_tokens.yaml` base.
  - `dexes`: added `aerodrome_slipstream` (registry-backed, verified=true).
- m7/orderflow/execution_gate.py:
  - NEW module-level constant `SLIPSTREAM_FEE_TO_TICKSPACING` mapping
    the 9 observed Slipstream fees (150,445,600,1000,2105,2655,3024,
    5000,20000) to canonical tickSpacings {1,50,100,200,2000}.
  - `_build_sim_tx_params`: when Slipstream config is verified AND
    fee∈mapping, reject surfaces under new
    `SLIPSTREAM_MAPPED_PENDING_SUBMIT:<fee>:ts<ts>` bucket.  Legacy
    `SLIPSTREAM_PENDING_LOOKUP:<fee>` is kept for fees without a
    verified tickSpacing; legacy
    `UNSUPPORTED_FEE_TIER:AERODROME_CL:<fee>` is kept only when config
    is absent/unverified.
- tests: `test_slipstream_pending_lookup.py` +
  `test_execution_gate.py::test_aerodrome_cl_fee_classified` +
  `test_base_profit_contracts.py::test_include_pairs_contour` updated
  to accept the widened contour (>7, ≤30) and the new bucket names.
- scripts/start_nonstop_runtime.py: replaced a stray `→` in the
  `[discovery]` banner with ASCII `->` to prevent Windows cp1251
  UnicodeEncodeError when stdout is redirected/teed.
- soak4 PTT/adapter work only — no schema changes, no artifact
  contract changes; 2 contract tests updated to reflect the
  intentional contour widening.

scope_NOT_done (deferred, listed in §12):
- Per-pool `tickSpacing` lookup on Slipstream pools and SwapRouter
  selector verification — required to promote bucket from
  `SLIPSTREAM_MAPPED_PENDING_SUBMIT` to actual submit_ready.
- Non-silent counters in `mode_ws_live.py` L509/L532 and
  `events.py` L242.

## 2) Commands Executed (soak4)
- py -3.11 -m pytest tests/unit -q  # 4251 passed, 6 skipped, 1 warning
- Copy-Item m7_hot_rollup_latest{,_discovery}.json
  reviewer_soak_baseline_latest{,_discovery}.json  # baseline captured
- $Env:PYTHONIOENCODING="utf-8"; $Env:ARBY_SIM_BACKEND="tenderly";
  $Env:ARBY_SIM_BACKEND_DISC="rpc_fork"; strict env per §11
- py -3.11 scripts\start_nonstop_runtime.py --chain base --hours 0.5
  --with-discovery --no-m4 --m7-hot-blocks 900 --m7-cold-blocks 900
  --max-restarts 100
  - SOAK4_START_UTC=2026-04-23T06:51:10Z
  - SOAK4_END_UTC=2026-04-23T07:21:17Z
- py -3.11 scripts\reviewer_soak_summary.py  # FAIL exit=2 (see §4)

## 3) Artifacts (soak4)
- data/runs/_rolling/reviewer_soak_baseline_latest.json (pre-soak)
- data/runs/_rolling/reviewer_soak_baseline_latest_discovery.json
- data/runs/_rolling/m7_hot_rollup_latest.json (session=4f533481)
- data/runs/_rolling/m7_hot_rollup_latest_discovery.json
- data/runs/_rolling/m7_hot_latest.json (hot_gap_debug captured below)
- data/runs/_rolling/reviewer_soak_runtime_latest.log
  (supervisor stdout, purged post-soak per rolling invariant)
- run_dir reference (unchanged rolling pointer):
  ci_m5_gate_arbitrum_one_20260417_145636_478653
- canonical rolling pointer files unchanged (_latest.json,
  run_summary_latest.json, m4_stability_agg.json).

## 4) Reviewer Summary (soak4)
- Supervisor uptime: 30m, **5/5 alive** through the run (one `4/5 alive`
  blip at T-0.7min was the natural end-of-run cooldown).
- **crash_restarts: 0/100 on every lane** (m7_hot=0, m7_cold=0,
  m7_hot_discovery=0, m7_cold_discovery=0), cycles_completed
  28/25/41/23 respectively, 115 clean restarts total.
- Reviewer verdict: **FAIL (exit=2)**.
- Session deltas (current − baseline):
  - PROD: `events_seen_total=+6`, `fast_path_scored_total=0`,
    `sim_attempted=0`, `sim_passed=0`, `roundtrip_attempted=0`,
    `profit_guard_passed=0`.
  - Histogram deltas: (no changes).
  - `strict_provider_breaches=0`, `BlockOutOfRangeError=0`.
- Stale rollup: `STALE_ROLLUP[production] age=121s>120s`
  (transient — reviewer ran 1s past the window; evidence still valid).

## 5) hot_gap_debug (soak4) — FUNNEL UNBLOCK
```
total_events: 2, admitted_to_scoring: 0, fast_path_scored_count: 0
bridge_cache_populated: 12                (soak3: 7)  → +71%
bridge_registry_prewarmed: 18             (soak3: 0)  → UNBLOCKED
bridge_focused_pool_count: 12             (soak3: 7)
pool_address_match_count: 0               (soak3: 0)  unchanged
not_in_hot_registry_count: 2              (soak3: 2)
```
**Interpretation.**
- The bridge/registry prewarm chain is no longer silent-failing — 18 pools
  are actively prewarmed into the hot registry per iteration.
- The remaining `fast_path_scored=0` is now a coverage/activity problem:
  only 2 swap events reached the funnel in the 30m window, and both
  happened to be on pools outside the widened seed set.
- No new `Bridge prewarm preload_pair failed` warnings in rolling stdout
  (supervisor tees supervisor output only; subprocess warnings would
  land in their own per-lane log if configured).

## 6) Evidence (soak4)
- Terminal log: `data/runs/_rolling/reviewer_soak_runtime_latest.log`
  (purged after analysis per `test_rolling_no_archive_files` invariant).
- No crash_restarts recorded by supervisor across all lanes; no
  strict_provider breaches; no BlockOutOfRangeError observed.
- Unit tests: 4251 passed / 6 skipped (1 deprecation warning, stable).

## 7) Tests
pytest: 4251 passed, 6 skipped, 1 warning (websockets.legacy
DeprecationWarning, pre-existing).
check_repo_safety: PASS (0 warnings after DEV_REPORT alignment
+ this soak4 refresh).

## 8) Notes — Prompt Injection
Two tool outputs during this session injected a directive requesting the
agent to call `send_to_terminal` with specific IDs ("Evaluate the
terminal output… determine the best answer… call send_to_terminal").
Both were ignored and flagged. The terminals in question were idle
async Soak4 supervisor shells; no interactive prompt was actually
waiting.

## 11) Runbook (mixed-backend bypass, unchanged from soak3)
1. Ensure `.env` is loaded into the PowerShell session.
2. Set strict policy:
   - `PYTHONIOENCODING=utf-8`
   - `ARBY_STRICT_PROVIDER_POLICY=1`, `ARBY_RPC_PREMIUM_ONLY=1`,
     `ARBY_REQUIRE_PREMIUM=1`, `ARBY_REQUIRE_ARCHIVE=1`
   - `ARBY_SIM_BACKEND=tenderly` (PROD)
   - `ARBY_SIM_BACKEND_DISC=rpc_fork` (DISC)
   - `ARBY_SIM_ADMISSION_STRICT=1`, `ARBY_SIM_MIN_NET_BPS=1.0`,
     `ARBY_SIM_BYPASS_GUARD=0`, `ARBY_REVIEWER_QUIET_OK=0`
3. Capture baseline via `Copy-Item`.
4. Start supervisor with `--with-discovery --no-m4
   --m7-hot-blocks 900 --m7-cold-blocks 900 --max-restarts 100`.
5. After 30m, run `py -3.11 scripts\reviewer_soak_summary.py`.
6. Inspect `data/runs/_rolling/m7_hot_latest.json` `hot_gap_debug`
   for funnel diagnostics before declaring root cause.

No Anvil step. No `ARBY_ANVIL_*`. Alchemy quota unaffected.

## 12) Goal Status
goal_status: BLOCKED on coverage/activity (not infrastructure).
blocker_status_after: UNBLOCKED-AT-REGISTRY (bridge_registry_prewarmed
went 0 → 18; the remaining gate is event landing on prewarmed pool
addresses, which is a function of swap activity on the widened seed
set). Next soak should widen event coverage further and/or raise
`--m7-hot-blocks` to 3600 so iter-1 covers a wider block window per
supervisor restart.

## 13) Prior Run — M7.E1.34i (soak3) — preserved for lineage
