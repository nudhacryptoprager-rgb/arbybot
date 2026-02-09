# Status: M4 (DEX↔DEX Atomic Execution v1)

**Status**: 🚧 **IN PROGRESS** (M4-smoke ✅, M4-profit ⏳)  
**Updated**: 2026-02-09  
**Gate Version**: `ci_m4_execution_gate.py` v1.1.0  
**Tests**: 522 passed

---

## DoD Profile Status

| Profile | Status | Criterion | Golden Result |
|---------|--------|-----------|---------------|
| **smoke** | ✅ **DONE** | `simulations_passed >= 1` AND `accounting_complete` AND `blocks_consistent` AND `all_signals_simulated` | PASS |
| **profit** | ⏳ IN PROGRESS | `total_net_usdc > 0` | FAIL (-$0.29) |

**Чому profit ще не PASS:**  
Golden fixture має 1 profitable (+$0.38) і 1 unprofitable (-$0.67) = **сумарно -$0.29**.  
Потрібен prefilter або top-K selection щоб не симулювати завідомо збиткові сигнали.

---

## Canonical Commands

```bash
# 1 COMMAND = 1 GATE = PASS/FAIL

# SMOKE profile — Expected: PASS ✅
python scripts/ci_m4_execution_gate.py --offline --profile smoke

# PROFIT profile — Expected: FAIL ❌ (total_net_usdc < 0)
python scripts/ci_m4_execution_gate.py --offline --profile profit

# Full CI pipeline
python scripts/ci_full_pipeline.py
```

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
