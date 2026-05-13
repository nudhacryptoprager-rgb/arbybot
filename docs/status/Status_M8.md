# Status: M8 New-Pool Sniping Pivot

**Status**: REACHED — Phase 1 listener foundation verified.

`goal_status`: IN_PROGRESS  
`pipeline_ready`: false  
`production_profit_ready`: false  
`close_allowed`: false  
`primary_blocker_of_session`: M8_PHASE1_VERIFIED  
`blocker_status_before`: M8_FOUNDATION_NOT_IMPLEMENTED  
`blocker_status_after`: RESOLVED  
`docs_reread_confirmed`: true  
`phase1_verified_at`: 2026-05-13T19:31:56Z  
`phase1_artifact`: data/runs/_rolling/new_pool_sniper_latest.json  
`phase1_soak_result`: PASS (parse_ok=7, candidates=7, rpc_error_rate=1.875%, cycles=120)  

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

1. Phase 1 RESOLVED — listener foundation verified by 60-min soak.
2. Phase 2 (scoring / dry-run) not yet started.
3. verification_from_block for aerodrome (ve33) and pancakeswap_v3 factories pending archive RPC
   (drpc unstable for eth_getLogs without topic0 filter; TODO in config/new_pool_factories.yaml).
4. Live execution must remain disabled until Phase 1 and Phase 2 evidence is green.

## Phase 1 Evidence (VERIFIED 2026-05-13)

- ✅ `py -3.11 -m pytest tests/unit -q` → 5289 passed, 0 failed
- ✅ Offline smoke: schema_family=m8_sniper, schema_revision=phase1.1
- ✅ Slipstream topic0 verified against ICLFactory.sol on GitHub
- ✅ 10-min online smoke: parse_ok=1, candidates=1, status=ACTIVE
- ✅ 60-min soak: parse_ok=7, parse_failed=0, candidates=7, cycles=120, rpc_error_rate=1.875%
- ✅ HexBytes regression fixed and covered by TestParseRawLogHexBytesCompat (6 tests)
- ✅ new_pool_sniper_latest.json registered in canonical rolling set tests

## Next Required Evidence (Phase 2)

- Honeypot / scam / freshness filters return non-zero reject counts on known rugpull tokens
- Dry-run submit rehearsal (`snipe_candidates_total > 0` with `dry_run=True`)
- Scoring rank is stable across 3 consecutive soaks
