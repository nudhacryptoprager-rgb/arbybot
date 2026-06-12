# Status: M8.2 Cross-DEX Expansion & Mirror Handoff

**Status**: **M8_2_CANDIDATE_COVERAGE_PROVEN / M8_2_QUALITY_BLOCKED** (subgraph gate only; independent of M9 economics)

**Scan methodology (confirmed):**
- Token-first expansion: **CONFIRMED** (`expand_token_neighborhood` per registry token).
- Canonical + P0 candidate DEX in `dex_ids_checked`: **CONFIRMED** (17 DEX incl. `alien_base_v2`, `alien_area51`, `quickswap_algebra`, `iziswap_base`).
- Full per-token × dex × anchor scan coverage: **PROVEN** (`active_scan_coverage_rate=1.0`, `missing_dexes=[]`, `m8_2_scan_coverage_report` blockers=[]).
- Candidate matrix coverage: **PROVEN** (`candidate_dex_attempt_matrix` tokens=701, `candidate_scan_coverage_rate=1.0`, `candidate_coverage` blockers=[]).

`goal_status`: BLOCKED (`SUBGRAPH_READY_LOW` only)
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

| Gate | Threshold | Current (2026-06-11 fresh expansion) |
|------|-----------|----------------------------------------:|
| `active_scan_coverage_rate` | ≥ 0.98 | **1.0** |
| `candidate_scan_coverage_rate` | ≥ 0.98 | **1.0** |
| `scan_attempt_matrix` tokens | > 0 | **701** |
| `candidate_dex_attempt_matrix` tokens | > 0 | **701** |
| `scan_actual_attempts` | — | **55155** |
| `candidate_scan_actual_attempts` | — | **31545** |
| `missing_dexes` | [] | **[]** |
| `subgraph_ready_tokens` | ≥ 3 | **1** |
| `verified_second_pool_count` | ≥ 10 | **13** |
| `multi_venue_tokens` | ≥ 14 | **22** |
| `connector_routes_count` | > 0 | **67** |
| `active_factory_second_pool_count` | — | **9** |
| Freshness order | sniper ≤ hints ≤ expansion | **PASS** |

`m8_2_scan_coverage_report` blockers: **[]** (canonical coverage PROVEN).  
`m8_2_acceptance_report` blockers: **`SUBGRAPH_READY_LOW` only** (quality subgraph gate; `VERIFIED_SECOND_POOL_LOW` and `MULTI_VENUE_TOKENS_LOW` cleared).

**Honest mirror verdict:** expanded universe (17 canonical DEX + 5 unsupported candidate lanes) still shows dominant `NO_POOL` on factory scan; `active_factory_second_pool_count=9` from batch multicall path. P0 configured candidates deduplicated via `covered_by_canonical_scan` where already in canonical `dex_rows`.

## Scan performance (fresh evidence)

| Mode | Runtime (701 tokens) | Notes |
|------|---------------------:|-------|
| Serial `audit_full` (prior) | ~31m | 13 DEX, no candidate matrix |
| `candidate_summary` + Multicall batch | **~18m** | 17 DEX, full matrices, neg-cache |

`M8_2_SCAN_PERFORMANCE_OPTIMIZED`: **REACHED** for `candidate_summary` mode (Multicall3 factory batch + candidate dedup + progress artifact). `audit_full` retained for regression.

Progress artifact: `data/tmp/m8_cross_dex_expand_progress.json`  
CLI: `--scan-mode candidate_summary` (default), `--scan-mode audit_full`, `--scan-mode hot_path_incremental`

## Last Expansion Artifact

`artifact_path`: data/runs/_rolling/m8_cross_dex_expansion_latest.json  
`generated_at_utc`: 2026-06-11T22:19:31Z  
`scan_mode`: candidate_summary  
`routes_admitted_count`: 1033  
`m8_tokens_in`: 701  
`hint_tokens_matched`: 782  
`external_hints_enabled`: true  
`hints_generated_at_utc`: 2026-06-11T20:27:09Z (fresh hint refresh)  
`candidate_dexes_seen`: 9  
`candidate_dexes_configured`: 4  
`unsupported_candidate_dexes`: alien_base_v3, quickswap_v2, hydrex, pancake_infinity, balancer_v3  
`batch_resolver_stats`: multicall_chunks=696, calls=65535, pools_found=18

## Provenance split (expansion routes)

| Origin | Count |
|--------|------:|
| `m8_watchlist_hint` | 782 |
| `exploration` | 251 |
| `canonical_routes_count` | 782 |
| `routes_rejected_not_m8_derived` | 251 |

## Hint quality (fresh hint refresh)

| Status | Count (approx) |
|--------|---------------:|
| `HINT_STALE` | 866 |
| Verified eligible | 165 |
| `truth_status` | STALE_HINT_RISK |

Radar stubs (`coinmarketcap_dex`, `dexpaprika`, `moralis`, `codex_defined`): **NOT_CONFIGURED** in report (`radar_provider_status`).

## M8.2 Blockers (not M9)

- `SUBGRAPH_READY_LOW` (**active**)
- ~~`VERIFIED_SECOND_POOL_LOW`~~ (cleared: 13 ≥ 10)
- ~~`MULTI_VENUE_TOKENS_LOW`~~ (cleared: 22 ≥ 14)
- ~~`CANDIDATE_DEX_COVERAGE_INCOMPLETE`~~ (cleared)

## M8.2 Quality Improvements (code)

- **Scan modes**: `audit_full`, `candidate_summary` (default), `hot_path_incremental`
- **Multicall3 factory batch** (`m8/discovery/scan_batch.py`) for V2/V3/Algebra/iZiSwap/ve33 reads
- **Candidate dedup**: `covered_by_canonical_scan` — no double RPC for P0 DEX already in canonical `dex_rows`
- **Negative-result cache** with TTL across tokens in one expansion run
- **Progress artifact** for foreground operator visibility
- **Candidate coverage audit v2**: rate ≥ 0.98 + unsupported `UNSUPPORTED_*` matrix + anchor histograms

## Coverage Expansion Plan

Purpose: increase the chance of detecting `1->2` venue transitions for M8-sniped
tokens without weakening M8-rooted provenance or on-chain truth gates.

| Priority | Target | Role | Admission rule |
|----------|--------|------|----------------|
| P0 | Alien Base V2 / Area51 / V3, QuickSwap V2 / Algebra, iZiSwap Base | Candidate configured DEX coverage | Config + matrix + on-chain verify; V3/V2 hint-only until factory proof |
| P1 | Hydrex, Pancake Infinity, Balancer V3 | Distinct-pricing / emerging venue research | Hint/R&D; matrix `UNSUPPORTED_*` only |
| Radar | DexScreener, GeckoTerminal, CMC, DexPaprika, Moralis, Codex | Non-RPC mirror discovery | Hint-only; stubs NOT_CONFIGURED until API wiring |

Required report fields (present in fresh acceptance report):

- `candidate_dexes_seen`, `candidate_dexes_configured`, `unsupported_candidate_dexes`
- `mirror_source_yield_by_provider`, `api_hint_to_onchain_verified_rate`, `stale_hint_rate`
- `truth_status`, `candidate_scan_attempted_by_anchor`

## Out of Scope for M8.2

- `cycles_quoteable`, `qsr_econ`, `cycles_positive_gross` — evaluated only in `m9_lane_acceptance_report.py`
- Bridge `graph_ready_from_expansion` proves handoff volume, not M8.2 quality REACHED
- M9 shadow/economics: **NOT_EVALUATED** until `m8_2_acceptance_report --strict` PASS (blocked on subgraph)

## Canonical Docs

- `Roadmap.md`
- `scripts/m8_2_acceptance_report.py`
- `data/runs/_rolling/m8_cross_dex_expansion_latest.json`
- `data/runs/_rolling/m8_external_pool_hints_latest.json`
