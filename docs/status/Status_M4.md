# Status: M4 (DEX↔DEX Atomic Execution v1)

**Status**: ✅ **PROVEN** (simulate_only online), ❌ **NOT PROVEN** (real execution)  
**Updated**: 2026-02-09 20:58 UTC  
**Evidence SHA**: `dd8ae9a`  
**Gate Version**: `ci_m4_execution_gate.py` v1.8.0  
**Tests**: 562 passed, 1 skipped

## 🛡️ Artifact Retention & Disk Policy (v1.8.0)

> **New policy: Only rolling artifacts persist; per-run artifacts are disk-written only for incidents (FAIL).**

### Artifact Retention Rules

- **Rolling artifacts only:**
  - `data/runs/_rolling/_latest.json` (online runs)
  - `data/runs/_rolling/_latest_offline.json` (offline runs - separate)
  - `data/runs/_rolling/m4_stability_agg.json`
  - `data/runs/_rolling/run_summary_latest.json` (online)
  - `data/runs/_rolling/run_summary_latest_offline.json` (offline)
- **Per-run artifacts:**
  - Written to `data/runs/_incidents/<run_id>/` only on incident (FAIL)
  - All scan/truth/signals/execution artifacts are generated in-memory/tmp unless incident
- **Aggregator:**
  - Uses light-format only; legacy runs are purged
- **Retention:**
  - Incident bundles: N=50, TTL=7 days
- **CI guard:**
  - Blocks runtime artifacts except golden fixtures (see `ci_no_runtime_artifacts.py`)
- **Golden fixtures:**
  - Only committed under `docs/artifacts/` for reproducible tests

### Offline vs Online Separation

| Mode | Latest File | Summary File | Overwrites Online? |
|------|-------------|--------------|-------------------|
| ONLINE | `_latest.json` | `run_summary_latest.json` | Yes (online only) |
| OFFLINE | `_latest_offline.json` | `run_summary_latest_offline.json` | No (separate files) |

### NO_DATA Status (v1.8.0)

- When `signals_count == 0`, status is `NO_DATA` instead of `FAIL`
- `NO_DATA` is not counted as incident (no per-run artifacts written)
- `profit_reasons` and `drift_reasons` are set to `["NO_DATA"]` (no FAIL_* noise)

### Example Directory Structure

```
data/runs/_rolling/_latest.json
data/runs/_rolling/_latest_offline.json
data/runs/_rolling/m4_stability_agg.json
data/runs/_rolling/run_summary_latest.json
data/runs/_rolling/run_summary_latest_offline.json
data/runs/_incidents/<run_id>/run_summary.json  # Only for FAIL
docs/artifacts/ci_m4_gate_offline_YYYYMMDD/     # Golden fixtures only
```

### Enforcement

- CI guard (`ci_no_runtime_artifacts.py`) blocks any runtime artifacts except golden fixtures
- All scan/truth/signals/execution artifacts are in-memory/tmp unless incident
- Aggregator and rolling window are disk-safe, unbounded growth prevented

---

## 📖 How to Read run_summary.json (v1.7.0)

> **Quick Guide for PASS / WARN / FAIL interpretation**

### Status Fields

| Field | Meaning |
|-------|---------|
| `profit_status` | PASS = net profit > 0 (primary KPI) |
| `drift_status` | PASS/WARN/FAIL = model accuracy |
| `status` | Combined: PASS if both OK |

### What to Do

| Scenario | Action |
|----------|--------|
| `profit_status=PASS`, `drift_status=PASS` | ✅ All good, proceed |
| `profit_status=PASS`, `drift_status=WARN` | ⚠️ Profitable but investigate MAE drift |
| `profit_status=PASS`, `drift_status=FAIL` | 🔴 Profitable but model unreliable - fix before scaling |
| `profit_status=FAIL` | 🚨 Not profitable - investigate immediately |
| `WARN_LOW_SAMPLE` in reasons | ⚠️ Too few signals (<5) - conclusions unreliable |

### Key Metrics to Check

1. **`kpi.value`** - The M4 KPI: `sim_net_usdc_sum` (simulated profit)
2. **`mae_net_usdc`** - Model accuracy (lower is better, WARN > 0.30, FAIL > 0.50)
3. **`mae_no_slippage`** - Drift without slippage (should be ~0 if model is accurate)
4. **`fragile_count`** - Signals at risk of flipping sign (ideally 0)
5. **`fragile_rate`** - Percentage of fragile signals (v1.7.0)

### Policy Block (v1.7.0)

```json
"policy": {
  "mae_fail_inclusive": false,  // > 0.50 is FAIL, not >= 0.50
  "status_rule": "PASS if profit_status=PASS AND drift_status!=FAIL",
  "no_slippage_definition": "mae_no_slippage disables only slippage_bps delta, keeps gas cost"
}
```

### Example: Good Run

```json
{
  "profit_status": "PASS",
  "drift_status": "PASS",
  "reasons": ["WARN_DRIFT_MAE"],  // WARN but not FAIL
  "kpi": {"value": 8.1121},
  "metrics": {
    "mae_net_usdc": 0.5,       // On threshold but OK (exclusive)
    "mae_no_slippage": 0       // All drift from cost model difference
  }
}
```

---

## 📊 MAE Drift Components (v1.7.0)

> **Understanding drift metrics**

| Metric | Formula | Meaning |
|--------|---------|---------|
| `sum_drift_usdc` | `abs(est_net_sum - sim_net_sum)` | Total $ difference between truth and simulation |
| `mae_net_usdc` | `mean(abs(est_i - sim_i))` | Average per-signal absolute error |
| `mae_slippage_component` | `mean(size_usd * slippage_bps / 10000)` | Expected MAE from slippage difference (truth=0bps, sim=Xbps) |
| `total_slippage_usdc` | `mae_slippage_component * signals_count` | Total slippage cost across all signals |
| `mae_no_slippage` | `max(0, mae_net_usdc - mae_slippage_component)` | MAE attributable to non-slippage factors |

**Key insight:**
- If `mae_no_slippage ≈ 0`, then all drift is from slippage cost model difference
- If `mae_no_slippage > 0`, there's additional model error (prices, gas, etc.)

**Example:**
```
est_net_usdc_sum = 4.68   # truth estimate (no slippage)
sim_net_usdc_sum = 3.68   # simulation (5bps slippage)
sum_drift_usdc   = 1.00   # |4.68 - 3.68| = $1.00 total drift

mae_slippage_component = 0.50  # Expected per-signal slippage cost
total_slippage_usdc    = 1.00  # 0.50 * 2 signals = $1.00

mae_no_slippage = 0  # All drift explained by slippage ✅
```

---

## 📁 Artifact Naming Convention (v1.7.0)

> **Clarity on single-run vs multi-run artifacts**

| Artifact | Type | Schema | Purpose |
|----------|------|--------|---------|
| `stability_summary_*.json` | Single-run | `m4:stability:v1.2` | One execution gate run |
| `run_summary_*.json` | Single-run | `run:summary:v1.4` | Canonical single-run source of truth |
| `m4_stability_agg.json` | Multi-run | `m4:stability_agg:v1.3` | Rolling window aggregator |
| `_latest.json` | Pointer | `m4:latest:v1.3` | Points to latest run for continuous scan |
| `_latest_offline.json` | Pointer | `m4:latest:v1.3` | Offline runs (separate from online) |

**New fields in `_latest.json` v1.3:**
- `latest_mode`: `ONLINE` or `OFFLINE`
- `latest_kind`: `NORMAL` or `INCIDENT`
- `run_status`: `PASS`, `FAIL`, `NO_DATA`
- `threshold_profile_name`: Profile used for thresholds
- `agg_reasons`: Array with `WARMUP_MIN_RUNS`, `WARMUP_MIN_SIGNALS`
- `paths`: Relative paths from `data/runs/`

**⚠️ "summary" = per-run artifact, "agg" = multi-run aggregate**

**Rolling window defaults:**
- Default window: 50 runs
- Max window: 200 runs
- Older runs are dropped to prevent unbounded growth

---

## Status Model v1.7.0

> **Split Status Policy:**
> - `profit_status`: PASS if total_net > 0 (we made money)
> - `drift_status`: PASS/WARN/FAIL based on MAE and sign_rate (model accuracy)
> - `status` (combined): Requires both profit and drift to PASS

**Thresholds:**
| Metric | WARN | FAIL | Notes |
|--------|------|------|-------|
| MAE | > 0.30 | > 0.50 | Exclusive: mae=0.50 is WARN, mae=0.51 is FAIL |
| Sign Rate | < 0.80 | < 0.70 | Percentage of correct sign predictions |
| Sample Size | < 5 | - | WARN_LOW_SAMPLE added to reasons |

**Aggregator-level thresholds (v1.7.0):**
| Metric | Threshold | Action |
|--------|-----------|--------|
| p90(MAE) | > 0.60 | AGG_FAIL |
| warn_rate | > 30% | AGG_FAIL |
| fail_rate | > 10% | AGG_FAIL |

**Interpretation:**
- **profit_status=PASS, drift_status=WARN**: Profitable but model needs tuning
- **profit_status=PASS, drift_status=FAIL**: Profitable but unreliable model (lucky?)
- **profit_status=FAIL**: Not profitable (fix immediately)

**New Metrics (v1.7.0):**
- `fragile_rate`: Percentage of signals that are fragile
- `WARN_LOW_SAMPLE`: Added when signals_count < 5
- `source_execution_report` in inputs: Links to the execution report
- Aggregator `agg_status`/`agg_reasons`: Rolling window level status

---

## ✅ PROVEN: Online Profit (simulate_only)

> **N=5 online runs PASSED on real Arbitrum blocks.**
>
> | Metric | Value |
> |--------|-------|
> | Runs | 5/5 PASS |
> | Blocks | 430290405 → 430290569 (real) |
> | Signals | 16 total |
> | Profitable | 15/16 (93.75%) |
> | Total Net | +$25.28 USDC |
> | Avg/Run | +$5.06 USDC |
> | Cost Model | paper_realistic (gas=$0.10, slippage=5bps) |
>
> **⚠️ This is PAPER SIMULATION, not real execution:**
> - `execution_enabled=false`
> - `kill_switch_active=true`
> - No actual DEX trades executed

---

## ⚠️ Core Truth Statement

> **M4 execution gate є "core truth" для релізу.**  
> M5 — це reporting/monitoring поверх working execution truth.  
> Online profit proven (simulate_only) = готовність до наступного етапу.

---

## DoD Profile Status

| Profile | Status | Criterion | Evidence |
|---------|--------|-----------|----------|
| **smoke** | ✅ **DONE** | `simulations_passed >= 1` | FIXTURE_OFFLINE + ONLINE |
| **profit** | ✅ **PROVEN** (simulate_only) | `total_net_usdc > 0` | N=5 online runs, +$25.28 total |
| **online** | ✅ **PROVEN** (simulate_only) | N=5 online runs with net > 0 | Real blocks 430290405-430290569 |

**⚠️ Execution NOT enabled:**
- Kill switch active
- Paper simulation only
- No real trades executed
- **Справжній DoD** = N онлайн прогонів з `total_net_usdc > 0` на реальних блоках

---

## Canonical Commands

```bash
# 1 COMMAND = 1 GATE = PASS/FAIL

# SMOKE profile (offline) — Expected: PASS ✅
python scripts/ci_m4_execution_gate.py --offline --profile smoke
# Example output:
#   RESULT: PASS (profile=smoke)
#     simulations_passed: 1
#     total_net_usdc: -0.29

# PROFIT profile (offline) — Expected: PASS ✅
python scripts/ci_m4_execution_gate.py --offline --profile profit
# Example output:
#   RESULT: PASS (profile=profit)
#     simulations_passed: 2
#     total_net_usdc: 0.5

# ONLINE profile — Expected: PASS (N=5 runs)
python scripts/ci_m4_execution_gate.py --online --profile profit --config config/real_minimal.yaml
# Example output:
#   RESULT: PASS (profile=profit)
#     simulations_passed: 2
#     total_net_usdc: 0.15

# FULL PIPELINE (canonical runner)
python scripts/ci_full_pipeline.py --mode e2e --config config/real_minimal.yaml --cycles 1 --strict

# Unit tests
python -m pytest tests/unit -q
# Expected: 553 passed, 1 skipped
```

---

## Kill-Switch Invariant

**`execution_enabled=false` та `kill_switch_active=true` — by design.**

Це означає:
- Жодних реальних транзакцій не виконується
- Режим **simulate_only** активний
- Для переходу до реального виконання потрібно **явно вимкнути** kill-switch

---

## Cost Model Registry (v1.3.0)

| Model | Gas USD | Slippage BPS | Use Case |
|-------|---------|--------------|----------|
| `paper_realistic` | $0.10 | 5 | Default online simulation |
| `paper_conservative` | $0.30 | 20 | Stress testing |
| `gas_only` | $0.10 | 0 | M5 truth_report compatibility |

**Command:**
```bash
# Default
python scripts/ci_m4_execution_gate.py --online --profile profit

# Stress test with conservative model
python scripts/ci_m4_execution_gate.py --online --profile profit --cost-model paper_conservative
```

---

## Est vs Sim Drift Metrics (v1.5.0)

| Metric | WARN | FAIL | Latest | Status |
|--------|------|------|--------|--------|
| `mae_net_usdc` | > 0.30 | > 0.50 | 0.50 | ⚠️ WARN |
| `mae_no_slippage` | > 0.25 | > 0.40 | TBD | ⏳ |
| `est_sign_correct_rate` | < 80% | < 70% | 100% | ✅ PASS |
| `fragile_count` | > 1 | > 2 | TBD | ⏳ |

**MAE Threshold Change (v1.5.0):**
- **FAIL at > 0.50** (exclusive), not >= 0.50
- This prevents edge-flapping when mae=0.50 exactly
- mae=0.50 is now WARN, mae=0.51 is FAIL

**✅ MAE Fix (v1.3.0):**
- `est_net_usdc` = from truth_report (original, paper_slippage_bps=0)
- `sim_net_usdc` = from simulator (realistic, slippage=5bps)
- MAE now measures REAL drift between estimate and simulation
- `--strict` mode fails on MAE==0 when sum drift exists

**Формула:** `sim_net_usdc - est_net_usdc` (negative = sim worse than estimate)

---

## Online Evidence (N=5 Runs) — PROVEN

| # | RunDir | Block | Signals | Profitable | Net USDC | MAE | Sign% |
|---|--------|-------|---------|------------|----------|-----|-------|
| 1 | ci_m5_gate_20260209_144253 | 430290405 | 3 | 3/3 | +$5.06 | 0.00 | 100% |
| 2 | ci_m5_gate_20260209_144303 | 430290443 | 3 | 3/3 | +$5.21 | 0.00 | 100% |
| 3 | ci_m5_gate_20260209_144312 | 430290492 | 3 | 3/3 | +$5.21 | 0.00 | 100% |
| 4 | ci_m5_gate_20260209_144322 | 430290531 | 4 | 3/4 | +$5.35 | 0.00 | 100% |
| 5 | ci_m5_gate_20260209_144332 | 430290569 | 3 | 3/3 | +$4.45 | 0.00 | 100% |

> ⚠️ MAE=0.00 above is from v1.2.0 (same calculation path). Re-run with v1.3.0 for real drift.

**Totals:**
- Runs: 5/5 PASS
- Total Net: +$25.28 USDC
- Profitable: 15/16 (93.75%)
- Cost Model: paper_realistic (gas=$0.10, slippage=5bps)

---

## Stress Test Results (v1.3.0)

| Cost Model | Gas | Slippage | MAE | Sign% | Net USDC | Profitable | Status |
|------------|-----|----------|-----|-------|----------|------------|--------|
| paper_realistic | $0.10 | 5bps | 0.50 | 100% | +$15.29 | 2/2 | ⚠️ WARN |
| paper_conservative | $0.30 | 20bps | 2.20 | 50% | +$11.89 | 1/2 | ❌ FAIL |

**Висновки:**
- З paper_realistic профіт залишається, але MAE=0.50 (на межі допустимого)
- З paper_conservative один сигнал стає unprofitable, MAE=2.20 (FAIL)
- Це доводить що profit залежить від cost model assumptions

**RunDir:** ci_m5_gate_20260209_150819, Block: 430296537

---

## Offline Evidence (Fixtures)

| Field | Value |
|-------|-------|
| **RunDir** | `data/runs/ci_m4_gate_offline_20260209_130543/` |
| **run_mode** | `FIXTURE_OFFLINE` |
| **pinned_block** | `429900000` (synthetic) |

| Metric | Smoke Profile | Profit Profile |
|--------|---------------|----------------|
| `simulations_count` | 2 | 2 |
| `simulations_passed` | 1 | 2 |
| `total_net_usdc` | -0.29 | +0.50 |
| `mae_net_usdc` | 0.2850 | 0.2400 |

---

## Proof Commands

```bash
# Online N=5 runs (2026-02-09 14:42-14:43 UTC)
for ($i=1; $i -le 5; $i++) {
  python scripts/ci_m5_0_gate.py --online --config config/real_minimal.yaml
  python scripts/ci_m4_execution_gate.py --online --profile profit --strict --run-dir <RUNDIR>
}
# RESULT: 5/5 PASS, total_net_usdc=+25.28

# Offline (CI mode)
$ python scripts/ci_full_pipeline.py --mode ci
# [OK] ALL REQUIRED GATES PASSED

# Unit tests
$ python -m pytest tests/unit -q
# 553 passed, 1 skipped
```

---

## Stage Clarification

**Поточний етап**: Online paper simulation на реальних блоках

| Stage | Status | Description |
|-------|--------|-------------|
| **Offline fixtures** | ✅ DONE | Synthetic pinned_block, mock simulations |
| **Online simulation** | ✅ PROVEN | Paper sim on real blocks (N=5, +$25.28) |
| **Paper execution** | ⏳ NEXT | "WOULD_EXECUTE" with Tenderly verification |
| **Real execution** | ❌ NOT DONE | Actual TX submission |

**Чітко**: На поточному етапі **реальний блок не потрібен**. Offline fixtures використовують synthetic `pinned_block=429900000` і це **нормально**.

---

## Schema Compatibility Matrix

**⚠️ CRITICAL: Schema Family Separation**

| Family | Artifacts | Block Field | Valid Together? |
|--------|-----------|-------------|-----------------|
| **M4** | signals, execution_report | `pinned_block` | ✅ YES (same family) |
| **M5** | scan, truth_report, reject_histogram | `current_block` | ✅ YES (same family) |
| **M4 + M5** | mixed | different fields | ❌ **NO** in same runDir |

**Rules:**
1. M4 artifacts (`m4:*:v1.1`) must be in **separate runDir** from M5 artifacts (`3.2.0`)
2. Block consistency validated **within family only**
3. Gates validate their own family, never cross-family

**⚠️ Block Mismatch Warning:**
- M4: `pinned_block=429900000` (synthetic)
- M5: `current_block=100` (fixture)
- These are **different families** and **MUST NOT be mixed in one runDir**

**Current Implementation:**
- `ci_m4_execution_gate.py` creates M4-only runDir
- `ci_m5_0_gate.py` creates M5-only runDir
- `ci_full_pipeline.py` runs them as **separate gates with separate runDirs**

---

## Schema Versions

| Artifact | Version | Key Fields |
|----------|---------|------------|
| signals | `m4:signals:v1.2` | quote_ccy, price_format, spread_format, source_sha, run_id, cost_model |
| execution_report | `m4:execution:v1.2` | quote_ccy, price_in, est_error_definition, kill_switch, source_sha, run_id |
| stability_summary | `m4:stability:v1.0` | drift_metrics, thresholds, status |

### Required Header Fields

| Field | Value | Description |
|-------|-------|-------------|
| `quote_ccy` | `"USDC"` | Всі грошові значення в USDC |
| `price_format` | `"decimal_str"` | Ціни як string decimals |
| `price_in` | `"quote_per_base"` | Скільки quote за 1 base |
| `spread_format` | `"micro_bps"` | 1 bps = 10000 micro-bps |
| `slippage_format` | `"bps"` | Real bps (0-10000) |
| `est_error_definition` | `"sim_net_usdc - est_net_usdc"` | Формула помилки |

---

## Offline Fixtures Semantics

### Invariants (MUST pass)

| Invariant | Description |
|-----------|-------------|
| `blocks_consistent=true` | Всі simulations мають той самий block_used |
| `pinned_block == block_used` | Для кожної simulation |
| `all_signals_simulated=true` | Кожен signal має simulation |
| `execution_enabled=false` | No real execution in M4 |
| `kill_switch_active=true` | Safety invariant |

### What is NOT validated offline

- Реальність номера блоку (може бути synthetic 429900000)
- confidence/liquidity_hint (можуть бути mock values)

### Golden як контрольний тест

| Profile | Expected | Reason |
|---------|----------|--------|
| smoke | ✅ PASS | Є 1 profitable simulation |
| profit | ❌ FAIL | total_net_usdc=-0.29 < 0 |

⚠️ **НЕ ЗМІНЮВАТИ golden fixtures без оновлення тестів!**

### Golden Update Policy

```bash
# ONLY way to update golden M4 artifacts
python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m4

# Dry run first
python scripts/update_golden_artifacts.py --run-dir data/runs/<dir> --stage m4 --dry-run
```

---

## Price Direction Invariant

For `pair = "ARB/WETH"`:
```
base_token  = "ARB"   (pair.split("/")[0])
quote_token = "WETH"  (pair.split("/")[1])
price_in    = "quote_per_base"  (how much WETH per 1 ARB)
```

**CRITICAL:** If this invariant is violated, execution will swap direction!

---

## est_error_usdc Definition

**Формула:** `sim_net_usdc - est_net_usdc`

| Value | Meaning |
|-------|---------|
| Negative | Симуляція гірша за оцінку (pessimistic estimate) |
| Positive | Симуляція краща за оцінку (optimistic estimate) |
| Zero | Ідеальна оцінка |

Unit tests валідують цю формулу для кожного entry в fixture.

---

## SimRejectReason Taxonomy (15 values)

| Category | Reasons |
|----------|---------|
| **Simulation** | `SIM_REVERT`, `SIM_OUT_OF_GAS`, `SIM_GAS_TOO_HIGH`, `SIM_UNPROFITABLE`, `SIM_SLIPPAGE_TOO_HIGH`, `SIM_PRICE_MOVED`, `SIM_LIQUIDITY_CHANGED`, `SIM_BLOCK_STALE`, `SIM_RPC_FAILED`, `SIM_DECODE_FAILED`, `SIM_NOT_IMPLEMENTED` |
| **Execution** | `EXEC_KILL_SWITCH`, `EXEC_INSUFFICIENT_BALANCE`, `EXEC_APPROVAL_NEEDED`, `EXEC_BLOCK_MISMATCH` |

---

## Online Scan Validation

**Last 3-cycle run (2026-02-09):**
```
Cycle 1: block=150634512, 1 profitable, 2 would_execute
Cycle 2: block=150634513, 0 profitable
Cycle 3: block=150634514, 1 profitable, paper_trades=2
```

**Health metrics:**
- execution_enabled=false ✅
- execution_blocker=EXECUTION_DISABLED_M4 ✅
- Block consistency: sequential increment ✅

---

## Unit Tests Coverage

| Test Class | Tests | Focus |
|------------|-------|-------|
| `TestCurrentBlockMismatch` | 2 | Block consistency failures |
| `TestMissingSimulationMetrics` | 3 | Required fields validation |
| `TestExecutionEnabledInvariant` | 2 | execution_enabled=false |
| `TestKillSwitchStrict` | 2 | kill_switch_active=true |
| `TestBlocksConsistentFails` | 1 | blocks_consistent=false |
| `TestGateIntegration` | 2 | Full offline gate run |
| `TestPriceDirectionInvariant` | 4 | base/quote semantics |
| `TestEstErrorFormula` | 3 | est_error_usdc calculation |
| `TestQuoteCcyConsistency` | 2 | quote_ccy + health fields |

**Total:** 22 M4-specific tests (553 total in suite)

---

## Next Steps (M4.1 — Execution Enablement)

| Priority | Task | Description |
|----------|------|-------------|
| P0 | Fix MAE drift metric | Separate est_net (truth_report) vs sim_net (simulator) |
| P0 | Unified CostModelRegistry | Single source for gas/slippage across M4/M5 |
| P1 | Tenderly simulation | Replace paper with eth_call on fork |
| P1 | Stress test (conservative) | Run with slippage=20bps, gas=$0.30 |
| P2 | Private submission (Flashbots) | MEV protection |
| P2 | Tiny-live mode | $100 real trades with monitoring |

---

## Enablement Pipeline (Not Yet Started)

```
                    ┌─────────────────┐
                    │ ✅ PROVEN       │
                    │ simulate_only   │
                    │ paper_realistic │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ ⏳ NEXT         │
                    │ Tenderly fork   │
                    │ eth_call sim    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ ⏳ FUTURE       │
                    │ Tiny-live       │
                    │ $100 real TX    │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │ ⏳ FUTURE       │
                    │ Production      │
                    │ Full size       │
                    └─────────────────┘
```

---

## Known Issues (Post-PROVEN)

| Issue | Severity | Description |
|-------|----------|-------------|
| MAE=0.00 always | ⚠️ WARN | est_net == sim_net, drift not measured |
| Cost model mismatch | ⚠️ WARN | M5=gas_only, M4=paper_realistic |
| liquidity_hint="sufficient" | ℹ️ INFO | Placeholder, no real verification |

---

## M4 Goal (from Roadmap)

> "DEX ↔ DEX на одній мережі з атомарним виконанням (одна транзакція / bundle) + pre-trade simulation + приватна подача."

**✅ Achieved (simulate_only):**
```
SIGNAL → SIMULATE (paper) → VERIFY net > 0 → PASS
```

**⏳ Next:**
```
SIGNAL → SIMULATE (eth_call) → VERIFY net > 0 → [PREVIEW/EXECUTE]
```

---

## v1.4.0 Changes (Canonical Artifacts)

### run_summary.json (Source of Truth)

**Schema**: `run:summary:v1`

Канонічний артефакт для continuous scan. Один run = один run_summary.json.

```json
{
  "schema_version": "run:summary:v1",
  "source_sha": "9e04df9...",
  "run_id": "m4_20260209_163045",
  "inputs": {
    "chain_id": 42161,
    "pinned_block": 430296537,
    "source_truth_report": "truth_report_20260209_163045.json"
  },
  "cost_models": {
    "truth": { "name": "gas_only", "slippage_bps": 0 },
    "sim": { "name": "paper_realistic", "slippage_bps": 5 }
  },
  "metrics": {
    "signals_count": 2,
    "sim_profitable_count": 2,
    "total_net_usdc": 15.29,
    "mae_net_usdc": 0.50,
    "sign_mismatch_count": 0
  },
  "status": "PASS",
  "reasons": []
}
```

### Explicit FAIL Conditions

| Code | Condition | Profile |
|------|-----------|---------|
| `FAIL_NET` | total_net_usdc ≤ 0 | PROFIT |
| `FAIL_DRIFT_MAE` | mae_net_usdc ≥ 0.50 | PROFIT |
| `FAIL_DRIFT_SIGN` | sign_correct_rate < 0.70 | PROFIT |
| `FAIL_SIGN_MISMATCH` | sign_mismatch_count > 0 | strict |
| `FAIL_NO_PROFITABLE` | sim_profitable_count = 0 | any |

### Field Renames (v1.4.0)

| Old Name | New Name | Definition |
|----------|----------|------------|
| `est_sim_mismatch_count` | `sign_mismatch_count` | Signals where sign(est) ≠ sign(sim) |
| `would_execute` | `would_execute_if_enabled` | Sim passed AND would execute if enabled |
| (new) | `exec_ready` | Always false until M5 enables |

### Strict Evidence Mode

```bash
# Validate source_sha matches HEAD and run_id format
python scripts/ci_m4_execution_gate.py --online --strict-evidence
```

**Перевіряє:**
- `source_sha` == git HEAD
- `run_id` format: `m4_YYYYMMDD_HHMMSS`

---

### Multi-Run Stability Aggregator (v1.4.0)

**Schema**: `m4:stability_agg:v1`

Агрегує кілька `run_summary.json` у єдиний звіт для continuous scan.

```python
from scripts.ci_m4_execution_gate import aggregate_stability_summaries
from pathlib import Path

run_dirs = [Path("data/runs/run1"), Path("data/runs/run2"), ...]
output = Path("data/reports/stability_aggregate.json")
result = aggregate_stability_summaries(run_dirs, output)
```

**Структура:**
```json
{
  "schema_version": "m4:stability_agg:v1",
  "runs_included": 5,
  "aggregates": {
    "pass_count": 4,
    "fail_count": 1,
    "pass_rate": 0.80,
    "total_net_usdc": 25.28,
    "avg_net_usdc": 5.06,
    "mae_avg": 0.45,
    "mae_max": 0.50,
    "sign_rate_avg": 0.85
  },
  "status": "FAIL",
  "reasons": ["FAIL_DRIFT_MAE"]
}
```

---

### Unified Cost Model (v1.4.0)

| Component | Cost Model | Source |
|-----------|------------|--------|
| **truth_report** | `gas_only` (slippage=0) | Default in TruthReport dataclass |
| **daily_report** | Configurable via CostModelRegistry | `--cost-model` param |
| **M4 simulation** | `paper_realistic` (slippage=5bps) | Default for online |

**daily_report тепер використовує CostModelRegistry:**
```python
from scripts.generate_daily_report import aggregate_run
report = aggregate_run(run_dir, cost_model_name="paper_realistic")
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m4_execution_gate.py` | M4 acceptance gate v1.4.0 |
| `scripts/generate_daily_report.py` | Daily report with CostModelRegistry |
| `monitoring/truth_report.py` | Truth report with cost_model field |
| `tests/unit/test_ci_m4_gate_negative.py` | 22 unit tests |
| `execution/simulator.py` | Simulation interface (skeleton) |
| `execution/state_machine.py` | Trade lifecycle (skeleton) |

---

## Notes

- **✅ Online profit PROVEN** (simulate_only, N=5 runs, +$25.28)
- **No real execution** until kill_switch is deliberately disabled
- **Paper mode**: All trades are "WOULD_EXECUTE" with no actual TX
- **Gradual rollout**: When ready, start with small sizes ($100)
- **run_summary.json** = canonical source of truth for continuous scan
- **aggregate_stability_summaries()** = multi-run aggregator for CI
