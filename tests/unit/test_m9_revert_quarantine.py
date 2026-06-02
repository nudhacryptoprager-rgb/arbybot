"""Tests for the M9 revert-quarantine feedback writer.

Covers the schema .2 fix: each quarantined route records the reverting
``pool_address`` so the next run can exclude it by address directly, instead of
re-parsing token symbols from the route_id (which is ambiguous when a token
symbol itself contains '-', e.g. "open-slide").
"""
from __future__ import annotations

import json
import logging
from types import SimpleNamespace

from m9.graph_arb.runner import _write_revert_quarantine

log = logging.getLogger("test.revert_quarantine")


def _leg(route_id, reject_reason, ok=False):
    return SimpleNamespace(route_id=route_id, reject_reason=reject_reason, ok=ok)


def _edge(pair_id, pool_address):
    return SimpleNamespace(pair_id=pair_id, pool_address=pool_address)


def _qr(route_id, pair_id, pool_address, reject_reason="QUOTE_REVERT"):
    cycle = SimpleNamespace(edges=[_edge(pair_id, pool_address)])
    return SimpleNamespace(
        cycle=cycle,
        leg_results=[_leg(route_id, reject_reason)],
    )


def _write_and_load(cycle_results, tmp_path):
    out = tmp_path / "m9_revert_quarantine.json"
    _write_revert_quarantine(cycle_results, log, output_path=str(out))
    if not out.exists():
        return None
    with out.open(encoding="utf-8") as fh:
        return json.load(fh)


def test_revert_dominant_route_records_pool_address(tmp_path):
    """A revert-dominant route writes pool_address into the quarantine entry."""
    # 6 reverting legs (>=5 and revert_rate 1.0 >= 0.8 threshold)
    results = [
        _qr("uniswap_v3:WETH-open-slide@100", "WETH_open-slide", "0xDEAD")
        for _ in range(6)
    ]
    data = _write_and_load(results, tmp_path)
    assert data is not None
    assert data["schema_version"] == "m9_revert_quarantine.2"
    routes = data["routes"]
    assert len(routes) == 1
    entry = routes[0]
    assert entry["quarantine_reason"] == "QUOTE_REVERT_DOMINANT"
    # pool_address is recorded (lowercased) — robust to hyphenated token symbols
    assert entry["pool_address"] == "0xdead"
    assert entry["revert_count"] == 6
    assert entry["revert_rate"] == 1.0


def test_hyphenated_token_symbol_still_quarantined(tmp_path):
    """A route whose token symbol contains '-' is quarantined by pool_address.

    Previously the reader parsed symbols from the route_id and mis-split
    "open-slide-WETH" into {"open", "slide-WETH"}; recording the pool_address
    sidesteps that ambiguity entirely.
    """
    results = [
        _qr("uniswap_v3:open-slide-WETH@100", "open-slide_WETH", "0xBEEF")
        for _ in range(5)
    ]
    data = _write_and_load(results, tmp_path)
    assert data is not None
    assert data["routes"][0]["pool_address"] == "0xbeef"


def test_below_threshold_not_quarantined(tmp_path):
    """Routes with < 5 errors or revert_rate < 0.8 are not quarantined."""
    # Only 4 reverting legs — below the >=5 minimum.
    results = [
        _qr("uniswap_v3:FUSD-USDC@100", "FUSD_USDC", "0xCAFE")
        for _ in range(4)
    ]
    data = _write_and_load(results, tmp_path)
    assert data is None  # no file written when nothing qualifies


def test_mixed_errors_below_revert_rate_not_quarantined(tmp_path):
    """A route with mostly non-revert errors stays out of quarantine."""
    results = []
    # 2 hard reverts + 6 other errors → revert_rate 0.25 < 0.8
    for _ in range(2):
        results.append(_qr("uniswap_v3:AAA-BBB@500", "AAA_BBB", "0x1234", "QUOTE_REVERT"))
    for _ in range(6):
        results.append(_qr("uniswap_v3:AAA-BBB@500", "AAA_BBB", "0x1234", "QUOTE_TIMEOUT"))
    data = _write_and_load(results, tmp_path)
    assert data is None


# --- reader-side resolution (the feedback loop that recovers qsr/quote_revert_rate) ---

from m9.graph_arb.runner import resolve_revert_quarantine_addresses


def _inv_route(dex_id, token0, token1, pool_address, fee=None):
    return {
        "dex_id": dex_id,
        "token0": token0,
        "token1": token1,
        "pool_address": pool_address,
        "fee": fee,
    }


def test_schema_v2_direct_pool_address_resolved():
    """schema .2 entries are quarantined by their recorded pool_address directly."""
    rq = {
        "schema_version": "m9_revert_quarantine.2",
        "routes": [
            {"route_id": "uniswap_v4:WETH-open-slide@100", "pool_address": "0xDEAD"},
        ],
    }
    addrs = resolve_revert_quarantine_addresses(rq, inventory_routes=[])
    assert addrs == {"0xdead"}


def test_legacy_v1_hyphenated_token_resolved_from_inventory():
    """A stale schema .1 entry (no pool_address) for a hyphenated token symbol
    is resolved to the pool_address via exact route_id reconstruction.

    This is the regression that previously left qsr=0.0: the old symbol-fragment
    match split "WETH-open-slide" into the wrong symbol set and never excluded
    the reverting pool.
    """
    rq = {
        "schema_version": "m9_revert_quarantine.1",
        "routes": [
            {"route_id": "uniswap_v4:WETH-open-slide@100", "pool_address": None},
            {"route_id": "uniswap_v4:open-slide-WETH@100", "pool_address": None},
            {"route_id": "uniswap_v3:FUSD-USDC@100", "pool_address": None},
        ],
    }
    inventory = [
        _inv_route("uniswap_v4", "WETH", "open-slide", "0xAAA", fee=100),
        _inv_route("uniswap_v3", "FUSD", "USDC", "0xBBB", fee=100),
        _inv_route("uniswap_v2", "ANTHROPIC", "WETH", "0xCCC", fee=None),  # unrelated
    ]
    addrs = resolve_revert_quarantine_addresses(rq, inventory)
    # Both the forward (WETH-open-slide) and reverse (open-slide-WETH) probe ids
    # map to the same pool; FUSD-USDC resolves too. Unrelated route excluded.
    assert addrs == {"0xaaa", "0xbbb"}


def test_legacy_v1_no_inventory_match_returns_empty():
    """A legacy entry with no matching inventory route resolves to nothing."""
    rq = {
        "schema_version": "m9_revert_quarantine.1",
        "routes": [
            {"route_id": "uniswap_v4:WETH-ghost@100", "pool_address": None},
        ],
    }
    inventory = [_inv_route("uniswap_v4", "WETH", "open-slide", "0xAAA", fee=100)]
    assert resolve_revert_quarantine_addresses(rq, inventory) == set()


def test_mixed_schema_v2_and_v1_both_resolved():
    """A file mixing direct (.2) and legacy (.1) entries resolves both."""
    rq = {
        "routes": [
            {"route_id": "uniswap_v3:A-B@500", "pool_address": "0x111"},
            {"route_id": "uniswap_v4:C-D@100", "pool_address": None},
        ],
    }
    inventory = [_inv_route("uniswap_v4", "C", "D", "0x222", fee=100)]
    assert resolve_revert_quarantine_addresses(rq, inventory) == {"0x111", "0x222"}
