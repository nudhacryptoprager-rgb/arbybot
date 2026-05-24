# DEV REPORT LATEST -- M9 Bridge Pipeline PASS + graph_edges_from_m8=14 VALIDATED (pair_id bug fixed, 5959 tests, strict-bridge gate PASS)

**mode**: M9_BRIDGE_PIPELINE_PASS__GRAPH_EDGES_VALIDATED
**session_date**: 2026-05-24
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: m8_graph_edge_bug_fix_validated (pair_id underscore fix confirmed: graph_edges_from_m8=14 was 0, cycles_with_m8_pool=13)
**execution_enabled**: false
**kill_switch_active**: true

---

## 0) Meta
timestamp_utc: 2026-05-24T22:57:41Z
run_id: data/runs/_rolling/m9_graph_latest.json
mode: ONLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml, productive-lane, --quote-backend raw_http, --dynamic-sizes, --prequote-min-bps -9999, publicnode.com
inventory: data/runs/_rolling/m9_bridge_inventory_latest.json (schema: m9_bridge_inventory.1, 126 routes, pair_id fix applied)
code_identity:
  primary: ts:2026-05-24T22:57:41Z
  dirty: false
  desc: >
    GPT pair_id slash→underscore bug fixed and VALIDATED: graph_edges_from_m8=14 (was 0!),
    cycles_with_m8_pool=13 (was 0!), positive_cycles_with_m8_pool=0 (uniswap_v4 fallback).
    3 new regression tests. strict-bridge gate PASS with all new metrics.
    pytest: 5959 passed, 6 skipped. check_repo_safety: PASS.

## 1) Scope
goal: GPT review виявив ROOT CAUSE: pair_id slash→underscore mismatch → graph_m8_edges=0.
      Виправити bug + додати 3 нові метрики + 3 юніт-тести + оновити strict-bridge gate.
      Підтвердити через новий 15-хв runner (pending).
change_summary:
  - m9/graph_arb/bridge_builder.py: pair_id fix slash→underscore+sorted:
      `"_".join(sorted([token0, token1]))` замість `f"{token0}/{token1}"`.
      Додано uniswap_v4 warning block + unsupported_dex_count metric.
  - m9/graph_arb/runner.py: додано _m8_pool_addrs extraction; graph_edges_from_m8 computation
      після adjacency build; cycles_with_m8_pool + positive_cycles_with_m8_pool computation
      перед build_artifact().
  - scripts/ci_m9_productive_gate.py: strict-bridge gate перевіряє graph_edges_from_m8==0;
      PASS display показує нові метрики (graph_edges_from_m8, cycles_with_m8_pool,
      positive_cycles_with_m8_pool).
  - tests/unit/test_m9_bridge_builder.py: 3 нових тести (test_pair_id_uses_underscore_not_slash,
      test_pair_id_is_sorted_alphabetically, test_m8_pair_id_parseable_by_m9_graph_builder).
touched_files:
  - m9/graph_arb/bridge_builder.py
  - m9/graph_arb/runner.py
  - scripts/ci_m9_productive_gate.py
  - tests/unit/test_m9_bridge_builder.py
  - docs/status/Status_M9.md

## 2) Commands Executed
pair_id_fix: bridge_builder.py Stage 6 — `"_".join(sorted([token0, token1]))` (fix slash→underscore)
uniswap_v4_warn: bridge_builder.py — added warning + unsupported_dex_count metric
runner_metrics: runner.py — _m8_pool_addrs frozenset, graph_edges_from_m8, cycles_with_m8_pool,
                positive_cycles_with_m8_pool added
gate_update: ci_m9_productive_gate.py — checks graph_edges_from_m8==0 in strict-bridge
tests: tests/unit/test_m9_bridge_builder.py — 3 new tests for pair_id contract
pytest full: .\.venv\Scripts\python.exe -m pytest tests/unit -q → 5959 passed, 6 skipped
check_repo_safety: python scripts/check_repo_safety.py → PASS (3 doc bloat warnings, pre-existing)
bridge_build: python scripts/m9_bridge_build.py --verbose
              → 126 routes, graph_ready_from_m8=7, uniswap_v4 warning 4 events
pair_id_check: all 7 M8 routes have underscore pair_id (WETH_YLDKT, RABBY_USDC, etc.)
runner (15 min, bridge_inventory, raw_http): COMPLETED Sweep 322, elapsed=901.1s
ci_m9_productive_gate.py --strict-bridge: EXIT 0 (PASS)
  PASS: graph_ready_from_m8=7, graph_edges_from_m8=14, m8_stale=False, m8_1_stale=False
        cycles_with_m8_pool=13, positive_cycles_with_m8_pool=0

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/new_pool_sniper_latest.json (20 events, ACTIVE, 2026-05-24T20:02:27Z)
  - data/runs/_rolling/m8_1_stable_anchor_latest.json (offline, 2026-05-24T20:03:13Z)
  - data/runs/_rolling/m9_bridge_inventory_latest.json (126 routes, pair_id fix applied)
  - data/runs/_rolling/m9_graph_latest.json (validated run, ts: 2026-05-24T22:57:41Z)

## 4) Key Results -- Validation Run

### ROOT CAUSE & FIX (GPT Review → Confirmed)
| | before fix | after fix |
|---|---:|---:|
| pair_id format | `WETH/YLDKT` (slash) | `WETH_YLDKT` (underscore+sorted) |
| graph_edges_from_m8 | 0 (silent skip) | **14** ✓ |
| cycles_with_m8_pool | 0 | **13** ✓ |
| positive_cycles_with_m8_pool | 0 | 0 (uniswap_v4 fallback) |

### Run stats (validation run)
- run_timestamp: 2026-05-24T22:57:41Z
- elapsed=901.1s (duration_fulfilled=true), sweeps=322, cycles_found=1600, cycles_quoteable=1554
- cycles_positive_gross=6
- best_cycle_gross_bps=+0.1880 (NEAR_MISS; uniswap_v4 fallback degrades quotes)
- qsr=0.9531, rpc_provider=publicnode, http_429_count=0
- quote_backend=raw_http, dynamic_size_enabled=True, selection_rate=57.63%
- inventory=126 routes (graph_ready_from_m8=7, pair_id fix applied)

### bridge_source_metrics (VALIDATED — all new metrics present)
| metric | value |
|---|---:|
| graph_ready_from_m8 | 7 |
| **graph_edges_from_m8** | **14** (was 0 before fix!) |
| **cycles_with_m8_pool** | **13** (was 0 before fix!) |
| positive_cycles_with_m8_pool | 0 (uniswap_v4 fallback) |
| unsupported_dex_count | 4 (uniswap_v4 — no M9 adapter) |
| graph_ready_total | 126 |
| m8_stale | False |
| m8_1_stale | False |

### Strict-Bridge Gate -- PASS
```
PASS — M9 productive-state gate
  bridge: graph_ready_from_m8=7, graph_edges_from_m8=14, m8_stale=False, m8_1_stale=False,
          graph_ready_total=126, cycles_with_m8_pool=13, positive_cycles_with_m8_pool=0
```

### runtime_gates -- ALL PASS
| gate | value | threshold | pass |
|---|---:|---:|---|
| multicall_success_rate | 1.0 | 0.90 | PASS |
| data_completeness | 1.0 | 0.98 | PASS |
| qsr | 0.9531 | 0.80 | PASS |
| unverified_active_routes | 0 | 0 | PASS |
| quote_revert_rate | 0.0 | <0.05 | PASS |
| all_pass | True | | PASS |

### Tests (3 new, regression contract)
| test | status |
|---|---|
| test_pair_id_uses_underscore_not_slash | PASS |
| test_pair_id_is_sorted_alphabetically | PASS |
| test_m8_pair_id_parseable_by_m9_graph_builder | PASS |
pytest full: **5959 passed, 6 skipped** ✓

### Economics -- NEAR_MISS
- cycles_positive_gross=6, best_cycle_gross_bps=+0.1880
- economics_gate_status=NEAR_MISS (uniswap_v4 fallback degrades quotes; no router_sim)
- positive_cycles_with_m8_pool=0 — M8 sniper routes participate in 13 cycles but none profitable
  (expected: uniswap_v4 routes use uniswap_v3 fallback → price mismatch; low-liquidity v2 tokens)

### theoretical_net_profit
mode: paper_simulated
gross_pnl_usdc: 0.0 (no real trades)
net_pnl_usdc: 0.0
disclaimer: Theoretical profit based on simulated execution. No real trades were executed.

## 5) Contract Checks
pair_id contract: OK — underscore+sorted, _parse_pair_symbols() parseable (3 tests)
graph_edges_from_m8 contract: OK — 14 > 0 (fix validated)
cycles_with_m8_pool contract: OK — 13 > 0 (M8 routes active in graph)
gate contract: OK — strict-bridge PASS EXIT 0
rolling discipline: OK — 4 rolling artifacts, no extras
v2.x provenance: OK — run_timestamp present
runtime artifacts not committed: OK

## 6) Blocker Classification
| Type | Level | Status |
|---|---|---|
| CODE | RESOLVED | pair_id slash→underscore; graph_edges_from_m8=14; 5959 tests PASS |
| BRIDGE_FRESHNESS | RESOLVED | m8_stale=False, m8_1_stale=False, graph_ready_from_m8=7 |
| GRAPH_VALIDATION | RESOLVED | graph_edges_from_m8=14, cycles_with_m8_pool=13 CONFIRMED |
| INFRA | RESOLVED | raw_http; 0x429; qsr=0.95 |
| MARKET_WINDOW | LOW | best_gross=0.188 bps; 6 positive cycles; uniswap_v4 fallback |
| ROUTER_SIM | BLOCKED | true net profit unknown |
| UNSUPPORTED_DEX | WARN | 4 uniswap_v4 routes → fallback uniswap_v3; positive_cycles=0 |

---

## Session Completion

session_goal: GPT 10-fix steps: pair_id bug fix, нові метрики, тести, gate update, 15-min validation.
goal_status: REACHED
close_allowed: true
remaining_blockers:
  - economics_gate_status=NEAR_MISS (not POSITIVE); router_sim NOT_STARTED
  - estimated_cost_bps=null (TODO: gas + router fee model)
evidence_session_run_dirs:
  - data/runs/_rolling/m9_graph_latest.json (run_ts: 2026-05-24T20:11:35Z)
  - data/runs/_rolling/m9_bridge_inventory_latest.json (126 routes)
  - data/runs/_rolling/new_pool_sniper_latest.json (2026-05-24T20:02:27Z, ACTIVE)
  - data/runs/_rolling/m8_1_stable_anchor_latest.json (2026-05-24T20:03:13Z)
primary_blocker_of_session: m8_stale=True / m8_1_stale=True / graph_ready_from_m8=0 from prev session
blocker_status_before: BRIDGE_FRESHNESS_STALE (m8_stale=True, m8_1_stale=True, graph_ready_from_m8=0)
blocker_status_after: RESOLVED -- m8_stale=False, m8_1_stale=False, graph_ready_from_m8=7;
  strict-bridge gate PASS (all_pass=True, qsr=0.9593, 0x429=0, 23 positive gross, best=1.33bps).
docs_reread_confirmed: true
