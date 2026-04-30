"""M7.E1.47/P1b: hot-lane consumer of tier_map artifact.

Verifies the read-and-merge behavior used by the hot prewarm in
`m7/orderflow/loop_runner.py` — tier_map.hot pool addresses are merged
into the priority prewarm set alongside cold_executable / near_executable.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from discovery.tier_classifier import (
    read_tier_map_artifact,
    write_tier_map_artifact,
)

CHAIN = "base"


def _merge_tier_hot(
    tier_hot_list, ptt_keys, cold_exec_pools
) -> tuple[int, int, int]:
    """Mirror of loop_runner P1b merge (kept in sync with code)."""
    in_ptt = 0
    added = 0
    for addr in tier_hot_list:
        a = (addr or "").lower()
        if not a:
            continue
        if a in ptt_keys:
            in_ptt += 1
        if a not in cold_exec_pools:
            cold_exec_pools.add(a)
            added += 1
    return len(tier_hot_list), in_ptt, added


def test_tier_hot_merges_into_priority(tmp_path):
    out = tmp_path / "tm.json"
    write_tier_map_artifact(
        {"hot": ["0xa", "0xb", "0xc"], "warm": [], "cold": []},
        chain=CHAIN, path=str(out),
    )
    rt = read_tier_map_artifact(chain=CHAIN, path=str(out))
    cold_exec = {"0xa"}  # already executable; should not double-add
    ptt = {"0xa", "0xb"}  # 0xc not in PTT yet
    n, in_ptt, added = _merge_tier_hot(rt["hot"], ptt, cold_exec)
    assert n == 3
    assert in_ptt == 2
    assert added == 2  # 0xb and 0xc are new
    assert cold_exec == {"0xa", "0xb", "0xc"}


def test_tier_hot_empty_is_safe(tmp_path):
    out = tmp_path / "tm.json"
    write_tier_map_artifact(
        {"hot": [], "warm": [], "cold": []}, chain=CHAIN, path=str(out)
    )
    rt = read_tier_map_artifact(chain=CHAIN, path=str(out))
    cold_exec: set = set()
    n, in_ptt, added = _merge_tier_hot(rt["hot"], set(), cold_exec)
    assert (n, in_ptt, added) == (0, 0, 0)
    assert cold_exec == set()


def test_tier_hot_handles_missing_artifact(tmp_path):
    # Reading a non-existent artifact returns empty canonical dict.
    rt = read_tier_map_artifact(chain=CHAIN, path=str(tmp_path / "missing.json"))
    assert rt == {"hot": [], "warm": [], "cold": []}
    cold_exec: set = set()
    n, _, added = _merge_tier_hot(rt["hot"], set(), cold_exec)
    assert n == 0 and added == 0


def test_tier_hot_normalizes_case(tmp_path):
    out = tmp_path / "tm.json"
    # Writer lowercases on write; reader returns lowercase.
    write_tier_map_artifact(
        {"hot": ["0xABCDef", "0x123abc"], "warm": [], "cold": []},
        chain=CHAIN, path=str(out),
    )
    rt = read_tier_map_artifact(chain=CHAIN, path=str(out))
    for a in rt["hot"]:
        assert a == a.lower()
    cold_exec: set = set()
    _, _, added = _merge_tier_hot(rt["hot"], set(), cold_exec)
    assert added == 2
