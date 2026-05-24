# DEV REPORT LATEST — M9 Smoke29c: Quarantine Expansion PASS (toxic_rate 0.99→0.42)

**mode**: M9_SMOKE29C_QUARANTINE_EXPANSION_PASS
**session_date**: 2026-05-24
**schema_family**: m9_graph_arb
**schema_revision**: m9.1
**run_label**: smoke29c (15-min real-RPC, publicnode, productive-lane, quarantine 59 entries)
**execution_enabled**: false
**kill_switch_active**: true

---

## 0) Meta
timestamp_utc: 2026-05-24T15:34:08Z
run_id: data/runs/_rolling/m9_graph_latest.json
mode: ONLINE
artifact_mode: rolling
config: config/exotic_base_anchor.yaml, productive-lane, --prequote-min-bps -9999, publicnode.com
code_identity:
  primary: ts:2026-05-24T15:34:08Z
  dirty: true — pool_depth_probe quoter injection + quarantine expansion (59 entries)
  desc: pool_depth_probe quoter fix, quarantine 3→59 entries (real on-chain probe ok=117), smoke29c gate PASS

## 1) Scope
goal (Roadmap): M9 Quarantine Expansion — on-chain depth probe on 117/119 pools, expand quarantine 3→59, confirm toxic_rate < 0.90 in productive lane
change_summary:
  - m9/graph_arb/pool_depth_probe.py: inject quoter_addr from config dexes block (critical fix — was 100% NO_QUOTER fail)
  - data/quarantine/m9_pool_depth_quarantine.json: 3→59 entries (+56: 36 TOXIC_PRICE_IMPACT + ~20 LOW_EFFECTIVE_DEPTH)
  - tests/unit/test_m9_invariants.py: TestProductiveGateToxicRateCheck (4 tests), TestUpdateQuarantine (5 tests)
touched_files:
  - m9/graph_arb/pool_depth_probe.py
  - data/quarantine/m9_pool_depth_quarantine.json
  - tests/unit/test_m9_invariants.py

## 2) Commands Executed
py -3.11 -m pytest -q: PASS (5928 tests, +9 from session)
py -3.11 scripts/check_repo_safety.py: PASS (2 pre-existing M7/M8 doc-bloat warnings)
py -3.11 scripts/ci_m9_productive_gate.py --artifact data/runs/_rolling/m9_graph_latest.json: EXIT 0 ✅
Pool depth probe: ok=117, fail=2, toxic=36, low_depth=21

## 3) Artifacts Attached
rolling:
  - data/runs/_rolling/m9_graph_latest.json (smoke29c, run_ts: 2026-05-24T15:19:06Z)

## 4) Key Results — Smoke29c

### Run stats
- run_timestamp: 2026-05-24T15:19:06Z
- generated_at_utc: 2026-05-24T15:34:08Z
- elapsed=901.8s (duration_fulfilled=true), sweeps=292, cycles_found=1453
- cycles_positive_gross=38 (first positive_gross ever in M9!) ✅
- best_cycle_net_bps=1.0854 (first positive net in M9!) ✅
- qsr=0.9642, rpc_provider=publicnode, http_429_count=0
- scan_scope.pool_quality_lane=productive, depth_quarantine_skipped=57

### runtime_gates — ALL PASS ✅
| gate | value | threshold | pass |
|---|---:|---:|---|
| multicall_success_rate | 1.0 | 0.90 | PASS |
| data_completeness | 1.0 | 0.98 | PASS |
| unverified_active_routes | 0 | 0 | PASS |
| qsr | 0.9642 | 0.80 | PASS |
| quote_revert_rate | 0.0 | <0.05 | PASS |
| **all_pass** | **true** | | **PASS** |

### Pool-Quality Gate — toxic_rate
| gate | value | threshold | pass |
|---|---:|---:|---|
| toxic_route_rate | 0.4183 | <0.90 | **PASS** ✅ |

### Economics — NEAR_MISS (breakthrough: first positive_gross cycles!)
- cycle_reject_histogram: NEGATIVE_GROSS=1363, CYCLE_QUOTE_FAILED=52, POSITIVE_GROSS=38
- loss_reason_histogram: TOXIC_ROUTE_PRICE_IMPACT=586, UNFAVORABLE_PRICES=596, QUOTE_FAILED=52, FEE_DRAG=181, POSITIVE=38
- cycles_positive_gross=38 (was 0 in smoke28!) ✅
- best_cycle_net_bps=1.0854 (first positive net in entire M9 session!) ✅
- economics_gate_status=NEAR_MISS (not BLOCKED_NO_POSITIVE_GROSS anymore!) ✅

### Pool Depth Probe Results (on-chain, 2026-05-24)
- ok=117, fail=2 (2 aerodrome non-CL, no QuoterV2), toxic=36, low_depth=21
- Quarantine: 3 → 59 entries (+56: AERO/EURC, AERO/USDC, AERO/WETH, EURC/USDC, EURC/WETH, TOSHI/WETH, VIRTUAL/WETH, LBTC/WETH, cbBTC/WETH and others)

### Smoke28 vs Smoke29c comparison
| Metric | smoke28 | smoke29c |
|---|---|---|
| depth_quarantine_skipped | 1 | **57** ✅ (+56) |
| toxic_route_rate | 0.9894 | **0.4183** ✅ (×2.4 reduction) |
| cycles_positive_gross | 0 | **38** ✅ (first ever!) |
| best_cycle_net_bps | 0.0 | **+1.0854** ✅ |
| economics_gate_status | BLOCKED_NO_POSITIVE_GROSS | **NEAR_MISS** ✅ |
| http_429_count | 0 | 0 ✅ |
| multicall_success_rate | 1.0 | 1.0 ✅ |
| all_pass | true | **true** ✅ |

### theoretical_net_profit
mode: paper_simulated
gross_pnl_usdc: 0.0 (no real trades; cycles_positive_gross=38 are NEAR_MISS, not executed)
net_pnl_usdc: 0.0
disclaimer: Theoretical profit based on simulated execution. No real trades were executed.

## 5) Contract Checks
status/reasons consistency: OK — all_pass=True, toxic_rate=0.4183 < 0.90
rolling discipline (3 files only): OK — m9_graph_latest.json is rolling artifact
v2.x provenance contract: OK — run_timestamp, generated_at_utc present; no deprecated fields
runtime artifacts not committed: OK — data/runs/** not in git

## 6) Blocker Classification
| Type | Level | Status |
|---|---|---|
| CODE | RESOLVED | pool_depth_probe quoter injection fix; 5928 tests PASS |
| DATA_COLLECTION | RESOLVED | quarantine 3→59 entries; toxic_rate 0.9894→0.4183 |
| MARKET_WINDOW | LOW | cycles_positive=38 (NEAR_MISS); best_net=1.09 bps (flat market) |

---

## Session Completion

session_goal: Run on-chain depth probe → expand quarantine → smoke29c → gate PASS with toxic_rate < 0.90.
goal_status: REACHED
close_allowed: true
remaining_blockers: toxic_rate=0.4183 — ~42% cycles still TOXIC (not all AERO/USDC UV3 addresses quarantined); economics_gate_status=NEAR_MISS (not POSITIVE); router_sim NOT_STARTED.
evidence_session_run_dirs: data/runs/_rolling/m9_graph_latest.json (run_ts: 2026-05-24T15:19:06Z)
primary_blocker_of_session: dRPC 429 rate limiting (smoke29/29b had mc_sr=0.76) + NO_QUOTER in pool_depth_probe (100% probe fail before fix).
blocker_status_before: ACTIVE — pool_depth_probe 100% fail (NO_QUOTER); smoke29 mc_sr=0.76 (dRPC 429); quarantine=3 entries.
blocker_status_after: RESOLVED — quoter injection fix; publicnode.com (0x429); quarantine 59 entries; toxic_rate 0.9894→0.4183; cycles_positive_gross=38; gate EXIT 0.
docs_reread_confirmed: true
