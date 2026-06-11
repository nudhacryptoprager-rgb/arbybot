# Status: M8.2 Cross-DEX Expansion & Mirror Handoff

**Status**: **M8_2_QUALITY_BLOCKED** (mirror/subgraph/handoff gates; independent of M9 economics)

`goal_status`: BLOCKED
`schema_family`: cross_dex_expansion
`execution_enabled`: false
`kill_switch_active`: true

## Role in Pipeline

M8.2 discovers second-venue pools, external hints, connector synthesis, and subgraph-ready tokens. It feeds the M9 bridge builder but does **not** own cycle quoteability or economics.

Acceptance artifact: `data/tmp/m8_2_acceptance_report_latest.json`  
Canonical command:

```powershell
py -3.11 scripts/m8_2_acceptance_report.py --strict
```

## M8.2 Quality Gates (strict)

| Gate | Threshold | Current (2026-06-11 post-hint-refresh) |
|------|-----------|--------------------------------------:|
| `subgraph_ready_tokens` | ≥ 3 | **1** |
| `verified_second_pool_count` | ≥ 10 | **4** |
| `multi_venue_tokens` | ≥ 14 | **13** |
| `connector_routes_count` | > 0 | **67** |
| Freshness order | sniper ≤ hints ≤ expansion | **PASS** |

`m8_2_acceptance_report` blockers: `SUBGRAPH_READY_LOW`, `VERIFIED_SECOND_POOL_LOW`, `MULTI_VENUE_TOKENS_LOW`

## Last Expansion Artifact

`artifact_path`: data/runs/_rolling/m8_cross_dex_expansion_latest.json  
`generated_at_utc`: 2026-06-11T16:53:33Z  
`routes_admitted_count`: 1024  
`m8_tokens_in`: 701  
`hint_tokens_matched`: 773  
`external_hints_enabled`: true  
`hints_generated_at_utc`: 2026-06-11T16:48:34Z

## Provenance split (expansion routes)

| Origin | Count |
|--------|------:|
| `m8_watchlist_hint` | 777 |
| `specialized_index_for_m8_token` | 164 |
| `exploration` | 83 |
| `canonical_routes_count` | 941 |
| `routes_rejected_not_m8_derived` | 83 |

## M8.2 Blockers (not M9)

- `SUBGRAPH_READY_LOW`
- `VERIFIED_SECOND_POOL_LOW`
- `HINTS_STALE` / `EXTERNAL_HINTS_STALE`
- `CONNECTOR_SYNTHESIS_WEAK`
- `MULTI_VENUE_TOKENS_LOW`

## Out of Scope for M8.2

- `cycles_quoteable`, `qsr_econ`, `cycles_positive_gross` — evaluated only in `m9_lane_acceptance_report.py`
- Bridge `graph_ready_from_expansion` proves handoff volume, not M8.2 quality REACHED

## Canonical Docs

- `Roadmap.md`
- `scripts/m8_2_acceptance_report.py`
- `data/runs/_rolling/m8_cross_dex_expansion_latest.json`
- `data/runs/_rolling/m8_external_pool_hints_latest.json`
