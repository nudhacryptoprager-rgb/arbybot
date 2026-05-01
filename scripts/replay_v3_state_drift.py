"""M7.E1.51 slice-4 — replay V3 state drift harness.

Purpose
-------
Validate that the local pool-price-state registry, when fed only with raw
WS Swap logs, reproduces the canonical ``slot0`` snapshot for the same
pools at the same block. This is an offline harness — it does not call
any live RPC. It consumes a JSON bundle of the form::

    {
        "chain": "base",
        "logs": [ { "address": ..., "blockNumber": ..., "logIndex": ...,
                    "data": "0x..." }, ... ],
        "ground_truth": {
            "<pool_address_lc>": {
                "block_number": 12345,
                "sqrt_price_x96": 79228162514264337593543950336,
                "tick": 0,
                "liquidity": 1000000
            }, ...
        }
    }

Output
------
JSON to stdout with::

    {
        "pools_total": int,
        "pools_matched": int,
        "pools_drift": int,
        "drift_pools_pct": float,
        "max_sqrt_price_drift_bps": float,
        "details": [ {"pool": ..., "drift_bps": ..., "ok": bool}, ... ],
        "verdict": "PASS" | "FAIL"
    }

Acceptance (slice-4): ``drift_pools_pct < 1.0`` AND
``max_sqrt_price_drift_bps < 5``.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict


def _abs_drift_bps(actual: int, expected: int) -> float:
    if expected == 0:
        return float("inf") if actual != 0 else 0.0
    return abs(actual - expected) / expected * 10_000.0


def replay_drift(bundle: Dict[str, Any]) -> Dict[str, Any]:
    # Local imports keep the module importable without a configured
    # PYTHONPATH for ad-hoc CLI usage.
    from m7.orderflow.pool_price_state import (
        PoolPriceStateRegistry,
    )

    chain = bundle.get("chain", "base")
    logs = bundle.get("logs", []) or []
    truth = bundle.get("ground_truth", {}) or {}

    reg = PoolPriceStateRegistry()
    for lg in logs:
        try:
            data_hex = lg.get("data") or ""
            payload = data_hex[2:] if data_hex.startswith("0x") else data_hex
            if len(payload) >= 320:
                reg.update_from_v3_log(chain, lg)
            elif len(payload) >= 128:
                reg.update_from_v2_log(chain, lg)
        except Exception:
            continue

    details = []
    matched = 0
    drift = 0
    max_bps = 0.0

    for pool_addr, gt in truth.items():
        st = reg.get(chain, pool_addr)
        if st is None:
            details.append({"pool": pool_addr, "ok": False, "reason": "MISSING"})
            drift += 1
            continue
        bps = _abs_drift_bps(st.sqrt_price_x96, int(gt["sqrt_price_x96"]))
        ok = (
            st.tick == int(gt["tick"])
            and bps == 0.0
            and st.liquidity == int(gt["liquidity"])
        )
        if ok:
            matched += 1
        else:
            drift += 1
        max_bps = max(max_bps, bps)
        details.append(
            {
                "pool": pool_addr,
                "ok": ok,
                "drift_bps": bps,
                "actual_tick": st.tick,
                "expected_tick": int(gt["tick"]),
            }
        )

    total = len(truth)
    drift_pct = (drift / total * 100.0) if total > 0 else 0.0
    verdict = "PASS" if (drift_pct < 1.0 and max_bps < 5.0) else "FAIL"

    return {
        "chain": chain,
        "pools_total": total,
        "pools_matched": matched,
        "pools_drift": drift,
        "drift_pools_pct": drift_pct,
        "max_sqrt_price_drift_bps": max_bps,
        "details": details,
        "verdict": verdict,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Replay V3 state drift harness")
    parser.add_argument("--bundle", required=True, help="Path to JSON bundle")
    args = parser.parse_args(argv)

    path = Path(args.bundle)
    if not path.is_file():
        print(json.dumps({"verdict": "FAIL", "reason": f"missing bundle: {path}"}))
        return 2

    with path.open("r", encoding="utf-8") as f:
        bundle = json.load(f)

    out = replay_drift(bundle)
    print(json.dumps(out, indent=2))
    return 0 if out["verdict"] == "PASS" else 1


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
