# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-08T22:25:00Z
run_id: e1_69_waves_b_c_d_complete_e_running
mode: HYBRID (Waves B/C/D offline-validated; Wave E online soak running)
artifact_mode: rolling
config: base / production + discovery / real_minimal.yaml
code_identity:
  primary: ts:2026-05-08T22:25:00Z
  desc: E1.69 Waves B/C/D complete (multi-hop intent + route graph + QuoterV2 multi-hop encoding + TVL scout + Flashblocks bridge surfacing). Wave E 1h online soak in progress.

## 1) Scope
goal: E1.69 Waves B + C + D complete; Wave E (1h online soak) running. User directive (May 8 2026): "robi vsi iteratsii" - executor authorized to bypass small-batch discipline to complete all 10 GPT routing-strategy steps in a single push. Previous: E1.69 Wave A WAVE_A_COMPLETE (depth_curve persistence + production-first ranking + dedup + production_sized counters); E1.68 SOAK_COMPLETE (frontier roundtrip PnL math fix).

## 2) Findings
- Multi-hop production routes were absent: cbETH/USDC, wstETH/USDC, BRETT/USDC etc. all rely on direct dust pools when their canonical depth lives in the WETH-bridged 2-hop path (Aerodrome CL + Uniswap V3 50M+ TVL).
- Route enumeration was not centralised: cold lane and hot lane each had ad-hoc 1-hop logic; no shared graph means no triangulation, no bridge-token amplification.
- QuoterV2 calldata only encoded single-hop; multi-hop paths require the dynamic `quoteExactInput(bytes path, uint256 amountIn)` ABI and were not callable from this codebase.
- TVL-driven discovery did not exist: the scanner relied entirely on event-driven hot lane + intent universe, with no path to surface "deep production-size pools we never see swap traffic from".
- Flashblocks HTTP lane existed but was not surfaced in rolling artifacts; reviewers had to introspect process state to verify it was running.

## 3) Changes (E1.69 Waves B + C + D)

### Wave B - multi-hop intent (Step 4)
- `discovery/intent_loader.py`:
  - New `IntentRoute(NamedTuple)` with `chain` + `tokens: tuple` and `hops` / `canonical_key` properties (direction-sensitive).
  - New `parse_intent_route_line()` accepting 3-token (2-hop) and 4-token (3-hop) lines.
  - `IntentUniverse` extended with `_routes`, `add_route()`, `get_routes_for_chain()`, `get_all_routes()`.
  - `load_intent()` loop now dispatches: 2-token line -> IntentPair; 3+ token line -> IntentRoute.
- `config/intent.txt`: 9 production multi-hop routes added on Base (cbETH/WETH/USDC, wstETH/WETH/USDC, BRETT/WETH/USDC, DEGEN/WETH/USDC, TOSHI/WETH/USDC, VIRTUAL/WETH/USDC, BRETT/AERO/USDC, DEGEN/AERO/USDC, cbBTC/WETH/USDC).
- Backward-compatible: existing IntentPair consumers (~20 import sites) untouched.

### Wave C - route graph + QuoterV2 multi-hop (Steps 3 + 5)
- New module `m7/routing/route_graph.py`:
  - `PoolEdge` dataclass (address, token0, token1, dex, fee_bps, tvl_usd).
  - `RoutePath` dataclass with `bottleneck_tvl_usd` property.
  - `build_adjacency()`, `enumerate_paths()` (1-3 hops, bridge whitelist gates intermediates), `rank_paths()` (production-tier first, bottleneck TVL desc, hops asc), `select_production_paths()`.
  - Pure logic, fully unit-tested; consumers will plug in their own pool list (cold lane or scout output).
- `dex/adapters/uniswap_v3.py`:
  - Selector + `encode_v3_path(tokens, fees)` for V3 path encoding (token | fee | token | fee | token).
  - `encode_quote_exact_input(tokens, fees, amount_in)` with proper dynamic-bytes ABI layout (head offset 0x40 + amountIn + length + padded path).
  - `decode_quote_exact_input_response()` extracting `amountOut` from the multi-hop response head.

### Wave D - TVL scout + Flashblocks surfacing (Steps 2 + 9)
- New package `m7/scouts/` with `tvl_scout.py`:
  - `PoolTVLEntry` dataclass with `production_grade` flag (>=$50k TVL).
  - `parse_defillama_pools()` fail-soft parser of DefiLlama yields response, chain-filtered.
  - `rank_pools_by_tvl()`, `select_production_pools()` with project whitelist (uniswap-v3/v4, aerodrome-v1/slipstream, sushiswap, pancake-v3) + top_n cap.
  - `fetch_defillama_pools()` opt-in via `ARBY_TVL_SCOUT_ENABLE=1`; httpx-based; returns [] on any error.
- `m7/orderflow/bridge_runtime.py`:
  - `candidate_source_breakdown` now exposes `flashblocks_http_enabled`, `flashblocks_http_calls_ok`, `flashblocks_http_logs_total`, and `tvl_scout_enabled` so reviewers can audit lane state from the rolling artifact alone.

### Tests
- `tests/unit/test_e1_69_wave_b.py`: 9 tests (parser, universe loading, direction sensitivity, backward compat).
- `tests/unit/test_e1_69_wave_c.py`: 15 tests (adjacency, path enumeration, ranking tiers, bridge whitelist, no-cycle / no-pool-revisit, V3 path encode/decode, calldata layout).
- `tests/unit/test_e1_69_wave_d.py`: 9 tests (production_grade threshold, DefiLlama parser, project whitelist, top_n cap, fail-soft fetcher, bridge surfacing).

## 4) Validation
```
pytest tests/unit/test_e1_69_wave_b.py -v       :  9 passed (0.18s)
pytest tests/unit/test_e1_69_wave_c.py -v       : 15 passed (0.38s)
pytest tests/unit/test_e1_69_wave_d.py -v       :  9 passed (0.29s)
pytest tests/unit -q                            : 4904 passed, 6 skipped, 1 warning (156s)
                                                  (+39 over Wave A baseline 4865)
scripts/check_repo_safety.py --allow-intent-edit: PASS (0 warnings)
```

## 5) Wave E - online soak (running)
Started 2026-05-08T20:22:50Z, 1.0h runtime, dashboard 8099. Env:
```
ARBY_SIZE_FRONTIER_USD=0.5,1,2,5,10,25,50,100,250,500,1000
ARBY_SPLIT_ROUTE_ENABLE=1
ARBY_REQUIRE_USD_BASIS=1
ARBY_COLD_REQUIRE_USD_BASIS=1
ARBY_MIN_EXPECTED_PROFIT_USD=0.01
ARBY_COLD_IMMEDIATE_SIM=1
ARBY_COLD_IMMEDIATE_NEAR=1
ARBY_POOL_STATE_HTTP_FEED=1
ARBY_PAPER_SIGNING=1
ARBY_ACTIVE_WS_LANES=2
ARBY_MIN_EXECUTABLE_SIZE_USD=10.0
ARBY_MIN_PRODUCTION_SIZE_USD=50.0
ARBY_FLASHBLOCKS_HTTP_LANE=1
```
Initial health probe (+30s): dashboard UP, ws_connected=5/507, opp_total=0 (pre-cold-cycle).
Monitor terminal logging to `data/tmp/soak_e169_monitor.log` every 5 minutes.

## 6) Honest Limits
- **Wave C is wired but not yet invoked**: `m7/routing/route_graph` exists with full unit-test coverage, but the cold lane scorer does not yet *call* `select_production_paths()`. Integration is the next iteration; Wave C provides the building block + contract.
- **Wave D scout is opt-in**: `fetch_defillama_pools()` only runs with `ARBY_TVL_SCOUT_ENABLE=1`, NOT set in the Wave E soak. The bridge surfacing flag (`tvl_scout_enabled`) will read `false`. Enabling the actual fetch loop requires a separate scheduler hook in `start_nonstop_runtime.py` - deferred.
- **QuoterV2 multi-hop encode is offline-validated only**: calldata layout matches Uniswap V3 spec but no on-chain `eth_call` round-trip executed. Wave E soak does NOT exercise multi-hop quoting yet (scoring still single-hop).
- **Multi-hop intent loaded but not routed**: cold/hot lanes ingest IntentPair, not IntentRoute. Routes will sit in `IntentUniverse._routes` until a downstream consumer is wired.
- This is consistent with the user's "all 10 steps in one session" directive: Waves B/C/D establish primitives + contracts; integration + measurement come from Wave E + follow-up sessions.

## Session Completion
session_goal: E1.69 Waves B/C/D - 6 of remaining 6 GPT directive steps (4, 3, 5, 2, 9 + Step 10 soak running)
goal_status: WAVES_BCD_COMPLETE_E_RUNNING
close_allowed: true (after soak completes; report to be regenerated then)
blocker_status_after: PARTIAL_PROGRESS (primitives shipped; integration into hot/cold scorers + scout scheduler is the next iteration)
remaining_blockers: route_graph integration into cold lane scorer; tvl_scout periodic invocation in supervisor; QuoterV2 multi-hop wired to scoring_parallel; Wave E completion + post-soak audit
docs_reread_confirmed: true
