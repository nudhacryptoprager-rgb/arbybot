# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-31T07:03:50Z
run_id: data/runs/_rolling (rolling artifact; Session 19)
mode: ONLINE (live BASE_RPC=publicnode, productive-lane, dynamic-sizes, ARBY_RPC_RPS_LIMIT=8)
artifact_mode: rolling
config:
  - online M9: python -m m9.graph_arb.runner --productive-lane --dynamic-sizes
code_identity:
  primary: ts:2026-05-31T07:03:50Z
  dirty: true

## 1) Scope
goal: Root-cause qsr=0.0 (Session 18) + implement quarantine feedback fix (Session 19)
goal_status: REACHED
  - Root cause of qsr=0.0 fully diagnosed (3-layer): DONE
    Layer 1: Bridge admits exotic/toxic V4 pools (GDOR TRUMP, MESH, BPS, etc.)
      17 V4 + 5 V3 meme/empty routes in 163-route inventory; all factory_verified=True;
      all 100% quote revert rate (no liquidity / honeypot / empty V4 pools)
    Layer 2: Graph contamination - GDOR TRUMP became 4th hub_token;
      all 1800 cycles touched toxic routes; cycles_quoteable=0
    Layer 3: Missing quarantine feedback - _write_revert_quarantine() wrote file
      but runner never loaded it; route_id format mismatch (probe vs inventory)

  - Quarantine feedback loop implemented + fixed: DONE
    Fix 1: Added revert quarantine loading in runner.py productive lane
    Bug: probe route_id "uniswap_v4:WETH-GDOR TRUMP@100" != inventory "m8_base_0x..."
    Fix 2: Resolve by (dex_id, frozenset({sym0,sym1}), fee) tuple matching
      17 pool_addresses resolved from 15 probe route_ids; merged with depth quarantine
    Fix 3: Writer extended - QUOTE_RPC_ERROR counts as hard failure + min 5 errors threshold
  
  - Result: qsr restored 0.0 -> 0.8375 (Session 19 M9 run, 5-min)
    GDOR TRUMP removed from hub_tokens; quote_revert_rate=0.0
    cycles_quoteable=335/400; 24 positive_gross; depth_quarantine_skipped=219 (202+17)

change_summary:
  - m9/graph_arb/runner.py: revert quarantine loader uses (dex_id, frozenset_syms, fee) tuple
    lookup + pool_address merge with depth quarantine
  - m9/graph_arb/runner.py: _write_revert_quarantine() extended: QUOTE_REVERT + QUOTE_RPC_ERROR
    both as hard failure; min total>=5 threshold before quarantining
  - m9/graph_arb/artifacts.py: revert_quarantine_skipped added as separate scan_scope field
  - docs/DEV_REPORT_LATEST.md: updated to Session 19

touched_files:
  - m9/graph_arb/runner.py
  - m9/graph_arb/artifacts.py
  - docs/DEV_REPORT_LATEST.md

## 2) Commands Executed

M9 Session 18 (root-cause run, qsr=0.0):
  BASE_RPC=https://base.publicnode.com ARBY_RPC_RPS_LIMIT=8 ARBY_RPC_RPS_BURST=8
  py -3.11 -m m9.graph_arb.runner --productive-lane --dynamic-sizes --require-factory-verified
    --inventory data/runs/_rolling/m9_bridge_inventory_latest.json --duration-minutes 5
  result: qsr=0.0 (BLOCKED_QSR; quote_revert_rate=0.59; 15 routes in revert quarantine)
  root cause: GDOR TRUMP as hub token; all 1800 cycles touched 15 reverting routes

M9 Session 19 (with quarantine fix, 5-min):
  BASE_RPC=https://base.publicnode.com ARBY_RPC_RPS_LIMIT=8 ARBY_RPC_RPS_BURST=8
  py -3.11 -m m9.graph_arb.runner --productive-lane --dynamic-sizes --require-factory-verified
    --inventory data/runs/_rolling/m9_bridge_inventory_latest.json --duration-minutes 5
  result: qsr=0.8375 (PASS>=0.80), cycles_quoteable=335/400, 24 positive_gross
          depth_quarantine_skipped=219 (202 depth + 17 revert merged)
          quote_revert_rate=0.0; GDOR TRUMP removed from hub_tokens
  new revert_quarantine written: 5 V3 routes (V4 now captured as QUOTE_RPC_ERROR)

Gates:
  py -3.11 -m pytest tests/unit/ -k m9 -q  # 465 passed
  py -3.11 scripts/check_repo_safety.py    # PASS (2 pre-existing warnings)

## 3) Artifacts
- data/runs/_rolling/m9_bridge_inventory_latest.json  <- graph_ready_total=163 (ts:2026-05-30T09:55:19Z)
- data/runs/_rolling/m9_graph_latest.json             <- generated_at=2026-05-31T07:03:50Z

## 4) Key Results

| Metric                           | Value        | Threshold | Status  |
|----------------------------------|:------------:|:---------:|:-------:|
| pytest unit tests (M9 subset)    | 465 pass     | 0 fail    | PASS    |
| M9 qsr (Session 19, 5-min fix)   | 0.8375       | >= 0.80   | PASS    |
| M9 qsr (Session 17, 15-min bench)| 0.9703       | >= 0.80   | PASS    |
| M9 cycles_quoteable              | 335 / 400    | > 0       | PASS    |
| M9 quote_revert_rate             | 0.0          | < 0.10    | PASS    |
| depth_quarantine_skipped         | 219 (202+17) | > 0       | PASS    |
| GDOR TRUMP in hub_tokens         | no           | no        | PASS    |
| cycles_positive_gross            | 24           | > 0       | PASS    |
| unverified_active_routes         | 0            | 0         | PASS    |

Note: best_cycle_gross_bps=7002 (WETH->AERO->WETH->SPACEX) is a phantom quote
(SPACEX meme token; PHANTOM_QUOTE_BPS_OVERFLOW: 43 cycles filtered). Quarantine
feedback will exclude SPACEX-related pools on next run if they fail consistently.

## 5) Current State (after Session 19)

### 5.1 Goals

| Goal                              | Status  | Details                                               |
|-----------------------------------|:-------:|-------------------------------------------------------|
| qsr=0.0 root cause identified     | REACHED | 3-layer diagnosis; GDOR TRUMP hub contamination       |
| Quarantine feedback loop fixed    | REACHED | route_id format mismatch resolved; qsr 0.0->0.8375    |
| M9 productive gate PASS           | REACHED | qsr=0.8375>=0.80 (S19); qsr=0.9703>=0.80 (S17 bench) |
| M4 economics (profit proof)       | BLOCKED | cycles_positive_gross=24 but all phantom quotes       |

### 5.2 Resolved Blockers

| Blocker                           | Status   | Evidence                                          |
|-----------------------------------|:--------:|---------------------------------------------------|
| M9 qsr=0.0 (Session 18)           | RESOLVED | S19: qsr=0.8375; quarantine feedback works        |
| GDOR TRUMP graph contamination    | RESOLVED | S19: not in hub_tokens; depth_quarantine_skipped=219 |
| Quarantine route_id mismatch      | RESOLVED | tuple-based resolution (dex_id, syms, fee)        |
| QUOTE_RPC_ERROR not quarantined   | RESOLVED | writer extended to capture RPC errors as hard fail|

### 5.3 Remaining Work

| Blocker                             | Type     | Next Action                             |
|-------------------------------------|:--------:|-----------------------------------------|
| Phantom quotes (SPACEX, openhuman)  | QUALITY  | second quarantine run will filter them  |
| M8.1 anchor stale (m8_1_stale=True) | INFRA    | refresh M8.1 stable anchor inventory   |
| BLOCKED_NO_POSITIVE_GROSS (real)    | MARKET   | Phase A: per-adapter cost model         |
| DEX palette (CPMM/CLMM coverage)    | STRATEGY | Phase B: aerodrome_stable, curve        |

## Session Completion
session_goal: Root-cause qsr=0.0 + quarantine feedback fix (Session 19)
goal_status: REACHED
  Root cause: 3-layer (bridge admits toxic pools -> hub contamination -> missing feedback)
  Fix: revert quarantine tuple-based resolve; writer extended for QUOTE_RPC_ERROR
  Result: qsr 0.0 -> 0.8375; cycles_quoteable 0 -> 335; quote_revert_rate 0.59 -> 0.0
  Tests: 465 M9 unit tests pass
close_allowed: true
primary_blocker_of_session: none (all session goals reached)
blocker_status_after: RESOLVED