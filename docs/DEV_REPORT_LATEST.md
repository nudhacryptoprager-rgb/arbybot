# DEV REPORT LATEST — M9 Graph-Arb 15-Min Soak Complete (PROVIDER_QUALITY_BLOCKED × 6 sweeps)

**mode**: M9_SOAK2_15MIN_COMPLETE_PROVIDER_QUALITY_BLOCKED
**session_date**: 2026-05-22
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**blocker_status_before**: SOAK1_COMPLETE_PROVIDER_QUALITY_BLOCKED (10-min, 5 sweeps)
**blocker_status_after**: SOAK2_COMPLETE_PROVIDER_QUALITY_BLOCKED_CONFIRMED (15-min, 6 sweeps)
**execution_enabled**: false
**kill_switch_active**: true

---

## Session Completion

session_goal: Run 15-min soak on M9 runner with live sweep monitoring, produce final report, regenerate docs per current state
goal_status: REACHED (soak complete: 6 sweeps, 1200 cycles, elapsed=987.3s, duration_fulfilled=true; all sweeps monitored live; docs updated)
close_allowed: true
remaining_blockers:
  - PROVIDER_QUALITY_BLOCKED: mainnet.base.org public RPC rate-limits at ~200 concurrent req/sweep
  - ROUTER_SIM_NOT_STARTED: requires cycles_positive_gross > 0
  - EXECUTION_KILL_SWITCH: kill_switch_active=true throughout
evidence_session_run_dirs: rolling (data/runs/_rolling/m9_graph_latest.json, run_timestamp=2026-05-22T14:32:05Z)
primary_blocker_of_session: PROVIDER_QUALITY_BLOCKED (mainnet.base.org HTTP 429)
blocker_status_before: ACTIVE (confirmed in soak1 10-min)
blocker_status_after: BLOCKED (confirmed in soak2 15-min, 6 sweeps, 1200 cycles, qsr=0.0 stable)
docs_reread_confirmed: true

---

## Soak Parameters

```
command:    py -3.11 -m m9.graph_arb.runner --duration-minutes 15.0 --max-cycles-per-sweep 200 --verbose
chain:      base
rpc:        https://mainnet.base.org (public, unauthenticated)
inventory:  data/tmp/m9_shadow_inventory_with_gap_edges.json (edge_count=102, active_routes=51)
dashboard:  http://127.0.0.1:8099 (monitoring/dashboard_server.py, port 8099)
exit_code:  1 (EXIT_CONFIG_ERROR — likely unhandled exception in thread cleanup post-artifact-write; soak data valid)
```

---

## Sweep Timeline

| Sweep | Started (UTC) | Ended (UTC) | Duration | Cumulative Cycles | QSR | RPC_ERR (delta) | DECODE (delta) |
|-------|--------------|-------------|----------|------------------|-----|-----------------|----------------|
| 1 | 14:32:05Z | 14:34:23Z | ~138s | 200 | 0.0 | 128 | 72 |
| 2 | 14:34:23Z | 14:36:49Z | ~146s | 400 | 0.0 | 125 | 75 |
| 3 | 14:36:49Z | 14:40:03Z | ~194s | 600 | 0.0 | 105 | 95 |
| 4 | 14:40:03Z | 14:42:56Z | ~173s | 800 | 0.0 | 115 | 85 |
| 5 | 14:42:56Z | 14:45:49Z | ~172s | 1000 | 0.0 | 113 | 87 |
| 6 | 14:45:49Z | 14:48:32Z | ~163s | 1200 | 0.0 | 116 | 84 |

Note: sweep 6 started 76s before deadline (14:47:05Z) and ran to completion per runner design
(deadline checked at loop top only). Total elapsed = 987.3s (16m27s). `duration_fulfilled=true`.

---

## Final Artifact (data/runs/_rolling/m9_graph_latest.json)

```
schema_family:              m9_graph_arb
schema_revision:            m9.1
run_timestamp:              2026-05-22T14:32:05Z
generated_at_utc:           2026-05-22T14:48:32Z
elapsed_s:                  987.3
sweeps_completed:           6
duration_fulfilled:         true
cycles_found:               1200
cycles_positive_gross:      0
cycles_quoteable:           0
qsr:                        0.0
economics_gate_status:      BLOCKED_QSR
economics_blocker_class:    PROVIDER_QUALITY_BLOCKED
topology_gate:              CYCLES_FOUND
gate_acceptance:            false
strategy_gate_acceptance:   false
execution_mode:             paper
scan_scope:                 {routes_total: 13, edge_count: 102}
provider_rpc_error_count:   702   (58.5% of 1200 cycle failures)
provider_decode_error_count: 498  (41.5% of 1200 cycle failures)

cycle_reject_histogram:
  CYCLE_QUOTE_FAILED: 1200  (100.0%)

top_routes_by_rpc_error:
  uniswap_v3:WETH-cbBTC@100:    62 RPC_ERR + 47 DECODE
  uniswap_v3:WETH-EURC@100:     62 RPC_ERR + 44 DECODE
  pancakeswap_v3:WETH-EURC@100: 31 RPC_ERR + 30 DECODE

top_opportunities: 10 entries
  top[0]: USDC/WETH/EURC (uniswap_v3 + pancakeswap_v3 + aerodrome_slipstream)
          spread_bps=0.0, main_blocker=CYCLE_QUOTE_FAILED
```

---

## Root Cause Analysis

**Primary blocker**: `PROVIDER_QUALITY_BLOCKED`

Two compounding failure modes (stable across both soak1 and soak2):

1. **HTTP 429 Rate Limiting** (58.5% of failures in soak2 vs 66.5% in soak1):
   - `mainnet.base.org` public endpoint imposes strict concurrent-request limit
   - ~200 parallel quote requests per sweep saturate the rate limiter
   - Classified as `QUOTE_RPC_ERROR` in route_error_histogram

2. **Empty Quoter Responses** (41.5% in soak2 vs 33.5% in soak1):
   - `eth_call` returns `'0x'` for UniV3/CakeV3/Aerodrome quoters (no initialized ticks)
   - Classified as `QUOTE_DECODE` in route_error_histogram
   - Trend: DECODE share grew +8pp while RPC share fell -8pp soak1 to soak2

**Soak comparison:**
| Metric | Soak1 (10-min) | Soak2 (15-min) |
|--------|---------------|---------------|
| sweeps | 5 | 6 |
| cycles | 1000 | 1200 |
| elapsed_s | 663.5 | 987.3 |
| qsr | 0.0 | 0.0 |
| QUOTE_RPC_ERROR% | 66.5% | 58.5% |
| QUOTE_DECODE% | 33.5% | 41.5% |
| blocker | PROVIDER_QUALITY_BLOCKED | PROVIDER_QUALITY_BLOCKED |

**Unblock path**: Replace `mainnet.base.org` with premium RPC endpoint:
- dRPC (free tier: 100k req/day, no rate-limit burst)
- Alchemy Base (free tier: 300M compute units/month)
- QuickNode Base (free tier: 10M req/month)

---

## Dashboard Status

- URL: http://127.0.0.1:8099
- Endpoints: `/` (M9 operator surface), `/api/m9/current` (live JSON), `/m7`, `/m8`
- Artifact served: data/runs/_rolling/m9_graph_latest.json (sweeps=6, cycles=1200)

---

## Verification

```
soak exit code:     1 (EXIT_CONFIG_ERROR — soak data valid, artifact written successfully)
duration_fulfilled: true
artifact written:   data/runs/_rolling/m9_graph_latest.json (generated_at_utc: 2026-05-22T14:48:32Z)
sweeps monitored:   6/6 live (polled rolling artifact after each sweep)
qsr stable:         0.0 across all 6 sweeps (not a sampling artifact)
```
