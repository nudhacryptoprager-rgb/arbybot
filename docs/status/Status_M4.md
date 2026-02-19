# Status: M4 (DEX<->DEX Atomic Execution)

**Status**: M4 SIMULATE-ONLY ACTIVE (paper profit DIAGNOSTIC, rolling quality gate WARN_QUALITY, roundtrip NOT_PROFITABLE)  
**Updated**: 2026-02-19  
**Gate Version**: v2.3.2  
**Policy Version**: 2.0.8  
**Engine Version**: v2.3.0  
**Infra Evidence**: see [Status_M5_0.md](Status_M5_0.md) for multicall/failover/WS proof  
**Profit Truth**: `profit_is_diagnostic=true`, `profit_truth_source=ONE_LEG_DIAGNOSTIC`, **Clean PnL NOT AVAILABLE** (`execution_pnl.cost_model_available=false`)

> ⚠️ **M4 НЕ ЗАКРИТО**: `net_usdc` з rolling є DIAGNOSTIC, не canonical DEX↔DEX truth. Потрібен `execution_pnl.cost_model_available=true` та `profit_truth_source=ROUNDTRIP_REAL`.

## v2.3.2 M4-specific Fixes (2026-02-19)

| Step | Change | File | Description |
|------|--------|------|-------------|
| 1 | **provenance hardened** | `m4/gates.py` | Init `run_timestamp=None`, fallback chain |
| 2 | **WETH/DAI rollback** | `config/real_minimal.yaml` | DISABLED (SUSPECT_LIQUIDITY+PRICE_SANITY) |
| 3 | **disabled_pools extended** | `config/real_minimal.yaml` | sushiswap_v3_WETH_DAI_3000 quarantined |

> **NOTE**: M5_0 infra changes (multicall/failover/pool_missing_keys) moved to [Status_M5_0.md](Status_M5_0.md)

## Status Separation (v2.0.7)

| DoD | What it means | Current Status |
|-----|---------------|----------------|
| **Core Truth (paper +PnL)** | N>=5 REGISTRY_REAL runs with total_net_usdc > 0 | [OK] PROVEN |
| **Rolling Quality Gate** | data_run_rate >= 0.30, agg_status != FAIL | [WARN] WARN_QUALITY |
| **M4.2 Roundtrip Profit** | Round-trip with real leg2 re-quote has net_pnl > 0 | [NO] NOT_PROFITABLE |
| **M4.2 Real Execution** | On-chain TX with profit | [NO] NOT STARTED |

**Висновок**: Paper profit доведений (core truth), rolling quality gate = WARN_QUALITY (acceptable for M4.1). Round-trip валідований (truth_mode_m42=true for real_minimal.yaml, profit_realism_status=ROUNDTRIP_NOT_PROFITABLE). 

**Snapshot (2026-02-19 v2.3.2)**: From `m4_stability_agg.json` (canonical source): runs_in_window=73, data_run_rate=0.9863, pass_rate=1.0, **total_net_usdc=$3998.20**, unique_pairs=8, **unique_routes=4** (**unique_routes_cross_dex=2** < target=4 -> WARN). POOL_DISABLED=6, POOL_MISSING=3 (UNI/WETH+GMX/USDC on Sushi - expected, pools don't exist). ws_connected=true, preflight.passed=true, **execution_ready_count=0** (kill_switch_active=true), **would_execute_count=0** (roundtrip NOT_PROFITABLE), quarantine_stats in artifacts. Provenance: v2.3.2 fix - `run_timestamp` now read from runDir scan artifact (no more NEW timestamp generation in rolling). **pool_missing_keys** now in scan.stats for observability. **WETH/DAI DISABLED** (v2.3.2 - SUSPECT_LIQUIDITY + PRICE_SANITY_FAILED on Sushi, needs quoter path investigation). **Clean PnL NOT AVAILABLE** (`execution_pnl.cost_model_available=false`). **profit_is_diagnostic=true** (M5_0 simulate_only mode). **field_success_rates=1.0** (all fields) after pool address fix.

> **NOTE: DIVERSITY_ROUTES_LOW (2 DEX limitation)**: With 2 active DEXes (uniswap_v3+sushiswap_v3), `unique_routes_cross_dex` maximum = 2. Policy target = 4 requires adding 3rd DEX with working quoter (camelot_v3 in real_expanded.yaml pending Algebra quoter integration).

**Evidence (ci_m5_gate_20260219_144126 - v2.3.2 run)**: `scan.infra.provider_id=alchemy`, `scan.infra.multicall.requested_fields=[slot0, liquidity, token0, token1, decimals, fee]`, `scan.infra.multicall.field_success_rates={slot0:1.0, liquidity:1.0, token0:1.0, token1:1.0, decimals:1.0, fee:1.0}`, `scan.infra.provider_router.endpoints_used=[alchemy]`, `truth_report.execution_ready_count=0`, `truth_report.would_execute_count=0`, `truth_report.profit_is_diagnostic=true`, `truth_report.profit_truth_source=ONE_LEG_DIAGNOSTIC`, `truth_report.profit_realism_status=ROUNDTRIP_NOT_PROFITABLE`, `run_context.run_timestamp=2026-02-19T13:41:47.819823+00:00`. **v2.3.2 additions**: `scan.stats.pool_missing_keys=[]`, `scan.stats.pool_missing_keys_total=0` (observability), provenance fix hardened (fallback chain). `intent_forced` runtime confirmed working (28 pairs with universe_source=intent_forced).

**Failover Evidence (ci_m5_gate_20260219_103811 - stress run)**: `--failover-stress 3` mode. `endpoints_used_count=2`, `endpoints_used=[alchemy, arbitrum_public]`, `failover_stress_active=true`, `requests_by_endpoint={alchemy_3470f46a:1, arbitrum_public_9722a04c:1}`, `errors_by_endpoint={alchemy_3470f46a:1}`, `stress_test_fails(alchemy)=1`. **Proof**: Primary endpoint (alchemy) had simulated failure, router successfully failed over to secondary (arbitrum_public). `field_success_rates={slot0:0.9211, liquidity:0.9474, token0:0.9474, token1:0.9474, decimals:1.0, fee:0.9211}` (rates < 1.0 due to UNI/WETH wrong pool addresses at that time, fixed in v2.3.0).

**Quality Note**: 
- **Per-run** (`run_summary_latest.quality_reasons`): `WARN_EXCLUDED_SIGNALS, WARN_CRITICAL_REJECTS, WARN_TOP_PAIR_DOMINANCE`
- **Window-level** (`_latest.agg_reasons`): `DIVERSITY_PAIRS_LOW` (unique_pairs=8 < 10), `DIVERSITY_ROUTES_LOW` (**unique_routes_cross_dex=2** < target=4, NOT unique_routes)
- See `data/runs/_rolling/run_summary_latest.json` (runDir: ci_m5_gate_20260219_144126).
- **Clean PnL NOT AVAILABLE**: `execution_pnl.cost_model_available=false`, cannot claim "canonical realized net PnL". `metrics.total_net_usdc` is diagnostic only.
- **v2.3.2 deferred**: Sushi PRICE_SANITY_FAILED diagnostic, WETH/DAI rollback until quoter path investigation complete.

**Anchor Discipline (v2.1.0-fix enforced):**
> Anchors MUST come from on-chain evidence (median valid quotes from runDir artifacts), NOT from market intuition.
> Bad pools get REMOVED/quarantined, NOT "fixed" by artificially raising anchors.
> If a pool returns extreme prices (e.g., WBTC/WETH sushi fee=500 returns `price_exact~3.4e28` at tick=887271 vs anchor 35), it's a bad pool, not a bad anchor.
> Evidence source: `data/runs/ci_m5_gate_*` scan artifacts → median price from valid quotes per pair.

**Quarantined Pools (v2.1.0-fix, 2026-02-18):**

> **Migration (v2.1.0-fix)**: Manual comment-out pools deprecated. Now using `disabled_pools:` section in YAML (machine-readable quarantine with reasons).

| Pool | Address | Reason | Evidence Run |
|------|---------|--------|--------------|
| sushiswap_v3_WBTC_WETH_500 | 0xf790... | tick=887271, price_exact~3.4e28 | ci_m5_gate_20260217_103807 |
| sushiswap_v3_LINK_USDC_3000 | 0x7e039... | price_exact~19.9 vs anchor 9.0 | ci_m5_gate_20260217_103807 |
| uniswap_v3_GMX_WETH_500 | 0xb435... | price_exact~0.00323 vs anchor 0.008 | ci_m5_gate_20260217_113317 |
| uniswap_v3_GMX_WETH_3000 | 0x1aEE... | price_exact~0.00327 vs anchor 0.008 | ci_m5_gate_20260217_113317 |
| sushiswap_v3_ARB_USDC_3000 | 0x14716... | price_exact~1.009 vs anchor 0.11 (inverted) | ci_m5_gate_20260217_113317 |

**Next Focus**: M5_0 always-online data-plane (WS + Alchemy + multicall) + dynamic anchors + runtime auto-quarantine via `strategy/quarantine.py`.

**Anchor values (from on-chain evidence 2026-02-17):**
| Pair | Old Anchor | New Anchor | Evidence |
|------|------------|------------|----------|
| WETH_USDC | 2800 | 1980 | median valid ~1977 |
| WETH_USDT | 2800 | 1980 | median valid ~1978 |
| WBTC_USDC | 98000 | 68000 | median valid ~68019 |
| ARB_WETH | 0.00035 | 0.000058 | median valid ~0.0000576 |
| ARB_USDC | 0.70 | 0.11 | median valid ~0.114 |
| GMX_WETH | 0.012 | 0.008 | sushi valid ~0.0084 |
| LINK_WETH | 0.0055 | 0.0045 | median valid ~0.0044 |
| wstETH_WETH | 1.15 | 1.20 | median valid ~1.22 |
| LINK_USDC | 11.0 | 9.0 | median valid ~8.79 |

**Result**: PRICE_SANITY_FAILED reduced from 12 → 5 (remaining are legitimate bad pools).  

## Roadmap Progress Mapping (v2.1.0-fix)

> **Clarification**: M4 in Roadmap.md = "Execution v1 (DEX↔DEX atomic)". This section maps actual progress to Roadmap.

| Roadmap Component | Description | Status |
|-------------------|-------------|--------|
| **Milestone 3** | Truth Engine / Opportunity Detection | [OK] MOSTLY CLOSED |
| **M4: Pre-trade simulation gate** | Paper-profit simulation with realistic costs | [OK] CLOSED (profit_realism via roundtrip) |
| **M4: Execution state machine** | `execution/state_machine.py` with TX lifecycle | [IN PROGRESS] stub exists, not wired to pipeline |
| **M4: Private send / bundle** | Flashbots/Bloxroute bundle submission | [NO] NOT STARTED |
| **M4: Post-trade realized accounting** | Compare simulated vs actual on-chain PnL | [NO] NOT STARTED |
| **M4: On-chain atomic swap** | Real DEX↔DEX TX with profit | [NO] NOT STARTED |

> **v2.1.0-fix Note**: Execution state machine now has `simulate_trade_execution()` stub that:
> - Runs simulation flow (PENDING → SIMULATING → SIM_PASSED/SIM_FAILED)
> - Checks ExecutionContext with kill_switch_active=True by default
> - Records would_execute + blocker for diagnostics
> This is NOT real execution - just validates the ex path with safety controls.

> **Note**: ROUNDTRIP_NOT_PROFITABLE is expected behavior — it means pre-trade simulation correctly identifies no arb opportunity in current market conditions. This is NOT a blocker for "pre-trade simulation gate" (working as designed), but IS a blocker for "execution readiness" (we won't execute losing trades).

## [WARN] PROFIT REALISM WARNING (v2.1.0)

**Paper profit PROVEN** under simulated cost model (`gas=$0.10`, `slippage=5bps`).  
**Profit realism NOT PROVEN** - round-trip shows actual losses:

1. **ROUNDTRIP real_quote_count=3, profitable_count=0**: всі roundtrip opportunities NOT_PROFITABLE
2. **BEST roundtrip: net_pnl_bps=-65.1** (WETH/USDC, uniswap_v3->sushiswap_v3)
3. **SUSPECT_SPREAD signals excluded (v2.0.4)**: Spread > 500bps triggers `is_excluded_spread=true`
4. **TOP_PAIR_NET_SHARE check active (v2.0.4)**: Single pair > 80% of net profit -> `FAIL_TOP_PAIR_DOMINANCE`
5. **Unified gas model (v2.1.0)**: L2+L1 overhead в roundtrip та opportunity_engine
6. **L1 fee parameterized**: `l1_data_gas_units=2000`, `l1_gas_price_gwei=30.0` в config

**M4.2 Blockers**:
- Roundtrip profitable_count=0 (actual market has no arb opportunity currently)
- Need to expand pairs/routes diversity (unique_pairs=6, unique_routes_cross_dex=2)
- ~~`tokens_anchor_price` outdated~~ **FIXED** (2026-02-17): All anchors updated from on-chain evidence

Until roundtrip shows profitable_count > 0, M4.2 profit = "paper profit under declared cost model", NOT "realistic profit".

## M4.2 Profit Truth Definition (v2.1.0)

> **FORMAL DEFINITION (binding):**
> When `truth_mode_m42=true` in config:
> - **Canonical profit** = Round-trip net_pnl_wei (leg1 + leg2 via QuoterV2, minus gas L2+L1)
> - **One-leg gross/net** = DIAGNOSTIC ONLY (not used in gating decisions)
> - **profit_realism_status** = mandatory field in truth_report (ROUNDTRIP_PROFITABLE | ROUNDTRIP_NOT_PROFITABLE | ONE_LEG_ONLY_DIAGNOSTIC)
> - **Roundtrip NOT_PROFITABLE is not a bug** — it means Truth Engine correctly detects no real arb opportunity

| Model | Description | Status |
|-------|-------------|--------|
| **One-leg spread** | `price_a / price_b` across DEX | DIAGNOSTIC ONLY |
| **Round-trip quoter** | `token_in -> token_out -> token_in` via QuoterV2 | [OK] Callback ready, leg2 re-quote wired |
| **Live gas** | `eth_getGasPrice` + WETH/USDC live price | [OK] In opportunity_engine + roundtrip |
| **Live slippage** | `(small_quote - target_quote) / target_quote` | [TODO] probe_slippage() ready, artifact integration pending |

**Reality Gates in Effect (v2.1.0):**
| Gate | Source | Threshold | Status |
|------|--------|-----------|--------|
| `PRICE_SANITY_FAILED` | `strategy/quotes.py` via `core.validators.check_price_sanity` | `price_sanity_max_deviation_bps` | [OK] CONNECTED (quoter-path) |
| `SUSPECT_LIQUIDITY` | `strategy/quotes.py` | `ticks>15` or `gas>500k` | [OK] ACTIVE |
| `SUSPECT_SPREAD_HARD` | `engine/opportunity_engine.py` | `spread > SUSPECT_SPREAD_BPS_HARD` (500bps) | [OK] ACTIVE |
| `NOTIONAL_DRIFT` | `engine/opportunity_engine.py` | `|notional - target| / target > max_drift%` | [OK] ACTIVE |
| `MIXED_SOURCE` | `engine/opportunity_engine.py` | one leg quoter_v2, one leg slot0 | [OK] v2.1.0 ACTIVE |
| `SLOT0_DIAGNOSTIC` | `engine/opportunity_engine.py` | both legs slot0 | [OK] v2.1.0 ACTIVE |

**M4.2 Quote Source Policy:**
| Source | When Used | M4.2 Status |
|--------|-----------|-------------|
| `quoter_v2` | QuoterV2 call success | [OK] CANONICAL for profit |
| `slot0` | QuoterV2 fails/unavailable | DIAGNOSTIC ONLY (excluded from gated top-N) |
| `mixed` | One leg quoter, one leg slot0 | REJECTED (no mixed-source opportunities) |

> **M4.2 NOTE**: slot0 fallback quotes are collected for diagnostics but NOT used in opportunity gating.
> Opportunities require BOTH legs to have `quote_source=quoter_v2`.

## Core Truth (from Roadmap.md)

> **M4 execution gate є "core truth" для релізу.**

| DoD Level | Criterion | Evidence Required | Status |
|-----------|-----------|-------------------|--------|
| **M4.1 Simulate-only** | Code/schema/invariants | FIXTURE_OFFLINE or REAL with simulate_only=true | [OK] PROVEN |
| **M4 Online Profit (core truth)** | Real profitability | `run_mode=REGISTRY_REAL`, N>=5 runs with `total_net_usdc > 0` | [OK] PROVEN |
| **Rolling Quality Gate** | Operational stability | `data_run_rate >= 0.30`, `agg_status != FAIL` | [WARN] WARN_QUALITY |

**Clarification (v2.0.6):**
> "Core Truth" (+PnL) != "Rolling Quality Gate". Core truth підтверджує що система генерує profit (paper).
> Rolling quality gate перевіряє стабільність в операційному режимі.
> agg_status=FAIL означає проблеми з якістю даних, НЕ відсутність profit.

**RunMode Canonical (v2.0.1):**
> `REGISTRY_REAL` is the canonical run_mode for online scanning.
> Legacy docs may use `REAL` as shorthand but artifacts MUST use `REGISTRY_REAL`.

**M4-profit DoD (посилання на Roadmap.md L52-62):**
> See `Roadmap.md` for canonical DoD definition.
> Quick ref: N>=5 runs in `m4_stability_agg.json.runs[]` with:
> `run_mode=REGISTRY_REAL`, `pinned_block!=429900000`, `block_is_synthetic=false`, `total_net_usdc>0`

**Evidence for M4 online-profit (v2.1.0-fix rolling snapshot post-quarantine, 2026-02-17):**

> **CORE TRUTH: PROVEN** (+PnL confirmed in N>=5 runs)
> **ROLLING QUALITY: WARN_QUALITY** (data_run_rate=1.0, diversity warnings remain)

| Metric | Value | Source |
|--------|-------|--------|
| runs_in_window | 53 | `_latest.json` |
| data_runs_count | 53 | `runs_since_timestamp.data_runs_count` |
| pass_count | 53 | `runs_since_timestamp.pass_count` |
| total_net_usdc (window) | $3202.51 | `quick_stats.total_net_usdc` |
| avg_net_usdc | $60.42 | `quick_stats.avg_net_usdc` |
| data_run_rate | 1.0 | `quick_stats.data_run_rate` |
| pass_rate | 1.0 | `quick_stats.pass_rate` |
| unique_pairs | 6 | `quick_stats.unique_pairs` |
| unique_routes_cross_dex | 2 | `quick_stats.unique_routes_cross_dex` |
| agg_status | WARN_QUALITY | `_latest.json` |
| agg_reasons | DIVERSITY_PAIRS_LOW, DIVERSITY_ROUTES_LOW | `_latest.json` |

> **v2.0.8 VERIFIED**:
> - `quotes_total >= quotes_fetched` in scan_*.json: OK (28/28)
> - `unique_routes_cross_dex=2` exists in rolling quick_stats: OK
> - `policy_version=2.0.8` in rolling: OK
> - DIVERSITY_ROUTES_LOW now uses unique_routes_cross_dex (2<4), not unique_routes (4)

> **DIVERSITY_ROUTES_LOW (v2.0.8)**: Очікуваний WARN до інтеграції 3-го DEX.
> Метрика routes = `unique_routes_cross_dex` (cross-DEX тільки). Target 4 потребує 3-го DEX (M5).

> **Why agg_status=WARN_QUALITY and Core Truth=PROVEN?**
> - 38 з 68 runs мають >=3 included signals (data runs)
> - Всі 38 data runs є прибуткові (pass_count=38, fail_count=0)
> - Core Truth: система генерує profit (total_net_usdc=$1166.16)
> - data_run_rate=0.5588 >= 0.50 threshold (QUALITY TARGET MET)
> - v2.0.8: Fixed fee_tiers iteration, QUOTE_ZERO_OUT gate, unique_routes_cross_dex, DIVERSITY_ROUTES uses cross_dex

> Source: `data/runs/_rolling/_latest.json`, `data/runs/_rolling/m4_stability_agg.json`
> Policy Version: 2.0.8 | Status Domain: status=NO_DATA|PASS|FAIL; quality_status=NO_DATA|PASS|WARN|FAIL_QUALITY

## Version Discipline (v2.1.0-fix)

| Track | Version | Scope | Notes |
|-------|---------|-------|-------|
| **Policy Version** | 2.0.8 | Thresholds, gates, DoD rules | v2.1.0-fix: WBTC pairs re-enabled (10 pairs total) |
| **Gate Version** | 2.1.0 | ci_m4_execution_gate.py, ci_m5_0_gate.py | v2.1.0-fix: --refresh-rolling-strict |
| **Engine Version** | 2.1.0-fix | quotes.py, run_scan_real.py, roundtrip.py | Decimal fix, gas_override, L1 calldata |
| **Schema Version** | 3.2.0 | Artifact JSON structure | Backward compatible |

> **v2.1.0-fix Engine Changes**:
> - `calculate_price_from_sqrt()`: `Decimal(10)**exp` prevents overflow for WBTC (8 decimals)
> - `simulate_roundtrip()`: `gas_override` parameter, `gas_source` field in result
> - `get_l1_cost_with_source()`: Pass representative swap calldata for accurate L1 estimate
> - `simulate_trade_execution()`: M4.3 dry-run stub with kill_switch=True default
> - `emit_rolling_artifacts()`: Deterministic run_summary selection (sort by timestamp)
> - Config: WBTC/WETH and WBTC/USDC re-enabled, 10 pairs total

## Docs Truth Map

| Document | Purpose | Source of Truth For |
|----------|---------|---------------------|
| `Roadmap.md` | Master plan, DoD definitions | Release criteria, feature priorities |
| `docs/status/Status_M4.md` | M4 milestone status | Current state, blockers, policy version |
| `docs/m4/ROLLING_CONTRACT.md` | Rolling artifact schemas | JSON structure, field semantics |
| `data/runs/_rolling/*` | Operational artifacts | Runtime metrics, provenance |

## Workflow (v2.0.0 - SHA-free)

| Mode | Description | Provenance |
|------|-------------|------------|
| **DEV** | Fast iteration cycle | run_timestamp only |
| **RELEASE** | Public proof | run_timestamp + rolling artifacts |

**Provenance Policy (v2.0.0):**
> SHA tracking completely removed.  
> `run_context.run_timestamp` is the primary provenance field.  
> `code_sha`, `evidence_sha` fields are None (deprecated).

**DEV Mode:**
- No SHA tracking or commit binding
- run_timestamp recorded for each run
- Minimal bundle: `_latest.json`, `run_summary_latest.json`, `m4_stability_agg.json` + runDir
- Use for rapid development and debugging

**RELEASE Mode:**
- Rolling artifacts with run_timestamp
- Use for milestone claims

## Docs Freeze Rules (v2.0.1)

**Зміни DoD/контрактів дозволені лише при:**
1. Зміні коду/скриптів, що вимагає нового контракту
2. Оновленні `docs/m4/ROLLING_CONTRACT.md` з новою схемою
3. Прикладі у rolling/runDir artifacts, що демонструє нову структуру

**Policy Version Discipline:**
- `policy_version` у `m4/policy.py` MUST змінюватись при будь-якому зсуві порогів `MIN_*`
- `policy_version` у rolling артефактах MUST дорівнювати `policy.py`
- Розбіжність = FAIL для release gates  

## Taxonomy Contract (v1.12.0)

| Reason Prefix | Status Required | Semantic |
|---------------|-----------------|----------|
| `FAIL_*` | status=FAIL | Hard failure, blocks passage |
| `WARN_*` | status=PASS allowed | Warning, quality concern |
| `NO_DATA` | status=NO_DATA | signals_count == 0 only |

**Invariant**: If `FAIL_*` appears in reasons, status MUST be FAIL. Enforced by `compute_status()`.

## Status Contract (v1.11.0+)

| Condition | Status | Semantic |
|-----------|--------|----------|
| `signals_count == 0` | NO_DATA | True absence of data |
| `signals > 0, net > 0` | PASS | Profitable (quality may warn) |
| `signals > 0, net <= 0` | FAIL | Unprofitable |
| `signals < 5` | quality_status=WARN | Low sample (not NO_DATA) |

**Rule**: NO_DATA only when signals_count == 0. Low sample -> WARN, not NO_DATA.

## Run Kinds (v1.11.0)

| Kind | Description | Counted in KPIs |
|------|-------------|-----------------|
| NORMAL | Regular online scan | [YES] Main KPIs |
| COVERAGE | Coverage batch run | [NO] Separate stats |
| SMOKE | Smoke test | [NO] Excluded |
| OFFLINE | Offline fixture | [NO] Excluded |

## Rolling KPIs (Targets)

| Metric | Target | FAIL | Description |
|--------|--------|------|-------------|
| `data_run_rate` | >= 0.50 | < 0.30 | % NORMAL runs with >=MIN_SIGNALS_FOR_PASS signals (v2.0.1: 3) |
| `fail_rate` | <= 0.10 | > 0.15 | % FAIL runs (v1.12.0 bites) |
| `fragile_rate_p90` | <= 0.30 | > 0.50 | p90 fragile rate |
| `unique_pairs` | >= 10 | < 3 | Pair diversity |
| `unique_routes` | >= 4* | < 2 | Route diversity |

**Diversity Targets Decision (v2.0.1, 2026-02-13):**
> `unique_routes >= 4` структурно недосяжно з 2 DEX (Uniswap V3 + SushiSwap V3).
> - **M4 online profit DoD**: `unique_routes=2` прийнято як достатнє (WARN_QUALITY допускається)
> - **M5 target**: `unique_routes >= 4` вимагає 3-й DEX adapter (Camelot, Curve, або інший)
> - **unique_pairs >= 10**: досяжно через верифікацію додаткових пулів (LINK/USDC, ARB/USDT, LINK/USDT)

## Thresholds (v2.0.1)

| Threshold | Value | Description |
|-----------|-------|-------------|
| `MIN_SIGNALS_FOR_PASS` | 3 | v2.0.1: lowered from 5 (real market ~3 signals) |
| `MIN_SIGNALS_WARN` | 2 | v2.0.1: lowered to match |
| `MAE_WARN` | 0.55 | MAE warning |
| `MAE_FAIL` | 0.80 | MAE failure |
| `SIGN_RATE_MIN` | 0.60 | Min sign correct rate |
| `AGG_FAIL_RATE_FAIL` | 0.15 | v1.12.0: fail_rate > 15% -> FAIL |
| `DIVERSITY_PAIRS_MIN` | 3 | v1.12.0: < 3 pairs -> FAIL |
| `DIVERSITY_ROUTES_MIN` | 2 | v1.12.0: < 2 routes -> FAIL |

### Policy Version Note (v2.0.1, 2026-02-12)
**BREAKING CHANGE**: З 2026-02-12 (v2.0.1) `MIN_SIGNALS_FOR_PASS=3` (було 5). Це означає:
- KPI `data_run_rate` та `low_sample_rate` рахуються від нового порогу
- Попередні значення (до v2.0.1) **несумісні** без перерахунку

### Acceptable States (agg_status)

| agg_status | DEV | RELEASE | Actions |
|------------|-----|---------|---------|
| `PASS` | [OK] | [OK] | Continue to next milestone |
| `WARN_QUALITY` (only DIVERSITY_*) | [OK] | [WARN] TEMP OK | Expand config to reach diversity targets |
| `WARN_QUALITY` (DATA_RUN_RATE/LOW_SAMPLE) | [WARN] | [FAIL] | Acceptable for M4.1 DEV, improve for RELEASE |
| `FAIL` | [FAIL] | [FAIL] | Fix underlying issues |
| `PASS_WARMUP` | [OK] | [WAIT] | Accumulate >=10 runs |

**TEMPORARY RULE (expires when targets met):**
> `WARN_QUALITY` з тільки `DIVERSITY_PAIRS_LOW` та/або `DIVERSITY_ROUTES_LOW` приймається як PASS-еквівалент для:
> - M4.1 simulate-only DoD
> - M4 online profit DoD (N>=5 runs proof)
>
> Це НЕ застосовується до M4.2 real execution DoD.
>
> **M4 Exit criteria (v2.0.6, 2026-02-13 - 42 runs in window):**
> - `unique_pairs`: 3/10 - потребує більше verified pools (LINK/USDT, GMX/USDC тощо)
> - `unique_routes`: 2/4 - затверджено як M4-ціль (з 2 DEX більше неможливо)
> - `data_run_rate`: 0.4878 >= 0.30 (threshold met, target 0.50 pending)
>
> **Diversity Decision (2026-02-13):**
> - M4 ok з `unique_routes=2` - більше з 2 DEX неможливо
> - `unique_pairs` target (10) переноситься в M5 як окреме requirements
> - Поточний `unique_pairs=3` достатній для M4 simulate-only proof (threshold >=3)
>
> **M5 Target (deferred):**
> - `unique_routes >= 4`: потребує 3-й DEX (Camelot, Curve)
> - `unique_pairs >= 10`: потребує verified pools для GMX, wstETH, etc.

## Canonical Commands

```bash
# Coverage batch (COVERAGE kind)
python scripts/run_coverage_batch.py --min-signals-target 30 --max-seconds 600 --profile profit

# M4 gate (profit, require-clean by default)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# Allow dirty worktree (dev only)
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --allow-dirty

# Check rolling KPIs
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "data_run_rate|no_data_rate|signals_per_run_p50"

# Reset window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window
```

## Rolling Artifacts

| File | Purpose |
|------|---------|
| `_latest.json` | Latest run pointer |
| `run_summary_latest.json` | Full run summary |
| `m4_stability_agg.json` | Rolling aggregator (segmented by run_kind) |

Location: `data/runs/_rolling/`

## Definition of Done

### M4.1: Simulate-Only -- [OK] PROVEN
- [x] Online scan generates signals
- [x] Simulator calculates PnL
- [x] Rolling artifacts persist
- [x] Evidence workflow works
- [x] agg_status = WARN_QUALITY (only DIVERSITY_*) accepted per Acceptable States table

### M4 Online Profit (core truth) -- [OK] PROVEN
- [x] N>=5 consecutive online runs with run_mode=REGISTRY_REAL (52 runs total, 24 data runs)
- [x] All data runs have total_net_usdc > 0 (pass_count=24, fail_count=0)
- [x] All runs use real pinned_block (not 429900000)
- [x] Paper profit confirmed under declared cost model
- [x] total_net_usdc (window): $416.18

**Rolling Quality Gate -- [WARN] WARN_QUALITY (v2.0.7, 2026-02-13):**
- [x] data_run_rate >= 0.30 (current: 0.4615 [OK])
- [x] agg_status != FAIL (current: WARN_QUALITY [OK])

**Поточні WARN причини (не блокують M4.1):**
> - FRAGILE_P90_ELEVATED
> - LOW_SAMPLE_RATE_ELEVATED (0.54 > 0.50)
> - DATA_RUN_RATE_WARN (0.46 < 0.50 target, але >= 0.30 threshold)
> - DIVERSITY_PAIRS_LOW (3 < 10 target)
> - DIVERSITY_ROUTES_LOW (2 < 4 target)
>
> Всі ці WARN прийнятні для M4.1 simulate-only per "Acceptable States" policy.

**Наступна ціль (M5 target):**
> 1. data_run_rate >= 0.50
> 2. unique_pairs >= 10
> 3. unique_routes >= 4 (requires 3rd DEX)

### M4.2: Real Execution -- [NO] NOT PROVEN
- [ ] Kill switch disabled
- [ ] Real TX submitted
- [ ] On-chain profit recorded

**Pre-flight checklist before M4.2:**
> Перед переходом до atomic execution (kill switch off) обов'язково виконати:
> 1. **Sanity-check cost model**: перевірити чому `net_usdc` однаковий у всіх 11 runs (~123 USDC)
> 2. **Reject breakdown analysis**: перегляд `reject_histogram` для прихованих edge cases
> 3. **Fragile/MAE distribution**: переконатися що MAE=0.5 реальний, а не артефакт фікстур
> 4. **Pool verification**: запустити `python scripts/verify_v3_pools.py` для всіх production pairs
> 5. **Gas estimation validation**: порівняти `estimated_gas` vs `actual_gas` з Tenderly trace
>
> Цей чек-ліст прив'язаний до Roadmap: M4 -> Execution v1 -> "Pre-trade simulation gate"

## Known Blockers (2026-02-13)

1. **Python version**: Pipelines running under Python 3.14, repo requires 3.11
2. ~~**Chain/provider mismatch**~~: FIXED - `.env` NETWORK=mantle corrected to arbitrum
3. ~~**Online scan unusable**~~: FIXED - quotes=10, dexes=2, spreads=2 achieved
4. ~~**Rolling artifacts need reset**~~: FIXED - v2.0 schema with timestamp-based provenance
5. ~~**Provenance fixes in v1.12.2**~~: REPLACED by v2.0.0 timestamp provenance
6. ~~**M4.1 quality thresholds**~~: RESOLVED (v2.0.6) - data_run_rate=0.4878, low_sample_rate=0.5122 with MIN_SIGNALS_FOR_PASS=3
7. ~~**M4 online profit DoD**~~: PROVEN (2026-02-13) - 42 real runs with total_net_usdc=$300.87
8. **DIVERSITY targets**: unique_pairs=3 (<10 target), unique_routes=2 (<4 target) - causes WARN_QUALITY
   - **Decision (v2.0.6)**: Accept `unique_routes=2` as M4.1 minimum. Target of 4 requires 3rd DEX (e.g., Curve, Camelot).
   - Pairs expansion: Add verified pairs (LINK/USDC, ARB/USDT) to `config/real_expanded.yaml` once pools verified.
   - Full diversity targets deferred to M5 when 3rd DEX adapter available.
9. **[WARN] PROFIT REALISM NOT PROVEN (v2.0.3)**:
   - Current paper model uses `gross_pnl = size_usd * spread_bps / 10000` -- **no price impact**.
   - **Evidence of bug**: LINK/WETH spread ~1133 bps (11.3%) between UniV3 and SushiV3 same block.
   - **Root cause**: SushiV3 LINK/WETH pool has ~8 million times less liquidity than UniV3 (7.8e14 vs 6.6e21).
   - **Impact**: $1000 trade on SushiV3 would have catastrophic slippage, but model shows +$113 profit.
   - **Mitigation (v2.0.3)**: `SUSPECT_SPREAD` flag for spreads > 300 bps, excluded from DoD at > 500 bps.
   - **Required for M4.2**: quoter-based PnL model with real `amountOut` queries.
   - **DO NOT proceed to M4.2 execution until quoter/impact model validated.**

**Next focus**: Rolling quality improvement to target (data_run_rate >= 0.50, low_sample_rate <= 0.50) via continued expanded config runs.

**Next engineering focus**: Diversity expansion (unique_pairs -> 10, unique_routes -> 4 via 3rd DEX) + pool verification for LINK/USDC, ARB/USDT.

### v2.0.0 Provenance Model
- SHA tracking completely removed (`code_sha`, `evidence_sha` = None)
- `run_timestamp` (ISO-8601) is the primary provenance field
- `code_identity` format: `ts:<ISO-8601>` (deterministic code ref)
- Rolling artifacts use `runs_since_timestamp` instead of `runs_since_sha`
- `attach_evidence.py` script deleted (no longer needed)
- `runs_by_code_sha` replaced with `runs_by_date`

### v2.0 Migration Policy
**CRITICAL**: v2.0 migration requires clearing rolling window to remove legacy `code_sha` entries and ensure metrics reflect timestamp-based provenance only.

### Warmup Period (post-reset)
After reset rolling window, `PASS_WARMUP` is expected until >=10 runs accumulate. KPIs are only valid after exiting warmup. Quality thresholds (`data_run_rate`, `low_sample_rate`, diversity) apply only after warmup completes.

| Action | Command |
|--------|---------|
| Reset window | `python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window` |
| Verify clean | Check aggregator has no legacy `code_sha` entries |
| Fresh start | Run 10+ NORMAL runs to populate new v2.0 metrics |

### DEV vs RELEASE Provenance

| Mode | Provenance | code_identity | Proof |
|------|------------|---------------|-------|
| DEV | `run_timestamp` | `ts:<ISO>` | Not required |
| RELEASE | `run_timestamp` | `ts:<ISO>` | Document in Status_M4.md |

### Recovery Steps
```bash
# 0. Enforce Python 3.11
py -3.11 -m venv .venv && .\.venv\Scripts\Activate.ps1

# 1. Verify chain/RPC consistency before running online
python -c "from core.rpc_urls import validate_chain_rpc_consistency; print(validate_chain_rpc_consistency(42161, 'arb-mainnet.g.alchemy.com'))"

# 2. Reset rolling window
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling --reset-window

# 3. Re-run online M5_0 until quotes_fetched > 0
python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml

# 4. Run M4 profit gate on valid runDir
python scripts/ci_m4_execution_gate.py --online --profile profit --artifact-mode rolling

# 5. Validate rolling artifacts
Get-Content data/runs/_rolling/m4_stability_agg.json | Select-String "schema_version|policy_version|agg_status|run_timestamp"
```

## Documentation

- [Policy & Thresholds](../m4/M4_POLICY.md)
- [Rolling Contract](../m4/ROLLING_CONTRACT.md)
- [Testing Guide](../TESTING.md)
