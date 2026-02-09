# M4 Policy

Threshold profiles, status rules, and warmup configuration.

## Threshold Profiles

### smoke (Testing)

| Metric | Threshold | Description |
|--------|-----------|-------------|
| MAE WARN | 0.30 | Warning threshold for drift |
| MAE FAIL | 0.50 | Failure threshold for drift |
| Sign Rate Min | 0.80 | Minimum sign correctness rate |
| Min Sample Size | 2 | Below this, WARN_LOW_SAMPLE |

### profit (Production)

| Metric | Threshold | Description |
|--------|-----------|-------------|
| MAE WARN | 0.55 | Warning threshold for drift |
| MAE FAIL | 0.80 | Failure threshold for drift |
| Sign Rate Min | 0.60 | Minimum sign correctness rate |
| Min Sample Size | 5 | Below this, WARN_LOW_SAMPLE |

## Status Rules

### Run Status

```
if signals_count == 0:
    status = "NO_DATA"
elif profit_status == "PASS" and drift_status != "FAIL":
    status = "WARN" if drift_status == "WARN" else "PASS"
else:
    status = "FAIL"
```

### Profit Status

- **PASS**: `total_net_usdc > 0` (profitable)
- **FAIL**: `total_net_usdc <= 0` (not profitable)

### Drift Status

- **PASS**: `mae_net_usdc <= mae_warn`
- **WARN**: `mae_warn < mae_net_usdc <= mae_fail`
- **FAIL**: `mae_net_usdc > mae_fail`

Note: Thresholds are exclusive (`>` not `>=`).

## Reasons

| Reason | Meaning | Impact |
|--------|---------|--------|
| `NO_DATA` | Zero signals in run | Status = NO_DATA |
| `WARN_LOW_SAMPLE` | Signals < min_sample_size | Weak statistics |
| `WARN_DRIFT_MAE` | MAE above warn threshold | Investigate |
| `FAIL_DRIFT_MAE` | MAE above fail threshold | Block |
| `FAIL_UNPROFITABLE` | Net PnL <= 0 | Block |
| `DIRTY_WORKTREE_PRECOMMIT` | Uncommitted changes | Weaker evidence |
| `WARMUP_MIN_RUNS` | Runs < 10 | In warmup |
| `WARMUP_MIN_SIGNALS` | Signals < 30 | In warmup |

## Warmup Configuration

Rolling window warmup protects against weak statistics:

| Setting | Value | Description |
|---------|-------|-------------|
| `max_runs` | 200 | Maximum runs in window |
| `min_runs` | 10 | Exit warmup after 10 runs |
| `min_signals` | 30 | Exit warmup after 30 signals |

During warmup:
- `agg_status = "PASS_WARMUP"`
- `agg_reasons` includes `WARMUP_MIN_RUNS` and/or `WARMUP_MIN_SIGNALS`

## Fragile Detection

Signals with low profit margin are "fragile" (easy to flip to loss):

- **Threshold**: $0.10 USDC
- **Fragile**: `0 < sim_net_usdc <= $0.10`
- **fragile_rate**: Percentage of fragile signals in run

## Evidence Policy

For **PROVEN** status:
1. At least one run with `code_dirty = false`
2. `evidence_sha` attached post-commit
3. `evidence.ok = true` (no blocking issues)

Evidence issues:
- `DIRTY_WORKTREE_PRECOMMIT`: Run made with uncommitted changes (weak evidence)
