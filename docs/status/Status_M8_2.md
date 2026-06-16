# Status: M8.2 Cross-DEX Expansion & Graph Handoff

**Status**: **M8_2_GRAPH_HANDOFF_REACHED / M8_2_RADAR_LAYER_CODE_READY / M8_2_ECONOMICS_OUT_OF_SCOPE / external_hints_expansion_freshness=REFRESHED**

`truth_boundary`: **ONCHAIN_VERIFY_REQUIRED** (external aggregators are hint-only; never canonical without verify)

**Radar rollout policy (runtime verification):**

```text
- Radar layer is hint-only; never canonical truth without on-chain verify.
- DexScreener is primary wide radar (token-pairs ~300 req/min); fast sweep via --radar-fast / pipeline-mode radar_fast.
- Two-phase default: radar_fast (verify none) → verify_subset (specialized on-chain) → secondary GeckoTerminal/TheGraph → CoinGecko fallback only.
- GeckoTerminal / TheGraph: secondary/audit lanes for tokens DexScreener missed or weak; not default full-scan blockers.
- CoinGecko Onchain: fallback/canary only (10k credits/month budget); not full-refresh default.
- Full multi-provider baseline: audit_nightly only, not every working cycle.
- Route liveness (0x/1inch/Uniswap): disabled via --skip-route-liveness unless keys configured.
- Admission gate: delta_onchain_verified > 0 in m8_radar_expansion_ab.py before selective CG rollout.
- Full M8.2 expansion only after hint refresh with freshness_order_ok=true.
- M9 shadow only when M8.2 handoff_ready=true (not because radar saw a pool).
```

Operational contract: [M8_2_RADAR_REFRESH_PIPELINE.md](../m8/M8_2_RADAR_REFRESH_PIPELINE.md)

`goal_status`: **REACHED** (handoff lane; quality blockers soft when `handoff_ready=true`)  
`handoff_ready`: **true**  
`handoff_lane`: **mirror_2leg**  
`execution_enabled`: false  
`kill_switch_active`: true

## Handoff vs economics (precise wording)

```text
M8.2 handoff readiness:     REACHED
M8.2 economics/quote:       out of scope (M9 owns quote/sizing)
M9 economics:               NOT_PROVEN
```

M8.2 fulfilled its role: found token-neighborhood topology and passed a connected graph universe to M9. It did **not** prove 2-leg mirror quote-ready or profit.

## DexScreener-first two-phase runtime evidence (2026-06-16)

```text
pipeline: m8_radar_two_phase_refresh.py --max-tokens 753 --skip-coingecko
phase1_radar_fast_duration_s: 256
phase2_verify_subset_duration_s: 20
radar_fast_tokens: 753
radar_candidates: 299
verify_subset_size: 32
verified_yield: 37
per_source_verified_yield: dexscreener=37
fetch_async: true
use_multicall: true (verify phase)
ws_head_block: pinned (47404660)
hints_generated_at_utc: 2026-06-16T08:31:24Z
expansion_generated_at_utc: 2026-06-16T08:51:03Z
EXPANSION_FRESHNESS_ORDER_VIOLATION: cleared
acceptance_goal_status: REACHED
handoff_ready: true
handoff_lane: mirror_2leg
acceptance_blockers: SUBGRAPH_READY_LOW, VERIFIED_SECOND_POOL_LOW (soft)
verified_second_pool_count: 5 (was 4)
multi_venue_tokens: 16 (was 14)
second_pool_hints_found: 1
```

## External hints freshness (2026-06-16)

```text
external_hints_expansion_freshness: REFRESHED
hints: 753 tokens (2026-06-16T08:31:24Z)
expansion: 676 routes / 362 tokens (2026-06-16T08:51:03Z)
hint_tokens_matched: 421
graph_topology_ready_tokens: 5
mirror_quote_ready_tokens: 3
handoff_lane: mirror_2leg
acceptance_blockers: SUBGRAPH_READY_LOW, VERIFIED_SECOND_POOL_LOW (soft)
```

## M8.2 Radar / Hint Layer (audit 2026-06-15)

Architecture boundary (do **not** replace M8 sniper with aggregators):

```text
M8 sniper          = on-chain first-seen truth
M8.1               = anchor/metadata/quote-probe context
M8.2 Radar         = external aggregators, hint-only
M8.2 Verify/Expansion = on-chain truth + graph handoff
M9                 = quote/depth/sizing/economics truth
```

Current hint artifact (`m8_external_pool_hints_latest.json`, `2026-06-16T08:31:24Z`):

```text
pipeline_mode: dexscreener_first_two_phase
per_source_verified_yield: dexscreener=37
verified_yield: 37
radar_candidates: 299
verify_subset_size: 32
```

Acceptance (`m8_2_acceptance_report_latest.json`): `goal_status=REACHED`, `handoff_ready=true`, `handoff_lane=mirror_2leg`; verified second pools from `active_factory_scan=4`, not external providers. Radar helps recall/coverage but weakly converts to bridge-grade evidence.

Wired today: `dexscreener_hints`, `geckoterminal_hints`, `graph_hints`, `thegraph_token_api_hints`, `coingecko_onchain_hints`, `defillama_dex_priority`, `external_route_liveness`, `pool_hints` verify pipeline, and DexScreener-first two-phase refresh. Stubs remain in `radar_providers` for CMC/DexPaprika/Moralis/Codex. CoinGecko Onchain is fallback/canary only; DeFiLlama is scan weights only; 0x/1inch/Uniswap are liveness benchmark only and not admission.

Implemented radar contract:

```text
m8_radar_pool_candidates_latest.json  — raw external candidates, no canonical claims
per-token radar_reason              — token_pair_seen | new_pool_seen | liquidity_seen
acceptance funnel split             — radar_seen → onchain_verified → bridge_eligible → m9_handoff
A/B gate                            — scripts/m8_radar_expansion_ab.py
default operator path                — scripts/m8_radar_two_phase_refresh.py
```

Implemented (code, 2026-06-15):

```text
m8/discovery/radar_layer.py           — contract + funnel + candidates artifact
m8/discovery/coingecko_onchain_hints.py
m8/discovery/defillama_dex_priority.py  — scan weights only
m8/discovery/external_route_liveness.py — 0x/1inch/Uniswap probes, no admission
scripts/m8_external_pool_hint_refresh.py — writes radar + hints; checkpoint/timeout flags
scripts/m8_radar_expansion_ab.py
scripts/m8_radar_two_phase_refresh.py    — DexScreener-first radar_fast → verify_subset → secondary/fallback
m8_2_acceptance_report.radar_funnel   — radar_seen / onchain_verified / bridge_eligible / m9_handoff
```

## Verified metrics (acceptance 2026-06-15)

| Metric | Value |
|--------|------:|
| `graph_topology_ready_tokens` | **5** |
| `connector_graph_ready_tokens` | **2** |
| `token_presence_graph_ready_tokens` | **1** |
| `cross_anchor_ready_tokens` | **3** |
| `mirror_quote_ready_tokens` | **3** |
| `mirror_topology_ready_tokens` | **7** |
| `economics_claim` | **false** |
| `requires_m9_quote` | **true** |

Artifact: `data/tmp/m8_2_acceptance_report_latest.json`  
Expansion: `data/runs/_rolling/m8_cross_dex_expansion_latest.json`

## Handoff route contract

All routes in graph-topology universe carry:

```text
requires_quote_validation = true
economics_claim           = false
handoff_lane              = graph_topology
```

Bridge (`--graph-handoff-only --no-registry`): **285** active routes, `graph_handoff_cycle_potential_routes=288`, `handoff_lane=graph_topology`.

Topology diagnostic: `scripts/m9_graph_topology_diagnostic.py` → `cycles_found_topology=28` (discovery lane, mostly 2-leg).

## Lanes

| Lane | Status |
|------|--------|
| `same_pair_mirror` (2-leg quote) | topology 2, quote-ready **0** |
| `graph_topology` (3/4-leg handoff) | **2 tokens ready** |
| `cross_anchor_mirror` | **0** (next expansion target) |
| `connector_graph` | **2** (primary useful signal) |

## Next owner

**M9 quote validation** — not production economics claim.

```powershell
py -3.11 scripts/m9_bridge_build.py --graph-handoff-only --no-registry --output data/tmp/m9_bridge_inventory_graph_handoff_latest.json
py -3.11 scripts/m9_lane_acceptance_report.py --m8-2-report data/tmp/m8_2_acceptance_report_latest.json
```

## Out of scope

- `cycles_positive_gross`, `qsr_econ` — M9 only after quote validation
- Do **not** label `M8_2_PROFIT_READY` or `QUALITY_REACHED` while `mirror_quote_ready_tokens=0` unless graph handoff also false
