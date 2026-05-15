"""M8 Phase 2 — Mirror data seeder.

Pre-populates the :class:`~strategy.entry_candidate_enricher.EntryCandidateEnricher`
``seen_pairs`` registry by replaying historical pool-creation events from multiple
DEXes *before* the live gate starts.

This enables mirror-spread estimation for the very first new-pool events seen in
the live stream, instead of waiting until the same token pair appears on a second
DEX during the live session.

Strategy
--------
For each factory in *configs* that has ``verification_from_block`` / ``verification_to_block``
set (the same block ranges used by the startup self-test), replay all pool-creation
events in that range through the enricher.

If no verification range is configured, skip that factory (don't generate extra RPC
load against uncharted block ranges).

Design
------
- Non-blocking: any RPC error per factory is caught and logged; seeding continues
  for remaining factories.
- The enricher is mutated in-place (``seen_pairs`` grows).
- The function returns a summary dict for logging only.
- Does NOT acquire phase2_lock; caller holds the lock before invoking this function
  (it is called once from main() during startup, before the WS thread starts).
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from discovery.new_pool_listener import FactoryConfig
    from strategy.entry_candidate_enricher import EntryCandidateEnricher


def seed_mirror_data(
    enricher: "EntryCandidateEnricher",
    w3: Any,
    configs: List["FactoryConfig"],
    *,
    lookback_blocks: int = 2000,
) -> Dict[str, Any]:
    """Replay historical pool events to seed the enricher ``seen_pairs`` registry.

    Parameters
    ----------
    enricher:
        Live enricher instance.  Its ``seen_pairs`` registry is updated in-place.
    w3:
        Initialized ``web3.Web3`` HTTP instance.
    configs:
        List of :class:`~discovery.new_pool_listener.FactoryConfig` objects.  Only
        factories with ``verification_from_block`` / ``verification_to_block`` are
        probed.
    lookback_blocks:
        Fallback lookback window when no verification range is configured.
        Set to ``0`` to disable the fallback and only use verification ranges.

    Returns
    -------
    Summary dict with keys ``seeded_pairs``, ``events_fetched``, ``rpc_errors``,
    ``elapsed_s``, ``per_dex``.
    """
    from discovery.new_pool_listener import parse_raw_log

    t0 = time.monotonic()
    total_fetched = 0
    total_rpc_errors = 0
    seeded_pairs_before = sum(len(v) for v in enricher._seen_pairs.values())
    per_dex: Dict[str, Dict[str, Any]] = {}

    for cfg in configs:
        dex_name = cfg.dex

        # Determine block range
        if cfg.verification_from_block is not None and cfg.verification_to_block is not None:
            from_block = cfg.verification_from_block
            to_block = cfg.verification_to_block
            range_source = "verification_range"
        elif lookback_blocks > 0:
            try:
                current = int(w3.eth.block_number)
                from_block = max(0, current - lookback_blocks)
                to_block = current
                range_source = f"lookback_{lookback_blocks}"
            except Exception as exc:
                per_dex[dex_name] = {"status": "SKIP_BLOCK_NUMBER_ERR", "error": str(exc)[:60]}
                total_rpc_errors += 1
                continue
        else:
            per_dex[dex_name] = {"status": "SKIP_NO_RANGE"}
            continue

        # Fetch logs
        try:
            params: Dict[str, Any] = {
                "fromBlock": from_block,
                "toBlock": to_block,
                "address": w3.to_checksum_address(cfg.factory),
            }
            if cfg.topic0:
                params["topics"] = [cfg.topic0]
            raw_logs = list(w3.eth.get_logs(params))
        except Exception as exc:
            per_dex[dex_name] = {
                "status": "RPC_ERROR",
                "error": str(exc)[:80],
                "range_source": range_source,
            }
            total_rpc_errors += 1
            continue

        # Parse and enrich
        enriched = 0
        parse_ok = 0
        for raw_log in raw_logs:
            event = parse_raw_log(raw_log, cfg)
            if event is None:
                continue
            parse_ok += 1
            total_fetched += 1
            try:
                enricher.enrich(event)
                enriched += 1
            except Exception:
                pass

        per_dex[dex_name] = {
            "status": "OK",
            "raw_logs": len(raw_logs),
            "parse_ok": parse_ok,
            "enriched": enriched,
            "from_block": from_block,
            "to_block": to_block,
            "range_source": range_source,
        }

    seeded_pairs_after = sum(len(v) for v in enricher._seen_pairs.values())
    new_pair_registrations = seeded_pairs_after - seeded_pairs_before

    return {
        "seeded_pairs": new_pair_registrations,
        "unique_pair_keys": len(enricher._seen_pairs),
        "events_fetched": total_fetched,
        "rpc_errors": total_rpc_errors,
        "elapsed_s": round(time.monotonic() - t0, 2),
        "per_dex": per_dex,
    }
