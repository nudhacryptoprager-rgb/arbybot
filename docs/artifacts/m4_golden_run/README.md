# M4 Golden Run Fixtures

This directory contains golden fixtures for the M4 Execution Gate.

## Schema Version

**Current:** `m4:execution:v1.1`

## Files

| File | Description |
|------|-------------|
| `signals_golden.json` | Input signals for simulation |
| `execution_report_golden.json` | v1.0 execution report (legacy) |
| `execution_report_golden_v1_1.json` | v1.1 execution report (current) |

## Schema v1.1 Changes (from v1.0)

| Field | v1.0 | v1.1 |
|-------|------|------|
| `chain_id` | - | `42161` (Arbitrum) |
| `pinned_block` | - | `429900000` |
| `execution_mode` | - | `"simulate_only"` |
| `block_used` (per sim) | - | Must match `pinned_block` |
| `gas_usd`, `net_usd` | string | number |
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
- **Requirement:** `total_net_usd > 0`
- **Use case:** Production readiness gate
- **Command:** `python scripts/ci_m4_execution_gate.py --offline --profile profit`

## Block Consistency Invariant

All blocks must match:
1. `signals.pinned_block` (header)
2. `signals[].pinned_block` (each signal)
3. `execution_report.pinned_block` (header)
4. `execution_report.simulations[].block_used` (each simulation)

Violations cause gate FAIL with `blocks_consistent = false`.

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

## Validation Commands

```bash
# Validate with SMOKE profile (default)
python scripts/ci_m4_execution_gate.py --offline

# Validate with PROFIT profile
python scripts/ci_m4_execution_gate.py --offline --profile profit

# Validate with strict mode
python scripts/ci_m4_execution_gate.py --offline --strict
```

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
