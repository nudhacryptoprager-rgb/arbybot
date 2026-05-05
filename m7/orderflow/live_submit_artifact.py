"""m7/orderflow/live_submit_artifact.py — Write live submit + post-trade PnL artifacts.

Each live execution attempt writes two rolling artifacts:
  data/runs/_rolling/live_submit_latest.json    — latest submission attempt
  data/runs/_rolling/live_pnl_latest.json       — latest post-trade PnL

These are overwritten on every attempt (rolling discipline).
The artifact schema is additive; downstream code must tolerate extra keys.

Public API:
  write_live_submit_artifact(spread_id, tx_hash, exec_result, *, canary_only)
  write_live_pnl_artifact(spread_id, before, after, gas_used, gas_price_wei, l1_fee_wei, eth_price_usd)
"""
from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from core.json_io import atomic_write_json
from core.logging import get_logger

logger = get_logger("m7.orderflow.live_submit_artifact")

_ROLLING_DIR = os.path.join("data", "runs", "_rolling")


def _rolling_path(name: str) -> str:
    return os.path.join(_ROLLING_DIR, name)


def write_live_submit_artifact(
    spread_id: str,
    tx_hash: Optional[str],
    exec_result: Any,
    *,
    canary_only: bool = True,
) -> None:
    """Write live_submit_latest.json with submission attempt fields.

    Fields (Step 3 — reviewer requirement):
      live_submit_attempted, relay, bundle_hash, tx_hash, included,
      receipt_status, canary_only, spread_id, timestamp
    """
    state = str(getattr(exec_result, "state", "UNKNOWN"))
    receipt = getattr(exec_result, "receipt", None)
    receipt_status = None
    if receipt is not None:
        receipt_status = getattr(receipt, "status", None)
        if receipt_status is None:
            receipt_status = (receipt or {}).get("status") if isinstance(receipt, dict) else None

    artifact: Dict[str, Any] = {
        "schema_version": "live_submit_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spread_id": spread_id,
        "canary_only": canary_only,
        "live_submit_attempted": True,
        "relay": os.environ.get("ARBY_FLASHBOTS_RELAY_BASE", "") or "direct_rpc",
        "bundle_hash": getattr(exec_result, "bundle_hash", None),
        "tx_hash": tx_hash,
        "state": state,
        "included": receipt_status == 1,
        "receipt_status": receipt_status,
        "error_message": getattr(exec_result, "error_message", None),
        "gas_used": getattr(exec_result, "gas_used", None),
        "gas_price_gwei": getattr(exec_result, "gas_price_gwei", None),
    }

    try:
        os.makedirs(_ROLLING_DIR, exist_ok=True)
        atomic_write_json(_rolling_path("live_submit_latest.json"), artifact)
        logger.info(
            "Live submit artifact written: tx_hash=%s state=%s included=%s",
            tx_hash, state, artifact["included"],
            extra={"context": {"live_submit_artifact": True}},
        )
    except Exception as exc:
        logger.warning("Failed to write live_submit_latest.json: %s", exc)


def write_live_pnl_artifact(
    spread_id: str,
    before: Dict[str, int],  # {token_address: balance_wei}
    after: Dict[str, int],
    gas_used: int,
    gas_price_wei: int,
    l1_fee_wei: int,
    eth_price_usd: float,
) -> None:
    """Write live_pnl_latest.json with post-trade PnL breakdown.

    Fields (Step 4 — reviewer requirement):
      balances_before, balances_after, gas_used, gas_price_wei, l1_fee_wei,
      total_gas_cost_wei, total_gas_cost_usd, per_token_delta_wei,
      realized_pnl_wei, net_pnl_usd
    """
    total_gas_cost_wei = gas_used * gas_price_wei + l1_fee_wei
    eth_per_wei = 1e-18
    total_gas_cost_usd = total_gas_cost_wei * eth_per_wei * eth_price_usd

    per_token_delta: Dict[str, int] = {}
    all_tokens = set(before) | set(after)
    for tok in all_tokens:
        per_token_delta[tok] = after.get(tok, 0) - before.get(tok, 0)

    # Naive realized PnL: assume single native-token delta (ETH/WETH position)
    native_delta_wei = sum(per_token_delta.values())
    realized_pnl_wei = native_delta_wei
    realized_pnl_usd = realized_pnl_wei * eth_per_wei * eth_price_usd
    net_pnl_usd = realized_pnl_usd - total_gas_cost_usd

    artifact: Dict[str, Any] = {
        "schema_version": "live_pnl_v1",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "spread_id": spread_id,
        "balances_before": before,
        "balances_after": after,
        "per_token_delta_wei": per_token_delta,
        "gas_used": gas_used,
        "gas_price_wei": gas_price_wei,
        "l1_fee_wei": l1_fee_wei,
        "total_gas_cost_wei": total_gas_cost_wei,
        "total_gas_cost_usd": round(total_gas_cost_usd, 6),
        "eth_price_usd": eth_price_usd,
        "realized_pnl_wei": realized_pnl_wei,
        "realized_pnl_usd": round(realized_pnl_usd, 6),
        "net_pnl_usd": round(net_pnl_usd, 6),
        "accounting_mode": "live",
    }

    try:
        os.makedirs(_ROLLING_DIR, exist_ok=True)
        atomic_write_json(_rolling_path("live_pnl_latest.json"), artifact)
        logger.info(
            "Live PnL artifact written: net_pnl_usd=%.6f gas_usd=%.6f",
            net_pnl_usd, total_gas_cost_usd,
            extra={"context": {"live_pnl_artifact": True}},
        )
    except Exception as exc:
        logger.warning("Failed to write live_pnl_latest.json: %s", exc)
