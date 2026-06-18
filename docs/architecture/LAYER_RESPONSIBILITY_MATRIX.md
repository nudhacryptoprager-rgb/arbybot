# Layer Responsibility Matrix

> Canonical ownership boundaries for M8 → M9 pipeline layers.  
> Enforced in CI by `scripts/audit_layer_responsibility.py`.

| Layer | owns | may_read | must_not_do | artifact_out | acceptance_gate |
|-------|------|----------|-------------|--------------|-----------------|
| **M8** | new-pool discovery, sniper events, factory hints | config anchors | economics sizing, decimals authority, depth probes | `new_pool_sniper_latest.json` | sniper operational |
| **M8.1** | stable-anchor inventory, route health diagnostics | M8 hints, config | profit claims, token metadata authority | `m8_1_stable_anchor_latest.json` | anchor pass rate |
| **M8.2** | cross-DEX expansion, graph topology handoff | M8/M8.1, external hints (hint-only) | economics, depth authority, decimals authority | `m8_cross_dex_expansion_latest.json` | `m8_2_acceptance_report.py` |
| **M8.3** | token metadata registry (decimals/symbol/name) | M8/M8.1/M8.2 routes, core config, on-chain ERC20 | pool discovery, quote economics, depth | `m8_3_token_metadata_registry_latest.json` | `m8_3_acceptance_report.py --strict` |
| **M9** | graph build, depth enrich, quote/economics shadow | M8.3 registry (consume only), M8.2 handoff bridge | token metadata authority, on-chain decimals overwrite of M8.3 | `m9_graph_*.json`, bridge inventory | `m9_lane_acceptance_report.py` |

## M8.3 authority contract

After M8.2 handoff, **all economics-grade token decimals** must come from:

```text
m8_3_token_metadata_registry_latest.json
```

M9/bridge may apply **missing-only** legacy fallback for legs without M8.3 provenance. They must **not** overwrite fields with `token*_decimals_source` prefixed `m8_3_`.

## Depth vs metadata

| Concern | Owner |
|---------|-------|
| Token decimals / symbol / name | M8.3 |
| Pool effective depth / probe status | M9 (`m9_enrich_bridge_depth.py`) |
| Quote smoke / productive admission | M9 (post-bridge) |
| Graph handoff topology | M8.2 |
