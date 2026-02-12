# Status: M4 (DEX<->DEX Atomic Execution)

**Status**: PROVISIONAL (M4.1 simulate-only PROVEN; M4 online profit DoD NOT PROVEN)  
**Updated**: 2026-02-12  
**Gate Version**: v2.0.0  
**Policy Version**: v2.0.1  
**Evidence**: Timestamp-based provenance (SHA tracking removed in v2.0)  

## Core Truth (from Roadmap.md)

> **M4 execution gate є "core truth" для релізу.**

| DoD Level | Criterion | Evidence Required | Status |
|-----------|-----------|-------------------|--------|
| **M4.1 Simulate-only** | Code/schema/invariants | FIXTURE_OFFLINE or REAL with simulate_only=true | ✅ PROVEN |
| **M4 Online Profit (core truth)** | Real profitability | `run_mode=REAL`, N=5 runs with `total_net_usdc > 0` | ❌ NOT PROVEN |

**M4-profit по суті (справжній DoD, цитата з Roadmap):**
```
N = 5 consecutive online runs where:
  - run_mode = "REAL" (not FIXTURE_OFFLINE)
  - pinned_block = real block (not 429900000)
  - total_net_usdc > 0
  - all from same runDir with consistent timestamps
```

> **Поки online DoD не виконано — "M4 profit" є математичною оцінкою, не доказом виконання.**

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
- Optional: reference commit SHA in Status_M4.md for documentation purposes
- Use for milestone claims  

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
| `unique_routes` | ≥ 4 | < 2 | Route diversity |

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
> `WARN_QUALITY` з тільки `DIVERSITY_PAIRS_LOW` та/або `DIVERSITY_ROUTES_LOW` приймається як PASS-еквівалент для M4.1 simulate-only DoD.
> **Exit criteria:** досягти `unique_pairs >= 10` і `unique_routes >= 4`, або явно затвердити нижчі targets у Roadmap.

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

### M4 Online Profit (core truth) — ❌ NOT PROVEN
- [ ] N=5 consecutive online runs with run_mode=REAL
- [ ] All runs have total_net_usdc > 0
- [ ] All runs use real pinned_block (not 429900000)
- [ ] agg_status = PASS (no WARN_QUALITY)

### M4.2: Real Execution — ❌ NOT PROVEN
- [ ] Kill switch disabled
- [ ] Real TX submitted

## Known Blockers (2026-02-12)

1. **Python version**: Pipelines running under Python 3.14, repo requires 3.11
2. ~~**Chain/provider mismatch**~~: FIXED - `.env` NETWORK=mantle corrected to arbitrum
3. ~~**Online scan unusable**~~: FIXED - quotes=10, dexes=2, spreads=2 achieved
4. ~~**Rolling artifacts need reset**~~: FIXED - v2.0 schema with timestamp-based provenance
5. ~~**Provenance fixes in v1.12.2**~~: REPLACED by v2.0.0 timestamp provenance
6. ~~**M4.1 quality thresholds**~~: RESOLVED (v2.0.1) - data_run_rate=1.0, low_sample_rate=0.0 with MIN_SIGNALS_FOR_PASS=3
7. **M4 online profit DoD**: NOT PROVEN - need N=5 real runs with total_net_usdc>0 per Roadmap.md
8. **DIVERSITY targets**: unique_pairs=4 (<10 target), unique_routes=2 (<4 target) - causes WARN_QUALITY

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
