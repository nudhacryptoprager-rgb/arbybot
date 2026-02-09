# Status: M4 (DEX↔DEX Atomic Execution v1)

**Status**: 🚧 **IN PROGRESS** (M4-smoke ✅, M4-profit ⏳)  
**Updated**: 2026-02-09  
**Predecessor**: M5_0 (✅ DONE), M5 (FROZEN)

---

## DoD Profile Status

| Profile | Status | Criterion |
|---------|--------|-----------|
| **smoke** | ✅ **DONE** | `simulations_passed >= 1` AND `accounting_complete` AND `blocks_consistent` |
| **profit** | ⏳ IN PROGRESS | `total_net_usd > 0` AND `sim_profitable_count >= 1` |

**Чому profit ще не PASS:**  
Golden має 1 profitable (+$0.38) і 1 unprofitable (-$0.67) = **сумарно -$0.29**.  
Потрібен prefilter або top-K щоб не симулювати завідомо збиткові.

---

## Schema Versions

| Artifact | Version | Description |
|----------|---------|-------------|
| signals | `m4:signals:v1.1` | base/quote, price_in, micro-bps, PnL breakdown |
| execution_report | `m4:execution:v1.1` | Numerical USDC (rounded), block consistency, kill_switch |

### Fixture Rules (ВАЖЛИВО)

1. **Synthetic pinned_block**: Offline fixtures використовують фіктивний `pinned_block=429900000`. Важливий **тільки інваріант консистентності** (всі blocks однакові), а не реальність номера блоку.

2. **Currency**: Всі грошові поля використовують USDC як quote currency:
   - signals: `*_usdc_est` (estimated)
   - execution_report: `*_usdc` (simulated/actual) + `quote_ccy="USDC"`

3. **est_error_usdc**: Визначення: `sim_net_usdc - est_net_usdc`
   - Негативне значення = симуляція гірша за оцінку
   - Позитивне = симуляція краща за оцінку

4. **Golden як контрольний тест**:
   - `--profile smoke` → **PASS** (є 1 profitable)
   - `--profile profit` → **FAIL** (total_net < 0)
   - НЕ ЗМІНЮВАТИ golden без оновлення тестів!

---

## Latest Progress (2026-02-09)

### M4 Execution Gate v1.1.0 Released

**Completed:**
- ✅ `ci_m4_execution_gate.py` v1.1.0 - production-quality gate
- ✅ **DoD Profiles**: `--profile smoke|profit`
  - SMOKE: ≥1 profitable simulation + accounting complete + blocks_consistent
  - PROFIT: total_net_usd > 0 + sim_profitable_count ≥ 1
- ✅ **Block Consistency Invariant**: pinned_block in header, block_used in each simulation
- ✅ **Numerical USD fields**: rounded to 4 digits (no float artifacts)
- ✅ **Price semantics**: base_token, quote_token, price_in="quote_per_base"
- ✅ **Spread as micro-bps**: spread_bps_micro (integer, 1 bps = 10000)
- ✅ **Slippage as real bps**: slippage_bps_actual (0-10000), slippage_format="bps"
- ✅ **PnL breakdown**: gross_pnl, gas, slippage, net per signal
- ✅ **Expanded est_vs_sim**: est_net_usd, sim_net_usd, mae_net_usd, est_sign_correct_rate
- ✅ **Route in simulations**: buy_dex, sell_dex copied from signal
- ✅ **Kill switch invariant**: kill_switch_active=true (no real execution)
- ✅ **Blocker taxonomy** (15 canonical SimRejectReason values)
- ✅ 14 unit tests in `test_ci_m4_gate_negative.py`
- ✅ Golden fixtures in `docs/artifacts/m4_golden_run/`

**Canonical Commands:**
```bash
# SMOKE profile — Expected: PASS ✅
python scripts/ci_m4_execution_gate.py --offline --profile smoke

# PROFIT profile — Expected: FAIL ❌ (total_net_usd < 0)
python scripts/ci_m4_execution_gate.py --offline --profile profit

# Strict mode
python scripts/ci_m4_execution_gate.py --offline --strict
```

**Golden Reference:**
- Path: `docs/artifacts/m4_golden_run/`
- README: describes schema, invariants, canonical reproduction

**Current signals (from last scan):**
```
ARB/WETH: spread=34.12 bps, net_pnl_est=$3.31
ARB/USDC: spread=82.38 bps, net_pnl_est=$8.14
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

## SimRejectReason Taxonomy

Canonical reasons for simulation/execution failures:

| Reason | Description |
|--------|-------------|
| `SIM_REVERT` | Contract reverted during simulation |
| `SIM_OUT_OF_GAS` | Gas limit exceeded |
| `SIM_GAS_TOO_HIGH` | Gas cost exceeds profit |
| `SIM_UNPROFITABLE` | Net PnL negative after costs |
| `SIM_SLIPPAGE_TOO_HIGH` | Slippage exceeds threshold |
| `SIM_PRICE_MOVED` | Price moved since signal |
| `SIM_LIQUIDITY_CHANGED` | Liquidity changed |
| `SIM_BLOCK_STALE` | Block is stale |
| `SIM_RPC_FAILED` | RPC call failed |
| `SIM_DECODE_FAILED` | Failed to decode result |
| `SIM_NOT_IMPLEMENTED` | Feature not implemented |
| `EXEC_KILL_SWITCH` | Kill switch activated |
| `EXEC_INSUFFICIENT_BALANCE` | Not enough balance |
| `EXEC_APPROVAL_NEEDED` | Token approval needed |
| `EXEC_BLOCK_MISMATCH` | Block mismatch during execution |

**NOTE:** M4 SimRejectReason is separate from M5_0 QuoteRejectReason to avoid conflicts.

---

## M4 Goal (from Roadmap)

> "DEX ↔ DEX на одній мережі з атомарним виконанням (одна транзакція / bundle) + pre-trade simulation + приватна подача."

---

## M4 Success Criterion (Minimal)

**Mінімальний критерій успіху:**

1. **1–2 пари** з реальними spread сигналами
2. **2 DEX** (Uniswap V3 + SushiSwap V3) на Arbitrum
3. **Сигнал знайдено** → **Симульовано** → **net > 0 після gas/slippage**

```
┌─────────────────────────────────────────────────────────────┐
│  SIGNAL → SIMULATE (eth_call) → VERIFY net > 0 → [PREVIEW] │
└─────────────────────────────────────────────────────────────┘
```

---

## Definition of Done (M4)

### M4.1 — Trade State Machine (skeleton)

| Deliverable | Status |
|-------------|--------|
| `execution/state_machine.py` — states: NEW → SIMULATING → READY → EXECUTING → DONE | ⏳ |
| State transitions logged with reason codes | ⏳ |
| Unit tests for state transitions | ⏳ |

### M4.2 — Pre-Trade Simulation Gate

| Deliverable | Status |
|-------------|--------|
| `execution/simulator.py` — `simulate(opportunity)` implemented | ⏳ |
| Build swap calldata (exactInputSingle / exactOutputSingle) | ⏳ |
| Execute eth_call on pinned block | ⏳ |
| Verify simulated_out ≈ expected within slippage | ⏳ |
| Gas estimate from simulation | ⏳ |
| Unit test: simulation matches expected | ⏳ |

### M4.3 — Net Profitability Check

| Deliverable | Status |
|-------------|--------|
| `net_pnl = gross_pnl - gas_cost - slippage_cost` | ⏳ |
| Reject signals where `net_pnl < min_threshold` | ⏳ |
| Log reason: `NET_NEGATIVE_AFTER_COSTS` | ⏳ |

### M4.4 — Private Send Integration (Optional for M4)

| Deliverable | Status |
|-------------|--------|
| Flashbots Protect / MEV blocker integration | ⏳ |
| Bundle submission (if using Flashbots) | ⏳ |
| Fallback to public mempool (with warning) | ⏳ |

### M4.5 — Post-Trade Accounting

| Deliverable | Status |
|-------------|--------|
| Track: realized PnL, gas paid, slippage realized | ⏳ |
| Compare expected vs actual | ⏳ |
| Log `EXECUTION_COMPLETE` with breakdown | ⏳ |

### M4.6 — Kill Switch / Circuit Breaker

| Deliverable | Status |
|-------------|--------|
| `execution/risk.py` — exposure limits | ⏳ |
| Circuit breaker on consecutive failures | ⏳ |
| Kill switch via ENV or signal | ⏳ |

---

## Acceptance Gate

```powershell
# M4 minimal acceptance
python scripts/ci_m4_execution_gate.py --dry-run
# EXPECT: ≥1 net-positive signal found

python scripts/ci_m4_execution_gate.py --simulate
# EXPECT: Simulation PASS, net > 0 after gas
```

---

## Blockers (Must Address Before M4 Complete)

| # | Blocker | Resolution |
|---|---------|------------|
| 1 | Simulator not implemented | M4.2 |
| 2 | No calldata builder | M4.2 |
| 3 | No eth_call integration | M4.2 |
| 4 | Slippage model is 0 bps | Add realistic estimate |

---

## Current State (from M5_0 close)

**Available now:**
- ✅ 2 net-positive signals: ARB/WETH (11 bps, $1.02), ARB/USDC (15 bps, $1.42)
- ✅ On-chain prices from slot0 (sqrt_price_x96)
- ✅ Paper cost model: gas $0.10 + slippage 0 bps
- ✅ Cross-artifact invariants verified
- ✅ 498 unit tests passing

**M4 TODO (execution layer):**
1. Build swap calldata for Uniswap V3
2. Execute eth_call simulation
3. Verify output matches expected
4. Estimate gas
5. Decide: EXECUTE or REJECT

---

## Files to Create/Modify

| File | Purpose | Priority |
|------|---------|----------|
| `execution/simulator.py` | Implement simulate() | P0 |
| `execution/calldata_builder.py` | Build swap calldata | P0 |
| `execution/state_machine.py` | Trade lifecycle | P1 |
| `execution/risk.py` | Circuit breaker, limits | P1 |
| `scripts/ci_m4_execution_gate.py` | M4 acceptance gate | P0 |

---

## Timeline

| Week | Focus |
|------|-------|
| 1 | M4.2: Simulator + calldata builder |
| 2 | M4.3: Net profitability + M4.1: State machine |
| 3 | M4.6: Risk controls + M4.5: Accounting |
| 4 | Integration testing, paper trades |

---

## Notes

- **No real execution** until simulation consistently predicts correct output
- **Paper mode first**: Log "would execute" without sending transaction
- **Gradual rollout**: Small sizes ($100), increase after validation

---

## Legacy M4 (REAL Pipeline Hardening) - CLOSED

The previous M4 focused on REAL pipeline with live RPC. That work is complete and merged into M5_0/M5.
