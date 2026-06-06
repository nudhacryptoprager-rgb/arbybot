"""Focused 2-leg/3-leg quotes for hot-path mirror routes (no full-graph rebuild)."""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Tuple

import json
import tempfile
from pathlib import Path

from m9.graph_arb.builder import build_graph_from_inventory
from m9.graph_arb.finder import find_cycles
from m9.graph_arb.models import GraphCycle

DEFAULT_CYCLE_LENGTH_CAPS: Dict[int, int] = {2: 8, 3: 12, 4: 6}


def _routes_to_inventory(
    routes: List[Dict[str, Any]],
    *,
    chain: str = "base",
) -> Dict[str, Any]:
    active = []
    for r in routes:
        row = dict(r)
        row.setdefault("status", "active")
        row.setdefault("chain", chain)
        active.append(row)
    return {"chain": chain, "active_routes": active}


def find_focused_cycles(
    routes: List[Dict[str, Any]],
    *,
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    cycle_length_caps: Optional[Dict[int, int]] = None,
    chain: str = "base",
    config_path: str = "config/exotic_base_anchor.yaml",
) -> List[GraphCycle]:
    """Build minimal graph from mirror routes and enumerate short cycles only."""
    if len(routes) < 2:
        return []
    inv = _routes_to_inventory(routes, chain=chain)
    tmp = Path(tempfile.gettempdir()) / "m8_hot_path_focus_inventory.json"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(inv, fh)
    adjacency = build_graph_from_inventory(
        str(tmp),
        config_path=config_path,
        require_factory_verified=False,
        lane="discovery",
    )
    caps = cycle_length_caps or DEFAULT_CYCLE_LENGTH_CAPS
    all_cycles: List[GraphCycle] = []
    for length in cycle_lengths:
        cap = int(caps.get(length, 50))
        all_cycles.extend(
            find_cycles(adjacency, cycle_lengths=(length,), max_cycles=cap)
        )
    return all_cycles


def _exotic_addrs_from_cycle(cycle: GraphCycle) -> List[str]:
    anchors = frozenset({"USDC", "USDBC", "USDbC", "DAI", "WETH", "ETH"})
    out: List[str] = []
    for e in cycle.edges:
        if e.token_in_sym.upper() not in anchors and e.token_in_addr:
            out.append(e.token_in_addr.lower())
        if e.token_out_sym.upper() not in anchors and e.token_out_addr:
            out.append(e.token_out_addr.lower())
    return list(dict.fromkeys(out))


def focused_quote_cycles(
    routes: List[Dict[str, Any]],
    *,
    w3: Any,
    sizes_usd: Tuple[float, ...] = (10.0, 100.0),
    cycle_lengths: Tuple[int, ...] = (2, 3, 4),
    cycle_length_caps: Optional[Dict[int, int]] = None,
    quote_backend: str = "raw_http",
    rpc_url: Optional[str] = None,
    max_cycles: int = 20,
    config_path: str = "config/exotic_base_anchor.yaml",
    honeypot_strict_evidence: bool = False,
) -> Dict[str, Any]:
    """Quote focused cycles for hot-path candidates."""
    from m9.graph_arb.quoter import schedule_cycle_quotes

    from monitoring.sniper_honeypot import positive_gross_counts_as_evidence

    t0 = time.perf_counter()
    cycles = find_focused_cycles(
        routes,
        cycle_lengths=cycle_lengths,
        cycle_length_caps=cycle_length_caps,
        config_path=config_path,
    )
    cycles_2leg = [c for c in cycles if len(c.edges) == 2]
    ordered = cycles_2leg + [c for c in cycles if len(c.edges) != 2]
    ordered = ordered[:max_cycles]
    if not ordered:
        return {
            "focused_quote_latency_ms": round((time.perf_counter() - t0) * 1000.0, 2),
            "cycles_found": 0,
            "cycles_2leg_found": 0,
            "cycles_quoted": 0,
            "cycles_positive_gross": 0,
            "cycles_positive_gross_evidence": 0,
            "results": [],
        }
    results = schedule_cycle_quotes(
        ordered,
        w3=w3,
        sizes_usd=sizes_usd,
        quote_backend=quote_backend,
        rpc_url=rpc_url,
        max_workers=1,
    )
    latency_ms = round((time.perf_counter() - t0) * 1000.0, 2)
    positive = sum(1 for qr in results if qr.gross_bps > 0)
    positive_evidence = sum(
        1
        for qr in results
        if qr.gross_bps > 0
        and positive_gross_counts_as_evidence(
            _exotic_addrs_from_cycle(qr.cycle),
            strict=honeypot_strict_evidence,
        )
    )
    return {
        "focused_quote_latency_ms": latency_ms,
        "cycles_found": len(ordered),
        "cycles_2leg_found": len(cycles_2leg),
        "cycles_quoted": len(results),
        "cycles_positive_gross": positive,
        "cycles_positive_gross_evidence": positive_evidence,
        "results": results,
    }
