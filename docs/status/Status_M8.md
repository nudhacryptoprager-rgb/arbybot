# Status: M8 New-Pool Sniping Pivot

**Status**: IN_PROGRESS — Phase 1 REACHED, Phase 2 PAPER_ONLY_STABILIZED.

`goal_status`: IN_PROGRESS
`phase1_status`: REACHED (R8b gate PASS 2026-05-14T18:01:39Z→18:16:49Z; 6/6 factory self-test)
`phase2_status`: PAPER_ONLY_STABILIZED (15m+30m+60m short gates ALL PASS 2026-05-14)
`phase1_close_allowed`: true
`phase2_real_execution_allowed`: false
`kill_switch_active`: true
`execution_enabled`: false
`production_profit_ready`: false
`close_allowed`: false

## Current Blockers

1. Phase 2 24h paper soak not yet completed.
2. `phase2_arb_gate`: BLOCKED_ZERO_SPREAD_MIRROR_AND_PNL_NULL — brand-new pairs lack a spread
   reference (no mirror yet for new memecoins). PnL will compute when arb-eligible pairs appear.
3. Real execution stays BLOCKED until Phase 2 evidence green and kill_switch flipped explicitly.

## Primary Rolling Artifact

- `data/runs/_rolling/new_pool_sniper_latest.json` (schema_revision=phase2.0)

Required top-level fields: `schema_family`, `schema_revision`, `generated_at_utc`, `source`,
`freshness_s`, `status`, `reasons`, `self_test_by_dex`, `run_scope`.

## Phase 1 Evidence (FINAL — 2026-05-14)

Phase 1 criteria ALL MET:
- RPC preflight PASS (chain_id 8453, archive, WS newHeads).
- 6/6 factory self-tests PASS: uniswap_v3, aerodrome_slipstream, aerodrome ve33,
  pancakeswap_v3, uniswap_v4, uniswap_v2.
- R8b gate: parse_failed=0, rpc_error_rate=0%, candidates_total=129, run_scope=all.
- factory_breakdown: uniswap_v4 raw=194/parse_ok=194 (100%), uniswap_v2 raw=12/parse_ok=12 (100%).
- Non-uniswap aerodrome/slipstream/pancakeswap_v3: MARKET_WINDOW_NO_POOL_CREATED (no code bug).
- Full historical archive probes: 4/4 PASS (all parsers correct on known block windows).

## Phase 2 Real-Input Evidence (2026-05-15)

Fixes shipped (5572 passed, 6 skipped):
- V4 StateView lens: `getSlot0` + `getLiquidity` on Base StateView `0xa3c0c9b6...`.
- Native ETH anchor: `0x000…000` priced as WETH.
- On-chain honeypot probes: `eth_getCode` + `totalSupply()` with per-token cache.
- Phase 2 summary selects most informative event (WOULD_ENTER > SKIP-with-liquidity > last).

30m gate evidence (2026-05-15T08:12:31Z, 6 cycles, 1856s):
- raw=212, parse_ok=212, parse_failed=0, rpc_errors=0.
- Per-dex: V4=174 (96.1%), V2=11, Aerodrome=5, V3=2, PancakeV3=2.
- `honeypot_result=PASS` (on-chain probe working).
- `V4_ZERO_AT_CREATION` dominates reject_histogram (expected: LP adds liquidity in separate tx).
- `check_phase2_gate.py`: PASS.
- `phase2_24h_soak_blocked_until_real_inputs` → **false** (criterion satisfied).

## Next Required Evidence (Phase 2 → 24h Paper Soak)

```powershell
$env:ARBY_SNIPER_ENABLE='1'; $env:ARBY_SNIPER_PAPER='1'
py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 1440 --prefer-ws --poll-interval-s 30 --blocks-back 50
```

Acceptance criteria:
- `snipe_candidates_total ≥ 5` with non-null `dry_run_decision` per event.
- `parse_failed=0` for 24h, `rpc_errors < 5%`.
- `execution_enabled: false` throughout.

## Phase Gates

Phase 1: listener-only foundation (REACHED).
Phase 2: scoring and dry-run (PAPER_ONLY_STABILIZED — 24h soak pending).
Phase 3: constrained real execution (BLOCKED — requires Phase 2 evidence + kill-switch flip).

## M9 Upstream Runtime (2026-06-11)

**Session: 45m sniper → M8.1 → bridge rebuild (foreground, dedicated RPC)**

| Metric | Value |
|--------|------:|
| `status` / `recent_events` | **ACTIVE** / **278** |
| `generated_at_utc` | **2026-06-11T16:06:29Z** |
| RPC errors / 429 | **0** / **0** |
| Sniper funnel | raw=278, parse_ok=278, cycles=90 |
| `m8_pending_pairs` tokens | **542** |
| Bridge `m8_stale` | **false** |
| Bridge `m8_new_pools_input` | **278** |
| Bridge `graph_ready_from_m8` | **196** |

`m8_upstream_runtime_status`: **REACHED** (fresh provenance-tagged discovery input accepted by bridge; M9 economics out of scope).

## M9 Bridge Status

`m9_bridge_role_status`: DISCOVERY_INPUT_OPERATIONAL
`m9_bridge_blocker`: M9_ECONOMICS_BLOCKED (upstream M8/M8.1 fresh; cycle-level economics not proven)

## Canonical Commands

```powershell
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/check_repo_safety.py
# Smoke (offline, 15 min):
py -3.11 scripts/sniper_smoke_run.py --chain base --duration-minutes 15 --prefer-ws
# Phase 2 gate check:
py -3.11 scripts/check_phase2_gate.py --artifact data/runs/_rolling/new_pool_sniper_latest.json
```
