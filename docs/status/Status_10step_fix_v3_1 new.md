# Status: M3 P3 Critical Fixes (v5 Consolidated)

**Date**: 2026-01-21
**Branch**: chore/claude-megapack  
**Base SHA**: 4cda626aa65be7ebcf1cc343a399dd8d2f39021b

---

## ⚠️ SOURCE OF TRUTH

**This file (`docs/Status_10step_fix_v3.md`) is the single source of truth.**

### Deprecated Status Files (DO NOT USE):
- `docs/Status_10step_fix_v2.md` - DEPRECATED
- `docs/Status_M3_P3_10step_fix.md` - DEPRECATED  
- `docs/Status_M3_P3_contracts_fix.md` - DEPRECATED
- `docs/Status_M3_P3_contracts_fix_v2.md` - DEPRECATED

---

## Current State

✅ All tests passing  
✅ Backward compatibility maintained (mode + schema 3.0.0)  
✅ Edge-case tolerant (empty spread_id allowed)
✅ Quality improvements (histogram totals, gate names, dexes_active)

## v5 Fix: Paper Trading Edge-Case Tolerance

### Problem
Test `test_empty_spread_id` expects `record_trade()` to return `True` for empty spread_id, not throw exception.

### Solution
- Removed validation that throws `PaperTradeValidationError`
- Empty spread_id is **allowed** (graceful handling)
- Auto-generates `opportunity_id = "opp_"` for empty spread_id

### Verify
```powershell
python -m pytest -q tests\unit\test_edge_cases.py::TestPaperTradingEdgeCases::test_empty_spread_id
```

---

## Quality Improvements Summary

| # | Feature | Status |
|---|---------|--------|
| 1 | `mode` + `run_mode` backward compat | ✅ |
| 2 | `schema_version = "3.0.0"` | ✅ |
| 3 | Histogram self-contained (totals) | ✅ |
| 4 | `gate_name` in reject_details | ✅ |
| 5 | Pool addr on INFRA_RPC_ERROR | ✅ |
| 6 | `dexes_active` = unique count | ✅ |
| 7 | Executable semantics documented | ✅ |
| 8 | Empty spread_id tolerance | ✅ |

---

## Metrics & Units Clarification

### amount_in Units
- **sample_rejects/sample_passed**: Raw token units (e.g., `1000000000000000000` = 1 ETH)
- **opportunity.amount_in**: Numeraire units (USDC, e.g., `"100.000000"`)
- **paper_trades.amount_in_numeraire**: Numeraire units (USDC)

### dexes_active Metric
**Contract**: Count of unique `dex_id` values seen in quotes during scan cycle.

Example: If scan touches uniswap_v3, sushiswap_v3, camelot_v3, pancakeswap_v3 → `dexes_active = 4`

### executable Semantics
- **spread_ids_executable**: "economically executable" - passed all gates, PnL > 0
- **execution_ready_count**: "on-chain ready" - always 0 in SMOKE mode

---

## Files Changed (v5)

| File | Change |
|------|--------|
| `strategy/paper_trading.py` | Remove validation exception, allow empty spread_id |

---

## Verification Commands

```powershell
# Full test suite (must be green)
python -m pytest -q

# Specific edge-case test
python -m pytest -q tests\unit\test_edge_cases.py::TestPaperTradingEdgeCases::test_empty_spread_id

# Smoke run
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v5

# Check histogram has totals
Get-Content data\runs\verify_v5\reports\reject_histogram_*.json

# Check paper_trades has opportunity_id
Select-String "opportunity_id" data\runs\verify_v5\paper_trades.jsonl
```

---

## Apply Instructions

```powershell
# Copy patched file
Copy-Item outputs/strategy/paper_trading.py strategy/

# Update Status (this file)
Copy-Item outputs/docs/Status_10step_fix_v3.md docs/

# Verify
python -m pytest -q

# Commit
git add -A
git commit -m "fix: paper_trading edge-case tolerance (empty spread_id)"
```

---

## Schema 3.0.0 Contract

Fields guaranteed in truth_report JSON:
```
schema_version, timestamp, mode, run_mode
health: rpc_success_rate, rpc_avg_latency_ms, rpc_total_requests, rpc_failed_requests,
        quote_fetch_rate, quote_gate_pass_rate, chains_active, dexes_active,
        pairs_covered, pools_scanned, top_reject_reasons
top_opportunities[]: spread_id, opportunity_id, dex_buy, dex_sell, pool_buy, pool_sell,
                     token_in, token_out, amount_in, amount_out, net_pnl_usdc, net_pnl_bps,
                     confidence, chain_id
stats: spread_ids_total, spread_ids_profitable, spread_ids_executable,
       signals_total, signals_profitable, signals_executable,
       paper_executable_count, execution_ready_count, blocked_spreads
revalidation: total, passed, gates_changed, gates_changed_pct
cumulative_pnl: total_bps, total_usdc
pnl: signal_pnl_bps, signal_pnl_usdc, would_execute_pnl_bps, would_execute_pnl_usdc
pnl_normalized: notion_capital_numeraire, normalized_return_pct, numeraire
```

**BUMP RULES**: Any field addition/removal/rename requires schema bump + migration PR.
