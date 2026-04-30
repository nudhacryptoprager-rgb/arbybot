"""M7.E1.47/P0: Triangular candidate detection on bridge events.

When a bridge pool emits an event but the registry has NO direct (in, out)
pair, `pool_registry.find_triangular_intermediates()` searches the intent
graph for an intermediate token X such that BOTH (in, X) AND (X, out) have
active entries. `score_backrun_fast` surfaces this as
``scoring_path="triangular_pending"`` + ``reject_reason=
"TRIANGULAR_CANDIDATE_DEFERRED:N"`` so the reviewer histogram attributes
it as ``TRIANGULAR_AVAILABLE`` (vs the older ``REGISTRY_MISS``).
"""
from __future__ import annotations

from m7.orderflow.pool_registry import (
    PoolRegistry,
    PoolRegistryEntry,
    _pair_key,
)


USDC = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
WETH = "0x4200000000000000000000000000000000000006"
AERO = "0x940181a94a35a4569e4529a3cdfb74e38fd98631"
CBETH = "0x2ae3f1ec7f1f5012cfeab0185bfc7aa3cf0dec22"


def _entry(addr: str, t0: str, t1: str, fee: int = 500) -> PoolRegistryEntry:
    return PoolRegistryEntry(
        address=addr,
        dex="uniswap_v3",
        adapter_type="uniswap_v3",
        fee=fee,
        token_a=t0,
        token_b=t1,
        liquidity=10 ** 20,
        sqrt_price_x96=2 ** 96,
        tick=0,
    )


def _populate(reg: PoolRegistry, addr: str, t0: str, t1: str) -> None:
    e = _entry(addr, t0, t1)
    k = _pair_key(t0, t1)
    reg._pools[k] = [e]
    reg._queried.add(k)


def test_find_triangular_intermediates_returns_X_when_both_legs_active():
    reg = PoolRegistry()
    # USDC/AERO + AERO/WETH active; query (USDC, WETH).
    _populate(reg, "0xpA", USDC, AERO)
    _populate(reg, "0xpB", AERO, WETH)
    out = reg.find_triangular_intermediates(USDC, WETH)
    assert AERO in out
    assert out == [AERO]


def test_find_triangular_intermediates_skips_inactive_leg():
    reg = PoolRegistry()
    _populate(reg, "0xpA", USDC, AERO)
    # AERO/WETH leg present but not active (liquidity=0).
    e = _entry("0xpB", AERO, WETH)
    e.liquidity = 0
    k = _pair_key(AERO, WETH)
    reg._pools[k] = [e]
    reg._queried.add(k)
    out = reg.find_triangular_intermediates(USDC, WETH)
    assert out == []


def test_find_triangular_intermediates_returns_empty_for_unknown_tokens():
    reg = PoolRegistry()
    out = reg.find_triangular_intermediates(USDC, WETH)
    assert out == []


def test_find_triangular_intermediates_handles_multiple_intermediates():
    reg = PoolRegistry()
    _populate(reg, "0xpA1", USDC, AERO)
    _populate(reg, "0xpB1", AERO, WETH)
    _populate(reg, "0xpA2", USDC, CBETH)
    _populate(reg, "0xpB2", CBETH, WETH)
    out = reg.find_triangular_intermediates(USDC, WETH, max_results=4)
    assert AERO in out
    assert CBETH in out
    assert len(out) == 2


def test_find_triangular_intermediates_excludes_direct_pair_self():
    reg = PoolRegistry()
    # Only the direct (USDC, WETH) edge — no intermediate X.
    _populate(reg, "0xpDirect", USDC, WETH)
    out = reg.find_triangular_intermediates(USDC, WETH)
    assert out == []


def test_score_backrun_fast_returns_triangular_pending_on_direct_miss():
    """End-to-end: bridge event on (USDC, WETH) with no direct pair but
    USDC/AERO + AERO/WETH legs in registry → score_backrun_fast emits a
    BackrunResult with scoring_path='triangular_pending' and a
    TRIANGULAR_CANDIDATE_DEFERRED:N reject_reason instead of returning None.
    """
    from tests.unit.conftest import _make_event
    from m7.orderflow.scoring_parallel import (
        score_backrun_fast,
        _pool_token_cache,
    )

    pool_addr = "0xfakebridgeUSDCweth"
    _pool_token_cache[pool_addr.lower()] = (USDC, WETH, 500)

    reg = PoolRegistry()
    _populate(reg, "0xpA", USDC, AERO)
    _populate(reg, "0xpB", AERO, WETH)

    event = _make_event(
        eid="evtri1",
        chain="base",
        pool_address=pool_addr,
        token_in="token0_in",
        token_out="token1_out",
        amount_in_wei=10 ** 8,
        block=100,
    )

    result = score_backrun_fast(
        event,
        pool_registry=reg,
        token_addresses={},
        current_block=100,
        addr_to_symbol={
            USDC.lower(): "USDC",
            WETH.lower(): "WETH",
            AERO.lower(): "AERO",
        },
        chain="base",
    )

    assert result is not None, "expected triangular_pending result, not None"
    assert result.scoring_path == "triangular_pending"
    assert (result.reject_reason or "").startswith("TRIANGULAR_CANDIDATE_DEFERRED:")
    assert result.backrun_token_in_address is not None
    assert result.backrun_token_out_address is not None
    # Intermediate token tag in size_normalization_source for telemetry.
    assert "triangular_via:" in (result.size_normalization_source or "")


def test_score_backrun_fast_still_returns_none_when_no_triangular():
    """No direct pair AND no triangular path → caller-side wrapping into
    REJECT_NOT_IN_HOT_REGISTRY remains the contract."""
    from tests.unit.conftest import _make_event
    from m7.orderflow.scoring_parallel import (
        score_backrun_fast,
        _pool_token_cache,
    )

    pool_addr = "0xfakebridgeUSDCweth_noPath"
    _pool_token_cache[pool_addr.lower()] = (USDC, WETH, 500)

    reg = PoolRegistry()  # empty — no triangular intermediates
    event = _make_event(
        eid="evtri2",
        chain="base",
        pool_address=pool_addr,
        token_in="token0_in",
        token_out="token1_out",
        amount_in_wei=10 ** 8,
        block=100,
    )

    result = score_backrun_fast(
        event,
        pool_registry=reg,
        token_addresses={},
        current_block=100,
        addr_to_symbol={USDC.lower(): "USDC", WETH.lower(): "WETH"},
        chain="base",
    )
    assert result is None
