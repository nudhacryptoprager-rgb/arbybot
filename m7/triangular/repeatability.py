"""
M7 triangular — Blocker and regime repeatability aggregation across runs.

Contains build_blocker_repeatability and build_regime_repeatability_summary
for temporal stability analysis of triangular blocker classes and regime
classifications across multiple measured runs.

Extracted from scripts/m7a_enumerate_cycles.py during M7.R1 structural refactor.
"""

from __future__ import annotations

import json
import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from m7.triangular.verdicts import (
    TWO_LEG_BASELINE_NET_BPS,
    classify_regime_bucket,
)

logger = logging.getLogger("m7.triangular.repeatability")


# ---------------------------------------------------------------------------
# Blocker repeatability — temporal stability of blocker classes across blocks
# ---------------------------------------------------------------------------

def build_blocker_repeatability(
    artifact_paths: List[str],
) -> Dict[str, Any]:
    """Aggregate multiple blocker summaries into a temporal repeatability report."""
    snapshots: List[Dict[str, Any]] = []

    for path_str in artifact_paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Artifact not found: %s", path)
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bs = data.get("blocker_summary")
        if not bs or "error" in bs:
            logger.warning("No valid blocker_summary in %s", path)
            continue
        block = data.get("measured", {}).get("block_number")
        snapshots.append({
            "artifact": path.name,
            "block": block,
            "universe_profile": data.get("universe_profile", "narrow_7"),
            "best_route_gross_bps": bs["best_route_gross_bps"],
            "best_route_gas_bps": bs["best_route_gas_bps"],
            "best_route_total_fee_bps": bs["best_route_total_fee_bps"],
            "best_route_net_bps": bs["best_route_net_bps"],
            "best_route_best_size_usd": bs["best_route_best_size_usd"],
            "route_failure_rate": bs["route_failure_rate"],
            "token_triple_concentration": bs["token_triple_concentration"],
            "top_blockers": bs["top_blockers"],
            "per_cycle_blocker_counts": bs.get("per_cycle_blocker_counts", {}),
            "global_blockers_present": bs.get("global_blockers_present", []),
        })

    if not snapshots:
        return {"error": "no_valid_artifacts", "artifacts_checked": len(artifact_paths)}

    def _range(key: str) -> Dict[str, float]:
        vals = [s[key] for s in snapshots if s[key] is not None]
        if not vals:
            return {"min": 0.0, "max": 0.0, "mean": 0.0}
        return {
            "min": round(min(vals), 4),
            "max": round(max(vals), 4),
            "mean": round(sum(vals) / len(vals), 4),
        }

    all_tags_seen: Counter = Counter()
    for s in snapshots:
        for tag in s["top_blockers"]:
            all_tags_seen[tag] += 1

    n_runs = len(snapshots)
    stable_blockers = [tag for tag, count in all_tags_seen.items() if count == n_runs]
    flapping_blockers = [tag for tag, count in all_tags_seen.items() if 0 < count < n_runs]

    per_cycle_tag_ranges: Dict[str, Dict[str, Any]] = {}
    all_per_cycle_tags = set()
    for s in snapshots:
        for tag in s.get("per_cycle_blocker_counts", {}):
            all_per_cycle_tags.add(tag)
    for tag in sorted(all_per_cycle_tags):
        counts = [s.get("per_cycle_blocker_counts", {}).get(tag, 0) for s in snapshots]
        per_cycle_tag_ranges[tag] = {
            "min": min(counts),
            "max": max(counts),
            "present_in_runs": sum(1 for c in counts if c > 0),
        }

    all_global_tags = set()
    for s in snapshots:
        for tag in s.get("global_blockers_present", []):
            all_global_tags.add(tag)
    global_tag_stability: Dict[str, int] = {}
    for tag in sorted(all_global_tags):
        global_tag_stability[tag] = sum(
            1 for s in snapshots if tag in s.get("global_blockers_present", [])
        )

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "blocker_repeatability": True,
        "timestamp": ts,
        "runs_count": n_runs,
        "universe_profile": snapshots[0].get("universe_profile", "narrow_7") if snapshots else "narrow_7",
        "block_range": {
            "min": min(s["block"] for s in snapshots if s["block"]),
            "max": max(s["block"] for s in snapshots if s["block"]),
        },
        "metric_ranges": {
            "best_route_gross_bps": _range("best_route_gross_bps"),
            "best_route_gas_bps": _range("best_route_gas_bps"),
            "best_route_total_fee_bps": _range("best_route_total_fee_bps"),
            "best_route_net_bps": _range("best_route_net_bps"),
            "best_route_best_size_usd": _range("best_route_best_size_usd"),
            "route_failure_rate": _range("route_failure_rate"),
            "token_triple_concentration": _range("token_triple_concentration"),
        },
        "blocker_class_stability": {
            "stable_blockers": sorted(stable_blockers),
            "flapping_blockers": sorted(flapping_blockers),
            "all_observed": sorted(all_tags_seen.keys()),
        },
        "per_cycle_tag_ranges": per_cycle_tag_ranges,
        "global_blocker_stability": global_tag_stability,
        "snapshots": snapshots,
    }


# ---------------------------------------------------------------------------
# Regime repeatability — M7.A.3 temporal regime aggregation across runs
# ---------------------------------------------------------------------------

def build_regime_repeatability_summary(
    artifact_paths: List[str],
) -> Dict[str, Any]:
    """Aggregate regime classifications across multiple measured runs."""
    run_entries: List[Dict[str, Any]] = []

    for path_str in artifact_paths:
        path = Path(path_str)
        if not path.exists():
            logger.warning("Artifact not found: %s", path)
            continue
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        bs = data.get("blocker_summary")
        ms = data.get("measured", {})
        if not bs or "error" in bs:
            logger.warning("No valid blocker_summary in %s", path)
            continue

        regime = data.get("regime_bucket")
        if regime is None:
            regime = classify_regime_bucket(ms, bs)

        block = ms.get("block_number")
        run_entries.append({
            "artifact": path.name,
            "block": block,
            "regime_bucket": regime,
            "best_route_net_bps": bs["best_route_net_bps"],
            "best_route_gross_bps": bs["best_route_gross_bps"],
            "route_failure_rate": bs["route_failure_rate"],
            "top_blockers": bs["top_blockers"],
        })

    if not run_entries:
        return {"error": "no_valid_artifacts", "artifacts_checked": len(artifact_paths)}

    regime_runs: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entry in run_entries:
        for tag in entry["regime_bucket"]:
            regime_runs[tag].append(entry)

    runs_by_regime: Dict[str, int] = {}
    best_net_bps_by_regime: Dict[str, float] = {}
    mean_best_net_bps_by_regime: Dict[str, float] = {}
    blocker_stability_by_regime: Dict[str, Dict[str, Any]] = {}
    beats_two_leg_baseline_by_regime: Dict[str, bool] = {}

    for tag in sorted(regime_runs.keys()):
        entries = regime_runs[tag]
        runs_by_regime[tag] = len(entries)

        nets = [e["best_route_net_bps"] for e in entries]
        best_net_bps_by_regime[tag] = round(max(nets), 4)
        mean_best_net_bps_by_regime[tag] = round(sum(nets) / len(nets), 4)
        beats_two_leg_baseline_by_regime[tag] = max(nets) > TWO_LEG_BASELINE_NET_BPS

        all_tags_in_regime: Counter = Counter()
        for e in entries:
            for bt in e["top_blockers"]:
                all_tags_in_regime[bt] += 1
        n_runs_in_regime = len(entries)
        stable = [bt for bt, c in all_tags_in_regime.items() if c == n_runs_in_regime]
        flapping = [bt for bt, c in all_tags_in_regime.items() if 0 < c < n_runs_in_regime]
        blocker_stability_by_regime[tag] = {
            "stable_blockers": sorted(stable),
            "flapping_blockers": sorted(flapping),
        }

    ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    return {
        "regime_repeatability": True,
        "timestamp": ts,
        "runs_count": len(run_entries),
        "regimes_observed": sorted(regime_runs.keys()),
        "runs_by_regime": runs_by_regime,
        "best_net_bps_by_regime": best_net_bps_by_regime,
        "mean_best_net_bps_by_regime": mean_best_net_bps_by_regime,
        "beats_two_leg_baseline_by_regime": beats_two_leg_baseline_by_regime,
        "blocker_stability_by_regime": blocker_stability_by_regime,
        "two_leg_baseline_net_bps": round(TWO_LEG_BASELINE_NET_BPS, 4),
        "run_entries": run_entries,
    }
