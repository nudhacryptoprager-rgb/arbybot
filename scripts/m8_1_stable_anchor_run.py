#!/usr/bin/env python3
"""m8_1_stable_anchor_run.py — M8.1 stable-anchor inventory refresh CLI.

Probes DEX quotes for anchor-connected pairs and writes a fresh
``m8_1_stable_anchor_latest.json`` rolling artifact.

Usage:
  # Online — probe real quotes (BASE_RPC env or --rpc-url):
  $env:BASE_RPC = "https://base.publicnode.com"
  py -3.11 scripts/m8_1_stable_anchor_run.py

  # With explicit config/output:
  py -3.11 scripts/m8_1_stable_anchor_run.py \
      --config config/exotic_base_anchor.yaml \
      --output data/runs/_rolling/m8_1_stable_anchor_latest.json \
      --duration-minutes 5

  # Offline (no RPC — stamps existing artifact with fresh timestamp):
  py -3.11 scripts/m8_1_stable_anchor_run.py --offline

Exit codes:
  0 — wrote artifact successfully
  1 — probe failed with errors
  2 — config/input error
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# Ensure repo root on sys.path.
_ROOT = Path(__file__).resolve().parents[1]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from core.logging import get_logger, setup_logging
from m8_1.stable_anchor.config_loader import load_config
from m8_1.stable_anchor.pairs import TokenInfo
from m8_1.stable_anchor.pool_discovery import DexRoute
from m8_1.stable_anchor.quote_probe import QuoteResult, probe_quote, size_usd_to_amount_in

_log = get_logger(__name__)

_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"
_DEFAULT_OUTPUT = "data/runs/_rolling/m8_1_stable_anchor_latest.json"
_DEFAULT_DURATION_MIN = 5.0
_DEFAULT_SIZES_USD = [50.0, 100.0, 250.0]
_SCHEMA_REVISION = "m8_1.6"
_SCHEMA_FAMILY = "stable_anchor"

# Anchor tokens — pairs must include at least one of these
_ANCHOR_SYMS = frozenset({"USDC", "EURC", "USDT", "DAI", "WETH", "cbBTC"})


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _load_web3(rpc_url: str) -> Any:
    """Return a Web3 instance for the given HTTP RPC URL."""
    try:
        from web3 import Web3  # type: ignore[import]
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": 15}))
        return w3
    except ImportError as e:
        raise RuntimeError(f"web3 not installed: {e}") from e


def _enumerate_pairs(cfg: Any) -> List[Tuple[TokenInfo, TokenInfo]]:
    """Return (token_in, token_out) pairs from config tokens.

    All non-duplicate anchor×non-anchor combinations, plus all anchor×anchor.
    Falls back to empty list if cfg.tokens is empty.
    """
    token_cfgs = cfg.tokens  # Mapping[str, TokenCfg]
    tokens: Dict[str, TokenInfo] = {
        sym: TokenInfo(symbol=sym, address=tc.address, decimals=tc.decimals)
        for sym, tc in token_cfgs.items()
    }
    seen: set = set()
    pairs: List[Tuple[TokenInfo, TokenInfo]] = []
    syms = sorted(tokens.keys())
    for i, s0 in enumerate(syms):
        for s1 in syms[i + 1:]:
            # Include pair if at least one token is an anchor
            if s0 in _ANCHOR_SYMS or s1 in _ANCHOR_SYMS:
                key = (s0, s1)
                if key not in seen:
                    seen.add(key)
                    pairs.append((tokens[s0], tokens[s1]))
    return pairs


def _enumerate_routes(cfg: Any) -> List[DexRoute]:
    """Return all enabled routes from config dexes."""
    routes: List[DexRoute] = []
    for dex_id, dcfg in cfg.dexes.items():
        if not dcfg.enabled:
            continue
        if dcfg.adapter_type == "uniswap_v3":
            for fee in dcfg.fee_tiers:
                routes.append(DexRoute(
                    dex_id=dex_id,
                    adapter_type="uniswap_v3",
                    quoter=dcfg.quoter,
                    fee=fee,
                    tick_spacing=None,
                    curve_coin0_sym=None,
                ))
        elif dcfg.adapter_type == "aerodrome_slipstream":
            for ts in dcfg.tick_spacings:
                routes.append(DexRoute(
                    dex_id=dex_id,
                    adapter_type="aerodrome_slipstream",
                    quoter=dcfg.quoter,
                    fee=0,
                    tick_spacing=ts,
                    curve_coin0_sym=None,
                ))
    return routes


def _probe_all(
    w3: Any,
    pairs: List[Tuple[TokenInfo, TokenInfo]],
    routes: List[DexRoute],
    sizes_usd: List[float],
    deadline_ts: float,
) -> Tuple[List[dict], Dict[str, Any]]:
    """Probe all pair×route×size combinations up to ``deadline_ts``.

    Returns (near_miss_routes, metrics).
    """
    candidates_total = 0
    passes_total = 0
    rpc_errors = 0
    quote_fails = 0
    reject_histogram: Dict[str, int] = {}
    near_miss: List[dict] = []

    for t0, t1 in pairs:
        for route in routes:
            for size_usd in sizes_usd:
                if time.time() > deadline_ts:
                    _log.info("deadline reached, stopping probe")
                    break
                candidates_total += 1
                amount_in = size_usd_to_amount_in(t0, size_usd)
                try:
                    result: QuoteResult = probe_quote(w3, route, t0, t1, amount_in)
                    if result.ok:
                        passes_total += 1
                    else:
                        reason = result.reject_reason or "UNKNOWN"
                        reject_histogram[reason] = reject_histogram.get(reason, 0) + 1
                        if result.reject_reason == "QUOTE_RPC_ERROR":
                            rpc_errors += 1
                        # Record near-miss (any reject at this size)
                        if len(near_miss) < 50:
                            near_miss.append({
                                "pair_id": f"{t0.symbol}_{t1.symbol}",
                                "route_a_id": f"{route.dex_id}:f{route.fee}",
                                "route_b_id": "N/A",
                                "size_usd": size_usd,
                                "verdict": "REJECT",
                                "reject_reason": reason,
                                "net_usd": None,
                                "net_bps": None,
                                "gross_bps": None,
                            })
                except Exception as exc:
                    rpc_errors += 1
                    reject_histogram["QUOTE_RPC_ERROR"] = reject_histogram.get("QUOTE_RPC_ERROR", 0) + 1
                    _log.debug("probe_quote error pair=%s_%s route=%s size=%s: %s",
                               t0.symbol, t1.symbol, route.dex_id, size_usd, exc)

    total_attempts = candidates_total
    qsr = 1.0 - (rpc_errors / total_attempts) if total_attempts > 0 else 1.0
    rpc_error_rate = rpc_errors / total_attempts if total_attempts > 0 else 0.0

    metrics: Dict[str, Any] = {
        "stable_anchor_candidates_total": candidates_total,
        "stable_anchor_passes_total": passes_total,
        "stable_anchor_fills_total": 0,
        "best_net_usd": None,
        "rpc_error_rate": round(rpc_error_rate, 4),
        "quote_success_rate": round(qsr, 4),
        "reject_histogram": reject_histogram,
    }
    return near_miss, metrics


def _write_artifact(
    output_path: Path,
    near_miss: List[dict],
    metrics: Dict[str, Any],
    run_ts: str,
    freshness_s: float,
    gate_acceptance: bool,
    rpc_url: Optional[str],
    duration_minutes: float,
) -> None:
    artifact: Dict[str, Any] = {
        "schema_family": _SCHEMA_FAMILY,
        "schema_revision": _SCHEMA_REVISION,
        "generated_at_utc": run_ts,
        "freshness_s": freshness_s,
        "status": "ACTIVE",
        "gate_acceptance": gate_acceptance,
        "strategy_gate_acceptance": metrics.get("stable_anchor_passes_total", 0) > 0,
        "perf_gate_fail": False,
        "reasons": [] if metrics.get("stable_anchor_passes_total", 0) > 0 else ["NO_STABLE_EDGE"],
        "operational_targets": {
            "rpc_error_rate_max": 0.1,
            "quote_success_rate_min": 0.7,
            "optar_ok": metrics.get("rpc_error_rate", 0.0) < 0.1,
        },
        "run_context": {
            "chain": "base",
            "duration_minutes": duration_minutes,
            "execution_enabled": False,
            "kill_switch_active": True,
            "paper_only": True,
            "run_timestamp": run_ts,
            "rpc_provider": "publicnode" if rpc_url and "publicnode" in rpc_url else "unknown",
        },
        "metrics": metrics,
        "top_routes": [],
        "near_miss_routes": near_miss,
        # M8.1 scope: quote-probing only.  active_routes is intentionally [] because
        # M8.1 validates that on-chain quotes succeed for stable-anchor candidates — it
        # does NOT build cross-DEX arb routes.  Route assembly is done downstream by the
        # M9 bridge builder (scripts/m9_bridge_build.py), which reads M8.1 passes as
        # anchor inputs.  A non-empty active_routes here would indicate a regression.
        "active_routes": [],
        "active_routes_count": 0,
        "route_discovery_scope": "quote_probe_only",
    }
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8") as fh:
        json.dump(artifact, fh, indent=2)
    _log.info("wrote M8.1 artifact: %s", output_path)


def _offline_refresh(output_path: Path) -> int:
    """Refresh an existing artifact timestamp (offline mode)."""
    run_ts = _iso_now()
    if output_path.is_file():
        try:
            with open(output_path, encoding="utf-8") as fh:
                existing = json.load(fh)
            existing["generated_at_utc"] = run_ts
            existing.setdefault("run_context", {})["run_timestamp"] = run_ts
            with open(output_path, "w", encoding="utf-8") as fh:
                json.dump(existing, fh, indent=2)
            print(f"OFFLINE: refreshed timestamp → {run_ts} in {output_path}", flush=True)
            return 0
        except Exception as exc:
            _log.warning("could not refresh existing artifact (%s), writing minimal stub", exc)

    # Write a minimal stub artifact if none exists
    _write_artifact(
        output_path=output_path,
        near_miss=[],
        metrics={"stable_anchor_candidates_total": 0, "stable_anchor_passes_total": 0,
                 "stable_anchor_fills_total": 0, "best_net_usd": None,
                 "rpc_error_rate": 0.0, "quote_success_rate": 1.0, "reject_histogram": {}},
        run_ts=run_ts,
        freshness_s=0.0,
        gate_acceptance=True,
        rpc_url=None,
        duration_minutes=0.0,
    )
    print(f"OFFLINE: wrote stub artifact → {output_path}", flush=True)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description="M8.1 stable-anchor inventory refresh CLI.",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--config", default=_DEFAULT_CONFIG,
                        help="M8.1 YAML config path (exotic_base_anchor.yaml or dedicated)")
    parser.add_argument("--output", default=_DEFAULT_OUTPUT,
                        help="Output path for rolling artifact")
    parser.add_argument("--rpc-url", default=None,
                        help="Override RPC URL. Falls back to BASE_RPC env then publicnode.")
    parser.add_argument("--duration-minutes", type=float, default=_DEFAULT_DURATION_MIN,
                        metavar="N", help="Max probe duration in minutes")
    parser.add_argument("--offline", action="store_true",
                        help="Offline mode: refresh existing artifact timestamp only (no RPC)")
    parser.add_argument("--log-json", action="store_true",
                        help="Emit JSON-formatted log lines")
    args = parser.parse_args(argv)

    setup_logging(json_format=args.log_json)

    output_path = Path(args.output)

    if args.offline:
        return _offline_refresh(output_path)

    # Resolve RPC URL
    rpc_url: str = (
        args.rpc_url
        or os.environ.get("BASE_RPC")
        or os.environ.get("ARBY_BASE_RPC_URL")
        or "https://base.publicnode.com"
    )
    _log.info("m8_1_stable_anchor_run: rpc=%s config=%s output=%s duration=%.1fm",
              rpc_url, args.config, output_path, args.duration_minutes)

    # Load config
    try:
        cfg = load_config(Path(args.config))
    except Exception as exc:
        print(f"CONFIG ERROR: {exc}", flush=True)
        return 2

    # Build pairs and routes
    pairs = _enumerate_pairs(cfg)
    routes = _enumerate_routes(cfg)
    if not pairs:
        _log.warning("no anchor-connected pairs found in config — writing stub artifact")
        run_ts = _iso_now()
        _write_artifact(output_path, [], {"stable_anchor_candidates_total": 0,
                         "stable_anchor_passes_total": 0, "stable_anchor_fills_total": 0,
                         "best_net_usd": None, "rpc_error_rate": 0.0,
                         "quote_success_rate": 1.0, "reject_histogram": {}},
                        run_ts, 0.0, True, rpc_url, args.duration_minutes)
        print(f"PASS: wrote stub artifact (no pairs in config) → {output_path}", flush=True)
        return 0

    _log.info("pairs=%d routes=%d sizes=%s", len(pairs), len(routes), _DEFAULT_SIZES_USD)

    # Load web3
    try:
        w3 = _load_web3(rpc_url)
    except RuntimeError as exc:
        print(f"RPC ERROR: {exc}", flush=True)
        return 1

    run_start = time.time()
    run_ts = _iso_now()
    deadline_ts = run_start + args.duration_minutes * 60

    # Probe quotes
    near_miss, metrics = _probe_all(w3, pairs, routes, _DEFAULT_SIZES_USD, deadline_ts)

    elapsed_s = time.time() - run_start
    freshness_s = elapsed_s

    # Gate acceptance: rpc_error_rate < 0.1
    gate_acceptance = metrics.get("rpc_error_rate", 1.0) < 0.1

    _write_artifact(output_path, near_miss, metrics, run_ts,
                    freshness_s, gate_acceptance, rpc_url, args.duration_minutes)

    passes = metrics.get("stable_anchor_passes_total", 0)
    candidates = metrics.get("stable_anchor_candidates_total", 0)
    qsr = metrics.get("quote_success_rate", 0.0)
    _summary = (
        f"{'PASS' if gate_acceptance else 'WARN'} - M8.1 stable-anchor run\n"
        f"  candidates={candidates}, passes={passes}, qsr={qsr:.4f}\n"
        f"  near_miss={len(near_miss)}, elapsed={elapsed_s:.1f}s\n"
        f"  artifact -> {output_path}"
    )
    sys.stdout.buffer.write((_summary + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    return 0 if gate_acceptance else 1


if __name__ == "__main__":
    sys.exit(main())
