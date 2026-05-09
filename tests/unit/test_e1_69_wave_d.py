"""E1.69 Wave D — TVL scout pure logic + Flashblocks/TVL bridge surfacing."""
from __future__ import annotations

import inspect

from m7.scouts.tvl_scout import (
    PoolTVLEntry,
    parse_defillama_pools,
    rank_pools_by_tvl,
    select_production_pools,
)


def _entry(addr: str, tvl: float, project: str = "uniswap-v3", chain: str = "base") -> PoolTVLEntry:
    return PoolTVLEntry(
        chain=chain, project=project, pool_address=addr,
        symbol="WETH-USDC", tvl_usd=tvl, volume_24h_usd=0.0,
    )


def test_pool_tvl_entry_production_grade_threshold() -> None:
    assert _entry("0x1", 49_999.0).production_grade is False
    assert _entry("0x2", 50_000.0).production_grade is True
    assert _entry("0x3", 5_000_000.0).production_grade is True


def test_rank_pools_by_tvl_descending() -> None:
    a = _entry("0xa", 1_000.0)
    b = _entry("0xb", 5_000.0)
    c = _entry("0xc", 50.0)
    assert rank_pools_by_tvl([a, b, c]) == [b, a, c]


def test_select_production_pools_filters_min_tvl() -> None:
    pools = [_entry(f"0x{i}", float(i) * 10_000.0) for i in range(1, 8)]
    sel = select_production_pools(pools, top_n=10, min_tvl_usd=50_000.0)
    assert all(p.tvl_usd >= 50_000.0 for p in sel)
    assert sel == sorted(sel, key=lambda p: p.tvl_usd, reverse=True)


def test_select_production_pools_top_n_cap() -> None:
    pools = [_entry(f"0x{i}", 1_000_000.0) for i in range(20)]
    sel = select_production_pools(pools, top_n=5)
    assert len(sel) == 5


def test_select_production_pools_project_whitelist() -> None:
    a = _entry("0xa", 1_000_000.0, project="uniswap-v3")
    b = _entry("0xb", 1_000_000.0, project="random-fork")
    sel = select_production_pools([a, b], top_n=10)
    assert a in sel and b not in sel


def test_parse_defillama_pools_handles_missing_fields() -> None:
    payload = {
        "data": [
            {"chain": "Base", "project": "uniswap-v3", "symbol": "WETH-USDC",
             "pool": "0xPOOL1", "tvlUsd": 1_000_000, "volumeUsd24h": 50},
            {"chain": "Base", "project": "junk"},  # missing pool/tvl
            {"chain": "Ethereum", "pool": "0xX", "tvlUsd": 9},  # wrong chain
            {"chain": "Base", "pool": "0xZ", "tvlUsd": "not-a-number"},
        ]
    }
    out = parse_defillama_pools(payload, chain="Base")
    assert len(out) == 1
    assert out[0].pool_address == "0xpool1"
    assert out[0].tvl_usd == 1_000_000.0


def test_parse_defillama_pools_empty_on_garbage() -> None:
    assert parse_defillama_pools(None) == []      # type: ignore[arg-type]
    assert parse_defillama_pools({}) == []
    assert parse_defillama_pools({"data": "nope"}) == []


def test_fetch_defillama_pools_disabled_by_default(monkeypatch) -> None:
    """ARBY_TVL_SCOUT_ENABLE unset -> empty list, no network."""
    from m7.scouts import tvl_scout
    monkeypatch.delenv("ARBY_TVL_SCOUT_ENABLE", raising=False)
    assert tvl_scout.fetch_defillama_pools() == []


def test_bridge_breakdown_surfaces_flashblocks_and_tvl_state() -> None:
    """E1.69 Wave D: bridge_runtime exposes flashblocks_http_enabled / tvl_scout_enabled."""
    import m7.orderflow.bridge_runtime as _br
    src = inspect.getsource(_br)
    assert '"flashblocks_http_enabled"' in src
    assert '"tvl_scout_enabled"' in src
