# Status: M3 P3 Critical Fixes (Consolidated)

**Date**: 2026-01-21
**Branch**: chore/claude-megapack  
**Base SHA**: a9a6a33e607284e5b1003f4eab5341abb2599c66

> **SOURCE OF TRUTH**: This file replaces all previous Status_*.md files.
> Previous versions (v2, v3) are deprecated.

## Current State

✅ All tests passing  
✅ Backward compatibility maintained (mode + schema 3.0.0)  
✅ New features added (run_mode, forensic samples, opportunity linking)

## 10 Quality Improvements (v4)

### Step 1: RPC Robustness
**Status**: Documentation only (architectural change deferred)

Retry/fallback logic requires RPC abstraction layer. Current SMOKE mode doesn't use real RPC.

### Step 2: Reject Details with Gate Name ✅

**Problem**: Can't distinguish "slippage gate" from "anchor deviation".

**Solution**: Added `gate_name` and `reason_family` to reject_details:
```json
{
  "gate_name": "slippage_gate",
  "reason_family": "SLIPPAGE",
  "slippage_note": "slippage_bps = (expected_out - min_out) / expected_out * 10000",
  "anchor_note": "anchor from CEX/oracle; deviation_bps = price difference used for sanity check"
}
```

### Step 3: Self-Contained Histogram ✅

**Problem**: `reject_histogram_*.json` not auditable without snapshot.

**Solution**: Added totals to histogram:
```json
{
  "run_mode": "SMOKE_SIMULATOR",
  "timestamp": "...",
  "chain_id": 42161,
  "current_block": 150123456,
  "quotes_total": 10,
  "quotes_fetched": 8,
  "gates_passed": 5,
  "histogram": {...}
}
```

### Step 4: Pool Address on INFRA_RPC_ERROR ✅

**Problem**: `pool: "unknown"` makes debugging impossible.

**Solution**: Keep `pool` address when known, add `target_pool` in details:
```json
{
  "pool": "0x...",
  "reject_details": {
    "target_pool": "0x...",
    ...
  }
}
```

### Step 5: Accurate dexes_active Count ✅

**Problem**: 4 dex_ids in data but `dexes_active=2`.

**Solution**: Track actual unique dex_ids seen:
```python
seen_dex_ids: Set[str] = set()
# ... add dex_id on each quote
scan_stats["dexes_active"] = len(seen_dex_ids)
```

### Step 6: Executable Semantics Clarified ✅

**Problem**: "executable" term is ambiguous.

**Solution**: Documented in truth_report.py:
- `spread_ids_executable`: **economically executable** (passed gates, PnL > 0)
- `execution_ready_count`: **ready for on-chain execution** (0 in SMOKE mode)

### Step 7: Paper Trades Contract ✅

**Problem**: No guarantee `opportunity_id`/`spread_id` present.

**Solution**: Added validation in `PaperSession.record_trade()`:
```python
def validate(self) -> None:
    if not self.spread_id or not self.spread_id.strip():
        raise PaperTradeValidationError("spread_id is required")
    if not self.opportunity_id or not self.opportunity_id.strip():
        raise PaperTradeValidationError("opportunity_id is required")
```

### Step 8: Mode vs Run_Mode Documentation ✅

**Problem**: Devs confuse `mode` and `run_mode`.

**Solution**: Added docstring in truth_report.py:
```
SEMANTIC CONTRACT:
- mode: TruthReport data source mode ("REGISTRY", "DISCOVERY")
- run_mode: Scanner runtime mode ("SMOKE_SIMULATOR", "REGISTRY_REAL")
```

### Step 9: Schema Contract Frozen ✅

**Problem**: Schema changes are "silent" and breaking.

**Solution**: Added schema contract documentation in truth_report.py:
```
SCHEMA CONTRACT:
Schema version 3.0.0 fields: [list of all fields]
BUMP RULES: Any field addition/removal/rename requires schema bump + migration PR.
```

### Step 10: Status Consolidation ✅

**Problem**: Multiple Status files, unclear source of truth.

**Solution**: This file is the single source of truth. Deprecated files:
- docs/Status_10step_fix_v2.md
- docs/Status_10step_fix_v3.md
- docs/Status_M3_P3_contracts_fix.md
- docs/Status_M3_P3_contracts_fix_v2.md

## Files Changed

| File | Changes |
|------|---------|
| `monitoring/truth_report.py` | Schema contract, mode/run_mode docs, executable semantics |
| `strategy/jobs/run_scan_smoke.py` | histogram totals, pool on errors, gate_name, dexes_active |
| `strategy/paper_trading.py` | spread_id/opportunity_id validation |

## Verification Commands

```powershell
# Full test suite
python -m pytest -q

# Smoke run
python -m strategy.jobs.run_scan_smoke --cycles 1 --output-dir data\runs\verify_v4

# Check histogram self-contained (Step 3)
Get-Content data\runs\verify_v4\reports\reject_histogram_*.json
# Should have: quotes_total, quotes_fetched, gates_passed

# Check gate_name in rejects (Step 2)
Get-Content data\runs\verify_v4\snapshots\scan_*.json | ConvertFrom-Json | Select -Expand sample_rejects | Select -First 1 | Select -Expand reject_details
# Should have: gate_name, reason_family

# Check dexes_active (Step 5)
Get-Content data\runs\verify_v4\reports\truth_report_*.json | Select-String "dexes_active"

# Check paper_trades has opportunity_id (Step 7)
Select-String "opportunity_id" data\runs\verify_v4\paper_trades.jsonl
```

## Apply Instructions

```powershell
# Copy files
Copy-Item outputs/monitoring/truth_report.py monitoring/
Copy-Item outputs/strategy/jobs/run_scan_smoke.py strategy/jobs/
Copy-Item outputs/strategy/jobs/run_scan.py strategy/jobs/
Copy-Item outputs/strategy/paper_trading.py strategy/

# Rename this as the source of truth
Copy-Item outputs/docs/Status_M3_P3_10step_fix.md docs/

# Verify
python -m pytest -q

# Commit
git add -A
git commit -m "fix: 10 quality improvements (v4) - histogram totals, gate names, dexes_active, validation"
```

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
