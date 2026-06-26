#!/usr/bin/env python3
"""M8.3 — refresh rolling token metadata registry from M8/M8.1/M8.2/bridge inputs."""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

log = logging.getLogger("m8_3_token_metadata_registry_refresh")

_DEFAULTS = {
    "expansion": REPO_ROOT / "data/runs/_rolling/m8_cross_dex_expansion_latest.json",
    "bridge": REPO_ROOT / "data/tmp/m9_bridge_inventory_graph_handoff_latest.json",
    "sniper": REPO_ROOT / "data/runs/_rolling/new_pool_sniper_latest.json",
    "anchor": REPO_ROOT / "data/runs/_rolling/m8_1_stable_anchor_latest.json",
    "hints": REPO_ROOT / "data/runs/_rolling/m8_external_pool_hints_latest.json",
    "capacity": REPO_ROOT / "data/tmp/m9_capacity_cycle_diagnostic_latest.json",
    "prior": REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
    "output": REPO_ROOT / "data/runs/_rolling/m8_3_token_metadata_registry_latest.json",
}


def _load(path: Path) -> dict | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser(description="M8.3 token metadata registry refresh")
    ap.add_argument("--chain", default="base")
    ap.add_argument("--config", default="config/exotic_base_anchor.yaml")
    ap.add_argument("--expansion", default=str(_DEFAULTS["expansion"]))
    ap.add_argument("--bridge", default=str(_DEFAULTS["bridge"]))
    ap.add_argument("--sniper", default=str(_DEFAULTS["sniper"]))
    ap.add_argument("--anchor", default=str(_DEFAULTS["anchor"]))
    ap.add_argument("--hints", default=str(_DEFAULTS["hints"]))
    ap.add_argument("--capacity", default=str(_DEFAULTS["capacity"]))
    ap.add_argument("--prior", default=str(_DEFAULTS["prior"]))
    ap.add_argument("--output", default=str(_DEFAULTS["output"]))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--skip-onchain", action="store_true")
    ap.add_argument("--max-onchain-probes", type=int, default=500)
    ap.add_argument(
        "--task-mode",
        choices=("legacy", "aggregated"),
        default="aggregated",
        help="legacy=token-only builder; aggregated=root aggregator + dex workers",
    )
    ap.add_argument(
        "--with-dex-workers",
        action="store_true",
        help="Run per-DEX route metadata workers (default when task-mode=aggregated)",
    )
    ap.add_argument("--no-dex-workers", action="store_true", help="Disable dex route workers")
    ap.add_argument(
        "--dex-worker-concurrency",
        type=int,
        default=4,
        help="Bounded parallel DEX metadata workers",
    )
    ap.add_argument(
        "--no-erc20-multicall",
        action="store_true",
        help="Disable Multicall3 batch for ERC20 decimals/symbol prefetch",
    )
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")

    from m8.metadata.registry import build_token_metadata_registry, save_registry
    from m8_1.stable_anchor.config_loader import load_config

    cfg = load_config(Path(args.config))
    bridge = _load(Path(args.bridge))
    expansion = _load(Path(args.expansion))
    sniper = _load(Path(args.sniper))
    anchor = _load(Path(args.anchor))
    hints = _load(Path(args.hints))
    capacity = _load(Path(args.capacity))
    prior = _load(Path(args.prior))

    w3 = None
    if not args.skip_onchain:
        try:
            from core.env import load_root_dotenv
            from core.rpc_urls import apply_productive_rpc_env, resolve_productive_http_rpc
            from web3 import Web3

            load_root_dotenv()
            os.environ.update(apply_productive_rpc_env(args.chain))
            rpc = resolve_productive_http_rpc(args.chain)
            w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 20}))
            log.info("On-chain ERC20 probes enabled")
        except Exception as exc:
            log.warning("On-chain probes disabled: %s", exc)

    with_dex = (args.with_dex_workers or args.task_mode == "aggregated") and not args.no_dex_workers
    doc = build_token_metadata_registry(
        chain=args.chain,
        bridge=bridge,
        expansion=expansion,
        sniper=sniper,
        anchor=anchor,
        external_hints=hints,
        prior_registry=prior,
        capacity=capacity,
        cfg=cfg,
        w3=w3,
        max_onchain_probes=args.max_onchain_probes,
        task_mode=args.task_mode,
        with_dex_workers=with_dex,
        use_erc20_multicall=not args.no_erc20_multicall,
        dex_worker_concurrency=args.dex_worker_concurrency,
    )

    cov = doc.get("coverage") or {}
    rc = doc.get("route_coverage") or {}
    log.info(
        "M8.3 registry: tokens=%s econ_verified=%s conflicts=%s unresolved=%s",
        cov.get("all_tokens_count"),
        cov.get("economics_grade_verified_count"),
        cov.get("decimals_conflict_count"),
        cov.get("unresolved_count"),
    )
    cycle = rc.get("cycle_participating_routes") or {}
    log.info(
        "cycle_participating economics_grade_known_rate=%.4f",
        float(cycle.get("economics_grade_known_rate") or 0.0),
    )
    dex_cov = (doc.get("dex_route_metadata") or {}).get("coverage") or {}
    cycle_dex = dex_cov.get("cycle_participating_routes") or {}
    log.info(
        "cycle_participating dex_route_metadata_ready_rate=%.4f routes=%s",
        float(cycle_dex.get("dex_metadata_ready_rate") or 0.0),
        cycle_dex.get("routes_count"),
    )

    print(json.dumps({"coverage": cov, "route_coverage": rc}, indent=2))
    if args.dry_run:
        return 0
    out = save_registry(doc, args.output)
    log.info("Written %s", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
