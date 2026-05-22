# Status: M9 Graph-Arb Long-Tail Shadow Scanner

**Status**: IMPLEMENTATION_PARTIAL_SOAK2_COMPLETE_PROVIDER_QUALITY_BLOCKED

`goal_status`: IN_PROGRESS
`schema_family`: m9_graph_arb
`schema_revision`: m9.1
`execution_enabled`: false
`kill_switch_active`: true
`execution_mode`: paper

## Last Artifact (2026-05-22T14:48:32Z — 15-min soak2, 6 sweeps)

`artifact_path`: data/runs/_rolling/m9_graph_latest.json
`run_timestamp`: 2026-05-22T14:32:05Z
`generated_at_utc`: 2026-05-22T14:48:32Z
`cycles_found`: 1200
`cycles_positive_gross`: 0
`cycles_quoteable`: 0
`best_cycle_net_bps`: 0
`qsr`: 0.0
`sweeps_completed`: 6
`elapsed_s`: 987.3
`duration_fulfilled`: true
`gate_acceptance`: false
`strategy_gate_acceptance`: false
`economics_gate_status`: BLOCKED_QSR
`economics_blocker_class`: PROVIDER_QUALITY_BLOCKED
`topology_gate`: CYCLES_FOUND
`scan_scope`: {routes_total: 13, edge_count: 102}
`cycle_reject_histogram`: {CYCLE_QUOTE_FAILED: 1200}
`provider_rpc_error_count`: 702  (58.5%)
`provider_decode_error_count`: 498  (41.5%)

## Phase Status

`schema_parity_status`: FIXED (m9.1 canonical fields: generated_at_utc, freshness_s, graph_topology, run_context, topology_gate, strategy_gate_acceptance, cycle_reject_histogram, route_error_histogram, edge_error_histogram, scan_scope)
`dry_run_bug_status`: FIXED (cycles_found_topology param added; dry-run no longer writes cycles_found=0)
`graph_build_status`: OPERATIONAL (1100 cycles found from inventory)
`cycle_finder_status`: OPERATIONAL
`quoter_status`: PROVIDER_QUALITY_BLOCKED (qsr=0.0; 10-min soak 5×200 cycles — 100% CYCLE_QUOTE_FAILED; mainnet.base.org 429 rate-limit + eth_call→'0x')
`runner_deadline_status`: FIXED (runner.py now uses deadline-aware while loop; --max-cycles-per-sweep limits batch size; partial artifact written after every sweep)
`intent_tier_baseline_status`: FIXED (CALIBRATION_TIER_BASELINE bumped 64→77 per M9 Base expansion)
`top_opportunities_status`: IMPLEMENTED (artifacts.py _build_top_opportunity(); fields: dex/factory/pool/pool_path/pair/market_size_usd/dynamic_size_usd/spread_bps/spread_usd/profit_usd/main_blocker)
`dashboard_m9_status`: IMPLEMENTED (monitoring/dashboard_m9.html + /api/m9/current endpoint; / route now serves M9 operator surface; M7/M8 at legacy /m7 and /m8 routes)
`economics_gate_status`: BLOCKED_QSR (qsr=0.0; economics_blocker_class=PROVIDER_QUALITY_BLOCKED)
`funnel_a_counters_status`: IMPLEMENTED (raw_hints, pairs_probed, dexes_probed, verified_tokens, verified_pools, active_routes, graph_ready_edges_proxy — extracted from inventory by extract_inventory_stats())
`inventory_reject_taxonomy_status`: IMPLEMENTED (missing_pool, bad_liquidity, stale_quote, quarantine_other, rpc_error, unknown_token, missing_pool_address — auto-classified from pools list)
`inventory_adapter_status`: IMPLEMENTED (best_inventory_path() picks shadow inventory with gap edges if available, else m8_1 exotic fallback; runner --inventory default=None fixed so shadow is auto-selected)
`default_wiring_status`: FIXED (runner --inventory default was "m8_1_exotic_inventory_latest.json"; changed to None so best_inventory_path() resolves to shadow with edge_count=102)
`router_sim_status`: NOT_STARTED (requires cycles_positive_gross > 0)
`execution_status`: BLOCKED (kill_switch_active=true)

## Soak Evidence — Soak2 (2026-05-22 15-min soak)

Soak params: `--duration-minutes 15.0 --max-cycles-per-sweep 200 --verbose`
Sweep timeline:
- Sweep 1: 14:32:05Z → 14:34:23Z (~138s), 200 cycles, qsr=0.0
- Sweep 2: 14:34:23Z → 14:36:49Z (~146s), 400 total, qsr=0.0
- Sweep 3: 14:36:49Z → 14:40:03Z (~194s), 600 total, qsr=0.0
- Sweep 4: 14:40:03Z → 14:42:56Z (~173s), 800 total, qsr=0.0
- Sweep 5: 14:42:56Z → 14:45:49Z (~172s), 1000 total, qsr=0.0
- Sweep 6: 14:45:49Z → 14:48:32Z (~163s), 1200 total, qsr=0.0
Total elapsed: 987.3s (16m27s). Sweep 6 started 76s before deadline and ran to completion.
duration_fulfilled=true. exit_code=1 (unhandled exception in cleanup; soak data valid).

Root cause: `mainnet.base.org` public RPC rate-limits (HTTP 429) after ~200 concurrent
requests (QUOTE_RPC_ERROR: 702/1200 = 58.5%); remaining 41.5% return `eth_call→'0x'`
(QUOTE_DECODE: 498/1200) — empty quoter data for stable/near-peg paths.
All 1200 cycles classified `CYCLE_QUOTE_FAILED`. blocker_class = PROVIDER_QUALITY_BLOCKED.
DECODE share grew +8pp (33.5%→41.5%) from soak1→soak2 — possible thin-tick-range signal.
Topology health confirmed: CYCLES_FOUND, 1200 cycles from 8-token graph, 13 routes, edge_count=102.
Top opportunity topology: USDC/WETH/EURC (uniswap_v3 + pancakeswap_v3 + aerodrome_slipstream).
Dashboard: operational at port 8099, /api/m9/current serving live rolling artifact.

Unblock path: replace `mainnet.base.org` with premium RPC endpoint (dRPC/Alchemy/QuickNode
free tier) to eliminate HTTP 429 rate limiting. This will unblock quote resolution and
allow economics gate to evaluate real gross_bps data.

## Soak Evidence — Soak1 (2026-05-22 10-min soak, archived)

Soak params: `--duration-minutes 10.0 --max-cycles-per-sweep 200 --verbose`
Sweep timeline: 5 sweeps, 1000 cycles, elapsed=663.5s
QUOTE_RPC_ERROR: 665/1000 = 66.5%; QUOTE_DECODE: 335/1000 = 33.5%
generated_at_utc: 2026-05-22T14:04:39Z (superseded by soak2)

## Blockers

1. `economics_gate` PROVIDER_QUALITY_BLOCKED — 100% of cycles fail quoting due to:
   - HTTP 429 rate limits from `mainnet.base.org` (66.5% of failures = QUOTE_RPC_ERROR)
   - Empty quoter responses `eth_call→'0x'` (33.5% of failures = QUOTE_DECODE)
   - `qsr=0.0` (quote success rate), `cycles_quoteable=0` in 10-min soak (5 sweeps, 1000 cycles)
   - **Unblock**: configure premium RPC endpoint (dRPC/Alchemy) in place of `mainnet.base.org`
2. `router_sim` NOT_STARTED — requires `cycles_positive_gross > 0`.
3. `execution_enabled` BLOCKED — kill_switch_active=true; no live trades.

## Resolved Blockers (this session)

- `runner_deadline` RESOLVED — `_run()` now uses `deadline = started_at + duration_minutes * 60` with `while time.monotonic() < deadline:` loop; `--max-cycles-per-sweep` (default 200) limits batch per sweep; partial artifact written after each sweep.
- `intent_tier_baseline` RESOLVED — `CALIBRATION_TIER_BASELINE` bumped 64→77 in `scripts/check_repo_safety.py`; `test_exceeds_limits_fails` test updated.
- `top_opportunities` RESOLVED — `_build_top_opportunity()` added to `artifacts.py`; `build_artifact()` emits `top_opportunities` list.
- `dashboard_m9` RESOLVED — `monitoring/dashboard_m9.html` created; `/api/m9/current` endpoint added to `dashboard_server.py`; default `/` route now serves M9 operator surface.
- `schema_parity` RESOLVED — `build_artifact()` now produces all 24+ canonical m9.1 fields.
- `dry_run_bug` RESOLVED — `cycles_found_topology` param prevents cycles_found=0 in dry-run artifacts.
- `execution_mode` RESOLVED — unified to `"paper"` (was `"shadow"`).
- `funnel_a_counters` RESOLVED — `extract_inventory_stats()` in builder.py extracts raw_hints, pairs_probed, dexes_probed, verified_tokens, verified_pools, active_routes, graph_ready_edges_proxy.
- `inventory_reject_taxonomy` RESOLVED — pools list auto-classified into missing_pool, bad_liquidity per quarantine_reason.
- `inventory_adapter` RESOLVED — `best_inventory_path()` selects shadow inventory with gap edges when available.
- `default_wiring` RESOLVED — runner `--inventory` default changed from hardcoded m8_1 path to `None`; now auto-selects shadow inventory (edge_count=102, active_routes=51) via `best_inventory_path(preferred=None)`.
- `m8_m9_wiring_test` RESOLVED — `tests/unit/test_m9_graph_builder.py` added (11 tests); `test_runner_default_none_reaches_shadow` locks the contract.

## Scope

M9 is a shadow scanner that discovers multi-hop arbitrage cycles (length 3–4) in the token exchange graph built from M8.1 stable-anchor inventory. It operates in paper mode only (`execution_mode=paper`) and writes a rolling artifact for monitoring. Execution gates must reach PASS before any live trade is enabled.

## Gates Required for PASS

1. `cycles_positive_gross >= 1`
2. `qsr >= 0.85`
3. `economics_gate_status == PASS`
4. `router_sim_gate == PASS` (not yet reached)

## Canonical Docs

- `Roadmap.md`
- `docs/m9/M9_GRAPH_LONG_TAIL_SHADOW.md`
- `data/runs/_rolling/m9_graph_latest.json`
