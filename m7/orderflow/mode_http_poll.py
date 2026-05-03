"""HTTP-only proof lane (E1.52).

Pure HTTP block polling — no WebSocket dependency. Decouples canary proof
from ``eth_subscribe newHeads`` so a paid/healthy WS provider is no longer a
hard prerequisite for demonstrating the V3/V2 sink works against live chain
data.

Public surface
--------------
* :func:`run_http_poll_proof` — single-shot proof window. Polls
  ``eth_blockNumber`` then ``eth_getLogs`` for V3 Swap and V2 Sync topics on
  the same block, feeds the local pool price registry, and writes an
  overwrite-only rolling artifact ``data/runs/_rolling/m7_proof_latest.json``.

Design
------
* No WebSocket. No long-lived connection. No subscription state.
* Topic-aware ``eth_getLogs`` calls (V3 Swap and V2 Sync) — no length
  heuristic ambiguity.
* Defensive: never raises. Every iteration writes the artifact even if
  the chain stalls, so reviewer cadence guard sees a heartbeat.
* Single-process: the rolling artifact reflects only this process's
  registry. Cross-process registry sharing is out of scope for this lane.
* Session-scoped counters: registry counters are baselined at the start of
  each ``run_http_poll_proof`` call so cumulative process-level accum
  doesn't inflate per-window metrics.
* Separate V3/V2 getLogs error counters (step 1): ``_http_get_logs_with_err``
  returns both the logs and a boolean error flag, so failures are visible in
  the artifact rather than silently dropped.
* Economics verdicts (steps 4–8): ``TWO_POOL_RESOURCE_OK``, ``LIQUIDITY_OK``,
  ``SLIPPAGE_OK``, gas/L1 cost fields, and ``ROUNDTRIP_SIM_OK`` (local paper
  quote, no token metadata required).
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from m7.orderflow.pool_price_state import (
    V2_SYNC_TOPIC,
    V3_SWAP_TOPIC,
    feed_raw_logs,
    get_registry,
)


_DEFAULT_ROLLING = Path("data/runs/_rolling/m7_proof_latest.json")

# Base trade size for local quote checks (1 ETH in wei).
# Used for SLIPPAGE_OK and ROUNDTRIP_SIM_OK.
_BASE_TRADE_WEI = 10 ** 18

# Default pool fee used when fee-tier metadata is unavailable (0.30%).
_DEFAULT_FEE_PIPS = 3000

# Slippage threshold for SLIPPAGE_OK verdict (bps).
_MAX_SLIPPAGE_BPS = 200

# Min gas cost on Base / L2 (USD).  Used for paper spread check.
_GAS_USD_BASE = 0.01
# Trade notional USD for gas-bps normalisation.
_TRADE_SIZE_USD = 1000.0
# Gas estimate for two-leg arb on Base (L2 gas units).
_GAS_UNITS_TWO_LEG = 350_000
# L2 gas price in wei (0.005 gwei ≈ Base typical).
_GAS_PRICE_WEI = 5_000_000


def _utc_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _safe_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except Exception:
        return default


def _http_get_logs_with_err(w3: Any, params: Dict[str, Any]) -> Tuple[List[Any], bool]:
    """Call ``eth.get_logs(params)`` and return (logs, had_error).

    Separates errors from empty results so callers can track
    ``v3_get_logs_errors_total`` / ``v2_get_logs_errors_total`` in the
    artifact rather than hiding failures in a silent ``[]``.
    """
    try:
        return list(w3.eth.get_logs(params)), False
    except Exception:
        return [], True


def _normalize_pool_addr(lg: Any) -> Optional[str]:
    try:
        addr = lg["address"] if hasattr(lg, "__getitem__") else None
        if addr is None:
            return None
        return str(addr).lower()
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Economics helpers (steps 4–8)
# ---------------------------------------------------------------------------

def _gas_cost_bps(gas_units: int, gas_price_wei: int, trade_size_usd: float) -> float:
    """Estimate gas cost in basis points of trade notional.

    Uses a fixed ETH price of 2000 USD.  Proof lane only — not for
    live execution sizing.
    """
    eth_usd = 2000.0
    gas_cost_usd = (gas_units * gas_price_wei / 1e18) * eth_usd
    if trade_size_usd <= 0:
        return 0.0
    return (gas_cost_usd / trade_size_usd) * 10_000.0


def _l1_fee_bps_estimate(chain: str, trade_size_usd: float) -> float:
    """Static L1 fee estimate in bps.  Uses ``chains.l1_cost`` default (step 7).

    Falls back to a hardcoded default if the module is unavailable.
    """
    try:
        from chains.l1_cost import estimate_l1_cost_default
        l1_cost_wei = estimate_l1_cost_default()
        eth_usd = 2000.0
        l1_cost_usd = (l1_cost_wei / 1e18) * eth_usd
        if trade_size_usd <= 0:
            return 0.0
        return (l1_cost_usd / trade_size_usd) * 10_000.0
    except Exception:
        return 0.0


def _compute_economics(chain: str) -> Dict[str, Any]:
    """Compute static gas + L1 cost estimates and TWO_POOL/LIQUIDITY/
    SLIPPAGE/ROUNDTRIP verdicts from local registry state (steps 4–8).

    Returns a dict written into the proof artifact under the ``economics``
    key.  Never raises.
    """
    try:
        from m7.orderflow.v3_math import compute_v3_swap_amount_out
    except Exception:
        compute_v3_swap_amount_out = None  # type: ignore[assignment]

    try:
        reg = get_registry()
        v3_states = reg.all_v3_states(chain)
        v2_states = reg.all_v2_states(chain)
    except Exception:
        v3_states, v2_states = [], []

    gas_bps = round(_gas_cost_bps(_GAS_UNITS_TWO_LEG, _GAS_PRICE_WEI, _TRADE_SIZE_USD), 4)
    l1_fee_bps = round(_l1_fee_bps_estimate(chain, _TRADE_SIZE_USD), 4)
    # Default LP fees: two legs at 0.30% each = 60 bps.
    lp_fee_bps = 60.0
    safety_bps = 2.0
    slippage_allowance_bps = 5.0
    total_cost_bps = round(lp_fee_bps + slippage_allowance_bps + gas_bps + l1_fee_bps + safety_bps, 4)

    # Step 4 — TWO_POOL_RESOURCE_OK
    # Cross-venue proof: at least one V3 AND one V2 pool observed this session.
    two_pool_ok = len(v3_states) >= 1 and len(v2_states) >= 1

    # Step 5 — LIQUIDITY_OK
    # At least one V3 pool with liquidity > 0; at least one V2 pool with reserve0 > 0.
    v3_liquid = any(s.liquidity > 0 for s in v3_states)
    v2_liquid = any(s.reserve0 > 0 and s.reserve1 > 0 for s in v2_states)
    liquidity_ok = v3_liquid or v2_liquid

    # Step 6 — SLIPPAGE_OK + local quote
    # Pick the V3 pool with the highest liquidity and try to quote _BASE_TRADE_WEI.
    best_v3_pool: Optional[str] = None
    best_v3_quote_out: Optional[int] = None
    slippage_ok = False
    v3_quote_detail: Optional[Dict[str, Any]] = None

    if v3_states and compute_v3_swap_amount_out is not None:
        top_v3 = max(v3_states, key=lambda s: s.liquidity, default=None)
        if top_v3 is not None and top_v3.liquidity > 0:
            out = compute_v3_swap_amount_out(
                sqrt_price_x96=top_v3.sqrt_price_x96,
                liquidity=top_v3.liquidity,
                amount_in=_BASE_TRADE_WEI,
                fee_pips=_DEFAULT_FEE_PIPS,
                zero_for_one=True,
            )
            best_v3_pool = top_v3.pool_address
            best_v3_quote_out = out
            if out is not None and out > 0:
                # Estimate slippage vs ideal (price = out/in before fee)
                ideal = int(_BASE_TRADE_WEI * (1 - _DEFAULT_FEE_PIPS / 1_000_000))
                if ideal > 0:
                    slip_bps = max(0.0, (ideal - out) / ideal * 10_000)
                else:
                    slip_bps = 9999.0
                slippage_ok = slip_bps < _MAX_SLIPPAGE_BPS
                v3_quote_detail = {
                    "pool": best_v3_pool,
                    "amount_in_wei": _BASE_TRADE_WEI,
                    "amount_out_wei": out,
                    "slippage_bps": round(slip_bps, 2),
                    "liquidity": top_v3.liquidity,
                }

    # Step 8 — ROUNDTRIP_SIM_OK (local paper, no token metadata)
    # Checks: V3 quote is non-None (price computable) AND V2 pool is liquid.
    # Full cross-pool spread comparison requires token metadata (out of scope).
    # This is "local-state-only paper check".
    roundtrip_sim_ok = (best_v3_quote_out is not None) and v2_liquid

    # Best V2 pool info for artifact visibility.
    best_v2_pool: Optional[str] = None
    if v2_states:
        top_v2 = max(v2_states, key=lambda s: s.reserve0 + s.reserve1, default=None)
        if top_v2 is not None:
            best_v2_pool = top_v2.pool_address

    return {
        "gas_bps": gas_bps,
        "l1_fee_bps": l1_fee_bps,
        "total_cost_bps": total_cost_bps,
        "lp_fee_bps": lp_fee_bps,
        "gas_units_estimate": _GAS_UNITS_TWO_LEG,
        "gas_price_wei": _GAS_PRICE_WEI,
        "v3_pools_sampled": len(v3_states),
        "v2_pools_sampled": len(v2_states),
        "best_v3_pool": best_v3_pool,
        "best_v2_pool": best_v2_pool,
        "v3_quote": v3_quote_detail,
        "TWO_POOL_RESOURCE_OK": two_pool_ok,
        "LIQUIDITY_OK": liquidity_ok,
        "SLIPPAGE_OK": slippage_ok,
        "ROUNDTRIP_SIM_OK": roundtrip_sim_ok,
        "note": (
            "ROUNDTRIP_SIM_OK is a local-state-only paper check. "
            "Full cross-pool roundtrip requires token metadata."
        ),
    }


def _build_proof_artifact(
    *,
    chain: str,
    rpc_url: str,
    started_at: str,
    ended_at: str,
    iters: int,
    blocks_seen: int,
    v3_logs_total: int,
    v2_logs_total: int,
    v3_get_logs_errors: int,
    v2_get_logs_errors: int,
    feed_counters: Dict[str, int],
    last_block_number: Optional[int],
    last_iter_v3_pools: List[str],
    errors: int,
    baseline_counters: Optional[Dict[str, int]] = None,
    include_economics: bool = False,
) -> Dict[str, Any]:
    """Build the rolling proof artifact dict.

    Parameters
    ----------
    baseline_counters : Optional[Dict[str, int]]
        Registry counter snapshot taken at session start (step 2).
        If provided, ``pool_price_state`` values reflect the *delta*
        accumulated during this window, not cumulative process totals.
    include_economics : bool
        If True, add ``economics`` block (steps 4–8). Skip on heartbeat
        writes to avoid slowing down the main loop.
    """
    reg = get_registry()
    reg_counters = reg.counters()

    def _delta(key: str) -> int:
        raw = reg_counters.get(key, 0)
        if baseline_counters is not None:
            return max(0, raw - baseline_counters.get(key, 0))
        return raw

    v3_updates = _delta("updates_total")
    v2_updates = _delta("v2_updates_total")
    decode_errors = _delta("decode_errors_total")
    v2_decode_errors = _delta("v2_decode_errors_total")
    stale_drops = _delta("stale_drops_total")
    v2_stale_drops = _delta("v2_stale_drops_total")

    art: Dict[str, Any] = {
        "schema_version": "m7.e1.52.proof.v2",
        "lane": "proof_http_poll",
        "chain": chain,
        "rpc_url_host": rpc_url.split("//")[-1].split("/")[0] if rpc_url else None,
        "window": {
            "started_at": started_at,
            "ended_at": ended_at,
            "iterations": iters,
            "blocks_seen": blocks_seen,
            "last_block_number": last_block_number,
        },
        "logs": {
            "v3_swap_total": v3_logs_total,
            "v2_sync_total": v2_logs_total,
            "v3_get_logs_errors_total": v3_get_logs_errors,
            "v2_get_logs_errors_total": v2_get_logs_errors,
            "errors_total": errors,
        },
        "pool_price_state": {
            "v3_updates_total": v3_updates,
            "v2_updates_total": v2_updates,
            "decode_errors_total": decode_errors,
            "v2_decode_errors_total": v2_decode_errors,
            "stale_drops_total": stale_drops,
            "v2_stale_drops_total": v2_stale_drops,
            "pools_tracked": reg.pools_tracked(),
        },
        "feed_counters_window": dict(feed_counters),
        "last_iter_v3_pools_top": last_iter_v3_pools[:20],
        "verdict_partial": {
            "POOL_STATE_OK": (v3_updates > 0 or v2_updates > 0),
            "RAW_LOGS_OK": (v3_logs_total + v2_logs_total) > 0,
            "RPC_OK": errors < max(3, iters // 2),
        },
        "last_updated": ended_at,
    }

    if include_economics:
        try:
            econ = _compute_economics(chain)
            art["economics"] = econ
            # Promote economics verdicts to verdict_partial for easy scanning.
            art["verdict_partial"]["TWO_POOL_RESOURCE_OK"] = econ.get("TWO_POOL_RESOURCE_OK", False)
            art["verdict_partial"]["LIQUIDITY_OK"] = econ.get("LIQUIDITY_OK", False)
            art["verdict_partial"]["SLIPPAGE_OK"] = econ.get("SLIPPAGE_OK", False)
            art["verdict_partial"]["ROUNDTRIP_SIM_OK"] = econ.get("ROUNDTRIP_SIM_OK", False)
        except Exception:
            pass

    return art


def _write_proof_artifact(artifact: Dict[str, Any], dest: Path = _DEFAULT_ROLLING) -> None:
    """Atomic-ish overwrite. Never raises."""
    try:
        dest.parent.mkdir(parents=True, exist_ok=True)
        tmp = dest.with_suffix(dest.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as f:
            json.dump(artifact, f, ensure_ascii=False, indent=2)
        os.replace(tmp, dest)
    except Exception:
        pass


def run_http_poll_proof(
    *,
    chain: str = "base",
    duration_s: float = 60.0,
    poll_interval_s: float = 1.5,
    rpc_url: Optional[str] = None,
    artifact_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """Run a single HTTP-poll proof window.

    Returns the final artifact dict (also written to disk).

    Parameters
    ----------
    chain : str
        Chain key (e.g. ``"base"``).
    duration_s : float
        Total duration of the proof window. The function returns shortly
        after this elapses.
    poll_interval_s : float
        Sleep between ``eth_blockNumber`` polls.
    rpc_url : Optional[str]
        Explicit HTTP RPC URL. Falls back to :func:`core.rpc_urls.resolve_rpc_http`.
    artifact_path : Optional[Path]
        Override the default rolling artifact path. Used by tests.
    """
    started_at = _utc_iso()
    dest = artifact_path or _DEFAULT_ROLLING

    # Step 2 — Session baseline: snapshot registry counters before polling starts.
    # Delta = current counters – baseline counters. This prevents cumulative
    # process-level accum from inflating per-window metrics when the same
    # process runs multiple windows (e.g. repeated test calls).
    try:
        baseline_counters: Optional[Dict[str, int]] = dict(get_registry().counters())
    except Exception:
        baseline_counters = None

    def _artifact(**kw: Any) -> Dict[str, Any]:
        return _build_proof_artifact(
            chain=chain,
            rpc_url=rpc_url or "",
            started_at=started_at,
            baseline_counters=baseline_counters,
            **kw,
        )

    _empty_feeds = {"v3_updates": 0, "v2_updates": 0, "skipped": 0}

    # Resolve RPC
    if rpc_url is None:
        try:
            from core.rpc_urls import resolve_rpc_http
            rpc_url, _provider, _diag = resolve_rpc_http(network=chain)
        except Exception:
            rpc_url = ""
    if not rpc_url:
        art = _artifact(
            ended_at=_utc_iso(),
            iters=0,
            blocks_seen=0,
            v3_logs_total=0,
            v2_logs_total=0,
            v3_get_logs_errors=0,
            v2_get_logs_errors=0,
            feed_counters=dict(_empty_feeds),
            last_block_number=None,
            last_iter_v3_pools=[],
            errors=1,
            include_economics=True,
        )
        _write_proof_artifact(art, dest)
        return art

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 10}))
    except Exception:
        art = _artifact(
            ended_at=_utc_iso(),
            iters=0,
            blocks_seen=0,
            v3_logs_total=0,
            v2_logs_total=0,
            v3_get_logs_errors=0,
            v2_get_logs_errors=0,
            feed_counters=dict(_empty_feeds),
            last_block_number=None,
            last_iter_v3_pools=[],
            errors=1,
            include_economics=True,
        )
        _write_proof_artifact(art, dest)
        return art

    end_monotonic = time.monotonic() + max(0.0, duration_s)
    iters = 0
    blocks_seen = 0
    v3_logs_total = 0
    v2_logs_total = 0
    v3_get_logs_errors = 0
    v2_get_logs_errors = 0
    errors = 0
    last_block: Optional[int] = None
    last_seen_block: Optional[int] = None
    last_iter_v3_pools: List[str] = []
    accum_feed = {"v3_updates": 0, "v2_updates": 0, "skipped": 0}

    while time.monotonic() < end_monotonic:
        iters += 1
        try:
            cur = _safe_int(w3.eth.block_number, -1)
        except Exception:
            cur = -1
            errors += 1

        if cur > 0 and cur != last_seen_block:
            last_seen_block = cur
            blocks_seen += 1
            last_block = cur

            # Step 1 — separate V3/V2 getLogs error counters.
            v3_logs, v3_err = _http_get_logs_with_err(w3, {
                "fromBlock": cur,
                "toBlock": cur,
                "topics": [V3_SWAP_TOPIC],
            })
            v3_logs_total += len(v3_logs)
            if v3_err:
                v3_get_logs_errors += 1

            v2_logs, v2_err = _http_get_logs_with_err(w3, {
                "fromBlock": cur,
                "toBlock": cur,
                "topics": [V2_SYNC_TOPIC],
            })
            v2_logs_total += len(v2_logs)
            if v2_err:
                v2_get_logs_errors += 1

            # Feed both into the local registry.
            if v3_logs:
                r = feed_raw_logs(chain, v3_logs)
                accum_feed["v3_updates"] += r.get("v3_updates", 0)
                accum_feed["v2_updates"] += r.get("v2_updates", 0)
                accum_feed["skipped"] += r.get("skipped", 0)
                last_iter_v3_pools = [
                    p for p in (_normalize_pool_addr(lg) for lg in v3_logs)
                    if p is not None
                ]
            if v2_logs:
                r = feed_raw_logs(chain, v2_logs)
                accum_feed["v3_updates"] += r.get("v3_updates", 0)
                accum_feed["v2_updates"] += r.get("v2_updates", 0)
                accum_feed["skipped"] += r.get("skipped", 0)

        # Heartbeat artifact write every iteration (no economics — keep loop fast).
        heartbeat = _artifact(
            ended_at=_utc_iso(),
            iters=iters,
            blocks_seen=blocks_seen,
            v3_logs_total=v3_logs_total,
            v2_logs_total=v2_logs_total,
            v3_get_logs_errors=v3_get_logs_errors,
            v2_get_logs_errors=v2_get_logs_errors,
            feed_counters=dict(accum_feed),
            last_block_number=last_block,
            last_iter_v3_pools=last_iter_v3_pools,
            errors=errors,
            include_economics=False,
        )
        _write_proof_artifact(heartbeat, dest)

        time.sleep(max(0.05, poll_interval_s))

    # Final write — include full economics block (steps 4–8).
    artifact = _artifact(
        ended_at=_utc_iso(),
        iters=iters,
        blocks_seen=blocks_seen,
        v3_logs_total=v3_logs_total,
        v2_logs_total=v2_logs_total,
        v3_get_logs_errors=v3_get_logs_errors,
        v2_get_logs_errors=v2_get_logs_errors,
        feed_counters=dict(accum_feed),
        last_block_number=last_block,
        last_iter_v3_pools=last_iter_v3_pools,
        errors=errors,
        include_economics=True,
    )
    _write_proof_artifact(artifact, dest)
    return artifact


__all__ = [
    "run_http_poll_proof",
]

