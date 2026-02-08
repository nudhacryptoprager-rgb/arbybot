# Status: M4 (DEX↔DEX Atomic Execution v1)

**Status**: 🚧 **IN PROGRESS**  
**Updated**: 2026-02-08  
**Predecessor**: M5_0 (CLOSED), M5 (FROZEN)

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
