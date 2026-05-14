# M8 Phase 2 — RPC Fork Backend Integration Plan

Status: research/design note (not yet implemented).

## Why

Phase 2 of M8 needs a fast, zero-infrastructure way to:
* simulate a buy + sell roundtrip on a newly created pool,
* detect honeypot tokens (transfer rejects, balance manipulation, tax-on-transfer),
* compute realistic slippage and gas costs.

Spinning up Anvil per candidate is expensive and only justified for the
terminal-stage execution check. The hot path needs RPC-only simulation.

## The asset we already have

`m7/orderflow/sim_backends/rpc_fork_backend.py` already implements
`eth_call` with `stateOverride` and exposes `simulate_swap_rpc_fork(...)`.
Key properties relevant to M8 Phase 2:

* Zero external infrastructure: uses production RPC (drpc / Alchemy /
  publicnode); supported by Geth / OP-Geth / dRPC / Alchemy.
* State overrides let us inject ERC-20 balances for the candidate trade
  without modifying chain state.
* Optional Flashblocks pre-confirmation tag on Base (`ARBY_FLASHBLOCKS_SIM=1`).

## Proposed M8 Phase 2 hook points

1. **Honeypot detector layer 1 — transfer simulation.**
   `discovery/honeypot_detector.py` (Phase 1 step 4 placeholder) calls
   `simulate_swap_rpc_fork()` with a tiny amount on the new pool to detect:
   - revert during transfer of either token,
   - non-zero "tax" (transfer-out delta < amount).

2. **Slippage estimator.**
   Same backend, larger amount, lookup `amountOut` vs the pool's
   constant-product math. If `predicted_slippage * 2.0 < observed_slippage`,
   trip the per-pool circuit breaker.

3. **Roundtrip realisability gate.**
   Phase 2 dry-run scoring (currently placeholders in the sniper artifact)
   moves to `simulate_swap_rpc_fork()` for both legs (`USDC -> token` and
   `token -> USDC`) on the same block tag. Output: `realisability_reason`
   is no longer a placeholder.

4. **Anvil reserved for terminal-stage.**
   The existing M7 Anvil infrastructure stays available but is invoked only
   for the *final* check before a paper / live submission, not for every
   candidate. This keeps RPC simulation as the hot path.

## Minimum integration surface

* New module `m8/scoring/realisability_simulator.py`:
  - Wraps `simulate_swap_rpc_fork` with M8-specific calldata builders for
    UniV3 / Aerodrome Slipstream / Aerodrome ve33 / Pancake V3 swaps.
  - Returns a structured result `{success, amount_out, gas, revert_reason}`.

* New artifact fields (additive, schema bump only when shipped):
  - `recent_events[].simulated_buy` (revert / amount_out / gas)
  - `recent_events[].simulated_sell` (same)
  - `recent_events[].realisability_reason` (concrete, not placeholder)

## Risks

* RPC-side `eth_call` with `stateOverride` is not universally supported on
  every provider; the fallback is "no honeypot data" (UNKNOWN) — never a
  false-positive PASS.
* Flashblocks pre-confirmation lag is OK-ish on Base but should not be
  required for correctness; it is purely a latency edge.

## Out of scope here

* Wiring this into M8 `runtime/smoke_run.py` — that is a Phase 2 task.
  Phase 1 closure does not depend on the simulator.
