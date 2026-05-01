# M7.E1.51 slice-5 — Anvil local sim backend (operational guide)

> Status: anvil backend is already wired in `m7/orderflow/simulation.py`
> (constants `BACKEND_ANVIL`, `_VALID_BACKENDS`). This document is the
> operational runbook for using it as the **production sim backend** when
> Tenderly credit/permission limits hit.

## When to switch from Tenderly to Anvil

Switch when `hot_runtime_artifacts` shows any of:

- `TENDERLY:HTTP_403_INSUFFICIENT_PERMISSIONS`
- `TENDERLY:CREDIT_QUOTA`
- `TENDERLY:INSUFFICIENT_FUNDS`

increasing across consecutive canary runs.

## Local anvil setup (Base mainnet fork)

```powershell
# Install foundry once
curl -L https://foundry.paradigm.xyz | bash
foundryup

# Pin a recent Base block to keep deterministic replay
$BASE_RPC = $env:ARBY_BASE_RPC_HTTP
anvil --fork-url $BASE_RPC --fork-block-number latest --port 8545 `
      --chain-id 8453 --steps-tracing --silent
```

Verify: `Invoke-WebRequest http://127.0.0.1:8545 -Method Post -ContentType 'application/json' -Body '{"jsonrpc":"2.0","method":"eth_chainId","params":[],"id":1}'` returns `0x2105`.

## ENV wiring

| Variable             | Value                       | Notes                               |
| -------------------- | --------------------------- | ----------------------------------- |
| `ARBY_SIM_BACKEND`   | `anvil`                     | router selects anvil path           |
| `ARBY_ANVIL_RPC_URL` | `http://127.0.0.1:8545`     | optional; default localhost:8545    |
| `ARBY_USE_LOCAL_PRICE_STATE` | `1`                  | default; pairs with slice-3 sink    |

## Acceptance metrics (slice-5 sign-off)

Run a 30m canary against Base with `ARBY_SIM_BACKEND=anvil` and verify in
`data/runs/_rolling/run_summary_latest.json`:

- `sim_attempted_delta > 0`
- `sim_failed_tenderly_*_delta == 0` (Tenderly errors absent)
- `sim_passed_delta >= sim_attempted_delta * 0.5` (≥50% pass-through)
- `gross_pnl_drift_bps_p95 < 10` vs reference Tenderly run on same logs

If `gross_pnl_drift_bps_p95 >= 10`, **do NOT promote anvil** — capture
the divergent bundle to `docs/artifacts/m7/anvil_drift/<timestamp>.json`
and open a slice-5b investigation.

## Failure modes & remediation

| Symptom                             | Root cause                          | Action                                    |
| ----------------------------------- | ----------------------------------- | ----------------------------------------- |
| `ECONNREFUSED 127.0.0.1:8545`       | anvil not running                   | restart `anvil --fork-url ...`            |
| Stale state vs WS logs              | fork block too old                  | `anvil_reset` with newer block            |
| `revert: ERC20: insufficient`       | impersonation needed                | `anvil_impersonateAccount`                |
| Drift > 10 bps                      | anvil tracing precision             | rerun with `--no-rate-limit` & full trace |

## Slice-5 verdict

This slice ships **operational documentation only**. The runtime
plumbing was already present (`simulation.py`). No code change needed.
Acceptance is gated by canary metrics under slice-8.
