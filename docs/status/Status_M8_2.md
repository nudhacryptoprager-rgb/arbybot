# Status: M8.2 Cross-DEX Expansion & Mirror Handoff

**Status**: **MIRROR_TOPOLOGY_FOUND / MIRROR_QUOTE_READY_BLOCKED** (not `M8_2_QUALITY_REACHED`)

`goal_status`: BLOCKED (`MIRROR_READY_LOW` + `SUBGRAPH_READY_LOW` + `MULTI_VENUE_TOKENS_LOW` + `VERIFIED_SECOND_POOL_LOW`; `handoff_ready=false`, `mirror_quote_ready_tokens=0`)
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

| Gate | Threshold | Current (2026-06-14 fresh expansion) |
|------|-----------|----------------------------------------:|
| `active_scan_coverage_rate` | ≥ 0.98 | **1.0** |
| `candidate_scan_coverage_rate` | ≥ 0.98 | **1.0** |
| `scan_actual_attempts` | — | **15021** |
| `missing_dexes` | [] | **[]** |
| `subgraph_ready_tokens` | ≥ 3 | **0** |
| `mirror_topology_ready_tokens` | ≥ 3 | **2** |
| `mirror_quote_ready_tokens` | ≥ 1 | **0** |
| `same_pair_mirror_tokens` | — | **2** |
| `verified_second_pool_count` | ≥ 10 | **2** |
| `multi_venue_tokens` | ≥ 14 | **11** |
| `connector_routes_count` | > 0 | **67** |
| Freshness order | sniper ≤ hints ≤ expansion | **PASS** |

`m8_2_scan_coverage_report` blockers: **[]** (canonical coverage PROVEN).  
`m8_2_acceptance_report` blockers: **`MIRROR_READY_LOW`**, **`SUBGRAPH_READY_LOW`**, **`MULTI_VENUE_TOKENS_LOW`**, **`VERIFIED_SECOND_POOL_LOW`**.

**Mirror lane (honest):** topology found on **2** tokens (`bNODE`, `TRITRI`) with same-pair routes on distinct DEXes, but each has only **1** quoteable leg (`SAME_PAIR_QUOTES_LT_2`). Second legs fail on-chain (`QUOTE_FAIL_ZERO_OUT` / `QUOTE_FAIL_REVERT`), not metadata gaps. `mirror_tokens` list is now explicit in expansion + acceptance top-level.

## Mirror topology tokens (quote smoke 2026-06-14)

| Token | DEX A | DEX B | Quoteable legs | Blocker |
|-------|-------|-------|----------------|---------|
| **bNODE** `0xf32e…d661` | aerodrome `QUOTE_OK_MIRROR_SMOKE` | uniswap_v3 `QUOTE_FAIL_ZERO_OUT` | 1/2 | `SAME_PAIR_QUOTES_LT_2` |
| **TRITRI** `0x0b09…bf18` | uniswap_v3 `QUOTE_OK_MIRROR_SMOKE` | uniswap_v4 `QUOTE_FAIL_REVERT` | 1/2 | `SAME_PAIR_QUOTES_LT_2` |

Failure breakdown (second legs): zero quoter output / zero on-chain liquidity (V3), V4 quoter revert + StateView liquidity=0 (V4). Not `QUOTE_CONFIG_MISSING` or `STALE_HINT` for these pools.

## Last Expansion Artifact

`artifact_path`: data/runs/_rolling/m8_cross_dex_expansion_latest.json  
`generated_at_utc`: 2026-06-14T20:28:00Z  
`routes_admitted_count`: 471  
`m8_tokens_in`: 203  
`hint_tokens_matched`: 220  
`external_hints_enabled`: true  
`hints_generated_at_utc`: 2026-06-14T20:10:18Z  

## M8 upstream (not blocker)

M8 sniper acceptance **REACHED** (`2026-06-14T19:38:05Z`): `m8_health.goal_status=REACHED`, `ws+http_fallback`, `rpc_errors=0/108`. Blocker is M8.2 mirror **quote** quality, not M8 listener health.

## M8.2 Blockers (not M9)

- `MIRROR_READY_LOW` (**active** — topology 2, quote-ready 0)
- `SUBGRAPH_READY_LOW` (**active** — 0 tokens)
- `MULTI_VENUE_TOKENS_LOW` (**active** — 11 < 14)
- `VERIFIED_SECOND_POOL_LOW` (**active** — 2 < 10)

## M8.2 Quality Improvements (code, this session)

- `resolve_route_token_addrs()` — backfill `token0_addr`/`token1_addr`, WETH native alias
- `build_mirror_token_details()` — per-token `dex_a`/`dex_b`/`pool_a`/`pool_b`/`quote_status` in acceptance
- V3 multi-fee-tier smoke + on-chain liquidity fallback; V4 quoter + StateView liquidity fallback
- `m8_mirror_quote_smoke.py --force-retry` (scoped retry on failed legs only; avoid full-route blast)
- Acceptance report top-level `mirror_tokens` + metrics

## Out of Scope for M8.2

- `cycles_quoteable`, `qsr_econ`, `cycles_positive_gross` — evaluated only in `m9_lane_acceptance_report.py`
- M9 shadow/economics: **NOT_EVALUATED** until `mirror_quote_ready_tokens > 0` and `handoff_ready=true`

## Canonical Docs

- `Roadmap.md`
- `scripts/m8_2_acceptance_report.py`
- `scripts/m8_mirror_quote_smoke.py`
- `data/runs/_rolling/m8_cross_dex_expansion_latest.json`
- `data/runs/_rolling/m8_external_pool_hints_latest.json`
