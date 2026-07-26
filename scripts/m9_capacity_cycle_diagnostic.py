#!/usr/bin/env python3
"""M9 cycle capacity diagnostic — count cycles by usable capacity floors and profiles."""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

_DEFAULT_BRIDGE = "data/tmp/m9_bridge_inventory_graph_handoff_latest.json"
_DEFAULT_OUTPUT = "data/tmp/m9_capacity_cycle_diagnostic_latest.json"
_DEFAULT_CONFIG = "config/exotic_base_anchor.yaml"
_DEFAULT_TARGETS = "data/tmp/m9_capacity_enrichment_targets_latest.json"


def _iso_now() -> str:
    return datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def stamp_capacity_provenance(
    report: Dict[str, Any],
    *,
    now_utc: Optional[str] = None,
    run_timestamp: Optional[str] = None,
    universe_contract: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Stamp capacity diagnostic with provenance, session binding, and universe contract."""
    from core.pipeline_provenance import (
        apply_pipeline_provenance,
        pipeline_session_id,
        stamp_run_context,
    )
    from m9.graph_arb.universe_contract import stamp_universe_contract

    ts = now_utc or _iso_now()
    report["generated_at_utc"] = ts
    report["run_timestamp"] = run_timestamp or ts
    sid = pipeline_session_id()
    if sid:
        report["session_id"] = sid
    report["run_context"] = stamp_run_context(
        report.get("run_context"),
        run_timestamp=report["run_timestamp"],
    )
    if universe_contract is not None:
        stamp_universe_contract(report, universe_contract)
    provenance_out = apply_pipeline_provenance(report, run_timestamp=report["run_timestamp"])
    report.update(provenance_out)
    return report


def _parse_cycle_lengths(raw: str) -> tuple[int, ...]:
    parts = [p.strip() for p in raw.split(",") if p.strip()]
    return tuple(int(p) for p in parts) or (2, 3, 4)


def _parse_floors(raw: str | None) -> tuple[float, ...]:
    if not raw:
        from m9.graph_arb.cycle_capacity import DEFAULT_CAPACITY_FLOORS_USD

        return DEFAULT_CAPACITY_FLOORS_USD
    return tuple(float(p.strip()) for p in raw.split(",") if p.strip())


def main() -> int:
    ap = argparse.ArgumentParser(description="M9 usable-capacity cycle diagnostic")
    ap.add_argument("--bridge", "--inventory", dest="bridge", default=_DEFAULT_BRIDGE)
    ap.add_argument("--config", default=_DEFAULT_CONFIG)
    ap.add_argument("--cycle-lengths", default=None, help="Comma-separated (default: from config scan_params)")
    ap.add_argument(
        "--floors",
        default=None,
        help="Comma-separated USD floors (default: 25,50,100,180)",
    )
    ap.add_argument(
        "--profile",
        default=None,
        help="Economics profile for narrow-bridge floor (default: active config profile)",
    )
    ap.add_argument("--output", default=_DEFAULT_OUTPUT)
    ap.add_argument(
        "--write-narrow-bridge",
        default=None,
        help="Write cycle-preserving bridge filtered to selected profile floor",
    )
    ap.add_argument(
        "--write-enrichment-targets",
        default=_DEFAULT_TARGETS,
        help="Write targeted route_ids for decimals/depth enrichment",
    )
    ap.add_argument(
        "--quarantine-rca",
        action="store_true",
        help="Include quarantine/toxic depth RCA (false-positive vs genuinely thin)",
    )
    ap.add_argument(
        "--four-leg-rca",
        action="store_true",
        help="Include discovery vs productive 4-leg route loss report",
    )
    ap.add_argument(
        "--lane",
        choices=("discovery", "productive"),
        default="productive",
    )
    ap.add_argument(
        "--require-factory-verified",
        action=argparse.BooleanOptionalAction,
        default=None,
        help="Match runner productive graph admission (default: true when --lane productive)",
    )
    ap.add_argument(
        "--allow-pre-depth-inventory",
        action="store_true",
        help="Discovery/offline only: skip post-depth requirement (forbidden with --lane productive)",
    )
    ap.add_argument(
        "--effective-inventory-path",
        default=None,
        help="Session-bound effective inventory output (fallback: ARBY_M9_EFFECTIVE_INVENTORY_PATH env)",
    )
    ap.add_argument("--chain", default="base", help="Chain for optional RPC truth enrich")
    ap.add_argument(
        "--session-id",
        default=None,
        help="Pipeline session id (fallback: ARBY_PIPELINE_SESSION_ID env)",
    )
    args = ap.parse_args()

    if args.lane == "productive" and args.allow_pre_depth_inventory:
        print(
            "ERROR: --allow-pre-depth-inventory is forbidden with --lane productive",
            file=sys.stderr,
        )
        return 2

    from m9.graph_arb.cycle_capacity import (
        narrow_routes_by_econ_capacity_closure,
        run_capacity_cycle_diagnostic,
    )
    from m9.graph_arb.universe_contract import (
        bind_cli_session_to_env,
        build_universe_contract,
        resolve_cycle_lengths_from_config,
        resolve_session_id,
    )

    bind_cli_session_to_env(args.session_id)

    require_fv = args.require_factory_verified
    if require_fv is None:
        require_fv = args.lane == "productive"

    if args.cycle_lengths:
        lengths = _parse_cycle_lengths(args.cycle_lengths)
    else:
        lengths = resolve_cycle_lengths_from_config(args.config)
    floors = _parse_floors(args.floors)

    from m9.graph_arb.effective_inventory import (
        load_effective_inventory,
        resolve_effective_inventory_path,
    )

    session_id = resolve_session_id(args.session_id)
    effective_out = (
        str(args.effective_inventory_path or "").strip()
        or resolve_effective_inventory_path(session_id)
    )
    try:
        effective_inventory_path = load_effective_inventory(
            session_id=session_id,
            effective_path=effective_out,
            source_bridge_path=args.bridge,
            config_path=args.config,
        )
    except (FileNotFoundError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2
    report = run_capacity_cycle_diagnostic(
        inventory_path=effective_inventory_path,
        config_path=args.config,
        cycle_lengths=lengths,
        floors_usd=floors,
        lane=args.lane,
        require_factory_verified=require_fv,
        include_four_leg_rca=args.four_leg_rca,
    )
    report["bridge_inventory_path"] = args.bridge
    report["effective_inventory_path"] = effective_inventory_path

    if args.write_enrichment_targets:
        targets_path = Path(args.write_enrichment_targets)
        targets_path.parent.mkdir(parents=True, exist_ok=True)
        targets_path.write_text(
            json.dumps(report.get("enrichment_targets") or {}, indent=2),
            encoding="utf-8",
        )
        report["enrichment_targets_path"] = str(targets_path)

    if args.write_narrow_bridge:
        bridge_path = Path(args.bridge)
        with bridge_path.open(encoding="utf-8") as fh:
            inv = json.load(fh)
        routes = list(inv.get("active_routes") or [])
        kept, narrow_meta = narrow_routes_by_econ_capacity_closure(
            routes,
            config_path=args.config,
            cycle_lengths=lengths,
            profile_name=args.profile,
            lane=args.lane,
        )
        narrow_doc = dict(inv)
        narrow_doc["active_routes"] = kept
        narrow_doc["capacity_narrow_meta"] = narrow_meta
        narrow_out = Path(args.write_narrow_bridge)
        narrow_out.parent.mkdir(parents=True, exist_ok=True)
        narrow_out.write_text(json.dumps(narrow_doc, indent=2), encoding="utf-8")
        report["narrow_bridge"] = {
            "path": str(narrow_out),
            **narrow_meta,
        }

    out = Path(args.output)
    if args.quarantine_rca:
        with Path(effective_inventory_path).open(encoding="utf-8") as fh:
            inv = json.load(fh)
        from m9.graph_arb.quarantine_depth_rca import run_quarantine_depth_rca

        qrca = run_quarantine_depth_rca(
            active_routes=list(inv.get("active_routes") or []),
            quarantined_routes=list(inv.get("quarantined_routes") or []),
        )
        report["quarantine_depth_rca"] = qrca
        qpath = out.parent / "m9_quarantine_depth_rca_latest.json"
        qpath.write_text(json.dumps(qrca, indent=2), encoding="utf-8")
        report["quarantine_depth_rca_path"] = str(qpath)
    out.parent.mkdir(parents=True, exist_ok=True)
    universe_contract = build_universe_contract(
        inventory_path=effective_inventory_path,
        config_path=args.config,
        lane=args.lane,
        require_factory_verified=require_fv,
        cycle_lengths=lengths,
        active_economics_profile=str(report.get("active_economics_profile") or ""),
        session_id=resolve_session_id(args.session_id),
        graph_fingerprint=report.get("graph_fingerprint"),
    )
    stamp_capacity_provenance(report, universe_contract=universe_contract)
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")

    summary = {
        "cycles_total": report.get("cycles_total"),
        "cycles_by_profile": report.get("cycles_by_profile"),
        "cycles_by_usable_capacity_floor": report.get("cycles_by_usable_capacity_floor"),
        "cycles_at_production_floor": report.get("cycles_at_production_floor"),
        "near_econ_cycles_count": report.get("near_econ_cycles_count"),
        "production_conservative_floor_usd": report.get("production_conservative_floor_usd"),
        "active_economics_profile": report.get("active_economics_profile"),
        "blocker_hint": report.get("blocker_hint"),
        "shadow_gate": report.get("shadow_gate"),
        "top_bottleneck_legs": (report.get("top_bottleneck_legs") or [])[:10],
        "enrichment_route_ids_count": (report.get("enrichment_targets") or {}).get(
            "route_ids_count"
        ),
    }
    if report.get("narrow_bridge"):
        summary["narrow_bridge"] = report["narrow_bridge"]
    if report.get("productive_four_leg_rca"):
        summary["productive_four_leg_rca"] = report["productive_four_leg_rca"]
    if report.get("quarantine_depth_rca"):
        q = report["quarantine_depth_rca"]
        summary["quarantine_depth_rca"] = {
            "primary_verdict": q.get("primary_verdict"),
            "by_rca_bucket": q.get("by_rca_bucket"),
            "false_positive_distinct_probe_count": q.get(
                "false_positive_distinct_probe_count"
            ),
        }
    print(json.dumps(summary, indent=2))
    print("written:", out)
    prod_cycles = int(report.get("cycles_at_production_floor") or 0)
    return 0 if prod_cycles > 0 else 2


if __name__ == "__main__":
    raise SystemExit(main())
