"""M7.E1.47/P1a: tier_map artifact emitted by cold lane.

Verifies the pure-function pipeline used by `m7/orderflow/loop_runner.py`
to produce `data/runs/_rolling/m7_tier_map_<chain>.json` from the
`_cold_active_pools` activity dict. The hot-lane consumer of this
artifact will land in P1b.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from discovery.tier_classifier import (
    PoolActivitySnapshot,
    TIER_MAP_SCHEMA_VERSION,
    TierThresholds,
    classify_pools_to_tiers,
    read_tier_map_artifact,
    write_tier_map_artifact,
)


CHAIN = "base"


def _snapshots_for_active_pools(active: dict, *, iteration: int, now_ts: float) -> list:
    """Mirror of the loop_runner P1a snapshot construction (kept in sync)."""
    out = []
    for addr, meta in active.items():
        li = meta.get("last_iter", iteration)
        if li == iteration:
            last_ts = now_ts
        else:
            last_ts = now_ts - max(0, iteration - li) * 50.0
        out.append(
            PoolActivitySnapshot(
                pool_address=addr,
                last_swap_ts=last_ts,
                swap_count_window=int(meta.get("event_count", 0)),
                chain=CHAIN,
            )
        )
    return out


def test_tier_map_pipeline_partitions_by_recency(tmp_path):
    now = time.time()
    iteration = 10
    active = {
        "0xpool_hot_a": {"event_count": 5, "last_iter": iteration},
        "0xpool_hot_b": {"event_count": 1, "last_iter": iteration},
        "0xpool_warm": {"event_count": 2, "last_iter": iteration - 5},  # 250s old
        "0xpool_cold": {"event_count": 1, "last_iter": iteration - 50},  # 2500s old
    }
    snaps = _snapshots_for_active_pools(active, iteration=iteration, now_ts=now)
    tier_map = classify_pools_to_tiers(
        snaps,
        now_ts=now,
        thresholds=TierThresholds(hot_max_age_s=120.0, warm_max_age_s=1800.0),
    )
    assert "0xpool_hot_a" in tier_map["hot"]
    assert "0xpool_hot_b" in tier_map["hot"]
    assert "0xpool_warm" in tier_map["warm"]
    assert "0xpool_cold" in tier_map["cold"]


def test_tier_map_artifact_round_trip(tmp_path):
    now = time.time()
    active = {"0xpA": {"event_count": 3, "last_iter": 1}}
    snaps = _snapshots_for_active_pools(active, iteration=1, now_ts=now)
    tier_map = classify_pools_to_tiers(snaps, now_ts=now)
    out_path = tmp_path / "tier_map.json"
    written = write_tier_map_artifact(
        tier_map, chain=CHAIN, path=str(out_path)
    )
    assert Path(written).is_file()
    payload = json.loads(out_path.read_text(encoding="utf-8"))
    assert payload["schema_version"] == TIER_MAP_SCHEMA_VERSION
    assert payload["chain"] == CHAIN
    assert payload["counts"]["hot"] == 1
    assert "0xpa" in payload["tiers"]["hot"]

    rt = read_tier_map_artifact(chain=CHAIN, path=str(out_path))
    assert "0xpa" in rt["hot"]


def test_tier_map_handles_empty_active_pools(tmp_path):
    out = tmp_path / "tier_map_empty.json"
    written = write_tier_map_artifact(
        {"hot": [], "warm": [], "cold": []}, chain=CHAIN, path=str(out)
    )
    rt = read_tier_map_artifact(chain=CHAIN, path=str(written))
    assert rt == {"hot": [], "warm": [], "cold": []}


def test_tier_map_chain_mismatch_returns_empty(tmp_path):
    out = tmp_path / "tm.json"
    write_tier_map_artifact(
        {"hot": ["0xa"], "warm": [], "cold": []},
        chain="ethereum",
        path=str(out),
    )
    rt = read_tier_map_artifact(chain=CHAIN, path=str(out))
    # Chain mismatch → reader returns canonical empty dict.
    assert rt == {"hot": [], "warm": [], "cold": []}
