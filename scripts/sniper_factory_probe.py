"""M8 — Per-factory eth_getLogs probe.

Runs a single eth_getLogs call per configured factory and reports:
  - raw log count
  - parse_ok count
  - errors

Useful for verifying multi-factory coverage before a full soak.

Usage::

    # Probe last 5000 blocks on Base:
    ARBY_SNIPER_ENABLE=1 py -3.11 scripts/sniper_factory_probe.py --chain base --blocks-back 5000

    # Probe specific block range:
    py -3.11 scripts/sniper_factory_probe.py --chain base --from-block 45940000 --to-block 45949999
"""
from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.env import load_root_dotenv
from core.logging import setup_logging
from discovery.new_pool_listener import FactoryConfig, load_factory_config, parse_raw_log

# ---------------------------------------------------------------------------
# RPC helpers (minimal, no funnel overhead)
# ---------------------------------------------------------------------------

def _resolve_rpc(chain: str, override: Optional[str]) -> str:
    if override:
        return override
    chain_upper = chain.upper()
    for env_var in (f"{chain_upper}_RPC", f"ARBY_{chain_upper}_RPC_URL", "ARBY_RPC_URL"):
        val = os.environ.get(env_var, "").strip()
        if val:
            return val
    raise RuntimeError(
        f"No RPC URL for chain={chain!r}. Set {chain_upper}_RPC env var or --rpc-url."
    )


def _get_block_number(w3: Any) -> Optional[int]:
    try:
        return int(w3.eth.block_number)
    except Exception as exc:
        print(f"[ERROR] eth_blockNumber failed: {exc}", file=sys.stderr)
        return None


def _get_logs_safe(w3: Any, params: Dict[str, Any]) -> tuple[List[Any], str]:
    """Returns (logs, error_str). error_str is '' on success."""
    try:
        return list(w3.eth.get_logs(params)), ""
    except Exception as exc:
        return [], str(exc)[:200]


# ---------------------------------------------------------------------------
# Per-factory probe
# ---------------------------------------------------------------------------

def _probe_factory(
    w3: Any,
    cfg: FactoryConfig,
    from_block: int,
    to_block: int,
) -> Dict[str, Any]:
    """Run a single eth_getLogs probe for one factory and return a result dict."""
    params: Dict[str, Any] = {
        "fromBlock": from_block,
        "toBlock": to_block,
        "address": w3.to_checksum_address(cfg.factory),
    }
    if cfg.topic0:
        params["topics"] = [cfg.topic0]

    t0 = time.monotonic()
    logs, err = _get_logs_safe(w3, params)
    elapsed = round(time.monotonic() - t0, 2)

    if err:
        return {
            "dex": cfg.dex,
            "factory": cfg.factory,
            "topic0": cfg.topic0,
            "topic0_verified": cfg.topic0_verified,
            "from_block": from_block,
            "to_block": to_block,
            "raw_logs": 0,
            "parse_ok": 0,
            "parse_failed": 0,
            "error": err,
            "elapsed_s": elapsed,
            "status": "ERROR",
        }

    raw_count = len(logs)
    parsed = [parse_raw_log(lg, cfg) for lg in logs]
    ok_count = sum(1 for e in parsed if e is not None)
    fail_count = raw_count - ok_count

    return {
        "dex": cfg.dex,
        "factory": cfg.factory,
        "topic0": cfg.topic0,
        "topic0_verified": cfg.topic0_verified,
        "from_block": from_block,
        "to_block": to_block,
        "raw_logs": raw_count,
        "parse_ok": ok_count,
        "parse_failed": fail_count,
        "error": None,
        "elapsed_s": elapsed,
        "status": "PASS" if ok_count > 0 else ("NO_EVENTS" if raw_count == 0 else "PARSE_FAIL"),
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main(argv: Optional[List[str]] = None) -> int:
    load_root_dotenv()
    setup_logging(json_format=False)

    parser = argparse.ArgumentParser(
        description="M8 — Per-factory eth_getLogs probe. Reports logs/parse_ok/error per dex.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--chain", default="base", help="Chain to probe.")
    parser.add_argument(
        "--blocks-back", type=int, default=5000, metavar="N",
        help="Probe this many historical blocks from current head (ignored if --from-block set).",
    )
    parser.add_argument("--from-block", type=int, default=None, metavar="N",
                        help="Explicit from_block (overrides --blocks-back).")
    parser.add_argument("--to-block", type=int, default=None, metavar="N",
                        help="Explicit to_block (default: current head).")
    parser.add_argument("--rpc-url", default=None, help="Override RPC URL.")
    parser.add_argument("--dex", default=None, help="Probe only this dex (filter).")
    args = parser.parse_args(argv)

    # Resolve RPC
    try:
        rpc_url = _resolve_rpc(args.chain, args.rpc_url)
    except RuntimeError as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 1

    try:
        from web3 import Web3
        w3 = Web3(Web3.HTTPProvider(rpc_url))
    except Exception as exc:
        print(f"[ERROR] web3 init failed: {exc}", file=sys.stderr)
        return 1

    # Resolve block range
    current_block = _get_block_number(w3)
    if current_block is None:
        print("[ERROR] Cannot get current block number.", file=sys.stderr)
        return 1

    to_block = args.to_block if args.to_block is not None else current_block
    from_block = (
        args.from_block
        if args.from_block is not None
        else max(0, to_block - args.blocks_back)
    )

    print(f"\n{'=' * 60}")
    print(f"SNIPER FACTORY PROBE — {args.chain.upper()}")
    print(f"Block range: {from_block} → {to_block}  ({to_block - from_block + 1} blocks)")
    print(f"{'=' * 60}")

    # Load factory configs
    try:
        configs = load_factory_config(chain_filter=args.chain)
    except Exception as exc:
        print(f"[ERROR] factory_config_load_failed: {exc}", file=sys.stderr)
        return 1

    if args.dex:
        configs = [c for c in configs if c.dex == args.dex]
        if not configs:
            print(f"[ERROR] No factory found for dex={args.dex!r}", file=sys.stderr)
            return 1

    results = []
    for cfg in configs:
        print(f"\n  Probing {cfg.dex} ({cfg.factory[:10]}…)  topic0_verified={cfg.topic0_verified}")
        r = _probe_factory(w3, cfg, from_block, to_block)
        results.append(r)
        status_tag = f"[{r['status']}]"
        if r["error"]:
            print(f"    {status_tag}  error: {r['error'][:80]}")
        else:
            pct = (
                f"  parse_rate={round(100.0 * r['parse_ok'] / r['raw_logs'], 1)}%"
                if r["raw_logs"] > 0 else ""
            )
            print(
                f"    {status_tag}  raw_logs={r['raw_logs']}  parse_ok={r['parse_ok']}"
                f"  parse_failed={r['parse_failed']}{pct}  ({r['elapsed_s']}s)"
            )

    # Summary table
    print(f"\n{'=' * 60}")
    print(f"{'DEX':<28} {'RAW':>6} {'OK':>6} {'FAIL':>6} {'ERR':>4}  STATUS")
    print(f"{'-' * 60}")
    for r in results:
        err_tag = "Y" if r["error"] else "."
        print(
            f"  {r['dex']:<26} {r['raw_logs']:>6} {r['parse_ok']:>6} {r['parse_failed']:>6}"
            f" {err_tag:>4}  {r['status']}"
        )
    print(f"{'=' * 60}\n")

    # Exit non-zero if any factory errored
    if any(r["error"] for r in results):
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
