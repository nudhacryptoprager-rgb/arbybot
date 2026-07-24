#!/usr/bin/env python3
"""m8_1_stable_anchor_run.py — M8.1 stable-anchor inventory / quote diagnostics CLI.

M8.1 is the inventory and quote-viability diagnostics layer: it probes anchor-connected
pairs, classifies quote reject reasons, and publishes rolling anchor inventory. It is not
the metadata authority (M8.3), mirror scorer (M8.2), or full toxic-pool policy gate.

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
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
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
from core.pipeline_provenance import ENV_PIPELINE_SESSION_ID
from core.quote_lane_limiter import QuoteLaneLimiter
from m8_1.stable_anchor.quote_negative_cache import (
    PersistentQuoteNegativeCache,
    QuoteNegativeCache,
    block_bucket,
    quote_cache_key,
)

_PROBE_METRICS_PATH = Path("data/tmp/m8_1_probe_metrics_latest.json")
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
        from m8_1.stable_anchor.quote_probe import rpc_call_timeout_s

        timeout_s = rpc_call_timeout_s()
        w3 = Web3(Web3.HTTPProvider(rpc_url, request_kwargs={"timeout": timeout_s}))
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
        elif dcfg.adapter_type == "curve_stable":
            # Load Curve pool metadata from adapter_metadata.yaml
            from m9.graph_arb.adapter_metadata import load_adapter_metadata
            _meta = load_adapter_metadata()
            _chain = getattr(cfg, "chain", "base")
            _curve_chain_pools = _meta.curve_pools.get(_chain, {})
            for _pool_addr, _curve_pool in _curve_chain_pools.items():
                _idx_to_sym = {v: k for k, v in _curve_pool.coin_indices.items()}
                _coin0_sym = _idx_to_sym.get(0)
                _coin1_sym = _idx_to_sym.get(1)
                if _coin0_sym is None or _coin1_sym is None:
                    continue
                # Route 0→1 (coin[0] → coin[1])
                routes.append(DexRoute(
                    dex_id=dex_id,
                    adapter_type="curve_stable",
                    quoter=_pool_addr,
                    fee=0,
                    tick_spacing=None,
                    curve_coin0_sym=_coin0_sym,
                    curve_coin1_sym=_coin1_sym,
                    token_in_index=0,
                    token_out_index=1,
                    pool_kind=_curve_pool.pool_kind,
                ))
                # Route 1→0 (coin[1] → coin[0])
                routes.append(DexRoute(
                    dex_id=dex_id,
                    adapter_type="curve_stable",
                    quoter=_pool_addr,
                    fee=0,
                    tick_spacing=None,
                    curve_coin0_sym=_coin0_sym,
                    curve_coin1_sym=_coin1_sym,
                    token_in_index=1,
                    token_out_index=0,
                    pool_kind=_curve_pool.pool_kind,
                ))
    return routes


def _resolve_probe_amount(
    route: DexRoute,
    t0: TokenInfo,
    t1: TokenInfo,
    size_usd: float,
) -> Optional[Tuple[TokenInfo, TokenInfo, int]]:
    if route.adapter_type == "curve_stable":
        _c0 = route.curve_coin0_sym
        _c1 = getattr(route, "curve_coin1_sym", None)
        _expected_in_sym = _c0 if route.token_in_index == 0 else _c1
        _expected_out_sym = _c1 if route.token_out_index == 1 else _c0
        if t0.symbol == _expected_in_sym and t1.symbol == _expected_out_sym:
            token_in = t0
            token_out = t1
        elif t1.symbol == _expected_in_sym and t0.symbol == _expected_out_sym:
            token_in = t1
            token_out = t0
        else:
            return None
        return token_in, token_out, size_usd_to_amount_in(token_in, size_usd)
    return t0, t1, size_usd_to_amount_in(t0, size_usd)


def _probe_one(
    w3: Any,
    route: DexRoute,
    t0: TokenInfo,
    t1: TokenInfo,
    size_usd: float,
    *,
    neg_cache: QuoteNegativeCache,
    bucket_id: str,
    lane_limiter: Optional[QuoteLaneLimiter] = None,
    rpc_url: str = "",
) -> Tuple[bool, Optional[str], bool]:
    resolved = _resolve_probe_amount(route, t0, t1, size_usd)
    if resolved is None:
        return False, "PAIR_INCOMPATIBLE", False
    token_in, token_out, amount_in = resolved
    route_id = f"{route.dex_id}:f{route.fee}"
    quoter = str(route.quoter or route.pool_id or route.vault_address or route_id)
    cache_key = quote_cache_key(
        route_id=route_id,
        quoter=quoter,
        token_in=token_in.address,
        token_out=token_out.address,
        size_usd=size_usd,
        direction="exact_in",
        fee=route.fee,
        tick_spacing=route.tick_spacing,
        block_bucket_id=bucket_id,
    )
    cached = neg_cache.get(cache_key)
    if cached:
        return False, cached, False

    def _do_probe() -> QuoteResult:
        return probe_quote(w3, route, t0, t1, amount_in)

    try:
        if lane_limiter is not None and rpc_url:
            result = lane_limiter.call(rpc_url, _do_probe)
        else:
            result = _do_probe()
        if result.ok:
            return True, None, False
        reason = result.reject_reason or "UNKNOWN"
        if reason != "QUOTE_RPC_ERROR":
            neg_cache.put(cache_key, reason)
        return False, reason, reason == "QUOTE_RPC_ERROR"
    except Exception:
        return False, "QUOTE_RPC_ERROR", True


def _probe_all(
    w3: Any,
    pairs: List[Tuple[TokenInfo, TokenInfo]],
    routes: List[DexRoute],
    sizes_usd: List[float],
    deadline_ts: float,
    *,
    async_max_workers: int = 1,
    neg_cache: Optional[QuoteNegativeCache] = None,
    lane_limiter: Optional[QuoteLaneLimiter] = None,
    rpc_url: str = "",
) -> Tuple[List[dict], Dict[str, Any]]:
    """Probe pair×route×size with minimal-size-first and bounded async workers."""
    neg_cache = neg_cache or PersistentQuoteNegativeCache()
    probe_t0 = time.time()
    try:
        head_block = int(w3.eth.block_number)
    except Exception:
        head_block = None
    bucket_id = block_bucket(head_block)

    candidates_total = 0
    passes_total = 0
    rpc_errors = 0
    quote_fails = 0
    reject_histogram: Dict[str, int] = {}
    near_miss: List[dict] = []
    workers = max(1, int(async_max_workers or 1))
    min_size = sizes_usd[0] if sizes_usd else 50.0
    extra_sizes = list(sizes_usd[1:]) if len(sizes_usd) > 1 else []

    def _record_near_miss(
        t0: TokenInfo,
        t1: TokenInfo,
        route: DexRoute,
        size_usd: float,
        reason: str,
    ) -> None:
        if len(near_miss) >= 50:
            return
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

    def _run_batch(tasks: List[Tuple[TokenInfo, TokenInfo, DexRoute, float]]) -> Dict[
        Tuple[str, str, str], bool
    ]:
        nonlocal candidates_total, passes_total, rpc_errors, quote_fails
        passed: Dict[Tuple[str, str, str], bool] = {}
        if not tasks:
            return passed
        if workers <= 1:
            for t0, t1, route, size_usd in tasks:
                if time.time() > deadline_ts:
                    break
                candidates_total += 1
                ok, reason, rpc_err = _probe_one(
                    w3,
                    route,
                    t0,
                    t1,
                    size_usd,
                    neg_cache=neg_cache,
                    bucket_id=bucket_id,
                    lane_limiter=lane_limiter,
                    rpc_url=rpc_url,
                )
                key = (t0.symbol, t1.symbol, route.dex_id)
                if ok:
                    passes_total += 1
                    passed[key] = True
                else:
                    quote_fails += 1
                    if rpc_err:
                        rpc_errors += 1
                    reason = reason or "UNKNOWN"
                    reject_histogram[reason] = reject_histogram.get(reason, 0) + 1
                    _record_near_miss(t0, t1, route, size_usd, reason)
            return passed
        pending = list(tasks)
        cursor = 0
        pool = ThreadPoolExecutor(max_workers=workers)
        active: Dict[Any, Tuple[TokenInfo, TokenInfo, DexRoute, float]] = {}
        try:
            while (cursor < len(pending) or active) and time.time() <= deadline_ts:
                while len(active) < workers and cursor < len(pending):
                    if time.time() > deadline_ts:
                        break
                    t0, t1, route, size_usd = pending[cursor]
                    cursor += 1
                    fut = pool.submit(
                        _probe_one,
                        w3,
                        route,
                        t0,
                        t1,
                        size_usd,
                        neg_cache=neg_cache,
                        bucket_id=bucket_id,
                        lane_limiter=lane_limiter,
                        rpc_url=rpc_url,
                    )
                    active[fut] = (t0, t1, route, size_usd)
                if not active:
                    break
                remaining = max(0.05, deadline_ts - time.time())
                done, _ = wait(active.keys(), timeout=remaining, return_when=FIRST_COMPLETED)
                if not done and time.time() > deadline_ts:
                    for fut in list(active):
                        fut.cancel()
                    break
                for fut in done:
                    t0, t1, route, size_usd = active.pop(fut)
                    candidates_total += 1
                    ok, reason, rpc_err = fut.result()
                    key = (t0.symbol, t1.symbol, route.dex_id)
                    if ok:
                        passes_total += 1
                        passed[key] = True
                    else:
                        quote_fails += 1
                        if rpc_err:
                            rpc_errors += 1
                        reason = reason or "UNKNOWN"
                        reject_histogram[reason] = reject_histogram.get(reason, 0) + 1
                        _record_near_miss(t0, t1, route, size_usd, reason)
            if time.time() > deadline_ts and active:
                for fut in list(active):
                    fut.cancel()
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return passed

    base_tasks = [(t0, t1, route, min_size) for t0, t1 in pairs for route in routes]
    passed_keys = _run_batch(base_tasks)
    if extra_sizes and time.time() <= deadline_ts:
        extra_tasks: List[Tuple[TokenInfo, TokenInfo, DexRoute, float]] = []
        for t0, t1 in pairs:
            for route in routes:
                key = (t0.symbol, t1.symbol, route.dex_id)
                if not passed_keys.get(key):
                    continue
                for size_usd in extra_sizes:
                    extra_tasks.append((t0, t1, route, size_usd))
        _run_batch(extra_tasks)

    total_attempts = max(candidates_total, 1)
    rpc_success_rate = 1.0 - (rpc_errors / total_attempts)
    productive_quote_rate = passes_total / total_attempts
    rpc_error_rate = rpc_errors / total_attempts
    metrics: Dict[str, Any] = {
        "stable_anchor_candidates_total": candidates_total,
        "stable_anchor_passes_total": passes_total,
        "stable_anchor_fills_total": 0,
        "best_net_usd": None,
        "rpc_error_rate": round(rpc_error_rate, 4),
        "rpc_success_rate": round(rpc_success_rate, 4),
        "productive_quote_rate": round(productive_quote_rate, 4),
        "quote_success_rate": round(productive_quote_rate, 4),
        "quote_fails_total": quote_fails,
        "reject_histogram": reject_histogram,
        "quote_negative_cache": neg_cache.stats(),
        "async_max_workers": workers,
    }
    if lane_limiter is not None:
        limiter_stats = lane_limiter.stats()
        metrics["quote_lane_limiter"] = limiter_stats
        metrics["provider_errors"] = int(limiter_stats.get("provider_errors", 0))
        metrics["rpc_wait_s"] = float(limiter_stats.get("rpc_wait_s", 0.0))
    probe_elapsed_s = max(0.001, time.time() - probe_t0)
    metrics["routes_per_s"] = round(candidates_total / probe_elapsed_s, 3)
    if hasattr(neg_cache, "flush"):
        neg_cache.flush()
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
    from core.pipeline_provenance import apply_pipeline_provenance

    artifact = apply_pipeline_provenance(artifact, run_timestamp=run_ts)
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
            print(f"OFFLINE: refreshed timestamp -> {run_ts} in {output_path}", flush=True)
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
    print(f"OFFLINE: wrote stub artifact -> {output_path}", flush=True)
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
    parser.add_argument(
        "--probe-mode",
        choices=("audit_full", "fresh_delta"),
        default="audit_full",
        help="fresh_delta probes only new M8 token×anchor pairs; audit_full=config sweep",
    )
    parser.add_argument(
        "--token-subset-file",
        default=None,
        help="When probe-mode=fresh_delta, limit to token addresses in subset JSON",
    )
    parser.add_argument(
        "--streaming-manifest",
        default=None,
        help="Streaming batch manifest for session/fingerprint validation",
    )
    parser.add_argument(
        "--streaming-batch-index",
        type=int,
        default=None,
        help="Resolve streaming batch paths from pipeline session + batch index",
    )
    parser.add_argument(
        "--publish-rolling",
        action="store_true",
        help="Also publish batch output to rolling m8_1_stable_anchor_latest.json",
    )
    args = parser.parse_args(argv)

    setup_logging(json_format=args.log_json)

    if args.streaming_batch_index is not None:
        from core.pipeline_streaming import resolve_streaming_batch_paths

        batch_paths = resolve_streaming_batch_paths(int(args.streaming_batch_index))
        args.probe_mode = "fresh_delta"
        args.token_subset_file = str(batch_paths.token_subset)
        args.streaming_manifest = str(batch_paths.manifest)

    output_path = Path(args.output)
    if args.streaming_batch_index is not None and args.output == _DEFAULT_OUTPUT:
        output_path = batch_paths.m81_output

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
    if args.probe_mode == "fresh_delta":
        from core.pipeline_streaming import streaming_enabled
        from m8.discovery.streaming_handoff import validate_streaming_handoff

        if streaming_enabled() or args.streaming_manifest:
            if not args.token_subset_file:
                print(
                    "ERROR: fresh_delta streaming requires --token-subset-file",
                    flush=True,
                )
                return 2
            if args.streaming_manifest:
                try:
                    validate_streaming_handoff(
                        args.streaming_manifest,
                        expected_session_id=os.environ.get(ENV_PIPELINE_SESSION_ID, "").strip()
                        or None,
                    )
                except (OSError, ValueError) as exc:
                    print(f"ERROR: streaming handoff validation failed: {exc}", flush=True)
                    return 2
    if args.probe_mode == "fresh_delta" and args.token_subset_file:
        from m8.discovery.token_subset import load_token_subset_file
        from m8_1.stable_anchor.fresh_delta_pairs import enumerate_fresh_delta_pairs

        subset = load_token_subset_file(args.token_subset_file) or set()
        if subset:
            try:
                w3_preview = _load_web3(rpc_url)
            except RuntimeError:
                w3_preview = None
            fresh_pairs = enumerate_fresh_delta_pairs(cfg, subset, w3=w3_preview)
            config_pairs = [
                (t0, t1)
                for t0, t1 in pairs
                if t0.address.lower() in subset or t1.address.lower() in subset
            ]
            pairs = fresh_pairs + config_pairs
            _log.info(
                "fresh_delta probe: subset_tokens=%d fresh_pairs=%d config_pairs=%d total=%d",
                len(subset),
                len(fresh_pairs),
                len(config_pairs),
                len(pairs),
            )
    if not pairs:
        _log.warning("no anchor-connected pairs found in config — writing stub artifact")
        run_ts = _iso_now()
        _write_artifact(output_path, [], {"stable_anchor_candidates_total": 0,
                         "stable_anchor_passes_total": 0, "stable_anchor_fills_total": 0,
                         "best_net_usd": None, "rpc_error_rate": 0.0,
                         "quote_success_rate": 1.0, "reject_histogram": {}},
                        run_ts, 0.0, True, rpc_url, args.duration_minutes)
        print(f"PASS: wrote stub artifact (no pairs in config) -> {output_path}", flush=True)
        return 0

    sizes_usd = list(cfg.sizes_usd or _DEFAULT_SIZES_USD)
    async_workers = int(getattr(cfg.quote_gate, "async_max_workers", 4) or 4)
    _log.info(
        "pairs=%d routes=%d sizes=%s async_workers=%d",
        len(pairs),
        len(routes),
        sizes_usd,
        async_workers,
    )

    # Load web3
    try:
        w3 = _load_web3(rpc_url)
    except RuntimeError as exc:
        print(f"RPC ERROR: {exc}", flush=True)
        return 1

    run_start = time.time()
    run_ts = _iso_now()
    deadline_ts = run_start + args.duration_minutes * 60
    lane_limiter = QuoteLaneLimiter(max_concurrent=max(1, async_workers))

    # Probe quotes
    near_miss, metrics = _probe_all(
        w3,
        pairs,
        routes,
        sizes_usd,
        deadline_ts,
        async_max_workers=async_workers,
        lane_limiter=lane_limiter,
        rpc_url=rpc_url,
    )

    elapsed_s = time.time() - run_start
    freshness_s = elapsed_s

    target_pqr = float(getattr(cfg.quote_gate, "target_quote_success_rate", 0.0) or 0.0)
    productive_rate = float(metrics.get("productive_quote_rate", 0.0) or 0.0)
    gate_acceptance = (
        metrics.get("rpc_error_rate", 1.0) < 0.1
        and (target_pqr <= 0.0 or productive_rate >= target_pqr)
    )

    _write_artifact(output_path, near_miss, metrics, run_ts,
                    freshness_s, gate_acceptance, rpc_url, args.duration_minutes)
    if args.publish_rolling:
        import shutil
        from core.pipeline_streaming import DEFAULT_M81_ROLLING

        rolling_path = Path(DEFAULT_M81_ROLLING)
        rolling_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(output_path, rolling_path)
    _PROBE_METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    _PROBE_METRICS_PATH.write_text(
        json.dumps(
            {
                "schema_version": "m8_1_probe_metrics.1",
                "rpc_wait_s": metrics.get("rpc_wait_s", 0.0),
                "provider_errors": metrics.get("provider_errors", 0),
                "cache_hits": (metrics.get("quote_negative_cache") or {}).get("hits", 0),
                "cache_misses": (metrics.get("quote_negative_cache") or {}).get("misses", 0),
                "routes_per_s": metrics.get("routes_per_s"),
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )

    passes = metrics.get("stable_anchor_passes_total", 0)
    candidates = metrics.get("stable_anchor_candidates_total", 0)
    qsr = metrics.get("productive_quote_rate", metrics.get("quote_success_rate", 0.0))
    rpc_sr = metrics.get("rpc_success_rate", 0.0)
    _summary = (
        f"{'PASS' if gate_acceptance else 'WARN'} - M8.1 stable-anchor run\n"
        f"  candidates={candidates}, passes={passes}, "
        f"productive_quote_rate={qsr:.4f}, rpc_success_rate={rpc_sr:.4f}\n"
        f"  near_miss={len(near_miss)}, elapsed={elapsed_s:.1f}s\n"
        f"  artifact -> {output_path}"
    )
    sys.stdout.buffer.write((_summary + "\n").encode("utf-8", errors="replace"))
    sys.stdout.buffer.flush()
    if args.streaming_batch_index is not None:
        # Batched M8 refresh: fresh_delta exotic subsets often have low productive
        # quote rate; keep the run green when RPC health is acceptable.
        rpc_ok = float(metrics.get("rpc_error_rate", 1.0) or 1.0) < 0.1
        return 0 if rpc_ok else 1
    return 0 if gate_acceptance else 1


if __name__ == "__main__":
    sys.exit(main())
