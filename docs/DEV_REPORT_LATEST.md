# DEV REPORT

## 0) Meta
timestamp_utc: 2026-05-31T08:41:14Z
run_id: data/runs/_rolling (rolling artifact; Session 19)
mode: ONLINE (live BASE_RPC=publicnode, productive-lane, dynamic-sizes, ARBY_RPC_RPS_LIMIT=8)
artifact_mode: rolling
config: config/exotic_base_anchor.yaml
pipeline: M8 sniper -> M8.1 stable-anchor -> bridge(+M8.2 registry) -> depth-enrich -> M9 graph
code_identity:
  primary: ts:2026-05-31T08:41:14Z
  dirty: true
safety: execution_enabled=false, kill_switch_active=true (no on-chain actions)

## 1) Scope
goal: (1) M8.2 pending-pair registry (single->multi venue promotion);
      (2) depth-aware sizing; (3) 20-min live run M8->M8.1->M8.2->M9 with monitoring + report.
goal_status: REACHED
  - M8.2 pending-pair registry: DONE (module + bridge integration + 20 tests)
  - Depth-aware sizing: DONE (models/builder/quoter/artifacts + 12 tests)
  - 20-min orchestrator run: DONE (exit=0, cycle 1130.4s, all 5 stages executed)
  - Full report with comparison tables: DONE (this document)
test_status: tests/unit -q = 6300 passed, 6 skipped

## 2) What was built (Session 19)

### 2a) M8.2 pending-pair registry  (m8/discovery/pending_pair_registry.py)
- Persistent cross-run accumulator keyed by exotic token on-chain address.
- Records each anchor-connected sniper event as a (dex_id, pool) venue observation.
- Promotes a token to active routes once observed on >=2 distinct quoteable venues
  across runs -> directly attacks Barrier #1 (multi-venue gate cut 311/313 routes;
  m8_multi_venue_quoteable was stuck at 2).
- Schema m8_pending_pairs.1, path data/runs/_rolling/m8_pending_pairs.json, TTL 48h.
- Pure module (file IO + dict only; no RPC, no bridge import). Disabled by default in
  bridge (registry_path=None) so unit tests stay side-effect free.
- Bridge wiring: Stage 3b updates registry; Stage 6b replays promotable events as m8
  routes tagged promoted_from_registry=True; registry_* keys added to
  bridge_source_metrics. CLI flags --registry / --no-registry / --registry-ttl-seconds.

### 2b) Depth-aware sizing
- models.py: GraphEdge.effective_depth_usd; GraphCycle.min_effective_depth_usd
  (min over edges, ignoring None); CycleQuoteResult.cycle_min_depth_usd + depth_capped.
- builder.py: populates effective_depth_usd on forward+reverse edges from inventory.
- quoter.py: cap_sizes_to_depth(sizes, depth, frac=1.0) caps the dynamic size ladder at
  the cycle bottleneck depth; no-op when depth is None/<=0. Guard
  isinstance(cycle_depth,(int,float)) and not bool and >0 (prevents MagicMock breakage).
- artifacts.py: infra_telemetry depth_aware_known_count / capped_count / known_rate.

### 2c) Orchestrator wiring (scripts/m9_rolling_orchestrator.py)
- Bridge rebuild now passes --registry data/runs/_rolling/m8_pending_pairs.json.
- New Step 3b run_depth_enrich() repopulates effective_depth_usd after bridge resets M8
  route depth to None (depth-aware sizing depends on it).

## 3) 20-minute live run (2026-05-31 10:22 -> 10:41, exotic_base_anchor)
Stages observed:
- M8 sniper: 7 min, 14 poll cycles (blocks 46669999 -> 46697998), 9 factories.
- M8.1 stable-anchor refresh: 10:29:30.
- Bridge rebuild with registry active: 10:29:31 (depth_ok_count=117).
- Depth-enrich: 259 active routes probed at 8 RPS.
- M9 graph scan: 607s, 8 sweeps, 1600 cycles quoted.
- Orchestrator exit=0, cycle wall-time 1130.4s.

## 4) Comparison tables

### Table A - Bridge funnel (BEFORE registry vs AFTER this run)
| metric                       | BEFORE (baseline) | AFTER (this run) | delta   |
|------------------------------|-------------------|------------------|---------|
| registry_enabled             | None              | True             | enabled |
| m8_multi_venue_quoteable     | 2                 | 8                | +6      |
| graph_ready_total            | 163               | 259              | +96     |
| active_routes                | 163               | 259              | +96     |

Note: the +96 graph-ready routes come from fresh M8 sniper data this cycle; the registry
ran for the first time (accumulation phase) and did not yet add promoted routes.

### Table B - M8.2 registry telemetry (first run = accumulation)
| metric                          | value |
|---------------------------------|-------|
| registry_tokens_tracked         | 323   |
| registry_venues_tracked         | 340   |
| registry_new_tokens             | 323   |
| registry_new_venues             | 340   |
| registry_multi_venue_tokens     | 0 quoteable / 9 any-venue |
| registry_promoted_routes        | 0     |

Venue-count distribution across 323 tokens: 1 venue=314, 2 venues=6, 4 venues=2, 6 venues=1.
Dex distribution (distinct tokens): uniswap_v4=217 (NON-quoteable), uniswap_v2=82,
uniswap_v3=15, aerodrome=8, aerodrome_slipstream=1.

Why 0 promotions is correct on run #1: of the 9 tokens already seen on >=2 venues, 0 have
>=2 quoteable venues -- their second venue is almost always uniswap_v4 (217 of 340 venues
are V4, which the quote backend cannot price). Promotion fires on a later cross-run cycle
when a token reappears on a 2nd quoteable (v2/v3/aerodrome) venue within the 48h TTL. This
is exactly the cross-run behaviour validated by unit test test_cross_run_promotion.

### Table C - Depth-aware sizing telemetry
| metric                       | value  |
|------------------------------|--------|
| depth_aware_known_count      | 24     |
| depth_aware_capped_count     | 24     |
| depth_aware_known_rate       | 0.015  |
| dynamic_size_selected_count  | 22     |
| dynamic_size_selection_rate  | 0.0138 |
| sizes_usd ladder             | [100, 250, 500] |

All 24 cycles with a known bottleneck depth were size-capped (100% cap rate where depth is
measured); for the remaining cycles depth-aware sizing is a no-op (no measured
effective_depth_usd), preserving prior behaviour.

### Table D - M9 scan funnel (this run vs Session 18 baseline)
| metric                          | Session 18 | this run   |
|---------------------------------|------------|------------|
| qsr                             | 0.0        | 0.535      |
| cycles_found                    | 1800       | 1600       |
| cycles_quoteable                | 0          | 856        |
| cycles_positive_gross           | 0          | 57         |
| best_cycle_gross_bps            | n/a        | 7897.31    |
| cost_adjusted_net_bps           | n/a        | 7886.31    |
| estimated_cost_bps              | n/a        | 11.0       |
| quote_revert_rate               | ~1.0       | 0.0367     |
| quote_rpc_error_rate            | n/a        | 0.0        |
| m8_multi_venue_verified         | n/a        | 8          |

### Table E - M9 reject histogram and scope
| reject reason                | count |
|------------------------------|-------|
| NEGATIVE_GROSS               | 799   |
| PHANTOM_QUOTE_BPS_OVERFLOW   | 508   |
| CYCLE_QUOTE_FAILED           | 236   |
| POSITIVE_GROSS               | 57    |

scan_scope: routes_total=144, edge_count=292, depth_quarantine_skipped=202.
hub_tokens: WETH, USDC, equivalenc, SYNTH, ANTHROPIC, SPACEX, AERO, SERVER, LIQUIDBGT, AI.

## 5) Interpretation
- The registry + depth-aware path is live-validated end-to-end: bridge ran with the
  registry on, the registry accumulated 323 tokens / 340 venues, depth-enrich repopulated
  depth, and M9 consumed depth-aware sizing telemetry -- all in one orchestrated cycle.
- qsr recovered from 0.0 (Session 18 toxic-route contamination) to 0.535, with 856
  quoteable cycles and 57 positive-gross cycles. quote_rpc_error_rate=0.0 and
  quote_revert_rate=0.037 confirm a clean, healthy scan.
- best_cycle_gross 7897 bps / cost-adjusted 7886 bps are exotic-token phantom magnitudes
  (thin pools); PHANTOM_QUOTE_BPS_OVERFLOW=508 shows guardrails flagging them, and the
  positive set still routes through real m8 pools (positive_cycles_with_m8_pool=57).

## 6) Known limitations / next step
- V4 routes are skipped by the depth probe (V4_DEPTH_UNSUPPORTED) and are non-quoteable,
  so V4-dominant tokens never reach multi-venue promotion on their own.
- Registry promotion requires >=2 quoteable venues within the 48h TTL; first run is
  accumulation-only by design (0 promotions expected and observed).
- Depth-aware sizing is a no-op where effective_depth_usd is unmeasured.
- To demonstrate a live promotion, a 2nd orchestrator cycle is needed so a tracked token
  reappears on a 2nd quoteable venue inside the TTL window.