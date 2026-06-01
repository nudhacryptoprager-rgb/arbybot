# DEV REPORT

## 0) Meta
timestamp_utc: 2026-06-01T09:58:47Z
goal_status: BLOCKED
blocker_status_after: TOPOLOGY_QUARANTINE_BLOCKED
docs_reread_confirmed: true
run_id: data/runs/_rolling
mode: ONLINE_BASE_PUBLICNODE_PLUS_OFFLINE_CI
artifact_mode: rolling
config: config/exotic_base_anchor.yaml

code_identity:
  primary: ts:2026-06-01T09:58:47Z
  dirty: true
  desc: |
    Session V4 depth/runtime validation. V4 Quoter ABI was corrected in
    pool_depth_probe.py and m8_1/stable_anchor/quote_probe.py. Base V4 quoter
    address is config-driven via config/dexes.yaml. M8->M8.1->M8.2->M9 was run
    on Base publicnode. V4 depth is now visible in bridge enrichment, but M9
    productive gate is blocked because the productive graph has zero cycles.

## 1) Scope

Goal: validate that the new V4 depth support is real at runtime, not only unit-level.

What changed:
- Added Base `uniswap_v4` quoter config in `config/dexes.yaml`.
- Corrected V4 quote ABI to `quoteExactInputSingle((PoolKey,bool,uint128,bytes)) -> (uint256 amountOut,uint256 gasEstimate)`.
- Added top-level dynamic-struct offset `0x20` for V4 calldata.
- Added V4 depth counters to bridge enrichment: `v4_depth_candidates`, `v4_depth_probe_ok`, `v4_depth_probe_failed`, `v4_depth_skipped_unsupported`.
- Added/updated tests around V4 encoding, decoding, missing quoter visibility, and enrichment metrics.

## 2) Commands Executed

```powershell
$env:ARBY_SNIPER_ENABLE='1'; $env:BASE_RPC='https://base.publicnode.com'
py -3.11 -u scripts/sniper_smoke_run.py --chain base --duration-minutes 2 --poll-interval-s 20 --blocks-back 100 --rpc-url https://base.publicnode.com --skip-self-test --skip-preflight
```

Result: PASS, 44 raw logs, 44 parsed, 44 candidates, 0 RPC errors.

```powershell
$env:BASE_RPC='https://base.publicnode.com'
py -3.11 -u scripts/m8_1_stable_anchor_run.py --config config/exotic_base_anchor.yaml --rpc-url https://base.publicnode.com --duration-minutes 2
```

Result: PASS, candidates=1144, passes=210, qsr=1.0000.

```powershell
py -3.11 -u scripts/m9_bridge_build.py --config config/exotic_base_anchor.yaml --registry data/runs/_rolling/m8_pending_pairs.json
py -3.11 -u scripts/m9_enrich_bridge_depth.py --chain base --verbose
```

Result: bridge OK, graph_ready_total=129; depth enrichment wrote V4 metrics.

```powershell
py -3.11 -u -m m9.graph_arb.runner --chain base --duration-minutes 15 --config config/exotic_base_anchor.yaml --quote-backend raw_http --inventory data/runs/_rolling/m9_bridge_inventory_latest.json --require-factory-verified --quote-workers 1 --productive-lane --dynamic-sizes
```

Result: BLOCKED, productive graph found 0 cycles.

```powershell
py -3.11 scripts/ci_m9_productive_gate.py
```

Result: FAIL as expected from zero-cycle productive artifact.

```powershell
py -3.11 -m pytest tests/unit -q
py -3.11 scripts/check_repo_safety.py
py -3.11 scripts/ci_full_pipeline.py --mode ci
```

Result: unit PASS (6358 passed, 6 skipped, 1 warning); safety PASS (2 pre-existing docs-bloat warnings); CI PASS.

## 3) Artifacts Used

- `data/runs/_rolling/new_pool_sniper_latest.json`
- `data/runs/_rolling/m8_1_stable_anchor_latest.json`
- `data/runs/_rolling/m8_pending_pairs.json`
- `data/runs/_rolling/m9_bridge_inventory_latest.json`
- `data/runs/_rolling/m9_graph_latest.json`
- `data/runs/m8_v4_chain_2m_stdout.log`
- `data/runs/m8_1_v4_chain_2m_stdout.log`
- `data/runs/m8_2_bridge_v4_chain_stderr.log`
- `data/runs/m8_2_depth_v4_chain_stderr.log`
- `data/runs/m9_v4_chain_productive_stderr.log`
- `data/runs/m9_v4_chain_discovery_stderr.log`

## 4) Key Results

| Layer | Evidence | Result |
|---|---:|---|
| M8 sniper | raw_logs=44, candidates=44, rpc_errors=0 | PASS |
| M8 dex mix | uniswap_v4=41, uniswap_v2=2, uniswap_v3=1 | V4 visible |
| M8.1 | candidates=1144, passes=210, qsr=1.0000 | PASS |
| M8.2 bridge | graph_ready_from_m8=29, graph_ready_total=129 | PASS |
| V4 depth enrichment | v4_candidates=4, v4_ok=3, v4_failed=1, skipped_v4=0 | PASS |
| M9 productive | cycles_found=0, qsr=0.0 | BLOCKED |
| M9 discovery comparison | found 5000 candidate cycles, quoted 600, qsr=0.1017 | discovery alive |
| Productive gate | runtime_gates.all_pass=false | FAIL |
| Unit suite | 6358 passed, 6 skipped | PASS |
| CI full pipeline | all required gates passed | PASS |

## 5) Interpretation

Progress:
- V4 is no longer blocked by `V4_DEPTH_UNSUPPORTED`.
- Live V4 quoter calls work after ABI correction.
- V4 depth telemetry is now visible in `m9_bridge_inventory_latest.json`.
- M8 sees fresh V4 pools and M8.2 promotes routes into the bridge.

Regression / blocker:
- M9 productive does not currently have a quoteable graph because quarantine leaves zero 3/4-hop cycles.
- Discovery mode still generates cycles, but quoted cycles are only `uniswap_v3`; V4/V2/ve33 routes are present as edges but do not participate in current cycle topology.
- Low qsr in the discovery comparison is not a provider 429 problem; it is denominator inflation from many unquoteable cycles.

## 6) Current Decision

Do not mark M9 productive as PASS. The correct status is:

`RUNTIME_VALIDATED__V4_DEPTH_VISIBLE__M9_PRODUCTIVE_TOPOLOGY_BLOCKED`

Next work should focus on cycle topology and productive-lane quarantine strategy, not on V4 ABI or RPC failover.
