"""E1.42 Iter 5 — tier_classifier runtime wiring tests."""

from __future__ import annotations

import json
import os

from discovery.tier_classifier import (
    PoolActivitySnapshot,
    TIER_MAP_SCHEMA_VERSION,
    TierThresholds,
    classify_pools_to_tiers,
    default_tier_map_path,
    read_tier_map_artifact,
    write_tier_map_artifact,
)


def _snap(addr, age_s, now_ts=10_000.0):
    return PoolActivitySnapshot(
        pool_address=addr,
        last_swap_ts=(now_ts - age_s) if age_s is not None else None,
        chain="base",
    )


def test_classify_pools_to_tiers_buckets_by_recency():
    now = 10_000.0
    snaps = [
        _snap("0xHOT1", age_s=10),     # within 120s -> hot
        _snap("0xHOT2", age_s=100),    # within 120s -> hot
        _snap("0xWARM1", age_s=600),   # 10 min -> warm (within 1800s)
        _snap("0xCOLD1", age_s=10_000),# > 1800s -> cold
        _snap("0xCOLD2", age_s=None),  # never seen -> cold
    ]
    out = classify_pools_to_tiers(snaps, now_ts=now)
    assert sorted(out["hot"]) == ["0xhot1", "0xhot2"]
    assert out["warm"] == ["0xwarm1"]
    assert sorted(out["cold"]) == ["0xcold1", "0xcold2"]


def test_classify_pools_dedupes_within_bucket():
    now = 10_000.0
    snaps = [_snap("0xABC", 10), _snap("0xabc", 50)]  # both hot, dup addr
    out = classify_pools_to_tiers(snaps, now_ts=now)
    assert out["hot"] == ["0xabc"]


def test_classify_pools_skips_empty_address():
    now = 10_000.0
    snaps = [_snap("", 10), _snap("0xKEEP", 10)]
    out = classify_pools_to_tiers(snaps, now_ts=now)
    assert out["hot"] == ["0xkeep"]


def test_write_then_read_roundtrip(tmp_path):
    tier_map = {"hot": ["0xH"], "warm": ["0xW"], "cold": ["0xC"]}
    path = tmp_path / "m7_tier_map_base.json"
    write_tier_map_artifact(tier_map, chain="base", path=str(path))
    assert path.is_file()
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    assert data["schema_version"] == TIER_MAP_SCHEMA_VERSION
    assert data["chain"] == "base"
    assert data["counts"] == {"hot": 1, "warm": 1, "cold": 1}
    assert sorted(data["tiers"].keys()) == ["cold", "hot", "warm"]

    loaded = read_tier_map_artifact(chain="base", path=str(path))
    assert loaded == {"hot": ["0xh"], "warm": ["0xw"], "cold": ["0xc"]}


def test_read_returns_empty_on_missing_file(tmp_path):
    path = tmp_path / "missing.json"
    out = read_tier_map_artifact(chain="base", path=str(path))
    assert out == {"hot": [], "warm": [], "cold": []}


def test_read_returns_empty_on_chain_mismatch(tmp_path):
    path = tmp_path / "m7_tier_map_base.json"
    write_tier_map_artifact({"hot": ["0xH"]}, chain="base", path=str(path))
    out = read_tier_map_artifact(chain="arbitrum_one", path=str(path))
    assert out == {"hot": [], "warm": [], "cold": []}


def test_read_returns_empty_on_schema_mismatch(tmp_path):
    path = tmp_path / "bad.json"
    payload = {
        "schema_version": "older_schema_v0",
        "chain": "base",
        "tiers": {"hot": ["0xH"]},
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f)
    out = read_tier_map_artifact(chain="base", path=str(path))
    assert out == {"hot": [], "warm": [], "cold": []}


def test_default_tier_map_path_is_canonical(tmp_path):
    p = default_tier_map_path("base")
    p_norm = p.replace("\\", "/")
    assert p_norm.endswith("/_rolling/m7_tier_map_base.json")


def test_thresholds_respected_via_classify_pools_to_tiers():
    now = 10_000.0
    snaps = [_snap("0xA", 30), _snap("0xB", 200)]
    th = TierThresholds(hot_max_age_s=60.0, warm_max_age_s=300.0)
    out = classify_pools_to_tiers(snaps, now_ts=now, thresholds=th)
    assert out["hot"] == ["0xa"]
    assert out["warm"] == ["0xb"]
    assert out["cold"] == []
