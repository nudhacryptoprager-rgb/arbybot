# Status: M8 New-Pool Sniping Pivot

**Status**: OPEN - documentation scaffold only; implementation not started.

`goal_status`: OPEN  
`pipeline_ready`: false  
`production_profit_ready`: false  
`close_allowed`: false  
`primary_blocker_of_session`: M8_FOUNDATION_NOT_IMPLEMENTED  
`blocker_status_before`: UNRESOLVED  
`blocker_status_after`: IN_PROGRESS  
`docs_reread_confirmed`: true

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

1. M8 runtime implementation has not landed.
2. `new_pool_sniper_latest.json` is not yet produced.
3. Schema-contract and golden fixture tests are not yet implemented.
4. Phase CLI flags in `step_pivot.md` are target interfaces, not verified commands.
5. Live execution must remain disabled until Phase 1 and Phase 2 evidence is green.

## Next Required Evidence

- `py -3.11 scripts/check_repo_safety.py --allow-roadmap-edit --allow-intent-edit`
- `py -3.11 -m pytest tests/unit -q`
- First listener-only smoke that writes `new_pool_sniper_latest.json`
- Schema-contract test for the artifact
- DEV report updated only with fresh artifact-backed claims
