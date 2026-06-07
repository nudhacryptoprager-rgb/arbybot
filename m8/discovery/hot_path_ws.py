"""Live WebSocket hot-path: new-pool event -> mirror-resolve -> focused quote."""
from __future__ import annotations

import copy
import logging
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

from discovery.new_pool_listener import FactoryConfig, NewPoolEvent, parse_raw_log
from m8.discovery.anchor_registry import build_anchor_maps, symbol_for_address
from m8.discovery.hot_path_mirror import (
    candidate_tokens_from_event,
    resolve_best_neighborhood_for_event,
)
from m8.discovery.pending_pair_registry import (
    DEFAULT_REGISTRY_PATH,
    load_registry,
    save_registry,
    update_registry,
)
from m8.discovery.token_watchlist import (
    DEFAULT_WATCHLIST_PATH,
    load_watchlist,
    metrics_summary,
    run_active_second_pool_scan,
    save_watchlist,
    scan_due,
    upsert_watch_entry_from_event,
)

logger = logging.getLogger(__name__)


def enrich_event_dict(
    event: NewPoolEvent,
    registry: Optional[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """NewPoolEvent -> dict with symbols for anchor split + registry update."""
    d = event.to_dict()
    reg_tokens = (registry or {}).get("tokens") or {}
    addr_to_sym, _ = build_anchor_maps(config or {})

    def _sym(addr: str) -> str:
        low = addr.lower()
        cfg_sym = symbol_for_address(low, addr_to_sym)
        if cfg_sym:
            return cfg_sym
        tok = reg_tokens.get(low) or {}
        return str(tok.get("symbol") or "")

    d["token0_symbol"] = _sym(d.get("token0", "")) or d.get("token0", "")[:10]
    d["token1_symbol"] = _sym(d.get("token1", "")) or d.get("token1", "")[:10]
    d["dex_id"] = d.get("dex", "")
    d["pool_address"] = d.get("pool", "")
    return d


class HotPathProcessor:
    """Per-event hot-path handler (thread-safe)."""

    def __init__(
        self,
        *,
        chain: str,
        config: Dict[str, Any],
        registry: Optional[Dict[str, Any]],
        anchor_artifact: Optional[Dict[str, Any]],
        registry_path: str = DEFAULT_REGISTRY_PATH,
        dry_run: bool = False,
        run_quote: bool = False,
        w3: Any = None,
        rpc_url: Optional[str] = None,
        config_path: str = "config/exotic_base_anchor.yaml",
        persist_registry: bool = True,
        honeypot_strict_evidence: bool = False,
        active_scan: bool = True,
        watchlist_path: str = DEFAULT_WATCHLIST_PATH,
    ) -> None:
        self.chain = chain
        self.config = config
        self.registry = copy.deepcopy(registry) if registry else load_registry(registry_path)
        self.anchor_artifact = anchor_artifact
        self.registry_path = registry_path
        self.dry_run = dry_run
        self.run_quote = run_quote and not dry_run
        self.active_scan = active_scan and not dry_run
        self.watchlist_path = watchlist_path
        self.watchlist = load_watchlist(watchlist_path)
        self.w3 = w3
        self.rpc_url = rpc_url
        self.config_path = config_path
        self.persist_registry = persist_registry
        self.honeypot_strict_evidence = honeypot_strict_evidence
        self._lock = threading.Lock()
        self._seen_ids: Set[str] = set()
        self.hot_path_events_seen = 0
        self.hot_path_mirrors_found = 0
        self.hot_path_cross_mechanic_candidates = 0
        self._event_to_mirror_ms: List[float] = []
        self._event_to_quote_ms: List[float] = []
        self._active_scan_runs = 0
        self._transition_triggers = 0
        self.candidates: List[Dict[str, Any]] = []

    def _ensure_scan_w3(self) -> bool:
        if self.w3 is not None:
            return True
        if not self.active_scan and not self.run_quote:
            return False
        try:
            from m8.discovery.hot_path_common import setup_quote_rpc

            self.w3, self.rpc_url, _ = setup_quote_rpc(self.chain)
            return True
        except Exception as exc:
            logger.warning("hot_path RPC setup failed: %s", exc)
            return False

    def handle_raw_log(self, cfg: FactoryConfig, raw_log: Any) -> None:
        event = parse_raw_log(raw_log, cfg)
        if event is None:
            return
        with self._lock:
            if event.event_id in self._seen_ids:
                return
            self._seen_ids.add(event.event_id)
        self._process_parsed_event(event)

    def _process_parsed_event(self, event: NewPoolEvent) -> None:
        event_ts = time.time()
        event_dict = enrich_event_dict(event, self.registry, self.config)
        event_candidates = candidate_tokens_from_event(event_dict, self.config)
        if not event_candidates:
            update_registry(self.registry, [event_dict], now_ts=event_ts)
            self._append_candidate(
                event_dict,
                reject_reason="REJECT_NO_CANDIDATE_TOKEN",
            )
            return

        self.hot_path_events_seen += 1

        transition_triggered = False
        scan_rows: List[Dict[str, Any]] = []
        if self.active_scan:
            for cand in event_candidates:
                entry = upsert_watch_entry_from_event(
                    self.watchlist,
                    event_dict,
                    exotic_address=cand["address"],
                    exotic_symbol=cand.get("symbol") or "",
                    now_ts=event_ts,
                    config=self.config,
                    registry=self.registry,
                )
                if not scan_due(entry, event_ts):
                    continue
                if not self._ensure_scan_w3():
                    continue
                self._active_scan_runs += 1
                scan_result = run_active_second_pool_scan(
                    token_address=cand["address"],
                    entry=entry,
                    chain=self.chain,
                    config=self.config,
                    registry=self.registry,
                    w3=self.w3,
                    watchlist=self.watchlist,
                    now_ts=event_ts,
                )
                scan_rows.append(scan_result)
                if scan_result.get("transition_1_to_2"):
                    self._transition_triggers += 1
                    transition_triggered = True

        focus_cand = event_candidates[0]
        from m8.discovery.token_classify import prior_venue_stats

        prior_pools, prior_dexes = prior_venue_stats(
            self.registry, focus_cand["address"]
        )
        update_registry(self.registry, [event_dict], now_ts=event_ts)

        from m8.discovery.token_classify import annotate_hot_path_row

        mirror_t0 = time.perf_counter()
        mirror_row, resolve_reason = resolve_best_neighborhood_for_event(
            event_dict,
            chain=self.chain,
            config=self.config,
            registry=self.registry,
            anchor_artifact=self.anchor_artifact,
            dry_run=self.dry_run,
        )
        event_to_mirror_ms = round((time.perf_counter() - mirror_t0) * 1000.0, 2)
        self._event_to_mirror_ms.append(event_to_mirror_ms)

        if mirror_row is None:
            self._append_candidate(
                event_dict,
                reject_reason=resolve_reason or "REJECT_NO_CANDIDATE_TOKEN",
            )
            return

        routes = mirror_row.get("routes_admitted") or []
        row = {
            **mirror_row,
            "event_id": event.event_id,
            "event_to_mirror_ms": event_to_mirror_ms,
            "event_candidate_tokens": mirror_row.get("event_candidate_tokens")
            or event_candidates,
            "selected_focus_token": mirror_row.get("selected_focus_token"),
            "selected_focus_reason": mirror_row.get("selected_focus_reason"),
            "dex": event.dex,
            "pool": event.pool,
            "block_number": event.block_number,
            "source": "live_ws",
            "active_scan_ran": bool(scan_rows),
            "active_scan_results": scan_rows,
            "transition_1_to_2": transition_triggered,
        }
        focus_addr = str(
            row.get("selected_focus_token")
            or row.get("exotic_address")
            or focus_cand["address"]
        )
        annotate_hot_path_row(
            row,
            config=self.config,
            registry=self.registry,
            focus_token=focus_addr,
            focus_symbol=str(row.get("exotic_symbol") or focus_cand.get("symbol") or ""),
            now_ts=event_ts,
            event_block=event.block_number,
            prior_pool_count=prior_pools,
            prior_dex_count=prior_dexes,
        )
        subgraph_ready = bool(mirror_row.get("subgraph_ready"))
        if not subgraph_ready:
            if resolve_reason in (
                "TOKEN_NOT_SEEN_ELSEWHERE",
                "CONNECTOR_NOT_FOUND",
                "SUBGRAPH_TOO_SMALL",
            ):
                row["reject_reason"] = resolve_reason
            else:
                hist = mirror_row.get("reject_reason_histogram") or {}
                if hist.get("TOKEN_NOT_SEEN_ELSEWHERE"):
                    row["reject_reason"] = "TOKEN_NOT_SEEN_ELSEWHERE"
                elif hist.get("CONNECTOR_NOT_FOUND"):
                    row["reject_reason"] = "CONNECTOR_NOT_FOUND"
                elif hist.get("SUBGRAPH_TOO_SMALL"):
                    row["reject_reason"] = "SUBGRAPH_TOO_SMALL"
                else:
                    row["reject_reason"] = "SUBGRAPH_TOO_SMALL"
            self.candidates.append(row)
            return

        self.hot_path_mirrors_found += 1
        if mirror_row.get("cross_mechanic"):
            self.hot_path_cross_mechanic_candidates += 1
        else:
            row["reject_reason"] = "REJECT_NOT_CROSS_MECHANIC"

        if self.run_quote and self.w3 is not None:
            from m8.discovery.hot_path_focused_quote import focused_quote_cycles

            quote_t0 = time.perf_counter()
            qb = focused_quote_cycles(
                routes,
                w3=self.w3,
                rpc_url=self.rpc_url,
                quote_backend="raw_http",
                cycle_lengths=(2, 3, 4),
                cycle_length_caps={2: 8, 3: 12, 4: 6},
                config_path=self.config_path,
                honeypot_strict_evidence=self.honeypot_strict_evidence,
            )
            event_to_quote_ms = round((time.perf_counter() - quote_t0) * 1000.0, 2)
            self._event_to_quote_ms.append(event_to_quote_ms)
            row["event_to_quote_ms"] = event_to_quote_ms
            row["focused_quote"] = {
                "focused_quote_latency_ms": qb.get("focused_quote_latency_ms"),
                "cycles_found": qb.get("cycles_found"),
                "cycles_positive_gross": qb.get("cycles_positive_gross"),
                "cycles_positive_gross_evidence": qb.get(
                    "cycles_positive_gross_evidence", 0
                ),
                "cycles_2leg_found": qb.get("cycles_2leg_found", 0),
            }
            if qb.get("cycles_positive_gross_evidence", 0) <= 0 and qb.get(
                "cycles_positive_gross", 0
            ) > 0:
                row["reject_reason"] = "REJECT_HONEYPOT_OR_TAX_FAIL"

        self.candidates.append(row)

    def _append_candidate(self, event_dict: Dict[str, Any], *, reject_reason: str) -> None:
        self.candidates.append(
            {
                "event_id": event_dict.get("event_id"),
                "reject_reason": reject_reason,
                "dex": event_dict.get("dex"),
                "pool": event_dict.get("pool"),
                "source": "live_ws",
            }
        )

    def registry_multi_venue_tokens(self) -> int:
        tokens = self.registry.get("tokens") or {}
        return sum(
            1
            for t in tokens.values()
            if len({v.get("dex") for v in (t.get("venues") or {}).values()}) >= 2
        )

    def finalize(self) -> Dict[str, Any]:
        if self.persist_registry:
            try:
                save_registry(self.registry, self.registry_path)
            except Exception as exc:
                logger.warning("registry save failed: %s", exc)
        try:
            save_watchlist(self.watchlist, self.watchlist_path)
        except Exception as exc:
            logger.warning("watchlist save failed: %s", exc)

        def _p50(vals: List[float]) -> Optional[float]:
            if not vals:
                return None
            s = sorted(vals)
            return s[len(s) // 2]

        from m8.discovery.hot_path_common import (
            bridge_shadow_acceptance_from_candidates,
            build_reject_reason_histogram,
            honeypot_evidence_policy,
            merge_expansion_reject_histogram,
            merge_per_dex_breakdown,
        )
        from m8.discovery.token_classify import (
            build_spread_lifetime_histograms,
            build_token_class_histogram,
        )

        per_dex = merge_per_dex_breakdown(self.candidates)
        subgraph_acceptance = bridge_shadow_acceptance_from_candidates(self.candidates)
        spread_hists = build_spread_lifetime_histograms(self.candidates)

        acceptance = {
            "hot_path_cross_mechanic_candidates_gt_0": self.hot_path_cross_mechanic_candidates
            > 0,
            "registry_multi_venue_tokens_gte_2": self.registry_multi_venue_tokens() >= 2,
            **subgraph_acceptance,
        }
        return {
            "schema_version": "m8_hot_path_live_ws_v1",
            "generated_at_utc": datetime.now(tz=timezone.utc).strftime(
                "%Y-%m-%dT%H:%M:%SZ"
            ),
            "mode": "live_ws",
            "chain": self.chain,
            "hot_path_events_seen": self.hot_path_events_seen,
            "hot_path_mirrors_found": self.hot_path_mirrors_found,
            "hot_path_cross_mechanic_candidates": self.hot_path_cross_mechanic_candidates,
            "registry_multi_venue_tokens": self.registry_multi_venue_tokens(),
            "active_scan_runs": self._active_scan_runs,
            "transition_triggers_1_to_2": self._transition_triggers,
            "phase_1_5": metrics_summary(self.watchlist),
            "watchlist_path": self.watchlist_path,
            "token_class_histogram": build_token_class_histogram(self.candidates),
            **spread_hists,
            "event_to_mirror_ms_p50": _p50(self._event_to_mirror_ms),
            "event_to_quote_ms_p50": _p50(self._event_to_quote_ms),
            "existence_blocker": (
                "M8_2_TOKEN_NEIGHBORHOOD_EXPANSION_MISSING"
                if not subgraph_acceptance.get("ready_for_bridge_shadow")
                else None
            ),
            "acceptance": acceptance,
            "reject_reason_histogram": build_reject_reason_histogram(self.candidates),
            "expansion_reject_histogram": merge_expansion_reject_histogram(
                self.candidates
            ),
            **per_dex,
            "honeypot_evidence": honeypot_evidence_policy(
                strict_requested=self.honeypot_strict_evidence
            ),
            "candidates": self.candidates,
        }


def run_live_ws_session(
    *,
    chain: str,
    config: Dict[str, Any],
    duration_minutes: float,
    registry_path: str = DEFAULT_REGISTRY_PATH,
    anchor_path: Optional[str] = None,
    dry_run: bool = False,
    run_quote: bool = False,
    config_path: str = "config/exotic_base_anchor.yaml",
    honeypot_strict_evidence: bool = False,
    active_scan: bool = True,
    watchlist_path: str = DEFAULT_WATCHLIST_PATH,
) -> Dict[str, Any]:
    """Subscribe to factory logs via WS and run hot-path per candidate event."""
    import os

    from discovery.new_pool_listener import load_factory_config
    from m8.runtime.ws_listener import WSPoolEventListener

    registry = load_registry(registry_path)
    anchor_art = None
    if anchor_path:
        import json
        from pathlib import Path

        p = Path(anchor_path)
        if p.exists():
            with open(p, encoding="utf-8") as fh:
                anchor_art = json.load(fh)

    w3 = None
    rpc_url = None
    rpc_provider = None
    if run_quote and not dry_run:
        from m8.discovery.hot_path_common import setup_quote_rpc

        w3, rpc_url, rpc_provider = setup_quote_rpc(chain)
        logger.info("Hot-path quote RPC: provider=%s", rpc_provider)

    ws_url = os.environ.get(f"{chain.upper()}_WSS") or os.environ.get("BASE_WSS")
    if not ws_url:
        try:
            from core.rpc_urls import resolve_rpc_ws

            ws_url, _, _ = resolve_rpc_ws(network=chain, env=dict(os.environ))
        except Exception:
            ws_url = None
    if not ws_url:
        raise RuntimeError(f"No WebSocket URL for chain={chain}")

    configs = load_factory_config(chain_filter=chain)
    processor = HotPathProcessor(
        chain=chain,
        config=config,
        registry=registry,
        anchor_artifact=anchor_art,
        registry_path=registry_path,
        dry_run=dry_run,
        run_quote=run_quote,
        w3=w3,
        rpc_url=rpc_url,
        config_path=config_path,
        honeypot_strict_evidence=honeypot_strict_evidence,
        active_scan=active_scan,
        watchlist_path=watchlist_path,
    )

    listener = WSPoolEventListener(
        ws_url=ws_url,
        configs=configs,
        on_event=processor.handle_raw_log,
    )
    thread = threading.Thread(target=listener.run, daemon=True, name="hot-path-ws")
    thread.start()
    logger.info(
        "Live WS hot-path started: duration_minutes=%.1f factories=%d",
        duration_minutes,
        len(configs),
    )
    deadline = time.monotonic() + duration_minutes * 60.0
    try:
        while time.monotonic() < deadline:
            time.sleep(1.0)
    except KeyboardInterrupt:
        logger.info("Live WS hot-path interrupted")
    finally:
        listener.stop()
        thread.join(timeout=5.0)

    out = processor.finalize()
    if rpc_provider:
        out["quote_rpc_provider"] = rpc_provider
    return out
