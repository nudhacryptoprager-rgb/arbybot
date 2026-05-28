"""Pool depth probe \u2014 measures effective on-chain depth for inventory routes (Step 1).

Writes ``effective_depth_usd`` and ``price_impact_at_100usd`` fields into each
active_route entry in the inventory. These fields enable the M9 productive lane
filter (``--productive-lane --min-effective-depth-usd <N>``) in the runner.

Algorithm per pool:
  1. Fetch slot0 (sqrtPriceX96) via Multicall snapshot \u2192 compute spot price.
  2. Call QuoterV2.quoteExactInputSingle at $100 USD equivalent amount.
  3. Compare actual output vs expected spot output.
  4. price_impact_at_100usd = 1 - (actual_out / expected_out)
  5. effective_depth_usd = $100 if impact < IMPACT_THRESHOLD else lower estimate.

Usage::

    py -3.11 -m m9.graph_arb.pool_depth_probe \\
        --chain base \\
        --inventory data/tmp/m9_verified_inventory.json \\
        --output data/tmp/m9_depth_enriched_inventory.json

    # Optionally write results to quarantine for thin pools:
    py -3.11 -m m9.graph_arb.pool_depth_probe \\
        --chain base \\
        --inventory data/tmp/m9_verified_inventory.json \\
        --update-quarantine data/quarantine/m9_pool_depth_quarantine.json \\
        --impact-threshold 0.50
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

log = logging.getLogger(__name__)

# Token USD prices (order-of-magnitude, same as runner.py)
_TOKEN_PRICE_USD: Dict[str, float] = {
    "WETH": 3500.0,
    "WETH_BASE": 3500.0,
    "cbBTC": 110000.0,
    "cbETH": 3700.0,
    "wstETH": 4200.0,
    "USDC": 1.0,
    "EURC": 1.10,
    "DAI": 1.0,
    "USDT": 1.0,
    "AERO": 0.70,
    "VIRTUAL": 0.80,
    "TOSHI": 0.0001,
    "BRETT": 0.08,
    "DEGEN": 0.005,
    "WELL": 0.04,
    "SNX": 2.5,
    "LINK": 15.0,
    "UNI": 8.0,
}

# Default probe size in USD
_PROBE_SIZE_USD = 100.0
# Impact threshold above which a pool is considered TOXIC
_IMPACT_THRESHOLD_TOXIC = 0.50
# Impact threshold above which a pool is LOW_EFFECTIVE_DEPTH
_IMPACT_THRESHOLD_LOW = 0.10

# V3 QuoterV2 selector: quoteExactInputSingle((address,address,uint256,uint24,uint160))
_V3_SELECTOR = bytes.fromhex("c6a5026a")
# Slipstream Quoter selector: quoteExactInputSingle((address,address,uint256,int24,uint160))
_SLIP_SELECTOR = bytes.fromhex("9e7defe6")
# ve33 pool selector: getAmountOut(uint256 amountIn, address tokenIn) -> uint256
_VE33_GET_AMOUNT_OUT_SELECTOR = bytes.fromhex("f140a35a")
# UniswapV2 pool selector: getReserves() -> (uint112 reserve0, uint112 reserve1, uint32 blockTimestampLast)
_V2_GET_RESERVES_SELECTOR = bytes.fromhex("0902f1ac")
# Adapter type sets for routing
_VE33_ADAPTER_TYPES = frozenset({
    "ve33",
    "ve33_stable",
    "ve33_volatile",
    "solidly_stable",
    "solidly_volatile",
    "aerodrome_stable",
    "aerodrome_v2_stable",
})
_V2_FORK_ADAPTER_TYPES = frozenset({"uniswap_v2", "sushiswap_v2", "baseswap_v2"})
_DEFAULT_V2_FEE_BPS = 30
# Per-adapter-type default fee map for V2 forks.
# Used when neither `fee` nor `fee_bps` field is present in the route metadata.
# Keeps probe math independent of field presence without a hard 30 bps fallback for all.
_V2_FORK_FEE_BPS_MAP: Dict[str, int] = {
    "uniswap_v2": 30,
    "sushiswap_v2": 30,
    "baseswap_v2": 30,
}
_FEE_DENOMINATOR_BPS = 10_000


def _encode_ve33_amount_out(amount_in: int, token_in: str) -> str:
    """Encode getAmountOut(uint256 amountIn, address tokenIn) calldata for ve33 pools."""
    amount_bytes = amount_in.to_bytes(32, "big")
    token_bytes = int(token_in, 16).to_bytes(32, "big")
    return "0x" + _VE33_GET_AMOUNT_OUT_SELECTOR.hex() + amount_bytes.hex() + token_bytes.hex()


def _v2_amount_out_from_reserves(
    pool_address: str,
    addr_in: str,
    addr_out: str,
    amount_in: int,
    rpc_url: str,
    fee_bps: int = _DEFAULT_V2_FEE_BPS,
) -> Optional[int]:
    """Compute V2-fork amountOut from getReserves() via xy=k formula."""
    if fee_bps < 0 or fee_bps >= _FEE_DENOMINATOR_BPS:
        return None
    calldata = "0x" + _V2_GET_RESERVES_SELECTOR.hex()
    hex_result = _raw_eth_call(rpc_url, pool_address, calldata)
    if not hex_result or hex_result == "0x":
        return None
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 192:  # 3 x 32 bytes
        return None
    r0 = int(raw[:64], 16)
    r1 = int(raw[64:128], 16)
    if r0 == 0 or r1 == 0:
        return None
    # UniV2 sorts tokens: token0 is lower address
    if int(addr_in, 16) < int(addr_out, 16):
        reserve_in, reserve_out = r0, r1
    else:
        reserve_in, reserve_out = r1, r0
    fee_multiplier = _FEE_DENOMINATOR_BPS - int(fee_bps)
    numerator = amount_in * fee_multiplier * reserve_out
    denominator = reserve_in * _FEE_DENOMINATOR_BPS + amount_in * fee_multiplier
    if denominator == 0:
        return None
    return numerator // denominator


def _route_v2_fee_bps(route: Dict[str, Any]) -> int:
    """Resolve V2-fork fee bps from route metadata.

    Priority: route['fee'] > route['fee_bps'] > per-adapter map > global default.
    """
    fee = int(route.get("fee") or 0)
    if fee > 0:
        return fee
    fee_bps = route.get("fee_bps")
    if fee_bps is not None:
        return int(float(fee_bps))
    adapter_type = route.get("adapter_type", "")
    return _V2_FORK_FEE_BPS_MAP.get(adapter_type, _DEFAULT_V2_FEE_BPS)


def _encode_v3_call(token_in: str, token_out: str, amount_in: int, fee: int) -> str:
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    fee_bytes = fee.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + amount_bytes + fee_bytes + sqrt_limit
    return "0x" + _V3_SELECTOR.hex() + payload.hex()


def _encode_slipstream_call(
    token_in: str, token_out: str, amount_in: int, tick_spacing: int
) -> str:
    addr_in = int(token_in, 16).to_bytes(32, "big")
    addr_out = int(token_out, 16).to_bytes(32, "big")
    amount_bytes = amount_in.to_bytes(32, "big")
    ts_bytes = tick_spacing.to_bytes(32, "big")
    sqrt_limit = (0).to_bytes(32, "big")
    payload = addr_in + addr_out + amount_bytes + ts_bytes + sqrt_limit
    return "0x" + _SLIP_SELECTOR.hex() + payload.hex()


def _decode_quote_response(hex_result: str) -> int:
    raw = hex_result[2:] if hex_result.startswith("0x") else hex_result
    if len(raw) < 64:
        raise ValueError(f"response too short: {len(raw) // 2} bytes")
    return int(raw[:64], 16)


def _raw_eth_call(rpc_url: str, to: str, data: str) -> Optional[str]:
    """Send raw eth_call via httpx (no web3 dependency)."""
    try:
        import httpx
    except ImportError:
        import urllib.request
        import urllib.error

        payload = json.dumps(
            {
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": to, "data": data}, "latest"],
                "id": 1,
            }
        ).encode()
        req = urllib.request.Request(
            rpc_url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                body = json.loads(resp.read())
                return body.get("result")
        except Exception as exc:
            log.debug("urllib eth_call failed: %s", exc)
            return None

    try:
        body = httpx.post(
            rpc_url,
            json={
                "jsonrpc": "2.0",
                "method": "eth_call",
                "params": [{"to": to, "data": data}, "latest"],
                "id": 1,
            },
            timeout=10,
        ).json()
        return body.get("result")
    except Exception as exc:
        log.debug("httpx eth_call failed: %s", exc)
        return None


def probe_pool_depth(
    route: Dict[str, Any],
    config_tokens: Dict[str, Any],
    rpc_url: str,
    probe_size_usd: float = _PROBE_SIZE_USD,
    spot_price_ratio: Optional[float] = None,
) -> Dict[str, Any]:
    """Measure effective depth for a single inventory route.

    Returns a dict with:
    - effective_depth_usd: USD amount tradeable at < IMPACT_THRESHOLD_LOW impact
    - price_impact_at_100usd: fraction 0-1 (0 = no impact, 1 = total loss)
    - probe_ok: True if quote succeeded
    - probe_error: error string if failed
    - probe_amount_in: raw amount_in used
    - probe_amount_out: raw amount_out received
    - depth_reject_reason: null | LOW_EFFECTIVE_DEPTH | TOXIC_PRICE_IMPACT
    """
    pair_id = route.get("pair_id", "")
    dex_id = route.get("dex_id", "")
    fee = int(route.get("fee") or 0)
    adapter_type = route.get("adapter_type", "uniswap_v3")
    tick_spacing = route.get("tick_spacing")
    quoter = route.get("quoter_addr", "") or ""
    pool_address = route.get("pool_address", "")

    result: Dict[str, Any] = {
        "effective_depth_usd": None,
        "price_impact_at_100usd": None,
        "probe_ok": False,
        "probe_error": None,
        "probe_amount_in": None,
        "probe_amount_out": None,
        "depth_reject_reason": None,
    }

    # For ve33 and v2 forks, the pool itself is the quoter; fall back to pool_address
    if adapter_type in _VE33_ADAPTER_TYPES or adapter_type in _V2_FORK_ADAPTER_TYPES:
        if not quoter or quoter == "0x" + "0" * 40:
            quoter = pool_address

    if not quoter or quoter == "0x" + "0" * 40:
        result["probe_error"] = "NO_QUOTER"
        return result

    # Parse pair symbols
    parts = pair_id.split("_")
    if len(parts) != 2:
        result["probe_error"] = f"BAD_PAIR_ID:{pair_id}"
        return result
    sym0, sym1 = parts[0], parts[1]

    t0 = config_tokens.get(sym0)
    t1 = config_tokens.get(sym1)
    if not t0 or not t1:
        result["probe_error"] = f"UNKNOWN_TOKEN:{sym0}|{sym1}"
        return result

    dec0 = t0.get("decimals", 18)
    dec1 = t1.get("decimals", 18)
    addr0 = t0.get("address", "")
    addr1 = t1.get("address", "")

    price0 = _TOKEN_PRICE_USD.get(sym0, 1.0)
    amount_in = int(probe_size_usd / price0 * (10 ** dec0))

    if amount_in <= 0:
        result["probe_error"] = "ZERO_AMOUNT_IN"
        return result

    result["probe_amount_in"] = amount_in

    # Encode calldata or compute amount_out directly (for v2 forks via getReserves)
    amount_out_precomputed: Optional[int] = None
    calldata: Optional[str] = None
    try:
        if adapter_type in _VE33_ADAPTER_TYPES:
            calldata = _encode_ve33_amount_out(amount_in, addr0)
        elif adapter_type in _V2_FORK_ADAPTER_TYPES:
            pool_addr_for_probe = pool_address or quoter
            amount_out_precomputed = _v2_amount_out_from_reserves(
                pool_addr_for_probe,
                addr0,
                addr1,
                amount_in,
                rpc_url,
                fee_bps=_route_v2_fee_bps(route),
            )
            if amount_out_precomputed is None:
                result["probe_error"] = "V2_RESERVES_FAILED"
                return result
            if amount_out_precomputed == 0:
                result["probe_error"] = "ZERO_AMOUNT_OUT"
                return result
        elif adapter_type == "aerodrome_slipstream" and tick_spacing:
            calldata = _encode_slipstream_call(addr0, addr1, amount_in, int(tick_spacing))
        else:
            calldata = _encode_v3_call(addr0, addr1, amount_in, fee)
    except Exception as exc:
        result["probe_error"] = f"ENCODE_ERROR:{exc}"
        return result

    if amount_out_precomputed is not None:
        # v2 forks: reserves-based computation, no RPC quoter call needed
        amount_out = amount_out_precomputed
    else:
        # Call quoter (v3, slipstream, ve33)
        if not calldata:
            result["probe_error"] = "NO_CALLDATA"
            return result
        hex_result = _raw_eth_call(rpc_url, quoter, calldata)
        if not hex_result or hex_result == "0x":
            result["probe_error"] = "QUOTE_FAILED_OR_REVERT"
            return result
        try:
            amount_out = _decode_quote_response(hex_result)
        except Exception as exc:
            result["probe_error"] = f"DECODE_ERROR:{exc}"
            return result
        if amount_out == 0:
            result["probe_error"] = "ZERO_AMOUNT_OUT"
            return result

    result["probe_amount_out"] = amount_out
    result["probe_ok"] = True

    # Compute impact: compare actual output to expected from spot
    # Expected output: (probe_size_usd / price0) tokens_in * price0/price1 = probe_size_usd / price1
    price1 = _TOKEN_PRICE_USD.get(sym1, 1.0)
    expected_out_units = probe_size_usd / price1
    expected_out_raw = expected_out_units * (10 ** dec1)
    if expected_out_raw > 0:
        actual_ratio = amount_out / expected_out_raw
        impact = 1.0 - actual_ratio
        result["price_impact_at_100usd"] = round(impact, 6)

        if impact <= _IMPACT_THRESHOLD_LOW:
            result["effective_depth_usd"] = probe_size_usd
        else:
            # Estimate: at what size does impact drop to threshold?
            # For thin V3 pools: impact grows roughly linearly with amount
            # effective_depth_usd ≈ probe_size_usd * THRESHOLD / impact
            est_depth = probe_size_usd * _IMPACT_THRESHOLD_LOW / max(impact, 1e-9)
            result["effective_depth_usd"] = round(est_depth, 2)

        if impact >= _IMPACT_THRESHOLD_TOXIC:
            result["depth_reject_reason"] = "TOXIC_PRICE_IMPACT"
        elif impact > _IMPACT_THRESHOLD_LOW:
            result["depth_reject_reason"] = "LOW_EFFECTIVE_DEPTH"
    else:
        result["probe_error"] = "ZERO_EXPECTED_OUT"

    return result


# Default quarantine TTL: 7 days.  Entries older than this are considered expired
# and pool_depth_filter will skip them (transient quarantine policy).
_QUARANTINE_TTL_SECONDS = 7 * 24 * 3600  # 604800


def _update_quarantine(
    quarantine_path: Path,
    results_by_pool: Dict[str, Dict[str, Any]],
    active_routes: List[Dict[str, Any]],
    impact_threshold: float,
    rpc_url: str,
) -> None:
    """Append newly confirmed toxic/thin pools to the quarantine JSON.

    Skips pools already present in the file (matched on pool_address lowercase).
    Only adds entries where depth_reject_reason is TOXIC_PRICE_IMPACT or
    LOW_EFFECTIVE_DEPTH and probe_ok=True.
    """
    import datetime

    # Load existing quarantine
    if quarantine_path.exists():
        with quarantine_path.open("r", encoding="utf-8") as fh:
            quarantine = json.load(fh)
    else:
        quarantine = {
            "schema_version": "m9_pool_depth_quarantine.1",
            "generated_at_utc": datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ"),
            "description": (
                "Evidence-based pool quarantine: specific pool/fee-tier routes excluded "
                "from M9 productive graph due to on-chain confirmed insufficient depth."
            ),
            "quarantined_pools": [],
        }

    existing_addrs: set[str] = {
        (e.get("pool_address") or "").lower()
        for e in quarantine.get("quarantined_pools", [])
    }

    today = datetime.date.today().isoformat()
    rpc_label = "publicnode.com" if "publicnode" in rpc_url else rpc_url.split("/")[2] if "//" in rpc_url else rpc_url
    new_count = 0

    for pool_addr, probe in results_by_pool.items():
        reject = probe.get("depth_reject_reason")
        if reject not in ("TOXIC_PRICE_IMPACT", "LOW_EFFECTIVE_DEPTH"):
            continue
        if not probe.get("probe_ok"):
            continue
        if pool_addr in existing_addrs:
            continue

        # Find matching route for pair/dex/fee metadata
        route = next(
            (r for r in active_routes if (r.get("pool_address") or "").lower() == pool_addr),
            {},
        )
        impact = probe.get("price_impact_at_100usd") or 0
        depth_usd = probe.get("effective_depth_usd") or 0

        # Compute retry_after_utc (quarantine expires after TTL, pool is re-probed)
        retry_dt = datetime.datetime.utcnow() + datetime.timedelta(seconds=_QUARANTINE_TTL_SECONDS)
        retry_after_utc = retry_dt.strftime("%Y-%m-%dT%H:%M:%SZ")

        entry: Dict[str, Any] = {
            "pool_address": pool_addr,
            "pair_id": route.get("pair_id", "UNKNOWN"),
            "dex_id": route.get("dex_id", "unknown"),
            "fee": int(route.get("fee", 0)),
            "reject_reason": reject,
            "quarantine_ttl_seconds": _QUARANTINE_TTL_SECONDS,
            "quarantined_at_utc": today,
            "retry_after_utc": retry_after_utc,
            "activation_path": (
                "Re-probe via pool_depth_probe --update-quarantine after retry_after_utc. "
                "If probe passes (impact < LOW_EFFECTIVE_DEPTH threshold), remove entry to re-activate."
            ),
            "evidence": {
                "price_impact_at_100usd": round(impact, 4),
                "effective_depth_usd": round(depth_usd, 2),
                "probe_size_usd": 100.0,
                "impact_threshold_used": impact_threshold,
                "measured_at": today,
                "rpc": rpc_label,
            },
            "note": (
                f"Auto-added by pool_depth_probe on {today}. "
                f"price_impact={impact * 100:.1f}%, effective_depth_usd={depth_usd:.2f}. "
                f"Expires (retry_after): {retry_after_utc}."
            ),
        }
        quarantine["quarantined_pools"].append(entry)
        existing_addrs.add(pool_addr)
        new_count += 1
        log.info(
            "Quarantine: added %s pair=%s reason=%s impact=%.1f%% retry_after=%s",
            pool_addr[:14],
            entry["pair_id"],
            reject,
            impact * 100,
            retry_after_utc,
        )

    if new_count > 0:
        quarantine["generated_at_utc"] = datetime.datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
        with quarantine_path.open("w", encoding="utf-8") as fh:
            json.dump(quarantine, fh, indent=2, ensure_ascii=False)
        log.info("Quarantine updated: %d new entries → %s", new_count, quarantine_path)
    else:
        log.info("Quarantine: no new entries to add (all probed pools already listed or clean)")


def main(argv: Optional[List[str]] = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    parser = argparse.ArgumentParser(
        description="Measure on-chain effective depth for M9 inventory routes."
    )
    parser.add_argument(
        "--chain",
        default="base",
        help="Chain identifier (used to resolve RPC URL)",
    )
    parser.add_argument(
        "--inventory",
        default="data/tmp/m9_verified_inventory.json",
        help="Path to M9 verified inventory JSON",
    )
    parser.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8_1 config YAML (for token addresses/decimals)",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output path for enriched inventory (default: overwrites --inventory)",
    )
    parser.add_argument(
        "--probe-size-usd",
        type=float,
        default=100.0,
        help="Quote size in USD for depth probe (default: 100)",
    )
    parser.add_argument(
        "--impact-threshold",
        type=float,
        default=0.50,
        help="Price impact threshold for TOXIC_PRICE_IMPACT classification (default: 0.50)",
    )
    parser.add_argument(
        "--update-quarantine",
        default=None,
        help="Quarantine JSON to update with newly confirmed toxic pools",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print results without writing files",
    )
    args = parser.parse_args(argv)

    # Resolve RPC URL
    rpc_url: Optional[str] = os.environ.get(
        "BASE_RPC", "https://mainnet.base.org"
    )
    try:
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
        chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, _, _ = resolve_rpc_http(chain_id=chain_id, network=args.chain, env=dict(os.environ))
    except Exception as exc:
        log.warning("Could not resolve RPC via core.rpc_urls: %s — using BASE_RPC env", exc)

    if not rpc_url:
        log.error("No RPC URL available. Set BASE_RPC env var.")
        return 1

    # Load inventory
    inv_path = Path(args.inventory)
    if not inv_path.exists():
        log.error("Inventory not found: %s", inv_path)
        return 1

    with inv_path.open("r", encoding="utf-8") as fh:
        inventory = json.load(fh)

    # Load config for token addresses and dex quoter addresses
    config_tokens: Dict[str, Any] = {}
    dex_quoters: Dict[str, str] = {}
    try:
        import yaml
        with open(args.config, encoding="utf-8") as fh:
            cfg_raw = yaml.safe_load(fh) or {}
        config_tokens = cfg_raw.get("tokens", {})
        # Build dex_id -> quoter_addr map from config dexes block
        for dex_id, dex_cfg in (cfg_raw.get("dexes") or {}).items():
            q = dex_cfg.get("quoter_v2") or dex_cfg.get("quoter")
            if q:
                dex_quoters[dex_id] = q
    except Exception as exc:
        log.warning("Could not load config %s: %s — using token price table only", args.config, exc)

    active_routes = inventory.get("active_routes", [])
    # Inject quoter_addr into routes that don't have it (from dex config fallback)
    injected = 0
    for route in active_routes:
        if not route.get("quoter_addr"):
            dex_id = route.get("dex_id", "")
            q = dex_quoters.get(dex_id)
            if q:
                route["quoter_addr"] = q
                injected += 1
    if injected:
        log.info("Injected quoter_addr for %d routes from dex config", injected)
    log.info("Probing %d active routes at $%.0f...", len(active_routes), args.probe_size_usd)

    results_by_pool: Dict[str, Dict[str, Any]] = {}
    ok_count = 0
    fail_count = 0
    toxic_count = 0
    low_depth_count = 0

    for route in active_routes:
        pool_addr = route.get("pool_address", "")
        if not pool_addr or pool_addr == "0x" + "0" * 40:
            continue

        probe = probe_pool_depth(
            route=route,
            config_tokens=config_tokens,
            rpc_url=rpc_url,
            probe_size_usd=args.probe_size_usd,
        )

        # Enrich route entry in-place
        route["effective_depth_usd"] = probe["effective_depth_usd"]
        route["price_impact_at_100usd"] = probe["price_impact_at_100usd"]
        route["depth_reject_reason"] = probe["depth_reject_reason"]
        route["depth_probe_ok"] = probe["probe_ok"]

        results_by_pool[pool_addr.lower()] = probe

        if probe["probe_ok"]:
            ok_count += 1
            impact = probe.get("price_impact_at_100usd") or 0
            reject = probe.get("depth_reject_reason")
            if reject == "TOXIC_PRICE_IMPACT":
                toxic_count += 1
                log.warning(
                    "TOXIC_PRICE_IMPACT: pool=%s pair=%s impact=%.1f%%",
                    pool_addr[:10],
                    route.get("pair_id"),
                    impact * 100,
                )
            elif reject == "LOW_EFFECTIVE_DEPTH":
                low_depth_count += 1
                log.info(
                    "LOW_EFFECTIVE_DEPTH: pool=%s pair=%s impact=%.1f%% depth_usd=%.2f",
                    pool_addr[:10],
                    route.get("pair_id"),
                    impact * 100,
                    probe.get("effective_depth_usd") or 0,
                )
        else:
            fail_count += 1
            log.debug("Probe failed: pool=%s error=%s", pool_addr[:10], probe.get("probe_error"))

        time.sleep(0.1)  # conservative rate limit for free-tier RPC

    log.info(
        "Probe complete: ok=%d fail=%d toxic=%d low_depth=%d",
        ok_count, fail_count, toxic_count, low_depth_count,
    )

    if not args.dry_run:
        output_path = Path(args.output or args.inventory)
        with output_path.open("w", encoding="utf-8") as fh:
            json.dump(inventory, fh, indent=2)
        log.info("Enriched inventory written to %s", output_path)

    # Update quarantine file with newly confirmed toxic/thin pools
    if args.update_quarantine and not args.dry_run:
        _update_quarantine(
            quarantine_path=Path(args.update_quarantine),
            results_by_pool=results_by_pool,
            active_routes=active_routes,
            impact_threshold=args.impact_threshold,
            rpc_url=rpc_url or "",
        )

    # Print summary table
    print("\n=== Pool Depth Probe Results ===")
    print(f"{'pool_address':<44} {'pair_id':<20} {'impact%':>8} {'depth_usd':>10} {'reason':<25}")
    print("-" * 115)
    for pool_addr, probe in sorted(results_by_pool.items(), key=lambda x: -(x[1].get("price_impact_at_100usd") or 0)):
        if not probe["probe_ok"]:
            continue
        route_entry = next(
            (r for r in active_routes if (r.get("pool_address") or "").lower() == pool_addr),
            {},
        )
        impact = probe.get("price_impact_at_100usd") or 0
        depth = probe.get("effective_depth_usd") or 0
        reason = probe.get("depth_reject_reason") or "OK"
        pair = route_entry.get("pair_id", "?")
        print(f"{pool_addr:<44} {pair:<20} {impact * 100:>7.1f}% {depth:>10.2f} {reason:<25}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
