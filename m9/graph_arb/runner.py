"""M9 graph-arb runner — CLI entry point for the shadow scanner."""
from __future__ import annotations

import argparse
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

# Process lock file
_LOCK_FILE = "data/tmp/m9_runner.lock"

# Approximate USD prices for Base-chain tokens used to compute quote sizes.
# These are order-of-magnitude values — update periodically.
# Without these, 18-decimal tokens get amount_in = 1000 * 10^18 → pool reverts.
_TOKEN_PRICE_USD_BASE: dict = {
    "WETH": 3500.0,
    "WETH_BASE": 3500.0,
    "cbBTC": 110000.0,
    "LBTC": 110000.0,
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
    "YFI": 8000.0,
    "LINK": 15.0,
    "UNI": 8.0,
}

# Exit codes
EXIT_OK = 0
EXIT_CONFIG_ERROR = 1
EXIT_NO_CYCLES = 2
EXIT_ALL_QUOTES_FAILED = 3


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _setup_logging(verbose: bool = False) -> None:
    import logging
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _get_provider_throttle_snapshot() -> "dict | None":
    """Return current provider_throttle snapshot, or None if unavailable."""
    try:
        from core.provider_throttle import provider_throttle
        return provider_throttle.snapshot()
    except Exception:
        return None


def _connect_rpc(chain: str) -> "object | None":
    """Attempt to connect to the chain RPC. Returns Web3 instance or None."""
    try:
        from core.rpc_urls import get_rpc_url  # type: ignore[import]
        from web3 import Web3  # type: ignore[import]

        url = get_rpc_url(chain)
        w3 = Web3(Web3.HTTPProvider(url))
        if w3.is_connected():
            return w3
        return None
    except Exception:
        return None


_REVERT_QUARANTINE_PATH = "data/tmp/m9_revert_quarantine.json"
# Route is flagged as revert-dominant when QUOTE_REVERT makes up this fraction of its leg errors
_REVERT_DOMINANT_THRESHOLD = 0.8


def _write_revert_quarantine(
    cycle_results: list,
    log: "logging.Logger",
    output_path: str = _REVERT_QUARANTINE_PATH,
) -> None:
    """Write QUOTE_REVERT-dominant routes to a quarantine feedback file.

    Routes where ≥80% of their leg failures are QUOTE_REVERT are structurally broken
    (pool does not exist at the given fee tier).  Writing them here allows the next
    inventory refresh to quarantine them before they waste quote budget.
    """
    import json as _json
    from datetime import datetime as _dt, timezone as _tz
    from pathlib import Path as _Path
    from collections import defaultdict as _dd

    # Accumulate per-route leg error counts
    route_errors: "_dd[str, dict]" = _dd(lambda: {"QUOTE_REVERT": 0, "OTHER": 0, "pair_id": ""})
    for qr in cycle_results:
        edges = qr.cycle.edges
        for i, leg in enumerate(qr.leg_results or []):
            if i >= len(edges):
                continue
            if not leg.ok and leg.reject_reason:
                entry = route_errors[leg.route_id]
                entry["pair_id"] = edges[i].pair_id
                if leg.reject_reason == "QUOTE_REVERT":
                    entry["QUOTE_REVERT"] += 1
                else:
                    entry["OTHER"] += 1

    quarantine = []
    for route_id, counts in route_errors.items():
        revert = counts["QUOTE_REVERT"]
        total = revert + counts["OTHER"]
        if total == 0:
            continue
        revert_rate = revert / total
        if revert_rate >= _REVERT_DOMINANT_THRESHOLD:
            quarantine.append(
                {
                    "route_id": route_id,
                    "pair_id": counts["pair_id"],
                    "revert_count": revert,
                    "total_leg_errors": total,
                    "revert_rate": round(revert_rate, 4),
                    "quarantine_reason": "QUOTE_REVERT_DOMINANT",
                }
            )

    if not quarantine:
        return

    quarantine.sort(key=lambda x: -x["revert_rate"])
    out = {
        "schema_version": "m9_revert_quarantine.1",
        "generated_at_utc": _dt.now(tz=_tz.utc).isoformat(),
        "route_count": len(quarantine),
        "threshold": _REVERT_DOMINANT_THRESHOLD,
        "routes": quarantine,
    }
    path = _Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = str(path) + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        _json.dump(out, fh, indent=2)
    try:
        import os as _os
        _os.replace(tmp, str(path))
    except PermissionError:
        import time as _t
        _t.sleep(0.5)
        import os as _os
        _os.replace(tmp, str(path))
    log.info(
        "QUOTE_REVERT quarantine written: %d routes → %s",
        len(quarantine), output_path,
    )


def main(argv: "list[str] | None" = None) -> int:
    # Load .env FIRST — must happen before any os.environ reads, including
    # get_rpc_url() / resolve_rpc_http().  Without this, BASE_RPC from .env
    # is invisible and the runner silently falls back to mainnet.base.org.
    from core.env import load_root_dotenv
    load_root_dotenv()

    parser = argparse.ArgumentParser(
        description="M9 graph-arb shadow scanner",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument("--chain", default="base", help="Chain identifier")
    parser.add_argument(
        "--config",
        default="config/exotic_base_anchor.yaml",
        help="M8_1 config YAML path",
    )
    parser.add_argument(
        "--inventory",
        default=None,
        help=(
            "Inventory artifact JSON path. "
            "If omitted, uses shadow inventory with gap edges if available, "
            "else m8_1 exotic inventory fallback."
        ),
    )
    parser.add_argument(
        "--duration-minutes",
        type=float,
        default=1.0,
        help="Wall-clock scan duration in minutes (hard deadline)",
    )
    parser.add_argument(
        "--cycles-limit",
        type=int,
        default=5000,
        help="Maximum cycles to find per topology sweep",
    )
    parser.add_argument(
        "--max-cycles-per-sweep",
        type=int,
        default=200,
        help="Maximum cycles to quote per sweep iteration (deadline loop)",
    )
    parser.add_argument(
        "--quote-timeout-s",
        type=float,
        default=10.0,
        help="Per-cycle quote timeout in seconds",
    )
    parser.add_argument(
        "--sizes-usd",
        nargs="+",
        type=float,
        default=[100.0, 250.0, 500.0],
        help="Quote sizes in USD (free-tier safe defaults; overridden by scan_params.sizes_usd in config YAML)",
    )
    parser.add_argument(
        "--dynamic-sizes",
        action="store_true",
        help=(
            "Quote each cycle across the supplied --sizes-usd ladder and select "
            "the best gross_bps size. Off by default to protect RPC budget."
        ),
    )
    parser.add_argument(
        "--dynamic-size-max-cycles",
        type=int,
        default=3,
        help=(
            "Maximum prioritized cycles per sweep to quote across the full "
            "--sizes-usd ladder when --dynamic-sizes is enabled. "
            "Default 3 — conservative for free-tier RPC. Overridden by scan_params in config YAML."
        ),
    )
    parser.add_argument(
        "--artifact-path",
        default="data/runs/_rolling/m9_graph_latest.json",
        help="Rolling artifact output path",
    )
    parser.add_argument("--verbose", action="store_true")
    parser.add_argument("--dry-run", action="store_true", help="Build graph only, skip quoting")
    parser.add_argument(
        "--quote-workers",
        type=int,
        default=4,
        help=(
            "Number of parallel quote worker threads. "
            "Reduce to 1-2 when using dRPC free tier to avoid HTTP 429."
        ),
    )
    parser.add_argument(
        "--quote-backend",
        default="direct_http",
        choices=["direct_http", "raw_http", "anvil_fork"],
        help=(
            "Quote backend: "
            "'direct_http' (web3 + eth_chainId, 2 HTTP/probe), "
            "'raw_http' (direct JSON-RPC, 1 HTTP/probe, recommended for 429 fix), "
            "'anvil_fork' (local fork at http://127.0.0.1:8545, no rate limits)."
        ),
    )
    parser.add_argument(
        "--require-premium-rpc",
        action="store_true",
        default=bool(os.environ.get("ARBY_REQUIRE_PREMIUM_RPC")),
        help=(
            "Hard-fail if the resolved RPC provider is 'public_fallback' or 'public'. "
            "Use this to prevent accidental runs against mainnet.base.org. "
            "Also enabled by env ARBY_REQUIRE_PREMIUM_RPC=1."
        ),
    )
    parser.add_argument(
        "--require-factory-verified",
        action=argparse.BooleanOptionalAction,
        default=bool(os.environ.get("ARBY_REQUIRE_FACTORY_VERIFIED")),
        help=(
            "Use verified inventory (data/tmp/m9_verified_inventory.json) produced "
            "by pool_verifier.  Also enabled by ARBY_REQUIRE_FACTORY_VERIFIED=1 env. "
            "Use --no-require-factory-verified to override the env var and force "
            "the default shadow inventory."
        ),
    )
    parser.add_argument(
        "--ws-freshness-url",
        default=None,
        help=(
            "WebSocket URL for newHeads freshness monitor (e.g. wss://mainnet.base.org). "
            "Optional — falls back to env BASE_WSS if not set."
        ),
    )
    parser.add_argument(
        "--scheduler",
        default="priority",
        choices=["priority", "round_robin"],
        help=(
            "'priority' (default): use CyclePriorityScheduler — hot/cold 2-tier queue "
            "with adaptive scoring (factory class, cross-DEX, fee, history). "
            "Quotes the most promising cycles first, reducing wasted RPC calls. "
            "'round_robin': legacy sliding-window over rank_cycles() output."
        ),
    )
    parser.add_argument(
        "--secondary-rpc",
        default=None,
        help=(
            "Secondary RPC HTTP URL for ProviderRouter failover (Step 8). "
            "Used when primary hits ARBY_PROVIDER_FAILOVER_THRESHOLD 429s. "
            "Also reads BASE_RPC_SECONDARY env var when not set."
        ),
    )
    parser.add_argument(
        "--anvil-url",
        default=None,
        help=(
            "Local Anvil fork RPC URL for anvil_fork quote backend (Step 10). "
            "Default: http://127.0.0.1:8545. Sets ARBY_ANVIL_RPC_URL env var."
        ),
    )
    parser.add_argument(
        "--prequote-min-bps",
        type=float,
        default=-500.0,
        help=(
            "Skip cycles where V3 prequote estimate is below this threshold (Step 4+9). "
            "Default -500 bps: only filter clearly hopeless cycles. "
            "Set to 0 to only quote cycles showing positive estimated spread."
        ),
    )
    parser.add_argument(
        "--no-prequote",
        action="store_true",
        help="Disable multicall prequote filter (Steps 1+3+4+9). Use when multicall is unavailable.",
    )
    parser.add_argument(
        "--allow-no-prequote-soak",
        action="store_true",
        default=False,
        help=(
            "Override the --no-prequote + duration>=5 safety gate. "
            "DEBUG/testing only — productive runs must use --prequote-min-bps instead."
        ),
    )
    # Pool-quality gate: productive lane (Steps 2+3)
    parser.add_argument(
        "--productive-lane",
        action="store_true",
        default=False,
        help=(
            "Enable productive lane: exclude quarantined thin pools from graph. "
            "Discovery lane (default) sees all pools including thin/toxic for RCA. "
            "Load quarantine from --pool-quarantine-path."
        ),
    )
    parser.add_argument(
        "--pool-quarantine-path",
        default="data/quarantine/m9_pool_depth_quarantine.json",
        help="Evidence-based pool depth quarantine JSON path (used with --productive-lane).",
    )
    parser.add_argument(
        "--min-effective-depth-usd",
        type=float,
        default=0.0,
        help=(
            "Minimum effective depth USD for productive lane filter (0 = disabled). "
            "Requires effective_depth_usd in inventory entries (run pool_depth_probe first)."
        ),
    )

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    import logging
    log = logging.getLogger(__name__)

    # Acquire process lock
    lock_path = Path(_LOCK_FILE)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    if lock_path.exists():
        log.warning("Lock file exists at %s — another runner may be active", _LOCK_FILE)

    lock_path.write_text(str(os.getpid()))

    try:
        return _run(args, log)
    finally:
        try:
            lock_path.unlink(missing_ok=True)
        except Exception:
            pass


def _run(args: argparse.Namespace, log: "logging.Logger") -> int:
    import logging
    from m9.graph_arb.builder import (
        build_graph_from_inventory, graph_token_count, graph_edge_count, graph_route_count,
        extract_inventory_stats, best_inventory_path,
    )
    from m9.graph_arb.finder import find_cycles, analyze_topology, rank_cycles
    from m9.graph_arb.artifacts import build_artifact, write_artifact

    run_timestamp = _iso_now()
    started_at = time.monotonic()
    sweeps_completed = 0
    process_id = os.getpid()

    # Resolve RPC URL early — before graph building so all build_artifact() calls
    # (including early-exit ones) record the correct provider identity.
    # Using resolve_rpc_http() instead of get_rpc_url() to capture provider/source.
    rpc_url: "str | None" = None
    rpc_provider: str = "unknown"
    rpc_source: str = "unknown"
    rpc_public_fallback_used: bool = False
    try:
        from core.rpc_urls import resolve_rpc_http, _CHAIN_KEY_TO_ID
        _chain_id = _CHAIN_KEY_TO_ID.get(args.chain.lower())
        rpc_url, rpc_provider, rpc_diag = resolve_rpc_http(
            chain_id=_chain_id,
            network=args.chain,
            env=dict(os.environ),
        )
        rpc_source = rpc_diag.get("source", "unknown")
        rpc_public_fallback_used = rpc_provider in ("public", "public_fallback")
        log.info(
            "RPC resolved: provider=%s source=%s public_fallback=%s",
            rpc_provider, rpc_source, rpc_public_fallback_used,
        )
        # Guard: hard-fail if premium RPC is required but we resolved a public endpoint
        if getattr(args, "require_premium_rpc", False) and rpc_public_fallback_used:
            log.error(
                "PREMIUM_RPC_REQUIRED: resolved provider '%s' (source=%s) is a public "
                "fallback. Set BASE_RPC in .env or ARBY_REQUIRE_PREMIUM_RPC is set. "
                "Unset ARBY_REQUIRE_PREMIUM_RPC or provide a premium endpoint.",
                rpc_provider, rpc_source,
            )
            return EXIT_CONFIG_ERROR
    except Exception as exc:
        log.warning("Could not resolve rpc_url for chain %s: %s", args.chain, exc)

    # Step 8 (GPT): Apply scan_params overrides from YAML config.
    # Config wins over CLI defaults — only overrides when CLI still holds the compile-time default.
    _CLI_SIZES_DEFAULT = [100.0, 250.0, 500.0]
    _CLI_DYN_MAX_DEFAULT = 3
    # Fix 7: track source of sizes_usd for artifact invariant
    _sizes_usd_source: str = "cli_default"
    try:
        import yaml  # noqa: PLC0415
        with open(args.config, encoding="utf-8") as _f:
            _cfg_raw = yaml.safe_load(_f) or {}
        _sp = _cfg_raw.get("scan_params") or {}
        if _sp.get("sizes_usd") and list(args.sizes_usd) == _CLI_SIZES_DEFAULT:
            args.sizes_usd = [float(v) for v in _sp["sizes_usd"]]
            _sizes_usd_source = "config.scan_params"
            log.info("scan_params: sizes_usd from config: %s", args.sizes_usd)
        elif list(args.sizes_usd) != _CLI_SIZES_DEFAULT:
            _sizes_usd_source = "cli_override"
        if _sp.get("dynamic_size_max_cycles") and args.dynamic_size_max_cycles == _CLI_DYN_MAX_DEFAULT:
            args.dynamic_size_max_cycles = int(_sp["dynamic_size_max_cycles"])
            log.info("scan_params: dynamic_size_max_cycles from config: %d", args.dynamic_size_max_cycles)
    except Exception as _sp_exc:
        log.debug("scan_params load skipped: %s", _sp_exc)

    # --require-factory-verified: auto-select the pre-verified inventory if the caller
    # did not supply an explicit --inventory path.  The verified inventory is produced by
    # pool_verifier.py (py -3.11 -m m9.graph_arb.pool_verifier ...) and only contains
    # routes confirmed on-chain via factory.getPool().
    _VERIFIED_INVENTORY = "data/tmp/m9_verified_inventory.json"
    _verified_inventory_exists: bool = os.path.exists(_VERIFIED_INVENTORY)
    if getattr(args, "require_factory_verified", False) and args.inventory is None:
        if os.path.exists(_VERIFIED_INVENTORY):
            args.inventory = _VERIFIED_INVENTORY
            log.info(
                "--require-factory-verified: auto-selected verified inventory %s",
                _VERIFIED_INVENTORY,
            )
        else:
            log.error(
                "HARD FAIL: --require-factory-verified set but verified inventory "
                "not found at %s. Run pool_verifier first: "
                "py -3.11 -m m9.graph_arb.pool_verifier --chain %s --config %s",
                _VERIFIED_INVENTORY, args.chain, args.config,
            )
            return EXIT_CONFIG_ERROR

    # Guard: --no-prequote + --dynamic-sizes is an invalid combination for productive runs.
    # Without the prequote funnel every cycle in the batch hits the raw-HTTP quoter directly,
    # which exhausts the dRPC free-tier RPS budget and yields qsr ≈ 0 via 429 floods.
    if getattr(args, "no_prequote", False) and getattr(args, "dynamic_sizes", False):
        log.error(
            "CONFIG_ERROR: --no-prequote and --dynamic-sizes cannot be combined. "
            "Without the prequote funnel all cycles hit the raw-HTTP quoter, "
            "burning free-tier RPS and producing qsr≈0. "
            "Use --prequote-min-bps -500 (permissive) instead of --no-prequote, "
            "or remove --dynamic-sizes."
        )
        return EXIT_CONFIG_ERROR

    # Guard: --no-prequote for soak duration (>=5 min) disables multicall_success_rate
    # and data_completeness — both runtime gates are null=FAIL without prequote.
    # This produces invalid productive-state artifacts that cannot pass the M9 gate.
    # Use --prequote-min-bps -500 (permissive, passes ~95% of cycles) instead.
    if (
        getattr(args, "no_prequote", False)
        and getattr(args, "duration_minutes", 0) >= 5
        and not getattr(args, "allow_no_prequote_soak", False)
    ):
        log.error(
            "CONFIG_ERROR: --no-prequote with duration_minutes=%s is not allowed for "
            "productive/soak runs. Removing prequote sets multicall_success_rate=null "
            "and data_completeness=null, both of which cause runtime_gates.all_pass=False. "
            "Use --prequote-min-bps -500 (permissive) instead. "
            "To bypass this guard explicitly use --allow-no-prequote-soak (debug only).",
            getattr(args, "duration_minutes", 0),
        )
        return EXIT_CONFIG_ERROR

    # Prefer merged shadow inventory if available
    inventory_path = best_inventory_path(preferred=args.inventory)
    log.info(
        "M9 graph-arb runner starting: chain=%s config=%s inventory=%s",
        args.chain, args.config, inventory_path,
    )

    # Extract inventory stats (Funnel A + reject taxonomy) before building graph
    inv_stats = extract_inventory_stats(inventory_path)
    funnel_a = inv_stats.get("funnel_a")
    inventory_reject_histogram = inv_stats.get("reject_histogram") or None
    # Inventory purity metric: active_routes without factory_verified=True
    unverified_active_routes: Optional[int] = (funnel_a or {}).get("unverified_active_routes")

    # M8→M9 bridge provenance: if inventory is a bridge inventory, extract metrics
    _bridge_source_metrics: Optional[Dict[str, Any]] = None
    _m8_pool_addrs: "frozenset[str]" = frozenset()
    try:
        import json as _json_bridge
        with open(inventory_path, encoding="utf-8") as _inv_fh:
            _inv_raw = _json_bridge.load(_inv_fh)
        _bsm = _inv_raw.get("bridge_source_metrics")
        if isinstance(_bsm, dict):
            _bridge_source_metrics = _bsm
            log.info(
                "Bridge inventory detected: graph_ready_total=%s m8_stale=%s m8_1_stale=%s",
                _bsm.get("graph_ready_total"),
                _bsm.get("m8_stale"),
                _bsm.get("m8_1_stale"),
            )
        # Extract M8 pool addresses for cycle participation tracking
        _m8_pool_addrs = frozenset(
            r.get("pool_address", "").lower()
            for r in _inv_raw.get("active_routes", [])
            if r.get("source") == "m8_sniper" and r.get("pool_address")
        )
    except Exception as _bsm_exc:
        log.debug("Bridge metrics extraction skipped: %s", _bsm_exc)

    # Build graph
    # Productive lane: load quarantined pool addresses (Steps 2+3)
    _lane = "productive" if getattr(args, "productive_lane", False) else "discovery"
    _exclude_pool_addresses: "Optional[frozenset[str]]" = None
    _depth_quarantine_skipped = 0
    if _lane == "productive":
        from m9.graph_arb.pool_depth_filter import load_quarantined_pool_addresses
        _quarantine_path = getattr(args, "pool_quarantine_path", "data/quarantine/m9_pool_depth_quarantine.json")
        _loaded = load_quarantined_pool_addresses(_quarantine_path)
        if _loaded:
            _exclude_pool_addresses = _loaded
            log.info(
                "Productive lane enabled: %d quarantined pools will be excluded from graph",
                len(_loaded),
            )
        else:
            log.info("Productive lane enabled: no quarantine addresses loaded (check path or placeholders)")

    try:
        adjacency = build_graph_from_inventory(
            inventory_path=inventory_path,
            config_path=args.config,
            require_factory_verified=getattr(args, "require_factory_verified", False),
            exclude_pool_addresses=_exclude_pool_addresses,
            min_effective_depth_usd=getattr(args, "min_effective_depth_usd", 0.0),
            lane=_lane,
        )
    except Exception as exc:
        log.error("Failed to build graph: %s", exc)
        return EXIT_CONFIG_ERROR

    if not adjacency:
        log.error("Empty graph — check inventory path: %s", inventory_path)
        from m9.graph_arb.models import GraphTopology
        topology = GraphTopology(
            token_count=0, edge_count=0, route_count=0,
            hub_tokens=[], dead_end_tokens=[],
            missing_edges_for_3cycle=[], adjacency_summary={},
        )
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=0,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
            rpc_provider=rpc_provider,
            rpc_source=rpc_source,
            rpc_public_fallback_used=rpc_public_fallback_used,
            unverified_active_routes=unverified_active_routes,
            sizes_usd_source=_sizes_usd_source,
            pool_quality_lane=_lane,
            depth_quarantine_skipped=len(_exclude_pool_addresses) if _exclude_pool_addresses else 0,
            bridge_source_metrics=_bridge_source_metrics,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_CONFIG_ERROR

    # Find cycles
    log.info("Finding cycles (limit=%d)...", args.cycles_limit)

    # Count graph edges sourced from M8 sniper routes (requires pair_id with underscore)
    if _m8_pool_addrs:
        _graph_edges_from_m8 = sum(
            1
            for token_edges in adjacency.values()
            for edges in token_edges.values()
            for e in edges
            if e.pool_address.lower() in _m8_pool_addrs
        )
        if _bridge_source_metrics is not None:
            _bridge_source_metrics["graph_edges_from_m8"] = _graph_edges_from_m8
        log.info("Graph edges from M8 sniper routes: %d", _graph_edges_from_m8)
    cycles = find_cycles(adjacency, max_cycles=args.cycles_limit)
    topology = analyze_topology(adjacency, cycles)
    ranked = rank_cycles(cycles)

    log.info("Found %d cycles across %d tokens", len(cycles), topology.token_count)

    if not cycles:
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
            rpc_provider=rpc_provider,
            rpc_source=rpc_source,
            rpc_public_fallback_used=rpc_public_fallback_used,
            unverified_active_routes=unverified_active_routes,
            sizes_usd_source=_sizes_usd_source,
            pool_quality_lane=_lane,
            depth_quarantine_skipped=len(_exclude_pool_addresses) if _exclude_pool_addresses else 0,
            bridge_source_metrics=_bridge_source_metrics,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_NO_CYCLES

    if args.dry_run:
        log.info("Dry-run mode: skipping quoting (topology cycles_found=%d)", len(cycles))
        artifact = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=[],
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=time.monotonic() - started_at,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            # Preserve topology cycle count even though quote results are empty
            cycles_found_topology=len(cycles),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
            rpc_provider=rpc_provider,
            rpc_source=rpc_source,
            rpc_public_fallback_used=rpc_public_fallback_used,
            unverified_active_routes=unverified_active_routes,
            sizes_usd_source=_sizes_usd_source,
            pool_quality_lane=_lane,
            depth_quarantine_skipped=len(_exclude_pool_addresses) if _exclude_pool_addresses else 0,
            bridge_source_metrics=_bridge_source_metrics,
        )
        write_artifact(artifact, args.artifact_path)
        return EXIT_OK

    # Connect RPC
    w3 = _connect_rpc(args.chain)
    if w3 is None:
        log.warning("Could not connect to RPC for chain %s — quoting will fail", args.chain)

    # Start optional WS freshness monitor
    ws_url = getattr(args, "ws_freshness_url", None) or os.environ.get("BASE_WSS")
    ws_monitor = None
    if ws_url:
        try:
            from m9.graph_arb.ws_monitor import start_ws_monitor
            ws_monitor = start_ws_monitor(ws_url)
            log.info("WS freshness monitor started: %s", ws_url)
        except Exception as exc:
            log.debug("WS monitor start failed: %s", exc)

    # Deadline-aware quote loop: run sweeps until wall-clock deadline expires.
    # Each sweep quotes a batch of max_cycles_per_sweep cycles, then writes a
    # partial artifact so the rolling artifact stays fresh even mid-soak.
    from m9.graph_arb.quoter import schedule_cycle_quotes
    deadline = started_at + args.duration_minutes * 60.0
    max_per_sweep = getattr(args, "max_cycles_per_sweep", 200)
    cycle_count = len(ranked)
    all_results: list = []
    sweep_num = 0

    # Build scheduler — priority mode (default) uses adaptive 2-tier hot/cold queue;
    # round_robin keeps the legacy sliding-window behaviour.
    _use_priority_scheduler = getattr(args, "scheduler", "priority") == "priority"
    _cycle_scheduler = None
    if _use_priority_scheduler:
        from m9.graph_arb.cycle_scheduler import CyclePriorityScheduler
        _cycle_scheduler = CyclePriorityScheduler(ranked)
        log.info(
            "CyclePriorityScheduler initialised: hot=%d cold=%d",
            _cycle_scheduler.hot_count, _cycle_scheduler.cold_count,
        )

    # Step 8: Provider router — primary + optional secondary RPC with 429 failover
    from m9.graph_arb.provider_router import ProviderRouter
    _secondary_rpc = getattr(args, "secondary_rpc", None) or os.environ.get("BASE_RPC_SECONDARY")
    _router = ProviderRouter(primary=rpc_url or "", secondary=_secondary_rpc or None)
    if _secondary_rpc:
        log.info("ProviderRouter: secondary RPC configured for failover")

    # Step 2: Pool state cache (TTL-backed, survives across sweeps within session)
    from m9.graph_arb.pool_state_cache import PoolStateCache
    _pool_cache = PoolStateCache()
    _pool_cache.load()  # warm from previous session; entries are stale but pool_addrs known

    # Step 10: Propagate Anvil URL env var for anvil_fork backend
    if getattr(args, "anvil_url", None):
        os.environ["ARBY_ANVIL_RPC_URL"] = args.anvil_url
        log.info("Anvil fork URL configured: %s", args.anvil_url)

    # Prequote imports (Steps 1+3+4+9)
    _prequote_enabled = not getattr(args, "no_prequote", False) and bool(rpc_url)
    _prequote_min_bps: float = getattr(args, "prequote_min_bps", -500.0)
    if _prequote_enabled:
        from m9.graph_arb.multicall_snapshot import snapshot_pool_states as _snapshot_pool_states
        from m9.graph_arb.multicall_snapshot import get_multicall_stats as _get_multicall_stats
        from m9.graph_arb.multicall_snapshot import reset_multicall_stats as _reset_multicall_stats
        from m9.graph_arb.v3_prequote import should_skip_cycle as _should_skip_cycle
        _reset_multicall_stats()  # start fresh for this run
        log.info(
            "Prequote funnel enabled: min_bps=%.1f (multicall snapshot + V3 pre-filter)",
            _prequote_min_bps,
        )
    else:
        _snapshot_pool_states = None  # type: ignore[assignment]
        _should_skip_cycle = None     # type: ignore[assignment]
        _get_multicall_stats = lambda: None  # type: ignore[assignment]

    _total_prequote_skipped = 0
    # Step 9 (GPT fix): 429-adaptive prequote threshold.
    # When multicall 429 rate spikes (>=10 per sweep), raise _prequote_min_bps to shed load.
    # After 5 stable sweeps (delta_429 < 5 each), relax back toward original value.
    _prequote_min_bps_orig = _prequote_min_bps
    _prev_mc_429: int = 0
    _stable_sweep_count: int = 0
    _ADAPT_SPIKE_THRESHOLD = 10  # 429s per sweep that triggers tightening
    _ADAPT_STABLE_THRESHOLD = 5  # 429s per sweep to count as "stable"
    _ADAPT_STABLE_WINDOW = 5     # consecutive stable sweeps before relaxing
    _ADAPT_STEP_UP = 50.0        # bps increase on spike
    _ADAPT_STEP_DOWN = 25.0      # bps decrease on stable window

    while time.monotonic() < deadline:
        if _cycle_scheduler is not None:
            # Priority mode: scheduler picks the best candidates each sweep
            batch = _cycle_scheduler.next_batch(max_per_sweep)
            if not batch:
                break
        else:
            # Round-robin (legacy): sliding window over pre-ranked list
            start_idx = (sweep_num * max_per_sweep) % cycle_count
            end_idx = min(start_idx + max_per_sweep, cycle_count)
            batch = ranked[start_idx:end_idx]
            if not batch:
                # cycle_count < max_per_sweep — all cycles covered in one sweep
                if sweep_num > 0:
                    break

        # Step 8: get active RPC (primary or secondary after failover)
        _active_rpc = _router.get_url() if rpc_url else rpc_url

        # Steps 1+3+4+9: Multicall pool snapshot → V3 prequote pre-filter
        _sweep_prequote_skipped = 0
        _prequote_skipped_ids: list = []
        if _prequote_enabled and _snapshot_pool_states is not None and batch:
            try:
                _pool_addrs = list({e.pool_address for c in batch for e in c.edges})
                _pool_states = _snapshot_pool_states(
                    _pool_addrs, rpc_url=_active_rpc, cache=_pool_cache
                )
                _filtered = []
                for _cyc in batch:
                    if _should_skip_cycle(_cyc, _pool_states, min_spread_bps=_prequote_min_bps):
                        _sweep_prequote_skipped += 1
                        _prequote_skipped_ids.append(_cyc.cycle_id)
                    else:
                        _filtered.append(_cyc)
                if _sweep_prequote_skipped:
                    log.debug(
                        "Prequote funnel: skipped %d/%d cycles (min_bps=%.1f)",
                        _sweep_prequote_skipped, len(batch), _prequote_min_bps,
                    )
                batch = _filtered
                _total_prequote_skipped += _sweep_prequote_skipped
            except Exception as _pq_exc:
                log.debug("Prequote snapshot error (non-fatal): %s", _pq_exc)

        new_results = schedule_cycle_quotes(
            batch,
            w3=w3,
            sizes_usd=tuple(args.sizes_usd),
            timeout_s=getattr(args, "quote_timeout_s", 10.0),
            max_workers=getattr(args, "quote_workers", 4),
            quote_backend=getattr(args, "quote_backend", "direct_http"),
            rpc_url=_active_rpc,
            token_prices=_TOKEN_PRICE_USD_BASE,
            dynamic_sizes=getattr(args, "dynamic_sizes", False),
            dynamic_size_limit=getattr(args, "dynamic_size_max_cycles", 3),
        )
        all_results.extend(new_results)
        # Feed results back to priority scheduler for adaptive score update
        if _cycle_scheduler is not None:
            _cycle_scheduler.record_results(new_results)
            if _prequote_skipped_ids:
                _cycle_scheduler.record_prequote_skips(_prequote_skipped_ids)
        # Step 8: record 429s from sweep for provider router
        _sweep_429s = sum(
            1 for qr in new_results
            for leg in (qr.leg_results or [])
            if not leg.ok and leg.raw_error and "429" in leg.raw_error
        )
        if _sweep_429s and _active_rpc:
            _router.record_429(_active_rpc)
        sweeps_completed += 1
        sweep_num += 1

        # Step 6 (GPT): operator surface — log dynamic_size summary per sweep
        if getattr(args, "dynamic_sizes", False):
            _sweep_dyn = sum(1 for qr in new_results if qr.dynamic_size_usd is not None)
            if _sweep_dyn:
                _dyn_sizes_seen = sorted({
                    qr.dynamic_size_usd for qr in new_results
                    if qr.dynamic_size_usd is not None
                })
                log.info(
                    "Sweep %d dynamic_size: %d/%d cycles selected non-default size (sizes: %s)",
                    sweeps_completed, _sweep_dyn, len(new_results),
                    [round(s, 1) for s in _dyn_sizes_seen],
                )

        # Step 9 (GPT fix): 429-adaptive prequote threshold.
        # Read current cumulative 429 count from multicall stats.
        if _prequote_enabled:
            _cur_mc_stats = _get_multicall_stats() or {}
            _cur_mc_429 = _cur_mc_stats.get("http_429", 0)
            _delta_429 = _cur_mc_429 - _prev_mc_429
            _prev_mc_429 = _cur_mc_429
            if _delta_429 >= _ADAPT_SPIKE_THRESHOLD:
                _prequote_min_bps = min(_prequote_min_bps + _ADAPT_STEP_UP, _prequote_min_bps_orig + 200.0)
                _stable_sweep_count = 0
                log.debug(
                    "429-adaptive: delta_429=%d >=threshold=%d, min_bps raised to %.1f",
                    _delta_429, _ADAPT_SPIKE_THRESHOLD, _prequote_min_bps,
                )
            elif _delta_429 < _ADAPT_STABLE_THRESHOLD:
                _stable_sweep_count += 1
                if _stable_sweep_count >= _ADAPT_STABLE_WINDOW and _prequote_min_bps > _prequote_min_bps_orig:
                    _prequote_min_bps = max(_prequote_min_bps - _ADAPT_STEP_DOWN, _prequote_min_bps_orig)
                    _stable_sweep_count = 0
                    log.debug(
                        "429-adaptive: %d stable sweeps, min_bps relaxed to %.1f",
                        _ADAPT_STABLE_WINDOW, _prequote_min_bps,
                    )
            else:
                _stable_sweep_count = 0

        # Write partial artifact after every sweep so rolling stays current
        elapsed_so_far = time.monotonic() - started_at
        _pt_snap = _get_provider_throttle_snapshot()
        _ws_snap = ws_monitor.snapshot() if ws_monitor is not None else None
        partial = build_artifact(
            chain=args.chain,
            duration_minutes=args.duration_minutes,
            cycle_results=all_results,
            topology=topology,
            sizes_usd=tuple(args.sizes_usd),
            run_timestamp=run_timestamp,
            started_at_mono=started_at,
            elapsed_s=elapsed_so_far,
            inventory_path=inventory_path,
            config_path=args.config,
            sweeps_completed=sweeps_completed,
            process_id=process_id,
            python_executable=sys.executable,
            venv_active=bool(os.environ.get("VIRTUAL_ENV")),
            funnel_a=funnel_a,
            inventory_reject_histogram=inventory_reject_histogram,
            quote_backend=getattr(args, "quote_backend", "direct_http"),
            quote_workers=getattr(args, "quote_workers", 4),
            provider_throttle_snapshot=_pt_snap,
            ws_freshness=_ws_snap,
            rpc_provider=rpc_provider,
            rpc_source=rpc_source,
            rpc_public_fallback_used=rpc_public_fallback_used,
            unverified_active_routes=unverified_active_routes,
            prequote_cycles_skipped=_total_prequote_skipped,
            scheduler_name=getattr(args, "scheduler", "priority"),
            multicall_stats=_get_multicall_stats() if _prequote_enabled else None,
            verified_inventory_exists=_verified_inventory_exists,
            sizes_usd_source=_sizes_usd_source,
            provider_router_snapshot=_router.snapshot(),
            prequote_min_bps=_prequote_min_bps,
            pool_quality_lane=_lane,
            depth_quarantine_skipped=len(_exclude_pool_addresses) if _exclude_pool_addresses else 0,
            bridge_source_metrics=_bridge_source_metrics,
        )
        write_artifact(partial, args.artifact_path)
        positive_so_far = sum(1 for qr in all_results if qr.gross_bps > 0)
        _sched_info = ""
        if _cycle_scheduler is not None:
            ss = _cycle_scheduler.score_summary()
            _sched_info = f" sched=hot:{ss.get('hot',0)}/cold:{ss.get('cold',0)}"
        log.info(
            "Sweep %d done: %d new, %d total, %d positive, elapsed=%.1fs/%.0fs%s",
            sweeps_completed, len(new_results), len(all_results),
            positive_so_far, elapsed_so_far, args.duration_minutes * 60, _sched_info,
        )

        if time.monotonic() >= deadline:
            break

        # Step 7: WS trigger — pace sweep to chain block cadence instead of busy-loop
        if ws_monitor is not None:
            _got_block = ws_monitor.wait_for_new_block(timeout_s=12.0)
            if not _got_block:
                log.debug("WsMonitor: no new block in 12s — continuing sweep")

    cycle_results = all_results

    # Persist pool state cache to disk for next session warm-up
    if _prequote_enabled:
        try:
            _pool_cache.save()
        except Exception as _save_exc:
            log.debug("pool_cache.save() failed (non-fatal): %s", _save_exc)

    if _total_prequote_skipped:
        log.info("Prequote funnel total: skipped %d cycles across %d sweeps", _total_prequote_skipped, sweeps_completed)

    # Collect final infra telemetry
    _pt_snap_final = _get_provider_throttle_snapshot()
    _ws_snap_final = ws_monitor.snapshot() if ws_monitor is not None else None
    if ws_monitor is not None:
        ws_monitor.stop()

    # M8 cycle participation metrics — must be computed after all cycle_results are collected
    if _bridge_source_metrics is not None and _m8_pool_addrs:
        _cycles_with_m8 = sum(
            1 for qr in cycle_results
            if any(e.pool_address.lower() in _m8_pool_addrs for e in qr.cycle.edges)
        )
        _positive_cycles_with_m8 = sum(
            1 for qr in cycle_results
            if qr.gross_bps > 0
            and any(e.pool_address.lower() in _m8_pool_addrs for e in qr.cycle.edges)
        )
        _bridge_source_metrics["cycles_with_m8_pool"] = _cycles_with_m8
        _bridge_source_metrics["positive_cycles_with_m8_pool"] = _positive_cycles_with_m8
        log.info(
            "M8 pool cycle participation: cycles_with_m8=%d positive_with_m8=%d",
            _cycles_with_m8, _positive_cycles_with_m8,
        )

    # Build and write final artifact with full elapsed_s
    artifact = build_artifact(
        chain=args.chain,
        duration_minutes=args.duration_minutes,
        cycle_results=cycle_results,
        topology=topology,
        sizes_usd=tuple(args.sizes_usd),
        run_timestamp=run_timestamp,
        started_at_mono=started_at,
        elapsed_s=time.monotonic() - started_at,
        inventory_path=inventory_path,
        config_path=args.config,
        sweeps_completed=sweeps_completed,
        process_id=process_id,
        python_executable=sys.executable,
        venv_active=bool(os.environ.get("VIRTUAL_ENV")),
        funnel_a=funnel_a,
        inventory_reject_histogram=inventory_reject_histogram,
        quote_backend=getattr(args, "quote_backend", "direct_http"),
        quote_workers=getattr(args, "quote_workers", 4),
        provider_throttle_snapshot=_pt_snap_final,
        ws_freshness=_ws_snap_final,
        rpc_provider=rpc_provider,
        rpc_source=rpc_source,
        rpc_public_fallback_used=rpc_public_fallback_used,
        unverified_active_routes=unverified_active_routes,
        prequote_cycles_skipped=_total_prequote_skipped,
        scheduler_name=getattr(args, "scheduler", "priority"),
        multicall_stats=_get_multicall_stats() if _prequote_enabled else None,
        verified_inventory_exists=_verified_inventory_exists,
        sizes_usd_source=_sizes_usd_source,
        provider_router_snapshot=_router.snapshot(),
        prequote_min_bps=_prequote_min_bps,
        pool_quality_lane=_lane,
        depth_quarantine_skipped=len(_exclude_pool_addresses) if _exclude_pool_addresses else 0,
        bridge_source_metrics=_bridge_source_metrics,
    )
    write_artifact(artifact, args.artifact_path)

    # Write QUOTE_REVERT quarantine: routes whose legs failed exclusively with QUOTE_REVERT.
    # This feedback file guides inventory refresh: quarantine these fee-tier/pool combos.
    _write_revert_quarantine(cycle_results, log)

    positive = sum(1 for qr in cycle_results if qr.gross_bps > 0)
    log.info(
        "Sweep complete: %d cycles quoted, %d positive gross, artifact written to %s",
        len(cycle_results),
        positive,
        args.artifact_path,
    )

    if not cycle_results:
        return EXIT_ALL_QUOTES_FAILED

    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
