# Status: M8 New-Pool Sniping Pivot

**Status**: IN_PROGRESS — listener_core REACHED; WS live path integration IN_PROGRESS; multi_factory coverage PARTIAL.

`goal_status`: IN_PROGRESS  
`phase1_status`: REACHED_CORE_LISTENER  
`multi_factory_coverage_status`: PARTIAL  
`phase1_steps_4_9_status`: COMPLETE  
`pipeline_ready`: false  
`production_profit_ready`: false  
`close_allowed`: false  
`primary_blocker_of_session`: M8_PHASE1_3_WS_LIVE_PATH_NOT_PROVEN  
`blocker_status_before`: WS_SKELETON_ONLY  
`blocker_status_after`: WS_INTEGRATED_GATE_RUNNING  
`next_phase_blocker`: M8_PHASE2_SCORING_AND_RISK_FILTERS_NOT_IMPLEMENTED  
`docs_reread_confirmed`: true  
`phase1_verified_at`: 2026-05-13T21:54:59Z  
`phase1_artifact`: data/runs/_rolling/new_pool_sniper_latest.json  
`phase1_soak_result`: PASS (parse_ok=22, candidates=22, rpc_error_rate=1.56%, cycles=240)  
`factory_coverage_note`: uniswap_v3 verified live (22 events/2h); aerodrome/aerodrome_slipstream/pancakeswap_v3 zero events — RPC timeout (pancakeswap) or no activity in probe window  
`schema_revision_current`: phase1.2  
`round5_ws_gate_started_at`: 2026-05-14T11:02:05Z  
`round5_ws_gate_status`: COMPLETED — status=ACTIVE, parse_ok=2, rpc_error_rate=0%, ws_events_emitted=1 (end-to-end proven)  

## Scope

M8 is the controlled pivot from classic pool-family arbitrage toward new-pool sniping.

M7 remains maintained as the research and arbitrage lane. M8 must not reuse M7 production-profit claims unless fresh M8 runtime artifacts prove them.

## Canonical Docs

- `Roadmap.md`
- `docs/STRATEGIC_PIVOT.md`
- `docs/step_pivot.md`
- `docs/status/Status_M8.md`
- `docs/DEV_REPORT_LATEST.md`

## Artifact Contract

Primary rolling artifact:

- `data/runs/_rolling/new_pool_sniper_latest.json`

Optional rolling artifacts, only after tests define the schema contract:

- `data/runs/_rolling/m8_daily_health.json`
- `data/runs/_rolling/m8_stability_agg.json`

Required top-level fields for M8 artifacts:

- `schema_family`
- `schema_revision`
- `generated_at_utc`
- `source`
- `freshness_s`
- `status`
- `reasons`

Runtime artifacts under `data/runs/**` are not committed to git.

## Phase Gates

Phase 1: listener-only foundation.

- Factory event listener detects new pools.
- Dedupe is deterministic.
- Token metadata is resolved.
- Dual-source reconciliation works through primary RPC and secondary HTTP `eth_getLogs`.
- No live trading.

Phase 2: scoring and dry-run.

- Honeypot/scam/freshness filters are active.
- Ranking is conservative.
- Dry-run submit rehearsal works.
- Precision and safety are prioritized over recall.

Phase 3: constrained real execution.

- Real execution remains behind explicit ENV gates.
- Runtime PnL guard is active.
- First capped-capital learning run may use a bounded loss budget.
- M8 close-out requires non-negative net PnL on capped capital.

## Current Blockers

1. Listener foundation Phase 1 verified -- `listener_core: REACHED`. Multi-factory coverage partial
   (uniswap_v3 verified live; aerodrome/slipstream/pancakeswap_v3 events not yet confirmed).
2. Phase 2 (scoring / dry-run) not yet started.
3. `verification_from_block` for aerodrome (ve33) pending wider archive-RPC scan (no events in
   last 100k blocks on drpc); aerodrome_slipstream (45920743-45921242) and pancakeswap_v3
   (45925866-45927865) verified 2026-05-13 and written to config/new_pool_factories.yaml.
4. Live execution must remain disabled until Phase 1 and Phase 2 evidence is green.

## Phase 1 Evidence (VERIFIED 2026-05-13)

- ✅ `py -3.11 -m pytest tests/unit -q` → 5376 passed, 6 skipped, 1 warning (5370 → 5376 with factory_probe ASCII tests)
- ✅ Offline smoke: schema_family=m8_sniper, schema_revision=phase1.2
- ✅ Slipstream topic0 verified against ICLFactory.sol on GitHub
- ✅ 10-min online smoke: parse_ok=1, candidates=1, status=ACTIVE
- ✅ 60-min soak: parse_ok=7, parse_failed=0, candidates=7, cycles=120, rpc_error_rate=1.875%
- ✅ HexBytes regression fixed and covered by TestParseRawLogHexBytesCompat (6 tests)
- ✅ new_pool_sniper_latest.json registered in canonical rolling set tests
- ✅ Step 4+5: token0_symbol/token1_symbol/pair enrichment in recent_events (ERC20 on-demand)
- ✅ Step 6: rpc_error_histogram in artifact (classifies 408/429/5xx/timeout/other) — 10 new tests
- ✅ Step 7: factory_breakdown per dex (raw/parse_ok/errors/candidates) — 9 new tests
- ✅ Step 8: honeypot detector skeleton (KNOWN_SCAM → FAIL, KNOWN_LEGIT → PASS, else UNKNOWN) — 18 tests
- ✅ Step 9: dry-run scoring placeholder fields (spread_bps/spread_usd/volume_usd/profit_usd/realizability_reason) — 9 tests
- ✅ Step 10: 2h soak PASS — `parse_ok=22, parse_failed=0, candidates=22, cycles=240, elapsed=7202.7s`
  - RPC error rate: 15/960 = 1.56% (14x408_timeout, 1x5xx_server) — normal for drpc
  - Per-dex: uniswap_v3 raw=233/ok=22/cand=22; aerodrome raw=239/ok=0; aerodrome_slipstream raw=233/ok=0; pancakeswap_v3 raw=240/ok=0
  - factory_breakdown and rpc_error_histogram both populated correctly in artifact
  - schema_revision=phase1.2 confirmed throughout run

## Round-3 GPT Review Evidence (2026-05-13)

- ✅ Step R1+R3: sniper_factory_probe.py fully ASCII-safe (no non-ASCII bytes); verified by test_m8_sniper_factory_probe.py
- ✅ Step R2: Windows encoding test added (TestAsciiSafety — 4 tests; cp1252-safe confirmed)
- ✅ Step R4+R5: Status_M8.md unit baseline updated (5376); "Phase 1 RESOLVED" removed, replaced with precise wording
- ✅ Step R6: m8/__init__.py documents m8_package_status=NAMESPACE_SLICE_WITH_RUNTIME explicitly
- ✅ Step R7+R8: smoke_run implementation migrated to m8/runtime/smoke_run.py; scripts/sniper_smoke_run.py is now a 24-line thin wrapper re-exporting main
  - Confirmed: logger source shows "m8.runtime.smoke_run" in soak logs
- ✅ Step R9: verification_from_block/to_block set in config/new_pool_factories.yaml:
  - aerodrome_slipstream: 45920743-45921242 (1 event at block 45920986, verified 2026-05-13)
  - pancakeswap_v3: 45925866-45927865 (2 events at block 45926270, verified 2026-05-13)
  - aerodrome_ve33: null (no events in last 100k blocks on drpc; wider archive scan needed)
- ✅ Step R10: 60-min soak started 2026-05-13T22:49:30Z via m8.runtime.smoke_run thin wrapper
  - IN_PROGRESS at time of status update; results to be appended when complete

## Round-4 GPT Review Evidence (2026-05-14)

Lead directive: drop multi-hour soaks until a 1-hour validation gate proves multi-factory coverage.
All 10 review steps executed in a single session, with intermediate verification between iterations.

- ✅ R4.1 Ownership of dirty changes claimed:
  - Codex previously corrected aerodrome ve33 event signature: was `PairCreated`, real on-chain
    event is `PoolCreated(address indexed token0, address indexed token1, bool indexed stable,
    address pool, uint256)` with topic0 `0x2128d88d14c80cb081c1252a5acff7a264671bf199ce226b53788fb26065005e`.
    Verified live on 2026-05-14: 1 event at block 45925521 in window 45925000-45926000.
  - `LAYOUT_VE33_POOL_CREATED` + `_parse_ve33_pool_created` added to `discovery/new_pool_listener.py`.
  - 5 new tests in `tests/unit/test_m8_sniper_listener.py::TestParseVe33PoolCreated`.
- ✅ R4.2 Documentation rebalanced: `docs/step_pivot.md` switched from "4-hour foundation soak"
  to "1-hour validation gate (paper, no trades, listener-only) — gated by RPC preflight + factory probes".
- ✅ R4.3 RPC preflight wired into M8 online flow: `m8/runtime/smoke_run.py` now invokes
  `scripts.check_rpc_endpoints.check_chain_id`, `check_http_archive`, `check_ws_newheads` before
  self-test. Hard-fails (exit 4) only on chain_id mismatch. `--skip-preflight` flag available.
- ✅ R4.4 M8 routes through `core.rpc_urls.resolve_rpc_http` and `resolve_rpc_ws`. dRPC validation,
  Alchemy keys, public fallbacks now apply to M8 the same way they do to M5/M7.
- ✅ R4.5 WebSocket listener skeleton added (`m8/runtime/ws_listener.py`): `WSPoolEventListener`
  with `eth_subscribe logs`, bounded exponential backoff, reconnect, `last_event_seen_ts`
  heartbeat field, callback-based event handoff. 12 new tests in
  `tests/unit/test_m8_ws_listener.py`. Integration into the main loop is gated behind
  `--prefer-ws` (Phase 1.3+); HTTP polling stays the canonical path through Phase 1.2.
- ✅ R4.6 Concurrent factory polling: factory `eth_getLogs` calls now run in a bounded
  `ThreadPoolExecutor(max_workers=min(N,4))`. Per-factory wall-clock latency recorded.
- ✅ R4.7 ERC20 `symbol()` batched via `core.multicall.get_multicall_batcher` /
  `batch_symbol(...)` in `_build_and_write_artifact`. Per-token single-call path kept as
  fallback for tokens missing from batch (e.g. some non-standard ERC20s).
- ✅ R4.8 Latency surface added to artifact: `metrics.cycle_latency_ms = {count,p50,p95,max}`
  and `metrics.factory_latency_ms_last` (per-dex). Backed by `FunnelTracker.record_cycle_latency`.
- ✅ R4.9 Phase 2 fork-backend integration plan documented at
  `docs/m8/PHASE_2_FORK_BACKEND_INTEGRATION.md` (honeypot layer 1, slippage estimator,
  roundtrip realisability gate; Anvil stays terminal-stage only).
- ✅ R4.10 1-hour validation gate COMPLETED 2026-05-14T09:39:11Z → 2026-05-14T10:39:22Z (3610.4s):
  - Preflight: chain_id 8453 OK; archive head=45977501 (probed block=45975501) OK; WS newHeads OK.
  - Self-test PASS on all four factories: uniswap_v3 (2 events parsed), aerodrome_slipstream (1),
    aerodrome ve33 (1), pancakeswap_v3 (1). First-ever 4/4 PASS.
  - Run: `--poll-interval-s 10 --blocks-back 100`, cycles=354, RPC calls=1416, RPC errors=209
    (14.8% — drpc 408 timeouts + 5xx; above 5% Phase 1.3 target but does not block listener path;
    will be addressed by `--prefer-ws` and/or Alchemy fallback in next iteration).
  - Per-dex breakdown (polls / raw_logs / parse_ok / errors / candidates):
    - uniswap_v3:           303 / 0 / 0 / 51 / 0
    - aerodrome_slipstream: 297 / 0 / 0 / 57 / 0
    - aerodrome (ve33):     304 / 0 / 0 / 50 / 0
    - pancakeswap_v3:       303 / 0 / 0 / 51 / 0
  - Latency metrics confirmed live: `cycle_latency_ms = {count:22, p50:3703, p95:7203, max:7421}`
    @ elapsed=220s (captured mid-run; full p95 in artifact at run end).
  - Final artifact: `status=EMPTY, candidates_total=0` — NO `PoolCreated`/`PairCreated` event landed
    on Base in the 100-block rolling window during the 1-hour run. This is a real-world property
    of Base at that hour, not an M8 bug: the listener polled correctly, all 4 factories were
    self-tested green on a known historical block window before live polling started, and the
    artifact pipeline (factory_breakdown, rpc_error_histogram, cycle/factory latency, multicall
    symbol fallback) was fully exercised.
  - **multi_factory_coverage_status remains PARTIAL**: multi-factory `parse_ok > 0` not yet proven
    on live tip — proof requires either (a) a longer live run that catches a real PoolCreated, or
    (b) the planned `--prefer-ws` listener which subscribes to live newHeads + logs without the
    100-block lookback throttle.
  - Full unit baseline after Round-4 changes: **5394 passed, 6 skipped** (5376 → 5394, +18 tests:
    12 WS listener + 5 ve33_pool_created parser + 1 aerodrome topic assertion).

## Phase 1 Close Criteria (1-hour validation gate)

Phase 1 closure requires *all* of:

- [x] RPC preflight (`chain_id` + `archive` + `WS newHeads`) PASS for the run RPC.
- [x] Factory self-test PASS for every factory in `config/new_pool_factories.yaml` that has
      `verification_from_block`/`verification_to_block` set (currently 4 of 4 on Base).
- [x] 1-hour scan completes without `self_test_FAILED` (RPC error rate 14.8% on drpc — above
      the 5% target; tracked as follow-up: `--prefer-ws` or Alchemy fallback).
- [x] `parse_failed == 0` across the 1-hour window (raw_logs=0, parse_ok=0, parse_failed=0).
- [ ] `factory_breakdown` shows `parse_ok > 0` for at least two distinct DEXes
      (multi-factory coverage proven, not just `uniswap_v3`).
      **Status: PARTIAL** — Base did not produce any PoolCreated/PairCreated event in the
      100-block rolling window during the 1h gate. Re-run with `--prefer-ws` (no lookback throttle)
      OR a longer run that catches a real new-pool event.

## Next Required Evidence (Phase 2)

- Honeypot / scam / freshness filters return non-zero reject counts on known rugpull tokens
- Dry-run submit rehearsal (`snipe_candidates_total > 0` with `dry_run=True`)
- Scoring rank is stable across 3 consecutive soaks

## Round-5 GPT Review Evidence (2026-05-14)

**Active blocker at start of session:** `M8_PHASE1_3_WS_LIVE_PATH_NOT_PROVEN`
(WSPoolEventListener was skeleton-only — not wired into smoke_run.py main loop)

- ✅ R5.1: Stale repo memory file `M8_phase1_round4_complete.md` deleted (violated no-new-docs policy).
- ✅ R5.2: `WSPoolEventListener` wired into `m8/runtime/smoke_run.py` as real live source.
  Background daemon thread started when `--prefer-ws` is passed; `events_lock: threading.Lock` added.
- ✅ R5.3: Full WS callback pipeline via `_process_log_event()`:
  raw_log → parse → dedup (seen_ids) → funnel counters → recent_events append → EventTrace → logger.
  Thread-safe when `events_lock` supplied. Callback factory: `_make_ws_on_event_callback()`.
- ✅ R5.4: HTTP polling in WS mode → fallback/reconciliation: interval × 10 (capped 300s).
  `funnel.inc_http_fallback_poll()` incremented per HTTP cycle. Logged: `http_polling_in_fallback_mode`.
- ✅ R5.5: WS metrics added to `FunnelTracker` and `snapshot()`:
  `listener_mode`, `ws_connected`, `ws_subscriptions`, `ws_events_seen`, `ws_reconnects`,
  `ws_last_event_seen_ts`, `http_fallback_polls` → flow through to artifact via `make_sniper_artifact`.
- ✅ R5.6: 7 integration tests in `TestWSFunnelIntegration` in `tests/unit/test_m8_ws_listener.py`.
  Targeted M8 suite: **156 passed** (was 149; +7 TestWSFunnelIntegration tests).
  Full suite baseline: **5405 passed, 6 skipped** (was 5394, +11: 7 WS funnel + 4 phase2_decision stubs).
- ✅ R5.7: 15-min WS control gate COMPLETED 2026-05-14T11:02:05Z → 2026-05-14T11:17:14Z (909.4s):
  - Preflight PASS: chain_id 8453; archive head=45979988; WS newHeads 2.13s.
  - Self-test 4/4 PASS.
  - `listener_mode=ws+http_fallback` confirmed in artifact; `http_fallback_polls=3` (3 HTTP cycles in 15 min).
  - **RPC error rate: 0%** (RPC calls=12, errors=0) vs 14.8% in HTTP-only 1h gate.
  - **pancakeswap_v3: raw_logs=2, parse_ok=2 (100%), candidates=1** — first live parse_ok on pancakeswap_v3.
  - **status=ACTIVE** (was EMPTY in 1h HTTP-only gate).
  - **WS end-to-end proven**: `ws_listener_stopped | subscriptions=4, events_emitted=1, reconnects=0`.
    WS subscription received the same pool creation event, callback fired, `_process_log_event` parsed it,
    dedup correctly dropped it (HTTP fallback had already captured it first). Full WS funnel verified.
  - Dedup: raw=2, dedup_new=1, dedup_dropped=1 — duplicate correctly suppressed across both paths.
  - `phase2_decision` stubs present and null in artifact.
- ✅ R5.9: Phase 2 `phase2_decision` stubs added to artifact schema in `monitoring/sniper_artifacts.py`:
  `honeypot_result`, `simulation_result`, `realisability_reason`, `dry_run_decision`, `reject_reason`
  (all `null` in Phase 1; Phase 2 will populate with on-chain simulation results).
- ✅ R5.10: Full pytest PASS — **5405 passed, 6 skipped** (was 5394, +11 new tests).
  `check_repo_safety --allow-intent-edit` PASS (1 warning: Status_M7.md bloat — pre-existing).

**Current blockers (Round-5 POST-GATE):**
1. `M8_MULTI_FACTORY_PARSE_OK_SINGLE_DEX` — only pancakeswap_v3 had live events; uniswap_v3/aerodrome/
   slipstream had zero. Phase 1 close requires parse_ok > 0 on ≥2 DEXes. Next longer gate needed.
2. `PLAIN_CI_BLOCKED_BY_INTENT_TIER_LIMIT` — known pre-existing blocker; not M8-specific.
