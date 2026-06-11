# Status: M8.2 Cross-DEX Expansion & Mirror Handoff

**Status**: **M8_2_QUALITY_BLOCKED** (mirror/subgraph/handoff gates; independent of M9 economics)

**Scan methodology (confirmed):**
- Token-first expansion: **CONFIRMED** (`expand_token_neighborhood` per registry token).
- All configured DEX in `dex_ids_checked`: **CONFIRMED** (13 DEX).
- Full per-token × dex × anchor scan coverage: **PROVEN** (`active_scan_coverage_rate=1.0`, `scan_attempt_matrix` tokens=696, `missing_dexes=[]`, `m8_2_scan_coverage_report` blockers=[]).

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

| Gate | Threshold | Current (2026-06-11 telemetry expansion) |
|------|-----------|----------------------------------------:|
| `active_scan_coverage_rate` | ≥ 0.98 | **1.0** |
| `scan_attempt_matrix` tokens | > 0 | **696** |
| `scan_actual_attempts` | — | **41760** |
| `missing_dexes` | [] | **[]** |
| `subgraph_ready_tokens` | ≥ 3 | **1** |
| `verified_second_pool_count` | ≥ 10 | **4** |
| `multi_venue_tokens` | ≥ 14 | **13** |
| `connector_routes_count` | > 0 | **67** |
| `active_factory_second_pool_count` | — | **0** |
| Freshness order | sniper ≤ hints ≤ expansion | **PASS** |

`m8_2_scan_coverage_report` blockers: **[]** (coverage PROVEN).  
`m8_2_acceptance_report` blockers: `SUBGRAPH_READY_LOW`, `VERIFIED_SECOND_POOL_LOW`, `MULTI_VENUE_TOKENS_LOW` (quality, not coverage).

**Honest mirror verdict:** on all 13 configured DEX, active scan logged **30875× `ACTIVE_SCAN_NO_POOL`**; `active_factory_second_pool_count=0`. No second-venue mirror found for single-venue M8 tokens at scan time.

## Last Expansion Artifact

`artifact_path`: data/runs/_rolling/m8_cross_dex_expansion_latest.json  
`generated_at_utc`: 2026-06-11T19:43:16Z  
`routes_admitted_count`: 1024  
`m8_tokens_in`: 701  
`hint_tokens_matched`: 773  
`external_hints_enabled`: true  
`hints_generated_at_utc`: 2026-06-11T16:48:34Z  
Runtime: ~31m foreground (701 tokens, full scan matrix telemetry)

## Provenance split (expansion routes)

| Origin | Count |
|--------|------:|
| `m8_watchlist_hint` | 773 |
| `exploration` | 251 |
| `canonical_routes_count` | 773 |
| `routes_rejected_not_m8_derived` | 251 |

## Hint quality (expansion pass)

| Status | Count |
|--------|------:|
| `HINT_STALE` | 245 |
| `HINT_POOLID_VERIFIED` | 87 |
| `HINT_ONCHAIN_VERIFIED` | 40 |
| `HINT_ONLY` | 27 |

Per-source verified yield: DexScreener **107**, GeckoTerminal **21**

## M8.2 Blockers (not M9)

- `SUBGRAPH_READY_LOW`
- `VERIFIED_SECOND_POOL_LOW`
- `HINTS_STALE` / `EXTERNAL_HINTS_STALE`
- `CONNECTOR_SYNTHESIS_WEAK`
- `MULTI_VENUE_TOKENS_LOW`

## M8.2 Quality Improvements (code)

- **Active factory scan** (bounded USDC/WETH × CLMM/V2 DEX set) when `token_seen_on_dexes < 2`
- **Hint refresh**: `--retry-single-venue` with backoff for single-venue watchlist tokens
- **Connector reject reasons**: `CONNECTOR_ANCHOR_NO_POOL`, `CONNECTOR_ANCHOR_NOT_QUOTEABLE`, `CONNECTOR_ADDRESS_UNKNOWN`
- **Diagnostics**: `subgraph_ready_debug` per token + `per_source_verified_yield` in `m8_2_acceptance_report`
- **Provenance in expansion summary**: `canonical_routes_count`, `exploration_routes_count`, `routes_by_origin_source`

## Out of Scope for M8.2

- `cycles_quoteable`, `qsr_econ`, `cycles_positive_gross` — evaluated only in `m9_lane_acceptance_report.py`
- Bridge `graph_ready_from_expansion` proves handoff volume, not M8.2 quality REACHED

## Canonical Docs

- `Roadmap.md`
- `scripts/m8_2_acceptance_report.py`
- `data/runs/_rolling/m8_cross_dex_expansion_latest.json`
- `data/runs/_rolling/m8_external_pool_hints_latest.json`
