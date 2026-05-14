# Status: M8 New-Pool Sniping Pivot

**Status**: IN_PROGRESS — listener_core REACHED; multi_factory coverage PARTIAL; Phase 2 scoring next.

`goal_status`: IN_PROGRESS  
`phase1_status`: REACHED_CORE_LISTENER  
`multi_factory_coverage_status`: PARTIAL  
`phase1_steps_4_9_status`: COMPLETE  
`pipeline_ready`: false  
`production_profit_ready`: false  
`close_allowed`: false  
`primary_blocker_of_session`: M8_NON_UNISWAP_FACTORY_COVERAGE_NOT_VERIFIED  
`blocker_status_before`: M8_FOUNDATION_NOT_IMPLEMENTED  
`blocker_status_after`: PARTIAL  
`next_phase_blocker`: M8_PHASE2_SCORING_AND_RISK_FILTERS_NOT_IMPLEMENTED  
`docs_reread_confirmed`: true  
`phase1_verified_at`: 2026-05-13T21:54:59Z  
`phase1_artifact`: data/runs/_rolling/new_pool_sniper_latest.json  
`phase1_soak_result`: PASS (parse_ok=22, candidates=22, rpc_error_rate=1.56%, cycles=240)  
`factory_coverage_note`: uniswap_v3 verified live (22 events/2h); aerodrome/aerodrome_slipstream/pancakeswap_v3 zero events — RPC timeout (pancakeswap) or no activity in probe window  
`schema_revision_current`: phase1.2  

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

## Next Required Evidence (Phase 2)

- Honeypot / scam / freshness filters return non-zero reject counts on known rugpull tokens
- Dry-run submit rehearsal (`snipe_candidates_total > 0` with `dry_run=True`)
- Scoring rank is stable across 3 consecutive soaks
