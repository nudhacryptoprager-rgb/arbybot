# PATH: strategy/scan_universe.py
"""
Scan universe resolution — resolves which pairs to quote before scanning.

Extracted from run_scan_real.py (R28.28) to separate universe/discovery logic
from scan orchestration.

Handles: hot_requote cache, discovery_runtime, intent, config fallback,
strategy_mode assignment, and hot_pairs cache writing.
"""

import json
import logging
import os
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List, Optional, Tuple

from config.pairs import load_pairs
from core.json_io import atomic_write_json, read_json

logger = logging.getLogger("scan_universe")

# Sentinel value: effectively uncapped while remaining an int
_UNCAPPED = 999_999


def _count_cross_dex_pairs(pair_dicts: List[Dict[str, Any]]) -> int:
    """Count cached pairs that still have >=2 distinct DEXes in pool_info."""
    cross_dex = 0
    for pair_dict in pair_dicts:
        dexes = {
            entry.get("dex")
            for entry in (pair_dict.get("pool_info") or [])
            if entry.get("dex")
        }
        if len(dexes) >= 2:
            cross_dex += 1
    return cross_dex


def _restore_discovery_runtime_from_hot_cache(
    hot_data: Dict[str, Any],
    hot_pair_dicts: List[Dict[str, Any]],
) -> Tuple[List[Any], Optional[Any], Optional[Dict[str, Any]]]:
    """Restore minimal discovery_runtime observability from hot cache metadata.

    Hot re-quotes should not erase the fact that the active universe was originally
    resolved via discovery_runtime. Without this, later funnel artifacts misleadingly
    report cross_dex_pairs_count=0 during hot cycles even when the cached universe
    came from multi-DEX discovery.
    """
    origin_universe = hot_data.get("origin_universe_source") or hot_data.get("universe_source")
    if origin_universe != "discovery_runtime":
        return [], None, None

    from discovery.runtime import RuntimeStats

    cross_dex_pairs = hot_data.get("cross_dex_pairs_count")
    if cross_dex_pairs is None:
        cross_dex_pairs = _count_cross_dex_pairs(hot_pair_dicts)

    pairs_resolved = hot_data.get("discovery_runtime_pairs_count", len(hot_pair_dicts))
    pools_resolved = hot_data.get("discovery_runtime_pools_resolved")
    if pools_resolved is None:
        pools_resolved = sum(len(pair_dict.get("pool_info") or []) for pair_dict in hot_pair_dicts)

    resolved_pairs: List[Any] = []
    for pair_dict in hot_pair_dicts:
        display_name = pair_dict.get("display_name") or f"{pair_dict.get('token_in')}/{pair_dict.get('token_out')}"
        for pool_info in (pair_dict.get("pool_info") or []):
            resolved_pairs.append(
                SimpleNamespace(
                    display_name=display_name,
                    dex=pool_info.get("dex"),
                    fee=pool_info.get("fee"),
                    pool_address=pool_info.get("address"),
                )
            )

    runtime_stats = RuntimeStats(
        enabled=True,
        pairs_evaluated=pairs_resolved,
        pairs_resolved=pairs_resolved,
        pools_resolved=pools_resolved,
        pools_from_cache=pools_resolved,
        pools_from_rpc=0,
        rpc_calls=0,
        cross_dex_pairs_count=cross_dex_pairs,
    )
    runtime_payload = runtime_stats.to_dict()
    runtime_payload["universe_active"] = True
    runtime_payload["from_hot_cache"] = True

    return resolved_pairs, runtime_stats, runtime_payload


def resolve_universe(
    config: Dict[str, Any],
    chain_key: str,
    dexes_list: List[str],
    run_kind: str,
    cap_switches: Dict[str, bool],
) -> Dict[str, Any]:
    """Resolve the scan universe (pairs to quote) based on config.

    Returns a dict with keys:
        pairs_list: resolved PairConfig list (or None for config-default)
        discovery_runtime_resolved: list of RuntimePair objects
        discovery_runtime_stats: RuntimeStats object or None
        stats_updates: dict of keys to merge into scan stats
    """
    universe_source = config.get("universe_source", "config")
    use_intent = (universe_source == "intent")
    force_intent = (universe_source in ("intent_verified", "intent_forced"))
    use_discovery_runtime = (universe_source == "discovery_runtime")

    # R27.3: Forbid intent/intent_forced for NORMAL/COVERAGE runs (no on-chain verify)
    if universe_source in ("intent", "intent_forced") and run_kind in ("NORMAL", "COVERAGE"):
        raise RuntimeError(
            f"universe_source='{universe_source}' is forbidden for run_kind={run_kind}. "
            "Intent-based universes lack on-chain verification. "
            "Use 'config' or 'discovery_runtime'."
        )

    discovery_runtime_resolved: List[Any] = []
    discovery_runtime_stats = None
    pairs_list = None
    stats_updates: Dict[str, Any] = {}

    # R28.11: Hot re-quote mode — skip discovery, reuse cached pairs
    _hot_pairs_file = os.environ.get("ARBY_HOT_PAIRS_FILE")
    if _hot_pairs_file and Path(_hot_pairs_file).is_file():
        try:
            from config.pairs import PairConfig
            _hot_data = read_json(_hot_pairs_file)
            _hot_pair_dicts = _hot_data.get("pairs", [])
            pairs_list = [PairConfig.from_dict(d) for d in _hot_pair_dicts]
            restored_pairs, restored_stats, restored_payload = _restore_discovery_runtime_from_hot_cache(
                _hot_data,
                _hot_pair_dicts,
            )
            if restored_pairs:
                discovery_runtime_resolved = restored_pairs
            if restored_stats is not None:
                discovery_runtime_stats = restored_stats
            logger.info(
                "HOT_REQUOTE: loaded %d cached pairs from %s (skipping discovery)",
                len(pairs_list), _hot_pairs_file,
            )
            stats_updates["universe_source"] = "hot_requote"
            stats_updates["scan_mode"] = "hot"
            stats_updates["hot_pairs_file"] = _hot_pairs_file
            stats_updates["hot_pairs_count"] = len(pairs_list)
            stats_updates["hot_pairs_origin_universe_source"] = (
                _hot_data.get("origin_universe_source") or _hot_data.get("universe_source")
            )
            if restored_payload is not None:
                stats_updates["discovery_runtime"] = restored_payload
        except Exception as hp_err:
            logger.warning(
                "HOT_REQUOTE: failed to load %s, falling back to full discovery: %s",
                _hot_pairs_file, hp_err,
            )
            pairs_list = None

    if pairs_list is None and use_discovery_runtime:
        try:
            from discovery.runtime import resolve_runtime_pairs, runtime_pairs_to_pair_configs

            max_pairs = config.get("discovery_runtime_max_pairs", 20)
            # R28.27: When uncapped, remove discovery cap
            if cap_switches.get("uncap_discovery_max_pairs"):
                logger.info("CAP_ISOLATION: discovery_runtime_max_pairs uncapped (was %d)", max_pairs)
                max_pairs = _UNCAPPED
            require_cross_dex = config.get("require_cross_dex", False)
            excluded_hints = config.get("excluded_pair_hints") or []
            discovery_runtime_resolved, discovery_runtime_stats = resolve_runtime_pairs(
                chain=chain_key,
                dexes=dexes_list if dexes_list else None,
                max_pairs=max_pairs,
                require_cross_dex=require_cross_dex,
                excluded_pair_hints=excluded_hints,
            )
            pairs_list = runtime_pairs_to_pair_configs(discovery_runtime_resolved)

            logger.info(
                "Using discovery_runtime universe (%d pools resolved -> %d unique pairs for quoting)",
                len(discovery_runtime_resolved),
                len(pairs_list),
            )
            stats_updates["universe_source"] = "discovery_runtime"
            stats_updates["discovery_runtime_pairs_count"] = len(pairs_list)
            stats_updates["discovery_runtime_pools_resolved"] = len(discovery_runtime_resolved)
            if discovery_runtime_stats:
                stats_updates["discovery_runtime"] = discovery_runtime_stats.to_dict()
        except Exception as dr_err:
            allow_fallback = config.get("discovery_runtime_allow_fallback", False)
            if allow_fallback:
                logger.warning(
                    "discovery_runtime failed, falling back to config (allowed by config): %s", dr_err,
                )
                pairs_list = load_pairs(chain_key, config, use_intent=False, force_intent=False)
                stats_updates["universe_source"] = "config (discovery_runtime fallback)"
                stats_updates["discovery_runtime_error"] = str(dr_err)
            else:
                logger.error("discovery_runtime failed (strict mode, no fallback): %s", dr_err)
                stats_updates["universe_source"] = "discovery_runtime_failed"
                stats_updates["discovery_runtime_error"] = str(dr_err)
                raise RuntimeError(
                    f"discovery_runtime resolution failed and fallback is disabled: {dr_err}"
                ) from dr_err
    elif pairs_list is None and force_intent:
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
        logger.info(
            "Using intent.txt universe FORCED (universe_source=%s -> intent_forced, %d pairs)",
            universe_source, len(pairs_list),
        )
        stats_updates["universe_source"] = "intent_forced"
        stats_updates["intent_pairs_count"] = len(pairs_list)
        stats_updates["intent_on_chain_verified"] = False
    elif pairs_list is None and use_intent:
        pairs_list = load_pairs(chain_key, config, use_intent=use_intent, force_intent=force_intent)
        logger.info("Using intent.txt universe (universe_source=intent)")
        stats_updates["universe_source"] = "intent"
    elif pairs_list is None:
        pairs_list = None
        logger.debug("Using config pairs (universe_source=config)")
        stats_updates["universe_source"] = "config"

    # R27.3: Encode strategy mode for artifact observability
    _us = stats_updates.get("universe_source", "config")
    if _us == "hot_requote":
        stats_updates["strategy_mode"] = "HOT_REQUOTE"
    elif _us == "discovery_runtime":
        stats_updates["strategy_mode"] = "DYNAMIC_VERIFIED"
    elif _us in ("intent", "intent_forced"):
        stats_updates["strategy_mode"] = "BOOTSTRAP"
    elif _us.startswith("config"):
        stats_updates["strategy_mode"] = "TRUTH_PROBE"
    else:
        stats_updates["strategy_mode"] = "UNKNOWN"
    stats_updates["same_dex_only"] = not config.get("require_cross_dex", True)

    # R39o: Hard clamp — restrict pairs to include_pairs whitelist when configured
    _include_pairs = config.get("include_pairs")
    if _include_pairs and pairs_list:
        _allowed = set(_include_pairs)
        _before = len(pairs_list)
        pairs_list = [p for p in pairs_list if p.display_name in _allowed]
        _after = len(pairs_list)
        if _after < _before:
            logger.info(
                "INCLUDE_PAIRS_CLAMP: %d -> %d pairs (whitelist: %s)",
                _before, _after, sorted(_allowed),
            )
        stats_updates["include_pairs_clamp"] = {"before": _before, "after": _after}
        # R39p: Recalculate downstream counters after clamp so artifacts are consistent
        stats_updates["discovery_runtime_pairs_count"] = _after
        _disc = stats_updates.get("discovery_runtime") or {}
        if _disc:
            _disc["cross_dex_pairs_count"] = _after
            _disc["pairs_resolved"] = _after
            stats_updates["discovery_runtime"] = _disc

    # R28.11: Save hot pairs cache after full discovery
    if pairs_list and _us != "hot_requote":
        _write_hot_pairs_cache(chain_key, _us, pairs_list, stats_updates=stats_updates)

    return {
        "pairs_list": pairs_list,
        "discovery_runtime_resolved": discovery_runtime_resolved,
        "discovery_runtime_stats": discovery_runtime_stats,
        "stats_updates": stats_updates,
    }


def _write_hot_pairs_cache(
    chain_key: str,
    universe_source: str,
    pairs_list: list,
    stats_updates: Optional[Dict[str, Any]] = None,
) -> None:
    """Write hot pairs cache for subsequent hot re-quote cycles."""
    try:
        _cache_dir = Path("data") / "cache"
        _cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path = _cache_dir / f"hot_pairs_{chain_key}.json"
        _cache_data = {
            "schema": "hot_pairs_cache:v1.0",
            "chain": chain_key,
            "universe_source": universe_source,
            "origin_universe_source": universe_source,
            "pairs_count": len(pairs_list),
            "pairs": [p.to_dict() if hasattr(p, "to_dict") else p for p in pairs_list],
        }
        if stats_updates:
            _cache_data["strategy_mode"] = stats_updates.get("strategy_mode")
            _cache_data["same_dex_only"] = stats_updates.get("same_dex_only")
            _cache_data["discovery_runtime_pairs_count"] = stats_updates.get(
                "discovery_runtime_pairs_count",
                len(pairs_list),
            )
            _cache_data["discovery_runtime_pools_resolved"] = stats_updates.get(
                "discovery_runtime_pools_resolved",
                0,
            )
            _disc = stats_updates.get("discovery_runtime") or {}
            _cache_data["cross_dex_pairs_count"] = _disc.get("cross_dex_pairs_count", 0)
        atomic_write_json(_cache_path, _cache_data)
        logger.debug("Hot pairs cache written: %s (%d pairs)", _cache_path, len(pairs_list))
    except Exception as _cache_err:
        logger.debug("Hot pairs cache write skipped: %s", _cache_err)
