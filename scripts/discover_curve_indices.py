"""
Discover Curve pool coin indices via eth_call coins(uint256).

Reads bridge inventory curve_stable pools, resolves symbols from config only
(exotic_base_anchor.yaml [tokens] + adapter_metadata.yaml curve.base.anchor_tokens),
writes rolling artifact for runtime merge (NOT into adapter_metadata.yaml pools).

Usage:
    py -3.11 scripts/discover_curve_indices.py
    py -3.11 scripts/discover_curve_indices.py --partial
    py -3.11 scripts/discover_curve_indices.py --output data/runs/_rolling/m9_curve_pool_indices_latest.json

Requires BASE_RPC env var or uses publicnode fallback.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
import yaml  # type: ignore[import]

RPC_URL = os.environ.get("BASE_RPC", "https://base.publicnode.com")
REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INVENTORY = REPO_ROOT / "data/runs/_rolling/m9_bridge_inventory_latest.json"
DEFAULT_METADATA = REPO_ROOT / "config/adapter_metadata.yaml"
DEFAULT_ANCHOR = REPO_ROOT / "config/exotic_base_anchor.yaml"
DEFAULT_OUTPUT = REPO_ROOT / "data/runs/_rolling/m9_curve_pool_indices_latest.json"
SCHEMA_VERSION = "m9_curve_pool_indices.1"

COINS_SELECTOR_UINT = "c6610657"
COINS_SELECTOR_INT128 = "23746eb8"

# Curve has two incompatible get_dy ABIs. A pool only implements one of them;
# calling the wrong selector reverts (the function does not exist at that
# selector). We use this to classify the pool variant so the M9 quoter sends
# the matching selector instead of producing generic QUOTE_REVERT.
GET_DY_SELECTOR_INT128 = "5e0d443f"   # get_dy(int128,int128,uint256)   -> stable/plain
GET_DY_SELECTOR_UINT256 = "556d6e9f"  # get_dy(uint256,uint256,uint256) -> crypto/tricrypto
# Nominal probe amount used only to detect which get_dy ABI the pool exposes.
# ABI-shape detection is independent of dx magnitude (wrong selector reverts
# regardless of arguments), so a fixed small nominal value is sufficient.
_VARIANT_PROBE_DX = 10 ** 6


def _classify_curve_variant(int128_ok: bool, uint256_ok: bool) -> tuple[str | None, str]:
    """Decide Curve pool variant from get_dy ABI-shape probe results.

    Pure helper (no IO) so the decision logic is unit-testable.

    Returns ``(pool_kind, probe_status)`` where ``pool_kind`` is
    ``"stable"`` | ``"crypto"`` | ``None`` (unquoteable / both reverted).
    The int128 (stable) ABI wins ties: a genuine stable pool may answer dust
    on both shapes via proxies, but stable is the safe default selector.
    """
    if int128_ok:
        return "stable", "QUOTE_OK_INT128"
    if uint256_ok:
        return "crypto", "QUOTE_OK_UINT256"
    return None, "QUOTE_REVERT_BOTH"



def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_known_tokens(anchor_path: Path, metadata_path: Path) -> dict[str, str]:
    """Token address -> symbol from config only (no hardcoded addresses in this script)."""
    known: dict[str, str] = {}
    if anchor_path.exists():
        anchor = yaml.safe_load(anchor_path.read_text(encoding="utf-8")) or {}
        for sym, spec in (anchor.get("tokens") or {}).items():
            addr = (spec or {}).get("address")
            if isinstance(addr, str) and addr.startswith("0x"):
                known[addr.lower()] = str(sym)
    if metadata_path.exists():
        meta = yaml.safe_load(metadata_path.read_text(encoding="utf-8")) or {}
        for addr, sym in (
            (meta.get("curve") or {}).get("base", {}).get("anchor_tokens") or {}
        ).items():
            if isinstance(addr, str) and isinstance(sym, str):
                known[addr.lower()] = sym
    return known


def eth_call(to: str, data: str) -> tuple[str | None, str | None]:
    """Return (result_hex, rpc_error_message)."""
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": to, "data": data}, "latest"],
    }
    resp = httpx.post(RPC_URL, json=payload, timeout=10)
    resp.raise_for_status()
    body = resp.json()
    if "error" in body:
        err = body["error"]
        msg = err.get("message") if isinstance(err, dict) else str(err)
        return None, msg or "rpc_error"
    result = body.get("result", "0x")
    if not result or result == "0x" or len(result) < 66:
        return None, "empty_result"
    return result, None


def get_coin(pool: str, index: int, use_uint: bool = True) -> str | None:
    selector = COINS_SELECTOR_UINT if use_uint else COINS_SELECTOR_INT128
    idx_bytes = index.to_bytes(32, "big").hex()
    result, _err = eth_call(pool, f"0x{selector}{idx_bytes}")
    if result is None:
        return None
    raw = result[2:] if result.startswith("0x") else result
    addr = "0x" + raw[-40:].lower()
    if addr == "0x" + "0" * 40:
        return None
    return addr


def discover_pool(pool_address: str) -> dict[str, int] | None:
    coins: dict[str, int] = {}
    for i in range(8):
        addr = get_coin(pool_address, i, use_uint=True)
        if addr is None:
            addr = get_coin(pool_address, i, use_uint=False)
        if addr is None:
            break
        coins[addr.lower()] = i
    return coins if coins else None


def _probe_get_dy(
    pool: str,
    selector: str,
    idx_in: int,
    idx_out: int,
) -> tuple[bool, str | None]:
    """Return (ok, rpc_error) for a single get_dy probe call."""
    calldata = (
        "0x"
        + selector
        + idx_in.to_bytes(32, "big").hex()
        + idx_out.to_bytes(32, "big").hex()
        + _VARIANT_PROBE_DX.to_bytes(32, "big").hex()
    )
    result, err = eth_call(pool, calldata)
    return result is not None, err


def probe_curve_variant(
    pool: str,
    idx_in: int,
    idx_out: int,
) -> tuple[str | None, str, dict]:
    """Classify get_dy ABI for one (idx_in -> idx_out) direction.

    Returns ``(pool_kind, probe_status, debug)`` where debug holds selector
    attempts and RPC errors for diagnostics.
    """
    debug: dict = {
        "pool": pool,
        "idx_in": idx_in,
        "idx_out": idx_out,
        "dx": _VARIANT_PROBE_DX,
        "attempts": [],
    }
    int128_ok, int128_err = _probe_get_dy(pool, GET_DY_SELECTOR_INT128, idx_in, idx_out)
    debug["attempts"].append(
        {
            "selector": GET_DY_SELECTOR_INT128,
            "ok": int128_ok,
            "rpc_error": int128_err,
        }
    )
    uint256_ok = False
    uint256_err: str | None = None
    if not int128_ok:
        uint256_ok, uint256_err = _probe_get_dy(pool, GET_DY_SELECTOR_UINT256, idx_in, idx_out)
        debug["attempts"].append(
            {
                "selector": GET_DY_SELECTOR_UINT256,
                "ok": uint256_ok,
                "rpc_error": uint256_err,
            }
        )
    pool_kind, status = _classify_curve_variant(int128_ok, uint256_ok)
    debug["probe_status"] = status
    return pool_kind, status, debug


def _inventory_route_pairs(
    active_routes: list[dict],
) -> dict[str, list[tuple[str, str]]]:
    """pool_address -> directed (token_in, token_out) pairs from bridge routes."""
    pairs: dict[str, set[tuple[str, str]]] = {}
    for route in active_routes:
        if route.get("adapter_type") != "curve_stable":
            continue
        pool = str(route.get("pool_address", "")).lower()
        t0, t1 = route.get("token0"), route.get("token1")
        if not pool or not t0 or not t1:
            continue
        pairs.setdefault(pool, set()).add((str(t0), str(t1)))
        pairs.setdefault(pool, set()).add((str(t1), str(t0)))
    return {pool: sorted(ps) for pool, ps in pairs.items()}


def _iter_symbol_probe_pairs(
    coin_indices: dict[str, int],
    route_pairs: list[tuple[str, str]],
) -> list[tuple[str, str]]:
    """Prefer bridge route pairs; fall back to all symbol pairs if none."""
    seen: set[tuple[str, str]] = set()
    ordered: list[tuple[str, str]] = []
    for sym_in, sym_out in route_pairs:
        if sym_in not in coin_indices or sym_out not in coin_indices:
            continue
        if coin_indices[sym_in] == coin_indices[sym_out]:
            continue
        key = (sym_in, sym_out)
        if key not in seen:
            seen.add(key)
            ordered.append(key)
    if ordered:
        return ordered
    syms = list(coin_indices.keys())
    for i, s0 in enumerate(syms):
        for s1 in syms[i + 1 :]:
            for pair in ((s0, s1), (s1, s0)):
                if coin_indices[pair[0]] == coin_indices[pair[1]]:
                    continue
                if pair not in seen:
                    seen.add(pair)
                    ordered.append(pair)
    return ordered


def probe_curve_variant_best(
    pool: str,
    coin_indices: dict[str, int],
    route_pairs: list[tuple[str, str]],
) -> tuple[str | None, str, dict]:
    """Try bridge-relevant symbol directions until one get_dy ABI probe succeeds."""
    probes: list[dict] = []
    for sym_in, sym_out in _iter_symbol_probe_pairs(coin_indices, route_pairs):
        idx_in = coin_indices[sym_in]
        idx_out = coin_indices[sym_out]
        pool_kind, status, detail = probe_curve_variant(pool, idx_in, idx_out)
        probes.append(
            {
                "token_in": sym_in,
                "token_out": sym_out,
                "idx_in": idx_in,
                "idx_out": idx_out,
                **detail,
            }
        )
        if pool_kind is not None:
            return pool_kind, status, {
                "winning_pair": [sym_in, sym_out],
                "idx_in": idx_in,
                "idx_out": idx_out,
                "probes": probes,
            }
    return None, "QUOTE_REVERT_BOTH", {"probes": probes}


def _pool_entry(
    coins: dict[str, int],
    known_tokens: dict[str, str],
    *,
    partial: bool = False,
    pool_kind: str = "stable",
    probe_status: str = "NOT_PROBED",
) -> dict:
    coin_indices: dict[str, int] = {}
    for addr, idx in sorted(coins.items(), key=lambda x: x[1]):
        sym = known_tokens.get(addr)
        if not sym:
            if partial:
                continue
            raise ValueError(f"unknown token {addr} at index {idx}")
        coin_indices[sym] = idx
    if len(coin_indices) < 2:
        raise ValueError("need at least two known coin indices")
    return {
        "pool_kind": pool_kind,
        "curve_variant": pool_kind,
        "probe_status": probe_status,
        "coin_indices": coin_indices,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover Curve coin indices for bridge pools")
    parser.add_argument("--inventory", type=Path, default=DEFAULT_INVENTORY)
    parser.add_argument("--metadata", type=Path, default=DEFAULT_METADATA)
    parser.add_argument("--anchor", type=Path, default=DEFAULT_ANCHOR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--partial",
        action="store_true",
        help="Skip unknown coins in multi-coin pools (anchor symbols only)",
    )
    parser.add_argument(
        "--strict-probe",
        action="store_true",
        help="Exit non-zero when any pool fails probe (default: write artifact, warn only)",
    )
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Include per-pool probe attempt details in the artifact",
    )
    args = parser.parse_args()

    if not args.inventory.exists():
        print(f"ERROR: inventory not found: {args.inventory}", file=sys.stderr)
        sys.exit(1)

    known_tokens = _load_known_tokens(args.anchor, args.metadata)
    if len(known_tokens) < 2:
        print("ERROR: no token symbols loaded from config", file=sys.stderr)
        sys.exit(1)

    inv = json.loads(args.inventory.read_text(encoding="utf-8"))
    active = inv.get("active_routes", [])
    route_pairs_by_pool = _inventory_route_pairs(active)
    curve_pools = sorted(route_pairs_by_pool.keys())

    print(f"Discovering coin indices for {len(curve_pools)} curve_stable pools")
    print(f"RPC: {RPC_URL}\n")

    pools_out: dict[str, dict] = {}
    failed: list[str] = []
    failed_detail: dict[str, dict] = {}

    for pool_addr in curve_pools:
        print(f"  {pool_addr} ...", end=" ", flush=True)
        coins = discover_pool(pool_addr)
        if not coins:
            print("FAILED (no coins)")
            failed.append(pool_addr)
            failed_detail[pool_addr] = {"reason": "no_coins"}
            continue
        try:
            entry = _pool_entry(coins, known_tokens, partial=args.partial)
        except ValueError as exc:
            print(f"FAILED ({exc})")
            failed.append(pool_addr)
            failed_detail[pool_addr] = {"reason": str(exc)}
            continue
        pool_kind, probe_status, probe_debug = probe_curve_variant_best(
            pool_addr,
            entry["coin_indices"],
            route_pairs_by_pool.get(pool_addr, []),
        )
        if pool_kind is None:
            print(f"SKIP ({probe_status})")
            failed.append(pool_addr)
            if args.debug:
                failed_detail[pool_addr] = {
                    "reason": probe_status,
                    "coin_indices": entry["coin_indices"],
                    "probe": probe_debug,
                }
            continue
        entry["pool_kind"] = pool_kind
        entry["curve_variant"] = pool_kind
        entry["probe_status"] = probe_status
        if args.debug:
            entry["probe_debug"] = probe_debug
        win = probe_debug.get("winning_pair", [])
        print(f"OK  {pool_kind} {win} {entry['coin_indices']}")
        pools_out[pool_addr] = entry

    by_status: dict[str, int] = {}
    for entry in pools_out.values():
        st = str(entry.get("probe_status", "UNKNOWN"))
        by_status[st] = by_status.get(st, 0) + 1

    artifact = {
        "schema_version": SCHEMA_VERSION,
        "chain": "base",
        "generated_at_utc": _iso_now(),
        "source_inventory": str(args.inventory.relative_to(REPO_ROOT)).replace("\\", "/"),
        "pools_discovered": len(pools_out),
        "pools_failed": len(failed),
        "probe_status_histogram": by_status,
        "pools": pools_out,
    }
    if args.debug and failed_detail:
        artifact["pools_failed_detail"] = failed_detail
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(artifact, indent=2), encoding="utf-8")
    print(f"\nWrote {len(pools_out)} pools -> {args.output}")
    print(f"probe_status_histogram: {by_status}")

    if failed:
        print(f"FAILED ({len(failed)}): {failed[:10]}{'...' if len(failed) > 10 else ''}", file=sys.stderr)
        if args.strict_probe:
            sys.exit(1)


if __name__ == "__main__":
    main()
