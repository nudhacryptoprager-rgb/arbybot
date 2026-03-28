# PATH: docs/FILES_SUMMARY.md
# Current Repository Summary

## Snapshot

Current repo snapshot excluding `.venv/`, `venv/`, `archive/`, and runtime/data folders under `data/`:

- Python files: `303`
- Markdown files: `36`
- JSON files: `26`

Top-level distribution of Python files:

- `tests/`: `160`
- `scripts/`: `35`
- `strategy/`: `31`
- `core/`: `20`
- `dex/`: `12`
- `m4/`: `9`
- `discovery/`: `8`
- `execution/`: `7`
- `chains/`: `5`
- `engine/`: `5`
- `monitoring/`: `4`
- `config/`: `3`
- `cex/`: `2`

## Root

- `README.md`: minimal package readme; points to `docs/README.md`
- `Roadmap.md`: single source of truth for milestone order and release logic
- `AGENTS.md`: reviewer/lead contract for Codex sessions
- `start.py`: main online scanner entry point and orchestration shell
- `pyproject.toml`: package/build/test metadata
- `requirements-dev.txt`: developer dependencies
- `run_online_test.py`: small helper entry point
- `setting_claude.md`, `setting_timlid.md`: external agent/operator notes, not source of truth

## config/

This folder contains chain, DEX, token, and runtime intent/config inputs.

- `config/__init__.py`
- `config/cex.yaml`
- `config/chains.yaml`
- `config/core_tokens.yaml`
- `config/dexes.yaml`
- `config/fees.yaml`
- `config/intent.README.md`
- `config/intent.txt`
- `config/onboard_arbitrum_one_candidate.yaml`
- `config/onboard_base_profit.yaml`
- `config/onboard_base_stage1.yaml`
- `config/onboard_base_stage2.yaml`
- `config/onboard_linea_stage1.yaml`
- `config/onboard_mantle_stage1.yaml`
- `config/onboard_mantle_stage2.yaml`
- `config/onboard_scroll_stage1.yaml`
- `config/onboard_zksync_candidate.yaml`
- `config/pairs.py`
- `config/real_intent_arbitrum_one.yaml`
- `config/real_live_probe.yaml`
- `config/real_minimal.yaml`
- `config/real_roundtrip_probe.yaml`
- `config/real_roundtrip_probe_lowfee.yaml`
- `config/smoke_minimal.py`
- `config/strategy.yaml`

Current operationally important configs:

- `config/real_minimal.yaml`: canonical arb primary online scan
- `config/onboard_base_profit.yaml`: narrowed Base profit contour and current research lane
- `config/chains.yaml`: RPC, WS, Flashblocks, provider endpoints
- `config/dexes.yaml`: protocol anchors, adapter routing
- `config/core_tokens.yaml`: canonical token/address map

## core/

Core shared utilities, contracts, models, invariants, and environment helpers.

- `core/__init__.py`
- `core/artifact_invariants.py`: cross-artifact validation
- `core/auto_size.py`: size adjustment helpers
- `core/constants.py`: enums, defaults, execution truth gates
- `core/env.py`: environment access helpers
- `core/exceptions.py`
- `core/format_money.py`
- `core/gate_helpers.py`
- `core/json_io.py`
- `core/logging.py`
- `core/math.py`
- `core/models.py`: canonical runtime dataclasses
- `core/multicall.py`
- `core/no_data.py`
- `core/pool_keys.py`
- `core/reject_reasons.py`
- `core/repo_checks.py`
- `core/rpc_urls.py`
- `core/time.py`
- `core/validators.py`

## chains/

Chain-specific runtime services.

- `chains/__init__.py`
- `chains/block.py`: block-number helpers
- `chains/flashblocks.py`: Flashblocks watcher/read-path helpers
- `chains/l1_cost.py`: L1 gas cost modeling
- `chains/providers.py`: RPC provider failover/quarantine

## dex/

DEX registry, adapter dispatch, and ABI assets.

- `dex/__init__.py`
- `dex/gating.py`
- `dex/registry.py`
- `dex/uniswap_v2_pair.json`
- `dex/abi/__init__.py`
- `dex/abi/algebra_quoter.json`
- `dex/abi/erc20.json`
- `dex/abi/uniswap_v2_factory.json`
- `dex/abi/uniswap_v2_pair.json`
- `dex/abi/uniswap_v2_router.json`
- `dex/abi/uniswap_v3_factory.json`
- `dex/abi/uniswap_v3_pool.json`
- `dex/abi/uniswap_v3_quoter_v2.json`
- `dex/adapters/__init__.py`
- `dex/adapters/algebra.py`
- `dex/adapters/ambient.py`
- `dex/adapters/iziswap.py`
- `dex/adapters/syncswap.py`
- `dex/adapters/uniswap_v2.py`
- `dex/adapters/uniswap_v3.py`
- `dex/adapters/ve33.py`

## discovery/

Intent-driven universe construction and pool resolution.

- `discovery/__init__.py`
- `discovery/index_factories.py`
- `discovery/intent_loader.py`
- `discovery/pool_resolver.py`
- `discovery/quarantine.py`
- `discovery/registry.py`
- `discovery/runtime.py`
- `discovery/verify.py`

## engine/

Economics and opportunity truth layer.

- `engine/__init__.py`
- `engine/opportunity_engine.py`: seed/paper opportunity model
- `engine/roundtrip.py`: canonical measured roundtrip/sweep truth engine
- `engine/triangular_graph.py`: verified pool graph builder for M7.A
- `engine/triangular_cycles.py`: 3-hop triangular cycle discovery, measured scoring, size sweep, blocker and verdict support

## execution/

Execution infrastructure exists but remains disabled in production.

- `execution/__init__.py`
- `execution/dex_dex_executor.py`
- `execution/economics.py`
- `execution/gas_estimate.py`
- `execution/preflight.py`
- `execution/simulator.py`
- `execution/state_machine.py`

## m4/

M4 gate, evidence, policy, and rolling storage.

- `m4/__init__.py`
- `m4/cli.py`
- `m4/discovery.py`
- `m4/evidence.py`
- `m4/fixtures.py`
- `m4/gates.py`
- `m4/metrics.py`
- `m4/policy.py`
- `m4/rolling_store.py`

## monitoring/

Operator-facing observability layer.

- `monitoring/__init__.py`
- `monitoring/dashboard.html`
- `monitoring/dashboard_server.py`
- `monitoring/quality_kpis.py`
- `monitoring/truth_report.py`

## strategy/

Current main orchestration and runtime assembly layer. This is the heaviest application package.

- `strategy/__init__.py`
- `strategy/artifacts.py`: truth/scan/reject/near-breakeven/final report assembly
- `strategy/chain_stats.py`: per-chain accumulation and repeatability state
- `strategy/compat.py`
- `strategy/config.py`
- `strategy/dynamic_anchors.py`
- `strategy/dynamic_sweep_runtime.py`: executable sweep requotes
- `strategy/execution_probe.py`
- `strategy/gates.py`
- `strategy/infra.py`: WS, dirty-set, RPC env resolution, infra helpers
- `strategy/jobs/__init__.py`
- `strategy/jobs/run_paper.py`
- `strategy/jobs/run_scan.py`
- `strategy/jobs/run_scan_real.py`: primary online scan orchestrator
- `strategy/jobs/run_scan_smoke.py`
- `strategy/live_stream.py`
- `strategy/long_scan_summary.py`: multi-chain frontier ranking
- `strategy/pair_trace.py`
- `strategy/paper_trading.py`
- `strategy/quarantine.py`
- `strategy/quote_adapters.py`
- `strategy/quote_metrics.py`
- `strategy/quote_policy.py`
- `strategy/quote_rpc.py`
- `strategy/quotes.py`: quote collection and fallback path
- `strategy/rolling_outputs.py`
- `strategy/roundtrip_selection.py`
- `strategy/run_artifact_extract.py`
- `strategy/runtime_disabled.py`
- `strategy/scan_universe.py`
- `strategy/spreads.py`

## scripts/

Operational CLI, CI gates, verification, and maintenance tooling.

Core gate scripts:

- `scripts/check_repo_safety.py`
- `scripts/ci_docs_consistency.py`
- `scripts/ci_full_pipeline.py`
- `scripts/ci_m3_gate.py`
- `scripts/ci_m4_execution_gate.py`
- `scripts/ci_m4_gate.py`
- `scripts/ci_m5_0_gate.py`
- `scripts/ci_m5_gate.py`
- `scripts/ci_no_runtime_artifacts.py`

Operational/debug scripts:

- `scripts/inspect_rolling.py`
- `scripts/inspect_run_dir.py`
- `scripts/generate_daily_report.py`
- `scripts/generate_intent.py`
- `scripts/pair_level_rca.py`
- `scripts/run_coverage_batch.py`
- `scripts/prune_run_dirs.py`
- `scripts/cleanup_rolling.py`
- `scripts/validate_universe.py`
- `scripts/warm_pool_cache.py`
- `scripts/suggest_anchor_updates.py`
- `scripts/verify_anchors.py`
- `scripts/verify_tokens.py`
- `scripts/verify_v3_pools.py`
- `scripts/doc_sync_helper.py`

Low-level diagnostic helpers:

- `scripts/_analyze_pools.py`
- `scripts/_check_roundtrip.py`
- `scripts/_check_scan.py`
- `scripts/_check_unresolvable.py`
- `scripts/find_sushi_pools.py`
- `scripts/lint_readiness.py`
- `scripts/make_golden_daily_report.py`
- `scripts/update_golden_artifacts.py`

## docs/

Documentation is milestone-driven and source-of-truth driven.

Key docs:

- `docs/README.md`
- `docs/WORKFLOW.md`
- `docs/DOCS_POLICY.md`
- `docs/TESTING.md`
- `docs/TECH_DEBT.md`
- `docs/DEV_REPORT_CANONICAL_UA.md`
- `docs/DEV_REPORT_LATEST.md`
- `docs/FILES_SUMMARY.md`
- `docs/ONBOARDING_MATRIX.md`
- `docs/ISSUE_3_CHECKLIST.md`

Milestone/status docs:

- `docs/status/INDEX.md`
- `docs/status/ARCHIVE_MAP.md`
- `docs/status/Status_M0.md`
- `docs/status/Status_M1.md`
- `docs/status/Status_M2.md`
- `docs/status/Status_M3.md`
- `docs/status/Status_M4.md`
- `docs/status/Status_M5.md`
- `docs/status/Status_M5_0.md`

M4 contracts:

- `docs/m4/M4_POLICY.md`
- `docs/m4/ROLLING_CONTRACT.md`

Golden/canonical docs artifacts:

- `docs/artifacts/daily_report_golden.json`
- `docs/artifacts/pool_whitelist.json`
- `docs/artifacts/reject_histogram_golden.json`
- `docs/artifacts/roundtrip_canonical_golden.json`
- `docs/artifacts/scan_golden.json`
- `docs/artifacts/scroll_dex_audit.json`
- `docs/artifacts/truth_report_golden.json`
- `docs/artifacts/golden/real_m5_0_golden.yaml`
- `docs/artifacts/golden/m5_golden_run/...`
- `docs/artifacts/m4_golden_run/README.md`

## data/

Data is runtime-only except explicit golden fixtures under `docs/artifacts/`.

- `data/runs/_rolling/_latest.json`: canonical latest rolling summary
- `data/runs/_rolling/run_summary_latest.json`: canonical primary-chain rolling summary
- `data/runs/_rolling/m4_stability_agg.json`: rolling M4 aggregation window
- `data/runs/_rolling/long_scan_latest.json`: multi-chain frontier ranking
- `data/runs/_rolling/hot_loop_latest.json`: hot-loop/operator snapshot
- `data/cache/*.json`: runtime caches such as dynamic anchors and hot pairs
- `data/runs/<runDir>/...`: per-run reports and snapshots, not for Git

## tests/

Tests are the largest single Python surface in the repo.

- `tests/conftest.py`
- `tests/__init__.py`
- `tests/unit/`: `152` unit/regression/contract files
- `tests/integration/`: `3` integration files

Current test suite emphasis:

- artifact schema stability
- M4/M5/M5_0 gate behavior
- roundtrip and sweep truth contracts
- rolling summary contracts
- repo safety and docs policy
- milestone-specific regressions (`R38`, `R39`, `R39x+*`)

## Current Architectural Reading

At the current stage the repo is not a toy scanner. It is a layered research platform with:

1. A mature quote/discovery/data plane.
2. A canonical measured roundtrip truth engine.
3. Stable rolling operational artifacts.
4. Disabled but substantial execution scaffolding.
5. Very large regression coverage focused on contracts and milestone safety.

The main remaining complexity is not missing structure; it is that the strategy thesis on current public infrastructure has reached an economics ceiling before online profitable execution was achieved.
