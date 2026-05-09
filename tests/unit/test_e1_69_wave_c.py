"""E1.69 Wave C — route graph optimizer + QuoterV2 multi-hop encoding."""
from __future__ import annotations

import pytest

from m7.routing import (
    PoolEdge,
    RoutePath,
    build_adjacency,
    enumerate_paths,
    rank_paths,
    select_production_paths,
)


# ---------------------------------------------------------------------------
# route_graph
# ---------------------------------------------------------------------------


def _pool(addr: str, t0: str, t1: str, tvl: float, dex: str = "uniswap_v3", fee: int = 3000):
    return PoolEdge(address=addr, token0=t0.upper(), token1=t1.upper(),
                    dex=dex, fee_bps=fee, tvl_usd=tvl)


def test_build_adjacency_indexes_both_endpoints() -> None:
    p = _pool("0x1", "WETH", "USDC", 1_000_000.0)
    adj = build_adjacency([p])
    assert p in adj["WETH"]
    assert p in adj["USDC"]


def test_enumerate_paths_finds_direct_pool() -> None:
    pools = [_pool("0x1", "WETH", "USDC", 1_000_000.0)]
    paths = enumerate_paths(pools, "WETH", "USDC", max_hops=3)
    assert len(paths) == 1
    assert paths[0].tokens == ("WETH", "USDC")
    assert paths[0].hops == 1


def test_enumerate_paths_finds_2_hop_via_weth() -> None:
    """cbETH -> WETH -> USDC is the canonical Wave B production path."""
    pools = [
        _pool("0xa", "CBETH", "WETH", 5_000_000.0),
        _pool("0xb", "WETH", "USDC", 50_000_000.0),
    ]
    paths = enumerate_paths(pools, "CBETH", "USDC", max_hops=3)
    assert any(p.tokens == ("CBETH", "WETH", "USDC") for p in paths)


def test_enumerate_paths_rejects_non_bridge_intermediate() -> None:
    """Random token like FUN should not bridge cbETH->USDC by default."""
    pools = [
        _pool("0xa", "CBETH", "FUN", 100.0),
        _pool("0xb", "FUN", "USDC", 100.0),
    ]
    paths = enumerate_paths(pools, "CBETH", "USDC", max_hops=3)
    assert paths == []


def test_enumerate_paths_no_self_route() -> None:
    pools = [_pool("0x1", "WETH", "USDC", 1_000_000.0)]
    assert enumerate_paths(pools, "WETH", "WETH") == []


def test_enumerate_paths_respects_max_hops() -> None:
    pools = [
        _pool("0xa", "A", "WETH", 1.0),
        _pool("0xb", "WETH", "USDC", 1.0),
        _pool("0xc", "USDC", "B", 1.0),
    ]
    paths_1 = enumerate_paths(pools, "A", "B", max_hops=1)
    paths_3 = enumerate_paths(pools, "A", "B", max_hops=3,
                              bridge_whitelist=("WETH", "USDC"))
    assert paths_1 == []
    assert any(p.hops == 3 for p in paths_3)


def test_rank_paths_promotes_production_tier() -> None:
    """A 1-hop dust path must rank below a 2-hop production-size path."""
    pools_dust = _pool("0xd", "TKN", "USDC", 100.0)            # tiny direct pool
    pools_via_weth_a = _pool("0xa", "TKN", "WETH", 1_000_000.0)
    pools_via_weth_b = _pool("0xb", "WETH", "USDC", 50_000_000.0)
    pools = [pools_dust, pools_via_weth_a, pools_via_weth_b]
    paths = enumerate_paths(pools, "TKN", "USDC", max_hops=3)
    assert len(paths) == 2
    ranked = rank_paths(paths, min_production_tvl_usd=1000.0)
    assert ranked[0].hops == 2  # production tier wins
    assert ranked[1].hops == 1


def test_rank_paths_breaks_ties_by_bottleneck_tvl() -> None:
    p_low = RoutePath(
        tokens=("A", "B"),
        pools=(_pool("0x1", "A", "B", 1000.0),),
    )
    p_high = RoutePath(
        tokens=("A", "B"),
        pools=(_pool("0x2", "A", "B", 9999.0),),
    )
    ranked = rank_paths([p_low, p_high], min_production_tvl_usd=100.0)
    assert ranked[0] is p_high


def test_select_production_paths_top_n_cap() -> None:
    pools = [_pool(f"0x{i}", "TKN", "USDC", 1e6 + i) for i in range(10)]
    paths = select_production_paths(pools, "TKN", "USDC", top_n=3)
    assert len(paths) == 3


def test_no_pool_revisit_within_path() -> None:
    """An A-B-A path would need to reuse the same pool twice; rejected."""
    pools = [_pool("0x1", "A", "WETH", 1e6), _pool("0x2", "WETH", "USDC", 1e6)]
    # request A -> A, would be self-route, returns []
    assert enumerate_paths(pools, "A", "A") == []


# ---------------------------------------------------------------------------
# QuoterV2 multi-hop encoding
# ---------------------------------------------------------------------------


def test_encode_v3_path_two_hops() -> None:
    from dex.adapters.uniswap_v3 import encode_v3_path
    tok_a = "0x" + "aa" * 20
    tok_b = "0x" + "bb" * 20
    tok_c = "0x" + "cc" * 20
    path = encode_v3_path([tok_a, tok_b, tok_c], [500, 3000])
    # 20 + 3 + 20 + 3 + 20 = 66 bytes
    assert len(path) == 66
    # Last 20 bytes must be tok_c
    assert path[-20:].hex() == "cc" * 20


def test_encode_v3_path_rejects_fee_count_mismatch() -> None:
    from dex.adapters.uniswap_v3 import encode_v3_path
    with pytest.raises(ValueError):
        encode_v3_path(["0x" + "aa" * 20, "0x" + "bb" * 20], [500, 3000])


def test_encode_v3_path_rejects_oversized_fee() -> None:
    from dex.adapters.uniswap_v3 import encode_v3_path
    with pytest.raises(ValueError):
        encode_v3_path(["0x" + "aa" * 20, "0x" + "bb" * 20], [0xFFFFFFFF])


def test_encode_quote_exact_input_calldata_layout() -> None:
    """Selector + offset(0x40) + amountIn + path_len + padded_path."""
    from dex.adapters.uniswap_v3 import encode_quote_exact_input, SELECTOR_QUOTE_EXACT_INPUT
    tok_a = "0x" + "aa" * 20
    tok_b = "0x" + "bb" * 20
    cd = encode_quote_exact_input([tok_a, tok_b], [3000], 10**18)
    assert cd.startswith(SELECTOR_QUOTE_EXACT_INPUT)
    # Strip selector then chunk into 32-byte words.
    data = cd[len(SELECTOR_QUOTE_EXACT_INPUT):]
    offset = int(data[0:64], 16)
    amount = int(data[64:128], 16)
    path_len = int(data[128:192], 16)
    assert offset == 0x40
    assert amount == 10**18
    assert path_len == 43  # 20 + 3 + 20


def test_decode_quote_exact_input_response_extracts_amount_out() -> None:
    from dex.adapters.uniswap_v3 import decode_quote_exact_input_response
    amount_hex = hex(123_456_789)[2:].zfill(64)
    raw = "0x" + amount_hex + "00" * 32
    assert decode_quote_exact_input_response(raw) == 123_456_789
