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
from typing import Any, Dict, List, Optional, Tuple

from config.pairs import load_pairs

logger = logging.getLogger("scan_universe")

# Sentinel value: effectively uncapped while remaining an int
_UNCAPPED = 999_999


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
            with open(_hot_pairs_file, "r", encoding="utf-8") as _hpf:
                _hot_data = json.load(_hpf)
            _hot_pair_dicts = _hot_data.get("pairs", [])
            pairs_list = [PairConfig.from_dict(d) for d in _hot_pair_dicts]
            logger.info(
                "HOT_REQUOTE: loaded %d cached pairs from %s (skipping discovery)",
                len(pairs_list), _hot_pairs_file,
            )
            stats_updates["universe_source"] = "hot_requote"
            stats_updates["scan_mode"] = "hot"
            stats_updates["hot_pairs_file"] = _hot_pairs_file
            stats_updates["hot_pairs_count"] = len(pairs_list)
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

    # R28.11: Save hot pairs cache after full discovery
    if pairs_list and _us != "hot_requote":
        _write_hot_pairs_cache(chain_key, _us, pairs_list)

    return {
        "pairs_list": pairs_list,
        "discovery_runtime_resolved": discovery_runtime_resolved,
        "discovery_runtime_stats": discovery_runtime_stats,
        "stats_updates": stats_updates,
    }


def _write_hot_pairs_cache(chain_key: str, universe_source: str, pairs_list: list) -> None:
    """Write hot pairs cache for subsequent hot re-quote cycles."""
    try:
        _cache_dir = Path("data") / "cache"
        _cache_dir.mkdir(parents=True, exist_ok=True)
        _cache_path = _cache_dir / f"hot_pairs_{chain_key}.json"
        _cache_data = {
            "schema": "hot_pairs_cache:v1.0",
            "chain": chain_key,
            "universe_source": universe_source,
            "pairs_count": len(pairs_list),
            "pairs": [p.to_dict() if hasattr(p, "to_dict") else p for p in pairs_list],
        }
        with open(_cache_path, "w", encoding="utf-8") as _cpf:
            json.dump(_cache_data, _cpf, indent=2)
        logger.debug("Hot pairs cache written: %s (%d pairs)", _cache_path, len(pairs_list))
    except Exception as _cache_err:
        logger.debug("Hot pairs cache write skipped: %s", _cache_err)
