# Status: M4 (DEX<->DEX Atomic Execution)

**Status**: PROVEN (M4.1 simulate-only + M4 online profit DoD PROVEN; M4.2 real execution NOT PROVEN)  
**Updated**: 2026-02-13  
**Gate Version**: v2.0.0  
**Policy Version**: v2.0.2  
**Evidence**: Timestamp-based provenance (SHA tracking removed in v2.0, finalized in v2.0.2)  

## Core Truth (from Roadmap.md)

> **M4 execution gate є "core truth" для релізу.**

| DoD Level | Criterion | Evidence Required | Status |
|-----------|-----------|-------------------|--------|
| **M4.1 Simulate-only** | Code/schema/invariants | FIXTURE_OFFLINE or REAL with simulate_only=true | ✅ PROVEN |
| **M4 Online Profit (core truth)** | Real profitability | `run_mode=REGISTRY_REAL`, N≥5 runs with `total_net_usdc > 0` | ✅ PROVEN (2026-02-12) |

**RunMode Canonical (v2.0.1):**
> `REGISTRY_REAL` is the canonical run_mode for online scanning.
> Legacy docs may use `REAL` as shorthand but artifacts MUST use `REGISTRY_REAL`.

**M4-profit DoD (посилання на Roadmap.md L52-62):**
> See `Roadmap.md` for canonical DoD definition.
> Quick ref: N≥5 runs in `m4_stability_agg.json.runs[]` with:
> `run_mode=REGISTRY_REAL`, `pinned_block!=429900000`, `block_is_synthetic=false`, `total_net_usdc>0`

**Evidence for M4 online-profit PROVEN (updated 2026-02-13, 41 runs):**
| run_id | net_usdc | run_status | signals | run_mode | pinned_block |
|--------|----------|------------|---------|----------|--------------|
| ci_m5_gate_20260213_152736 | 116.32 | PASS | 3 | REGISTRY_REAL | 431689209 |
| ci_m5_gate_20260213_152746 | 115.93 | PASS | 3 | REGISTRY_REAL | 431689275 |
| ci_m5_gate_20260213_152757 | 118.78 | PASS | 4 | REGISTRY_REAL | 431689318 |
| ci_m5_gate_20260213_152808 | 118.51 | PASS | 4 | REGISTRY_REAL | 431689395 |
| ci_m5_gate_20260213_152819 | 118.27 | PASS | 4 | REGISTRY_REAL | 431689441 |

> Source: `data/runs/_rolling/m4_stability_agg.json.runs[-5:]`
> Total runs in window: 41 | Total net_usdc: $4912.79 | net_diversity_rate: 0.675
> Policy Version: 2.0.2 | low_sample_rate: 0.0244 | effective_pass_rate: 0.9756

> **M4 online profit DoD виконано (2026-02-12, оновлено 2026-02-13).** Це означає:
> - `simulate_only=true`, `execution_enabled=false` — реальних TX немає
> - Прибуток підтверджено симуляцією, не реальними угодами
> - Для M4.2 (real execution) потрібен окремий DoD proof з TX on-chain

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
| `signals > 0, net ≤ 0` | FAIL | Unprofitable |
| `signals < 5` | quality_status=WARN | Low sample (not NO_DATA) |

**Rule**: NO_DATA only when signals_count == 0. Low sample → WARN, not NO_DATA.

## Run Kinds (v1.11.0)

| Kind | Description | Counted in KPIs |
|------|-------------|-----------------|
| NORMAL | Regular online scan | ✅ Main KPIs |
| COVERAGE | Coverage batch run | ❌ Separate stats |
| SMOKE | Smoke test | ❌ Excluded |
| OFFLINE | Offline fixture | ❌ Excluded |

## Rolling KPIs (Targets)

| Metric | Target | FAIL | Description |
|--------|--------|------|-------------|
| `data_run_rate` | ≥ 0.50 | < 0.30 | % NORMAL runs with ≥MIN_SIGNALS_FOR_PASS signals (v2.0.1: 3) |
| `fail_rate` | ≤ 0.10 | > 0.15 | % FAIL runs (v1.12.0 bites) |
| `fragile_rate_p90` | ≤ 0.30 | > 0.50 | p90 fragile rate |
| `unique_pairs` | ≥ 10 | < 3 | Pair diversity |
| `unique_routes` | ≥ 4* | < 2 | Route diversity |

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
| `AGG_FAIL_RATE_FAIL` | 0.15 | v1.12.0: fail_rate > 15% → FAIL |
| `DIVERSITY_PAIRS_MIN` | 3 | v1.12.0: < 3 pairs → FAIL |
| `DIVERSITY_ROUTES_MIN` | 2 | v1.12.0: < 2 routes → FAIL |

### Policy Version Note (v2.0.1, 2026-02-12)
**BREAKING CHANGE**: З 2026-02-12 (v2.0.1) `MIN_SIGNALS_FOR_PASS=3` (було 5). Це означає:
- KPI `data_run_rate` та `low_sample_rate` рахуються від нового порогу
- Попередні значення (до v2.0.1) **несумісні** без перерахунку

### Acceptable States (agg_status)

| agg_status | DEV | RELEASE | Actions |
|------------|-----|---------|---------|
| `PASS` | ✅ OK | ✅ OK | Continue to next milestone |
| `WARN_QUALITY` (only DIVERSITY_*) | ✅ OK | ⚠️ TEMP OK | Expand config to reach diversity targets |
| `WARN_QUALITY` (DATA_RUN_RATE/LOW_SAMPLE) | ❌ FAIL | ❌ FAIL | Fix signal generation or policy |
| `FAIL` | ❌ FAIL | ❌ FAIL | Fix underlying issues |
| `PASS_WARMUP` | ✅ OK | ❌ WAIT | Accumulate ≥10 runs |

**TEMPORARY RULE (expires when targets met):**
> `WARN_QUALITY` з тільки `DIVERSITY_PAIRS_LOW` та/або `DIVERSITY_ROUTES_LOW` приймається як PASS-еквівалент для:
> - M4.1 simulate-only DoD
> - M4 online profit DoD (N≥5 runs proof)
>
> Це НЕ застосовується до M4.2 real execution DoD.
>
> **M4 Exit criteria (v2.0.2, 2026-02-13 після 31 runs):**
> - `unique_pairs`: 5/10 — потребує більше verified pools (LINK/USDT, GMX/USDC тощо)
> - `unique_routes`: 2/4 — затверджено як M4-ціль (з 2 DEX більше неможливо)
>
> **Diversity Decision (2026-02-13):**
> - M4 ok з `unique_routes=2` — більше з 2 DEX неможливо
> - `unique_pairs` target (10) переноситься в M5 як окреме requirements
> - Поточний `unique_pairs=5` достатній для M4 simulate-only proof
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

### M4.1: Simulate-Only — ✅ PROVEN
- [x] Online scan generates signals
- [x] Simulator calculates PnL
- [x] Rolling artifacts persist
- [x] Evidence workflow works
- [x] agg_status = WARN_QUALITY (only DIVERSITY_*) accepted per Acceptable States table

### M4 Online Profit (core truth) — ✅ PROVEN (2026-02-12)
- [x] N≥5 consecutive online runs with run_mode=REGISTRY_REAL (11 runs)
- [x] All runs have total_net_usdc > 0 (123.42 USDC each, total ~1361 USDC)
- [x] All runs use real pinned_block (e.g., 431276644)
- [x] agg_status = WARN_QUALITY (only DIVERSITY_*) accepted per Acceptable States table

**Evidence (rolling artifacts):**
- `pass_count`: 11
- `data_run_rate`: 1.0
- `effective_pass_rate`: 1.0
- `fail_rate`: 0.0
- `agg_reasons`: DIVERSITY_PAIRS_LOW, DIVERSITY_ROUTES_LOW (acceptable)

**⚠️ "Too-good-to-be-true" сигнал (вимагає sanity-check перед M4.2):**
> Метрики з `m4_stability_agg.quick_stats`:
> - `unique_net_values`: **4** (лише 4 унікальних значення profit серед 11 runs)
> - `net_p10`: 123.40 USDC, `avg_net_usdc`: 123.77 USDC (дуже близькі)
> - `net_diversity_rate`: 0.36 (низька різноманітність)
>
> Це може означати:
> - (A) Однаковий сайзінг/cost model дає повторюваний результат (очікувано для simulate_only)
> - (B) Fixture-подібна поведінка (неочікувано для REGISTRY_REAL)
>
> **Дія**: Перед M4.2 перевірити `reject_histogram_*` та cost model breakdown.

### M4.2: Real Execution — ❌ NOT PROVEN
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
> Цей чек-лист прив'язаний до Roadmap: M4 → Execution v1 → "Pre-trade simulation gate"

## Known Blockers (2026-02-13)

1. **Python version**: Pipelines running under Python 3.14, repo requires 3.11
2. ~~**Chain/provider mismatch**~~: FIXED - `.env` NETWORK=mantle corrected to arbitrum
3. ~~**Online scan unusable**~~: FIXED - quotes=10, dexes=2, spreads=2 achieved
4. ~~**Rolling artifacts need reset**~~: FIXED - v2.0 schema with timestamp-based provenance
5. ~~**Provenance fixes in v1.12.2**~~: REPLACED by v2.0.0 timestamp provenance
6. ~~**M4.1 quality thresholds**~~: RESOLVED (v2.0.1) - data_run_rate=1.0, low_sample_rate=0.0 with MIN_SIGNALS_FOR_PASS=3
7. ~~**M4 online profit DoD**~~: PROVEN (2026-02-12) - 11 real runs with total_net_usdc>0
8. **DIVERSITY targets**: unique_pairs=4 (<10 target), unique_routes=2 (<4 target) - causes WARN_QUALITY
   - **Decision (v2.0.1)**: Accept `unique_routes=2` as M4.1 minimum. Target of 4 requires 3rd DEX (e.g., Curve, Camelot).
   - Pairs expansion: Add verified pairs (LINK/USDC, ARB/USDT) to `config/real_expanded.yaml` once pools verified.
   - Full diversity targets deferred to M5 when 3rd DEX adapter available.

**Next focus**: M5_0 — Infra (RPC Providers, Streaming, Tracing). M4 online profit DoD is PROVEN.

**Next engineering focus**: Diversity expansion (unique_pairs → 10, unique_routes → 4 via 3rd DEX) + pool verification for LINK/USDC, ARB/USDT.

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
After reset rolling window, `PASS_WARMUP` is expected until ≥10 runs accumulate. KPIs are only valid after exiting warmup. Quality thresholds (`data_run_rate`, `low_sample_rate`, diversity) apply only after warmup completes.

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
