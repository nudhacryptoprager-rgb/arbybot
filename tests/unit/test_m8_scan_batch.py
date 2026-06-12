"""Unit tests for M8.2 scan batch layer."""
from __future__ import annotations

from m8.discovery.scan_batch import (
    NegativeResultCache,
    split_candidate_rows,
    mirror_canonical_candidate_telemetry,
)
from m8.discovery.scan_telemetry import empty_candidate_scan_telemetry, empty_scan_telemetry


def test_negative_cache_ttl():
    cache = NegativeResultCache(ttl_s=3600.0)
    cache.put("0xabc", "uniswap_v3", "USDC", "NO_POOL")
    assert cache.get("0xabc", "uniswap_v3", "USDC") == "NO_POOL"


def test_split_candidate_rows_dedup_canonical():
    rows = [
        {"dex_id": "iziswap_base", "config_dex_id": "iziswap_base", "registry_status": "configured"},
        {"dex_id": "hydrex", "registry_status": "hint_only"},
    ]
    rpc, covered = split_candidate_rows(rows, {"iziswap_base", "uniswap_v3"})
    assert covered == {"iziswap_base": "iziswap_base"}
    assert len(rpc) == 1
    assert rpc[0]["dex_id"] == "hydrex"


def test_mirror_canonical_candidate_telemetry():
    scan = empty_scan_telemetry()
    cand = empty_candidate_scan_telemetry()
    scan["scan_attempt_matrix"] = {
        "0xabc": {
            "iziswap_base": {
                "USDC": {
                    "attempted": True,
                    "result": "NO_POOL",
                    "reason": "NO_POOL",
                }
            }
        }
    }
    mirror_canonical_candidate_telemetry(
        scan_telemetry=scan,
        candidate_telemetry=cand,
        token_address="0xabc",
        covered={"iziswap_base": "iziswap_base"},
        anchor_syms=["USDC"],
    )
    cell = cand["candidate_dex_attempt_matrix"]["0xabc"]["iziswap_base"]["USDC"]
    assert cell["reason"] == "covered_by_canonical_scan"
