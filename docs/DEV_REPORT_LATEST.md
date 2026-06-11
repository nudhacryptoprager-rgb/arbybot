# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-11T13:30:00Z
goal_status: BLOCKED
blocker_status_after: EXPANSION_PRODUCTIVE_ADMIT_STATIC_CONFIG_GATE
docs_reread_confirmed: true
run_id: m9-depth-truth-sizing-rca-2026-06-11
mode: M9_DEPTH_SIZING_PIPELINE_RCA
config: config/exotic_base_anchor.yaml

## Session Completion
session_goal: Prove depth ladder at runtime (force-reprobe), trace M8→M8.1→M8.2→M9 sizing pipeline, find why market_size_usd stays $0.05
goal_status: BLOCKED
close_allowed: false
remaining_blockers: EXPANSION_PRODUCTIVE_ADMIT_STATIC_CONFIG_GATE (416 V4 routes with measured depth rejected by static config flag); V3_ANALYTICAL_DEPTH_INSANE_VALUES (14 routes up to $31T); PERVERSE_DEPTH_GATE (unknown depth admitted, measured depth < $50 rejected)
docs_reread_confirmed: true

## Runtime evidence (fresh)

| Artifact | note | Key metrics |
|----------|------|-------------|
| `data/tmp/m9_bridge_inventory_shadow_latest.json` | post `--force-reprobe` | routes=656, with_depth=393, `exact100`=2 (was 297), `gt100_sane`=281, sane max≈$66k, `depth_probe_status`: MEASURED_CAPACITY=318, TOO_THIN=67, LOWER_BOUND_AT_MAX_PROBE=8, None=263 |
| enrich log (force-reprobe) | ~29 min RPC | candidates=656, force_reprobe=395, probed_ok=393, v4_ok=327/416 |
| `data/tmp/m9_graph_depth_truth_10m_v2.json` | 10m productive run | cycles_found=1106, cycles_quoteable=223, qsr=0.5348, qsr_econ=0.0, `depth_aware_known_rate`=0.0, top `market_size_usd`=$0.05, `cost_adjusted_net_bps`≈-12004 |
| `data/tmp/m9_quote_lane_rca_depth_truth_10m_v2.json` | strict-consistency | BALANCER_UNKNOWN_REVERT_WITH_METADATA=206, MAVERICK_NO_LIQUIDITY=154 |
| `data/tmp/m9_inventory_truth_enriched.json` | admission simulation | admitted=191 of 656; admitted WITH depth=17 (all insane values), WITHOUT depth=174 (maverick=120, balancer=37, curve=4, v3=12); fail histogram: expansion_admit_false=394–416, quarantined=67, depth_lt_50=4 |

## Commands executed

```powershell
py -3.11 -u scripts/m9_bridge_build.py --config config/exotic_base_anchor.yaml --registry data/runs/_rolling/m8_pending_pairs.json --include-expansion-duplicates-for-shadow --output data/tmp/m9_bridge_inventory_shadow_latest.json
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 scripts/m9_enrich_bridge_depth.py --chain base --inventory data/tmp/m9_bridge_inventory_shadow_latest.json --force-reprobe --verbose
py -3.11 scripts/bootstrap_productive_rpc_env.py -- py -3.11 -u -m m9.graph_arb.runner --chain base --config config/exotic_base_anchor.yaml --inventory data/tmp/m9_bridge_inventory_shadow_latest.json --duration-minutes 10 --productive-lane --require-factory-verified --quote-backend raw_http --quote-workers 1 --max-cycles-per-sweep 20 --artifact-path data/tmp/m9_graph_depth_truth_10m_v2.json
py -3.11 scripts/m9_quote_lane_diagnostic.py --artifact data/tmp/m9_graph_depth_truth_10m_v2.json --inventory data/tmp/m9_bridge_inventory_shadow_latest.json --output data/tmp/m9_quote_lane_rca_depth_truth_10m_v2.json --strict-consistency
```

## Root cause analysis: why the system does not see real pool sizes

The depth ladder measurement layer is now PROVEN at inventory level (281 sane depths > $100, up to $66k, `exact100` 297→2). The economics layer is blocked by an **admission topology bug**, not by measurement and not by the market.

### RC1 — static config gate discards the measured-depth universe (PRIMARY)

`m8/discovery/cross_dex_expand.py` sets `expansion_productive_admit = (dex_id in productive_dexes)` — a **static config flag** from `m9_dex_productivity.enabled_for_productive`, fully independent of measured depth.

`config/exotic_base_anchor.yaml` has `uniswap_v4.enabled_for_productive=false` ("admit via M8 sniper only until QSR proven"). All **416 of 656 routes are uniswap_v4 expansion routes** and carry `expansion_productive_admit=False`. These 416 rejected routes contain **327 measured depths, 300 MEASURED_CAPACITY, 278 sane > $100** — i.e. nearly the entire measured-depth universe the ladder just proved.

`m9/graph_arb/pool_quality.py::productive_admission_fail_reason` then rejects them (`expansion_productive_admit_false`). The flag's own rationale is obsolete: this session's force-reprobe quoted V4 successfully at probe level (`v4_ok=327/416`).

### RC2 — admitted graph is 91% depth-less

After admission: 191 routes, of which **174 have no depth** (maverick=120, balancer=37, curve=4, v3=12) and 17 have depth — all 17 with insane analytical values (see RC3). Every quoted cycle is therefore built from depth-less edges → `cycle.min_effective_depth_usd=None` → `depth_aware_known_rate=0.0` in runtime gates. This is why bridge `depth_known_rate≈0.60` and runtime `0.0` coexist: the admission filter inverts the depth distribution.

### RC3 — V3 analytical depth produces insane values

`m9/graph_arb/depth_capacity_probe.py::v3_liquidity_depth_lower_bound_usd` mis-scales Uniswap V3 `liquidity` (L is in sqrt-token units; the formula treats it as raw token units). Result: 14 routes with `effective_depth_usd` up to **$31T**. All 17 admitted routes WITH depth carry these garbage values, so even the surviving depth signal is unusable.

### RC4 — perverse depth gate rewards ignorance

`pool_quality.py::_depth_gate_ok`: route with `effective_depth_usd=None` **passes** admission; route with measured depth < $50 **fails**. The gate punishes measurement and admits unmeasured routes — the admitted set is systematically biased toward unknown depth, which then triggers the $0.05 micro-cap.

### RC5 — micro-cap arithmetic, not market verdict

`per_dex_sizing.py::productive_cycle_size_usd_cap`: cycle has a Maverick/Balancer/Curve leg AND no measured depth → size capped to **$0.05**. At $0.05 notional, fixed gas (~$0.06) = ~12,000 bps cost → `cost_adjusted_net_bps≈-12004` for every opportunity. This is deterministic arithmetic; no market data can change it while sizing stays at $0.05.

### RC6 — operator-facing log hides the cap

Runner logs `dynamic_size: [0.1]` because `round(0.05, 1) == 0.1`. Operators see $0.1 while actual quoted size is the $0.05 micro-cap.

### Secondary findings

- `per_dex_sizing.py::micro_ladder_for_family` is dead code (never called).
- M8 sniper contributes only 5/656 routes; `m8_stale=True` (age > 2.8h) — freshness, not sizing, blocker.
- Distinct quote lane: `BALANCER_UNKNOWN_REVERT_WITH_METADATA=206`, `MAVERICK_NO_LIQUIDITY=154` — independent adapter blocker that also forces failing legs into the micro path.

## Remediation plan (ordered)

1. **P0 — data-driven V4 productive admission.** Replace the static `expansion_productive_admit` reject with a depth-aware gate: admit expansion route when `depth_probe_status ∈ {MEASURED_CAPACITY, LOWER_BOUND_AT_MAX_PROBE}` AND sane `effective_depth_usd ≥ $50`. Alternatively flip `uniswap_v4.enabled_for_productive=true` (probe-level quote rate now proven, v4_ok=327/416) — prefer the depth-aware gate to keep the admission honest per-pool.
2. **P0 — fix `v3_liquidity_depth_lower_bound_usd`** scaling; add sanity cap (≤ $10M) and `ANALYTICAL_SUSPECT` status for out-of-range values; re-enrich the 14 poisoned rows.
3. **P1 — fix `_depth_gate_ok` asymmetry**: for distinct-pricing families require measured depth (or QUOTE_OK) instead of letting unknown-depth pass where measured-thin fails.
4. **P1 — log truthfully**: `round(s, 2)` in the dynamic_size sweep log.
5. **P1 — re-run 10m** after 1–3. Acceptance: `depth_aware_known_rate > 0`, at least one `market_size_usd ≥ $25`, `qsr_econ > 0`, `top_opportunities.effective_depth_usd` not None.
6. **P2 — adapter RCA**: Balancer `UNKNOWN_REVERT_WITH_METADATA` (206) and Maverick `NO_LIQUIDITY` (154) at leg level; do not touch gates for this.
7. **P2 — remove or wire `micro_ladder_for_family`** (dead code).
8. **P3 — fresh M8 sniper** before any production/profit claim chain.

## Decision

- **Measurement layer (ladder, force-reprobe): REACHED** — fresh runtime proof of real depth distribution (median sane ≈ $3.9k, max ≈ $66k).
- **Economics layer: BLOCKED** — admission topology discards the measured universe; sizing collapses to $0.05; net bps is a gas-arithmetic artifact.
- **No market verdict possible** until P0 items land. Longer soaks are pointless before that.
- `execution_enabled`: false | `kill_switch_active`: true
