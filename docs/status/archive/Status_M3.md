# Status_M3.md — Opportunity Engine

**Дата:** 2026-01-13  
**Milestone:** M3 — Opportunity Engine  
**Статус:** ✅ **M3-READY** | **Schema:** 2026-01-13b

---

## 1. M3 Completion Checklist

| Item | Status |
|------|--------|
| Confidence scoring (7 components) | ✅ |
| Revalidation in paper trading | ✅ |
| Counter invariant fix | ✅ |
| --cycles CLI option | ✅ |
| is_anchor_dex (3 args) | ✅ |
| code_errors counter | ✅ |
| pairs_covered fix | ✅ |
| CODE_ERROR status | ✅ |
| ErrorCode contract test | ✅ |
| **Confidence-gated executable** | ✅ |
| **Adaptive gas limits** | ✅ |
| **Adaptive ticks limits** | ✅ |
| **Adaptive price sanity (volatile pairs)** | ✅ |
| **RPC quarantine system** | ✅ |

---

## 2. Adaptive Gates

### Gas Limits by Size
```python
GAS_LIMITS_BY_SIZE = {
    10**17: 300_000,   # 0.1 ETH - tight
    10**18: 500_000,   # 1 ETH - standard
    10**19: 800_000,   # 10 ETH - larger trades
}
```

### Ticks Limits by Size
```python
TICKS_LIMITS_BY_SIZE = {
    10**17: 5,    # 0.1 ETH - tight
    10**18: 10,   # 1 ETH - standard
    10**19: 20,   # 10 ETH - more impact allowed
}
```

### Price Sanity for Volatile Pairs
```python
MAX_PRICE_DEVIATION_BPS = 1500         # 15% for stable pairs
MAX_PRICE_DEVIATION_BPS_VOLATILE = 2500  # 25% for volatile
HIGH_VOLATILITY_PAIRS = {"WETH/LINK", "WETH/UNI", "WETH/GMX", "WETH/ARB"}
```

---

## 3. RPC Quarantine System

### Settings
```python
MIN_REQUESTS_FOR_QUARANTINE = 5      # Min requests before quarantine
MIN_SUCCESS_RATE_FOR_ACTIVE = 0.1    # Below 10% = quarantine
QUARANTINE_DURATION_MS = 60_000      # 1 minute quarantine
```

### Behavior
- Endpoints with success_rate < 10% after 5 requests → quarantined
- Quarantined endpoints skipped for 1 minute
- Auto-release after quarantine expires
- Status shown in truth_report

---

## 4. Execution Gates

```python
executable_final = (
    buy_exec and           # DEX verified
    sell_exec and          # DEX verified
    is_profitable and      # net_pnl_bps > 0
    is_plausible and       # spread_bps <= 500
    is_confident           # confidence >= 0.5
)
```

---

## 5. M3-Ready Metrics

| Metric | Target | Current |
|--------|--------|---------|
| rpc_success_rate | ≥ 0.9 | ~0.9 (with quarantine) |
| gate_pass_rate | ≥ 0.5 | ~0.7 |
| invariants_ok | true | ✅ |
| PRICE_SANITY_FAILED | ≤ 30% of rejects | Reduced |
| executable requires confidence | ≥ 0.5 | ✅ |

---

## 6. Tests

**208 passed ✅**

---

## 7. CLI

```bash
# Single cycle
python -m strategy.jobs.run_scan --once --smoke --paper-trading --no-json-logs

# Multi-cycle stability test
python -m strategy.jobs.run_scan --cycles 10 --smoke --paper-trading --no-json-logs
```

---

## 8. Files Changed

| File | Changes |
|------|---------|
| `strategy/gates.py` | Adaptive gas/ticks/price_sanity limits |
| `chains/providers.py` | RPC quarantine system |
| `monitoring/truth_report.py` | rpc_endpoints_quarantined metric |
| `strategy/jobs/run_scan.py` | Confidence-gated executable |

---

## 9. Next Steps (M3+)

1. Multi-cycle stability test (10-20 cycles)
2. Provider health routing optimization
3. Pool quarantine (track PRICE_SANITY_FAILED per pool)
4. Real execution preparation

---

*M3 Complete: 2026-01-13*
