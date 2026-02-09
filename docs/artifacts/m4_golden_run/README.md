# M4 Golden Run Fixtures

This directory contains golden fixtures for the M4 Execution Gate.

## Schema Versions

| Artifact | Schema Version |
|----------|----------------|
| signals | `m4:signals:v1.1` |
| execution_report | `m4:execution:v1.1` |

## Files

| File | Description |
|------|-------------|
| `signals_golden.json` | Input signals (v1 - legacy) |
| `execution_report_golden.json` | v1.0 execution report (legacy) |
| `execution_report_golden_v1_1.json` | v1.1 execution report (current) |

## Canonical Reproduction Command

```bash
# Generate offline fixtures (SMOKE profile)
python scripts/ci_m4_execution_gate.py --offline --profile smoke

# Validate with PROFIT profile (stricter)
python scripts/ci_m4_execution_gate.py --offline --profile profit
```

**Expected Output:** `RESULT: PASS (profile=smoke)`

**RunDir Pattern:** `data/runs/ci_m4_gate_offline_YYYYMMDD_HHMMSS/`

## Schema v1.1 Changes (from v1.0)

### signals v1.1

| Field | Type | Description |
|-------|------|-------------|
| `price_format` | string | `"decimal_str"` - all prices are string decimals |
| `spread_format` | string | `"micro_bps"` - spread is integer (1 bps = 10000) |
| `base_token` | string | Base token symbol (first in pair) |
| `quote_token` | string | Quote token symbol (second in pair) |
| `price_in` | string | `"quote_per_base"` - canonical price direction |
| `spread_bps_micro` | integer | Spread in micro-bps (33.78 bps = 337800) |
| `size_usd_est` | number | Trade size in USD |
| `gross_pnl_usdc_est` | number | Gross PnL before costs |
| `gas_usdc_est` | number | Estimated gas cost |
| `slippage_usdc_est` | number | Estimated slippage cost |
| `confidence` | number | Signal confidence [0,1] |
| `liquidity_hint` | string | `"thin"`, `"adequate"`, `"deep"` |
| `signals_by_pair` | object | Count by pair |
| `signals_by_route` | object | Count by DEX route |

### execution_report v1.1

| Field | v1.0 | v1.1 |
|-------|------|------|
| `chain_id` | - | `42161` (Arbitrum) |
| `pinned_block` | - | `429900000` |
| `execution_mode` | - | `"simulate_only"` |
| `block_used` (per sim) | - | Must match `pinned_block` |
| `gas_usd`, `net_usd` | string | number |
| `slippage_bps_actual` | number (bps) | integer (micro-bps) |
| `gross_pnl_usd` | - | number |
| `base_token`, `quote_token` | - | strings |
| `est_was_correct` | - | boolean |
| `est_vs_sim` | - | metrics object |
| `accounting.accounting_complete` | - | boolean |
| `health.blocks_consistent` | - | boolean |

## DoD Profiles

The gate supports two DoD (Definition of Done) profiles:

### SMOKE Profile (default)
- **Requirement:** `simulations_passed >= 1` AND `accounting_complete = true`
- **Use case:** Development, CI validation
- **Command:** `python scripts/ci_m4_execution_gate.py --offline --profile smoke`

### PROFIT Profile
- **Requirement:** `total_net_usd > 0` AND `sim_profitable_count >= 1`
- **Use case:** Production readiness gate
- **Command:** `python scripts/ci_m4_execution_gate.py --offline --profile profit`

## Block Consistency Invariant

All blocks must match:
1. `signals.pinned_block` (header)
2. `signals[].pinned_block` (each signal)
3. `execution_report.pinned_block` (header)
4. `execution_report.simulations[].block_used` (each simulation)

Violations cause gate FAIL with `blocks_consistent = false`.

## Price Direction Invariant

For `pair = "ARB/WETH"`:
- `base_token = "ARB"` (first)
- `quote_token = "WETH"` (second)
- `price_in = "quote_per_base"` (how much WETH per 1 ARB)

**INVARIANT:** `base_token == pair.split("/")[0]`

## Blocker Taxonomy

Valid blockers from `core.reject_reasons.SimRejectReason`:

- `SIM_REVERT` - Contract reverted
- `SIM_OUT_OF_GAS` - Gas limit exceeded
- `SIM_GAS_TOO_HIGH` - Gas cost exceeds profit
- `SIM_UNPROFITABLE` - Net PnL negative
- `SIM_SLIPPAGE_TOO_HIGH` - Slippage threshold exceeded
- `SIM_PRICE_MOVED` - Price moved since signal
- `SIM_LIQUIDITY_CHANGED` - Liquidity changed
- `SIM_BLOCK_STALE` - Block is stale
- `SIM_RPC_FAILED` - RPC call failed
- `SIM_DECODE_FAILED` - Failed to decode result
- `SIM_NOT_IMPLEMENTED` - Feature not implemented
- `EXEC_KILL_SWITCH` - Kill switch activated
- `EXEC_INSUFFICIENT_BALANCE` - Not enough balance
- `EXEC_APPROVAL_NEEDED` - Token approval needed
- `EXEC_BLOCK_MISMATCH` - Block mismatch during execution

## What This Golden Proves

1. **Schema compliance** - artifacts match v1.1 schema
2. **Fixture mode works** - OFFLINE gate generates valid fixtures
3. **SMOKE profile passes** - at least 1 profitable simulation
4. **PROFIT profile fails** - total_net_usd may be negative (expected)
5. **Block consistency** - all blocks match pinned_block
6. **Blocker taxonomy** - blockers are from canonical enum

## Updating Golden Fixtures

1. Run gate in offline mode to generate new fixtures
2. Review the generated execution_report
3. Copy to this directory with `_golden` suffix
4. Update schema version if format changed
5. Run unit tests to verify

**DO NOT** modify golden fixtures without updating:
- Gate validation logic
- Unit tests
- This README
