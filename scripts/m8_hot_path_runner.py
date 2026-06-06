#!/usr/bin/env python3
"""Hot-path: live WS or batch sniper events -> mirror-resolve -> focused quote."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

_REPO = Path(__file__).resolve().parents[1]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

_DEFAULT_OUTPUT = "data/tmp/m8_hot_path_latest.json"


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="M8 hot-path mirror + focused quote")
    p.add_argument("--chain", default="base")
    p.add_argument("--config", default="config/exotic_base_anchor.yaml")
    p.add_argument(
        "--sniper",
        default="data/runs/_rolling/new_pool_sniper_latest.json",
    )
    p.add_argument(
        "--registry",
        default="data/runs/_rolling/m8_pending_pairs.json",
    )
    p.add_argument("--anchor", default="data/runs/_rolling/m8_1_stable_anchor_latest.json")
    p.add_argument("--output", default=_DEFAULT_OUTPUT)
    p.add_argument("--limit", type=int, default=10, help="Max batch events (non-WS mode)")
    p.add_argument(
        "--live-ws",
        action="store_true",
        help="Subscribe to live factory WS events (not recent_events batch)",
    )
    p.add_argument(
        "--duration-minutes",
        type=float,
        default=15.0,
        help="Live WS session duration",
    )
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--quote", action="store_true", help="Run focused M9 quotes (RPC)")
    p.add_argument(
        "--honeypot-strict-evidence",
        action="store_true",
        help="Require honeypot/tax PASS for positive gross (stub probe blocks profit claims)",
    )
    return p.parse_args()


def _run_batch(args: argparse.Namespace, config: dict, log: logging.Logger) -> dict:
    registry = None
    if Path(args.registry).exists():
        with open(args.registry, encoding="utf-8") as fh:
            registry = json.load(fh)

    anchor_art = None
    if Path(args.anchor).exists():
        with open(args.anchor, encoding="utf-8") as fh:
            anchor_art = json.load(fh)

    sniper = {}
    if Path(args.sniper).exists():
        with open(args.sniper, encoding="utf-8") as fh:
            sniper = json.load(fh)

    events = list(
        sniper.get("candidates")
        or sniper.get("events")
        or sniper.get("recent_events")
        or []
    )[: args.limit]
    from m8.discovery.hot_path_mirror import resolve_from_sniper_event

    candidates_out: list = []
    cross_mechanic_count = 0
    mirrors_found = 0
    events_seen = 0
    event_to_mirror_ms: list = []
    event_to_quote_ms: list = []

    for ev in events:
        events_seen += 1
        import time

        t0 = time.perf_counter()
        row = resolve_from_sniper_event(
            ev,
            chain=args.chain,
            config=config,
            registry=registry,
            anchor_artifact=anchor_art,
            dry_run=args.dry_run,
        )
        etm = round((time.perf_counter() - t0) * 1000.0, 2)
        event_to_mirror_ms.append(etm)
        row["event_to_mirror_ms"] = etm
        row["source"] = "batch_recent_events"
        routes = row.get("routes_admitted") or []
        if row.get("subgraph_ready"):
            mirrors_found += 1
        else:
            row["reject_reason"] = row.get("reject_reason") or "SUBGRAPH_TOO_SMALL"
        if row.get("cross_mechanic"):
            cross_mechanic_count += 1
        else:
            row.setdefault("reject_reason", "REJECT_NOT_CROSS_MECHANIC")
        candidates_out.append(row)

    w3 = None
    rpc_url = None
    rpc_provider = None
    if args.quote and not args.dry_run:
        from m8.discovery.hot_path_common import setup_quote_rpc
        from m8.discovery.hot_path_focused_quote import focused_quote_cycles

        w3, rpc_url, rpc_provider = setup_quote_rpc(args.chain)

        for c in candidates_out:
            routes = c.get("routes_admitted") or []
            if not c.get("subgraph_ready"):
                continue
            import time

            qt0 = time.perf_counter()
            qb = focused_quote_cycles(
                routes,
                w3=w3,
                rpc_url=rpc_url,
                quote_backend="raw_http",
                cycle_lengths=(2, 3, 4),
                cycle_length_caps={2: 8, 3: 12, 4: 6},
                config_path=args.config,
                honeypot_strict_evidence=args.honeypot_strict_evidence,
            )
            etq = round((time.perf_counter() - qt0) * 1000.0, 2)
            event_to_quote_ms.append(etq)
            c["event_to_quote_ms"] = etq
            c["focused_quote"] = {
                "focused_quote_latency_ms": qb.get("focused_quote_latency_ms"),
                "cycles_found": qb.get("cycles_found"),
                "cycles_2leg_found": qb.get("cycles_2leg_found"),
                "cycles_positive_gross": qb.get("cycles_positive_gross"),
                "cycles_positive_gross_evidence": qb.get(
                    "cycles_positive_gross_evidence", 0
                ),
            }

    def _p50(vals: list) -> float | None:
        if not vals:
            return None
        s = sorted(vals)
        return s[len(s) // 2]

    multi_venue = 0
    if registry:
        multi_venue = sum(
            1
            for t in (registry.get("tokens") or {}).values()
            if len({v.get("dex") for v in (t.get("venues") or {}).values()}) >= 2
        )

    from m8.discovery.hot_path_common import (
        bridge_shadow_acceptance_from_candidates,
        build_reject_reason_histogram,
        honeypot_evidence_policy,
        merge_expansion_reject_histogram,
        merge_per_dex_breakdown,
    )

    per_dex = merge_per_dex_breakdown(candidates_out)
    subgraph_acceptance = bridge_shadow_acceptance_from_candidates(candidates_out)

    payload = {
        "schema_version": "m8_hot_path_v1",
        "generated_at_utc": datetime.now(tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "mode": "batch_recent_events",
        "chain": args.chain,
        "hot_path_events_seen": events_seen,
        "hot_path_mirrors_found": mirrors_found,
        "hot_path_cross_mechanic_candidates": cross_mechanic_count,
        "registry_multi_venue_tokens": multi_venue,
        "event_to_mirror_ms_p50": _p50(event_to_mirror_ms),
        "event_to_quote_ms_p50": _p50(event_to_quote_ms),
        "existence_blocker": (
            "M8_2_TOKEN_NEIGHBORHOOD_EXPANSION_MISSING"
            if not subgraph_acceptance.get("ready_for_bridge_shadow")
            else None
        ),
        "acceptance": {
            "hot_path_cross_mechanic_candidates_gt_0": cross_mechanic_count > 0,
            "registry_multi_venue_tokens_gte_2": multi_venue >= 2,
            **subgraph_acceptance,
        },
        "reject_reason_histogram": build_reject_reason_histogram(candidates_out),
        "expansion_reject_histogram": merge_expansion_reject_histogram(candidates_out),
        **per_dex,
        "honeypot_evidence": honeypot_evidence_policy(
            strict_requested=args.honeypot_strict_evidence
        ),
        "candidates": candidates_out,
    }
    if rpc_provider:
        payload["quote_rpc_provider"] = rpc_provider
    return payload


def main() -> int:
    args = _parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    log = logging.getLogger("m8_hot_path_runner")

    import yaml

    with open(args.config, encoding="utf-8") as fh:
        config = yaml.safe_load(fh)

    if args.live_ws:
        from m8.discovery.hot_path_ws import run_live_ws_session

        payload = run_live_ws_session(
            chain=args.chain,
            config=config,
            duration_minutes=args.duration_minutes,
            registry_path=args.registry,
            anchor_path=args.anchor,
            dry_run=args.dry_run,
            run_quote=args.quote,
            config_path=args.config,
            honeypot_strict_evidence=args.honeypot_strict_evidence,
        )
    else:
        payload = _run_batch(args, config, log)

    out = Path(args.output)
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
    log.info(
        "Wrote %s mode=%s events_seen=%s cross_mech=%s multi_venue=%s mirror_p50=%s",
        out,
        payload.get("mode"),
        payload.get("hot_path_events_seen"),
        payload.get("hot_path_cross_mechanic_candidates"),
        payload.get("registry_multi_venue_tokens"),
        payload.get("event_to_mirror_ms_p50"),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
