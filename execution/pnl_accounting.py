"""E1.58 fix step #7: PnL accounting from wallet balance deltas.

A purely advisory module that captures token-balance snapshots before
and after an arb attempt and computes a PnL delta in USD.  The default
mode (``ARBY_PNL_DRY_RUN=1``) uses caller-supplied synthetic balances
and never makes RPC calls — the same path used by tests and offline
soaks.  Live mode reads ``balanceOf`` and native balance via web3 and
is gated on operator opt-in.

Public contract:

  * ``snapshot_balances(w3, owner, tokens, *, dry_run=None, override=None) -> dict``
  * ``compute_pnl(before, after, prices_usd) -> dict``

Both functions are pure (no side effects on rollup or files).  Caller
is responsible for persisting results into rolling artifacts.
"""

from __future__ import annotations

import os
from typing import Any, Dict, Iterable, Mapping, Optional


_ERC20_BALANCE_OF_ABI = [
    {
        "constant": True,
        "inputs": [{"name": "_owner", "type": "address"}],
        "name": "balanceOf",
        "outputs": [{"name": "balance", "type": "uint256"}],
        "type": "function",
    }
]


def _dry_run_default() -> bool:
    return os.environ.get("ARBY_PNL_DRY_RUN", "1").strip() != "0"


def snapshot_balances(
    w3,
    owner: Optional[str],
    tokens: Iterable[str],
    *,
    dry_run: bool | None = None,
    override: Optional[Mapping[str, int]] = None,
) -> Dict[str, int]:
    """Return ``{token_address: balance_wei}`` for each token in *tokens*.

    Native coin is represented as the string ``"native"`` (or the empty
    string) and uses ``eth.get_balance``.  In dry_run mode, the function
    returns ``override`` (or zeroed balances if no override given).
    """
    effective_dry = _dry_run_default() if dry_run is None else bool(dry_run)
    out: Dict[str, int] = {}

    if effective_dry:
        if override is not None:
            out.update({str(k): int(v) for k, v in override.items()})
        else:
            for t in tokens:
                out[t] = 0
        return out

    if w3 is None or not owner:
        # cannot read live balances without context — degrade to zeros
        for t in tokens:
            out[t] = 0
        return out

    for t in tokens:
        try:
            if t in (None, "", "native"):
                out[t] = int(w3.eth.get_balance(owner))
            else:
                contract = w3.eth.contract(address=t, abi=_ERC20_BALANCE_OF_ABI)
                out[t] = int(contract.functions.balanceOf(owner).call())
        except Exception:  # pragma: no cover - RPC dependent
            out[t] = 0
    return out


def compute_pnl(
    before: Mapping[str, int],
    after: Mapping[str, int],
    prices_usd: Mapping[str, float],
) -> Dict[str, Any]:
    """Compute per-token deltas and a USD total.

    ``prices_usd`` maps token address (or ``"native"``) to price per 1e18 wei.
    Tokens that appear only in ``after`` are treated as if their ``before``
    balance was zero (and vice versa).  Tokens missing from ``prices_usd``
    contribute zero USD but are surfaced in ``per_token_delta_wei`` so the
    operator can spot unpriced assets.
    """
    deltas: Dict[str, int] = {}
    keys = set(before.keys()) | set(after.keys())
    for k in keys:
        a = int(after.get(k, 0) or 0)
        b = int(before.get(k, 0) or 0)
        deltas[k] = a - b

    total_usd = 0.0
    unpriced = []
    for k, dv in deltas.items():
        price = prices_usd.get(k)
        if price is None:
            unpriced.append(k)
            continue
        try:
            # convert wei→whole units assuming 18 decimals (caller may
            # pre-scale prices_usd for non-18-decimal tokens)
            total_usd += float(dv) / 1e18 * float(price)
        except (TypeError, ValueError):
            unpriced.append(k)

    return {
        "per_token_delta_wei": deltas,
        "total_pnl_usd": round(total_usd, 6),
        "unpriced_tokens": unpriced,
    }


def post_trade_accounting_contract(
    before: Mapping[str, int],
    after: Mapping[str, int],
    prices_usd: Mapping[str, float],
    *,
    gas_used: int = 0,
    l1_fee_wei: int = 0,
    gas_price_wei: int = 0,
) -> Dict[str, Any]:
    """Step 8: single-call post-trade accounting contract.

    Combines balance deltas, gas cost, L1 fee, and net PnL into a
    single dict that can be stored directly in the rolling artifact.
    In dry_run mode (``ARBY_PNL_DRY_RUN=1``, the default) all balance
    inputs are caller-supplied synthetic values — no RPC calls are made.

    Fields returned:
      * ``balances_before`` / ``balances_after``: token→wei snapshots
      * ``gas_used``, ``gas_price_wei``, ``l1_fee_wei``
      * ``gas_cost_wei`` = gas_used × gas_price_wei
      * ``total_cost_wei`` = gas_cost_wei + l1_fee_wei
      * ``per_token_delta_wei``, ``total_pnl_usd``, ``unpriced_tokens``
        (from ``compute_pnl``)
      * ``net_pnl_usd``: total_pnl_usd minus gas/L1 cost in USD
      * ``accounting_mode``: ``"dry_run"`` | ``"live"``
    """
    pnl = compute_pnl(before, after, prices_usd)
    gas_cost_wei = int(gas_used) * int(gas_price_wei)
    total_cost_wei = gas_cost_wei + int(l1_fee_wei)
    native_price = float(prices_usd.get("native", 0.0) or 0.0)
    cost_usd = float(total_cost_wei) / 1e18 * native_price
    net_pnl_usd = round(float(pnl["total_pnl_usd"]) - cost_usd, 6)
    mode = "dry_run" if _dry_run_default() else "live"
    return {
        "balances_before": dict(before),
        "balances_after": dict(after),
        "gas_used": int(gas_used),
        "gas_price_wei": int(gas_price_wei),
        "l1_fee_wei": int(l1_fee_wei),
        "gas_cost_wei": gas_cost_wei,
        "total_cost_wei": total_cost_wei,
        "per_token_delta_wei": pnl["per_token_delta_wei"],
        "total_pnl_usd": pnl["total_pnl_usd"],
        "unpriced_tokens": pnl["unpriced_tokens"],
        "net_pnl_usd": net_pnl_usd,
        "accounting_mode": mode,
    }
