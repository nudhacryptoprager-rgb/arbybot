# Status: M4 (DEX↔DEX Atomic Execution v1)

**Status**: ✅ **DONE** (offline fixtures), ⏳ **NOT PROVEN** (online profit)  
**Updated**: 2026-02-09  
**Gate Version**: `ci_m4_execution_gate.py` v1.2.0  
**Tests**: 553 passed

---

## ⚠️ CRITICAL: What This Status Means

> **Offline fixtures PASS ≠ Proof of online profitability.**
>
> Поточний статус підтверджено **FIXTURE_OFFLINE (simulate_only)**.  
> Це валідує код/схеми/інваріанти, але **НЕ є доказом ONLINE PnL**.
>
> **M4-profit по суті** = N онлайн прогонів з `total_net_usdc > 0` на реальних блоках.  
> Поки цього немає — "profit ✅ DONE" є математичною оцінкою, не виконанням.

---

## ⚠️ Core Truth Statement

> **M4 execution gate є "core truth" для релізу.**  
> M5 — це reporting/monitoring поверх working execution truth.  
> Без стабільного M4 online-profit, M5 є лише "красивою звітністю".

---

## DoD Profile Status

| Profile | Status | Criterion | Evidence |
|---------|--------|-----------|----------|
| **smoke** | ✅ **DONE** | `simulations_passed >= 1` | FIXTURE_OFFLINE (net=-$0.29) |
| **profit** | ✅ **DONE** (offline) | `total_net_usdc > 0` | FIXTURE_OFFLINE (net=+$0.50) |
| **online** | ⏳ **NOT PROVEN** | N=5 online runs with net > 0 | Requires real block, not 429900000 |

**Fixture strategy:**
- SMOKE profile: 1 profitable (+$0.38) + 1 unprofitable (-$0.67) = net -$0.29 ✅
- PROFIT profile: 2 profitable (+$0.38 + $0.12) = net +$0.50 ✅

**⚠️ FIXTURE_OFFLINE Warning:**
- `pinned_block=429900000` є synthetic — це **норма для offline**
- FIXTURE_OFFLINE **НЕ доводить** що DEX↔DEX прибутковий онлайн
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

## Est vs Sim Drift Metrics

| Metric | Threshold | Current | Status |
|--------|-----------|---------|--------|
| `mae_net_usdc` | ≤ 0.30 | 0.24 | ✅ OK |
| `est_sign_correct_rate` | ≥ 80% | 100% | ✅ OK |
| `est_sim_mismatch_count` | 0 | 0 | ✅ OK |

**Формула:** `sim_net_usdc - est_net_usdc`

Якщо drift великий — сигнали "гарні", а результат посередній.

---

## Evidence Links (Reproducible Status)

**Last Verified Offline Run:**

| Field | Value |
|-------|-------|
| **RunDir** | `data/runs/ci_m4_gate_offline_20260209_123029/` |
| **Timestamp** | `20260209_123029` |
| **Artifacts** | `signals_20260209_123029.json`, `execution_report_20260209_123029.json` |
| **run_mode** | `FIXTURE_OFFLINE` |
| **pinned_block** | `429900000` (synthetic) |

**Key Metrics (from execution_report):**

| Metric | Smoke Profile | Profit Profile |
|--------|---------------|----------------|
| `simulations_count` | 2 | 2 |
| `simulations_passed` | 1 | 2 |
| `total_net_usdc` | -0.29 | +0.50 |
| `mae_net_usdc` | 0.2850 | 0.2400 |
| `pass_rate` | 50% | 100% |

**⚠️ Note:** These are FIXTURE_OFFLINE results. Online DoD requires N=5 runs on real blocks.

---

## Stage Clarification

**Поточний етап**: Offline execution gate з fixture даними

| Stage | Status | Description |
|-------|--------|-------------|
| **Offline fixtures** | ✅ DONE | Synthetic pinned_block, mock simulations |
| **Online simulation** | ⏳ NEXT | Real eth_call on real block |
| **Paper execution** | ⏳ FUTURE | "WOULD_EXECUTE" logging |
| **Real execution** | ⏳ FUTURE | Actual TX submission |

**Чітко**: На поточному етапі **реальний блок не потрібен**. Offline fixtures використовують synthetic `pinned_block=429900000` і це **нормально**.

---

## Schema Versions

| Artifact | Version | Key Fields |
|----------|---------|------------|
| signals | `m4:signals:v1.1` | quote_ccy, price_format, spread_format, base/quote tokens |
| execution_report | `m4:execution:v1.1` | quote_ccy, price_in, est_error_definition, kill_switch |

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

**Total:** 22 M4-specific tests (522 total in suite)

---

## Next Steps (M4-profit)

| Priority | Task | Description |
|----------|------|-------------|
| P0 | Top-K signal selection | Не симулювати завідомо збиткові |
| P0 | Prefilter by confidence | min_confidence >= 0.7 |
| P1 | Real eth_call simulation | Replace mock with actual RPC |
| P1 | Gas estimation from simulation | Use gas_used from trace |
| P2 | Private submission (Flashbots) | MEV protection |

---

## M4 Goal (from Roadmap)

> "DEX ↔ DEX на одній мережі з атомарним виконанням (одна транзакція / bundle) + pre-trade simulation + приватна подача."

**Minimal success criterion:**
```
SIGNAL → SIMULATE (eth_call) → VERIFY net > 0 → [PREVIEW/EXECUTE]
```

---

## Files Reference

| File | Purpose |
|------|---------|
| `scripts/ci_m4_execution_gate.py` | M4 acceptance gate v1.1.0 |
| `tests/unit/test_ci_m4_gate_negative.py` | 22 unit tests |
| `execution/simulator.py` | Simulation interface (skeleton) |
| `execution/state_machine.py` | Trade lifecycle (skeleton) |

---

## Notes

- **No real execution** until kill_switch is deliberately disabled
- **Paper mode**: All trades are "WOULD_EXECUTE" with no actual TX
- **Gradual rollout**: When ready, start with small sizes ($100)
