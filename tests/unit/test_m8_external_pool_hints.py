"""Unit tests for M8.2 external pool hint layer."""
from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from m8.discovery.dexscreener_hints import _pair_to_hint
from m8.discovery.dexscreener_mirror_layer import (
    DEXSCREENER_MIRROR_LAYER,
    build_dexscreener_mirror_artifact,
)
from m8.discovery.hint_verifier import is_bytes32_hex, verify_v4_pool_id
from m8.discovery.pool_hints import (
    BRIDGE_ELIGIBLE_HINT_STATUSES,
    HINT_DEX_UNSUPPORTED,
    HINT_ONCHAIN_VERIFIED,
    HINT_ONLY,
    HINT_POOLID_VERIFIED,
    PoolHint,
    build_artifact,
    dedupe_hints,
    hints_for_token,
    normalize_dex_id,
    normalize_pool_identity,
    route_bridge_eligible,
    verify_hint_onchain,
)
from m8.discovery.cross_dex_expand import expand_token_neighborhood


def _dexscreener_pair() -> dict:
    return {
        "chainId": "base",
        "dexId": "uniswap",
        "pairAddress": "0xpool1111111111111111111111111111111111111111",
        "pairCreatedAt": 1710000000000,
        "baseToken": {"address": "0xabc0000000000000000000000000000000000001"},
        "quoteToken": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        "liquidity": {"usd": 12000},
        "volume": {"h24": 500},
    }


def test_normalize_dex_id_dexscreener():
    assert normalize_dex_id("dexscreener", "uniswap") == "uniswap_v3"
    assert normalize_dex_id("geckoterminal", "uniswap-v4-base") == "uniswap_v4"


def test_pair_to_hint_dexscreener():
    h = _pair_to_hint(
        _dexscreener_pair(),
        chain="base",
        focus_token="0xabc0000000000000000000000000000000000001",
    )
    assert h is not None
    assert h.source == "dexscreener"
    assert h.dex_id == "uniswap_v3"
    assert h.liquidity_usd == 12000.0


def test_dexscreener_mirror_layer_classifies_all_mirrors():
    token = "0xabc0000000000000000000000000000000000001"
    supported = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0xpool1111111111111111111111111111111111111111",
        token0_addr=token,
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        focus_token=token,
        raw={"dexId": "uniswap"},
    )
    unsupported = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="hydrex",
        pool_address="0xpool2222222222222222222222222222222222222222",
        token0_addr=token,
        token1_addr="0x4200000000000000000000000000000000000006",
        focus_token=token,
        raw={"dexId": "hydrex"},
    )
    artifact = build_dexscreener_mirror_artifact(
        [token],
        config={
            "dexes": {
                "uniswap_v3": {
                    "adapter_type": "uniswap_v3",
                    "factory": "0xfactory",
                    "quoter": "0xquoter",
                    "enabled": True,
                }
            }
        },
        fetched_hints_by_token={token: [supported, unsupported]},
    )

    metrics = artifact["metrics"]
    assert artifact["sources"] == [DEXSCREENER_MIRROR_LAYER]
    assert metrics["dexscreener_all_mirrors_total"] == 2
    assert metrics["dexscreener_supported_mirrors_total"] == 1
    assert metrics["dexscreener_unknown_alias_mirrors_total"] == 1
    assert all(
        h["raw"]["mirror_recall_layer"] == DEXSCREENER_MIRROR_LAYER
        for h in artifact["hints"]
    )


def test_dedupe_hints():
    a = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0xpool1",
        token0_addr="0xa",
        token1_addr="0xb",
    )
    b = PoolHint.from_dict(a.to_dict())
    out = dedupe_hints([a, b])
    assert len(out) == 1


def test_hints_for_token_matches_focus_token():
    artifact = build_artifact(
        chain="base",
        sources=["geckoterminal"],
        hints=[
            PoolHint(
                source="geckoterminal",
                chain="base",
                dex_id="uniswap_v4",
                pool_address="0x" + "ab" * 32,
                token0_addr="0xweth",
                token1_addr="0xusdc",
                focus_token="0xfocus111111111111111111111111111111111111",
            ),
        ],
    )
    rows = hints_for_token(artifact, "0xfocus111111111111111111111111111111111111")
    assert len(rows) == 1


def test_hints_for_token_filter():
    artifact = build_artifact(
        chain="base",
        sources=["dexscreener"],
        hints=[
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="uniswap_v3",
                pool_address="0xpool1",
                token0_addr="0xabc",
                token1_addr="0xusdc",
            ),
            PoolHint(
                source="dexscreener",
                chain="base",
                dex_id="aerodrome",
                pool_address="0xpool2",
                token0_addr="0xdef",
                token1_addr="0xusdc",
            ),
        ],
    )
    rows = hints_for_token(artifact, "0xabc")
    assert len(rows) == 1
    assert rows[0].pool_address == "0xpool1"


def test_route_bridge_eligible_blocks_hint_only():
    assert route_bridge_eligible({"route_id": "legacy"}) is True
    assert route_bridge_eligible({"hint_status": HINT_ONLY}) is False
    assert route_bridge_eligible({"hint_status": HINT_ONCHAIN_VERIFIED}) is True
    assert route_bridge_eligible({"hint_status": HINT_POOLID_VERIFIED}) is True


def test_normalize_v4_pool_id_from_gecko_address():
    pool_id = "0x" + "ab" * 32
    hint = normalize_pool_identity(
        PoolHint(
            source="geckoterminal",
            chain="base",
            dex_id="uniswap_v4",
            pool_address=pool_id,
            token0_addr="0xa",
            token1_addr="0xb",
        )
    )
    assert hint.pool_id == pool_id
    assert is_bytes32_hex(hint.pool_id)
    assert hint.pool_manager.startswith("0x498581")


@patch("m8.discovery.hint_verifier._eth_call")
def test_v4_poolid_verified_via_stateview(mock_eth_call):
    pool_id = "0x" + "cd" * 32
    mock_eth_call.side_effect = [
        "0x" + "1" * 128,  # slot0 sqrtPrice > 0
        "0x" + format(1000, "064x"),  # liquidity > 0
    ]
    ok, method = verify_v4_pool_id(pool_id, chain="base", rpc_url="http://rpc.test")
    assert ok is True
    assert method == "v4_stateview"


@patch("m8.discovery.hint_verifier.verify_hint_specialized")
def test_verify_hint_onchain_maps_v4_to_poolid_status(mock_specialized):
    pool_id = "0x" + "ef" * 32
    hint = PoolHint(
        source="geckoterminal",
        chain="base",
        dex_id="uniswap_v4",
        pool_address=pool_id,
        token0_addr="0xa",
        token1_addr="0xb",
    )
    verified = PoolHint.from_dict(hint.to_dict())
    verified.verify_method = "v4_stateview"
    mock_specialized.return_value = (verified, "OK")
    out = verify_hint_onchain(hint, chain="base", verify_mode="specialized")
    assert out.hint_status == HINT_POOLID_VERIFIED
    assert out.verify_method == "v4_stateview"


def test_verify_hint_onchain_unsupported_dex():
    h = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="unknown_dex",
        pool_address="0xpool1",
        token0_addr="0xa",
        token1_addr="0xb",
    )
    out = verify_hint_onchain(h, chain="base", allowed_dex_ids={"uniswap_v3"})
    assert out.hint_status == HINT_DEX_UNSUPPORTED


@patch("m8.discovery.pool_hints.verify_hint_onchain")
def test_expand_token_neighborhood_merges_verified_hint(mock_verify):
    token = "0xabc0000000000000000000000000000000000001"
    registry = {
        "tokens": {
            token: {
                "symbol": "FOO",
                "venues": {
                    "v4::0xp1": {
                        "dex": "uniswap_v4",
                        "pool": "0xp100000000000000000000000000000000000001",
                        "token0": token,
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                    }
                },
            }
        }
    }
    verified_hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0xpool2222222222222222222222222222222222222222",
        token0_addr=token,
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        hint_status=HINT_ONCHAIN_VERIFIED,
        verify_method="factory_getPool",
    )

    def _fake_verify(h, **kwargs):
        return verified_hint

    mock_verify.side_effect = _fake_verify

    hints_art = build_artifact(
        chain="base",
        sources=["dexscreener"],
        hints=[verified_hint],
    )
    cfg = {
        "chain": "base",
        "tokens": {"USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"}},
        "dexes": {
            "uniswap_v4": {"adapter_type": "uniswap_v4", "enabled": True},
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v4": {"enabled_for_discovery": True, "enabled_for_productive": True},
            "uniswap_v3": {"enabled_for_discovery": True, "enabled_for_productive": True},
        },
    }
    mirror = MagicMock()
    mirror.find_pools_containing_token.return_value = []
    nh = expand_token_neighborhood(
        chain="base",
        config=cfg,
        registry=registry,
        exotic_address=token,
        exotic_symbol="FOO",
        dry_run=False,
        mirror_index=mirror,
        external_hints_artifact=hints_art,
    )
    assert nh["token_seen_on_dexes"] >= 2
    assert nh["hint_metrics"]["verified_second_pool_count"] >= 1
    assert nh["hint_metrics"]["eligible_hint_routes"] >= 1
    assert nh["token_seen_on_dexes"] >= 2
    mock_verify.assert_not_called()


@patch("m8.discovery.pool_hints.verify_hint_onchain")
def test_expand_token_neighborhood_rejects_invalid_dexscreener_mirrors(mock_verify):
    token = "0xabc0000000000000000000000000000000000001"
    registry = {
        "tokens": {
            token: {
                "symbol": "FOO",
                "venues": {
                    "v4::0xp1": {
                        "dex": "uniswap_v4",
                        "pool": "0xp100000000000000000000000000000000000001",
                        "token0": token,
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "token0_symbol": "FOO",
                        "token1_symbol": "USDC",
                    }
                },
            }
        }
    }
    hint_only = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0xpool3333333333333333333333333333333333333333",
        token0_addr=token,
        token1_addr="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        hint_status=HINT_ONLY,
    )
    unsupported = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="hydrex",
        pool_address="0xpool4444444444444444444444444444444444444444",
        token0_addr=token,
        token1_addr="0x4200000000000000000000000000000000000006",
        hint_status=HINT_ONLY,
    )
    mock_verify.return_value = hint_only

    hints_art = build_artifact(chain="base", sources=["dexscreener"], hints=[hint_only, unsupported])
    cfg = {
        "chain": "base",
        "tokens": {"USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"}},
        "dexes": {
            "uniswap_v4": {"adapter_type": "uniswap_v4", "enabled": True},
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v4": {"enabled_for_discovery": True, "enabled_for_productive": True},
            "uniswap_v3": {"enabled_for_discovery": True, "enabled_for_productive": True},
        },
    }
    mirror = MagicMock()
    mirror.find_pools_containing_token.return_value = []

    nh = expand_token_neighborhood(
        chain="base",
        config=cfg,
        registry=registry,
        exotic_address=token,
        exotic_symbol="FOO",
        dry_run=False,
        mirror_index=mirror,
        external_hints_artifact=hints_art,
    )

    assert nh["hint_metrics"].get("eligible_hint_routes", 0) == 0
    assert nh["hint_metrics"]["hint_rejected"] >= 2
    assert nh["hint_metrics"]["hint_rejected_hint_only"] >= 1
    assert nh["hint_metrics"]["hint_rejected_unsupported_dex"] >= 1


def test_graph_hints_import():
    from m8.discovery.graph_hints import fetch_token_hints

    with patch("m8.discovery.graph_hints.query_pools_by_token", return_value=[]):
        assert fetch_token_hints("0xabc") == []


def test_v4_slot0_empty_falls_back_to_v3_factory_in_specialized():
    """When V4 StateView slot0 is empty, verify_hint_specialized tries V3 factory.

    DexScreener may label V3 pools as V4 based on labels. The V4 poolId won't
    match StateView, but the pool is a real V3 pool found via factory.getPool.
    """
    from m8.discovery.hint_verifier import verify_hint_specialized

    pool_id = "0x" + "ff" * 32
    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v4",
        pool_address=pool_id,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        raw={"pair": {"feeTier": 3000}},
    )

    with patch(
        "m8.discovery.hint_verifier.verify_v4_pool_id",
        return_value=(False, "V4_SLOT0_EMPTY"),
    ), patch(
        "m8.discovery.hint_verifier.verify_factory_pool",
        return_value=(True, "factory_getPool"),
    ) as mock_factory, patch.dict(
        "os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False
    ):
        out, reason = verify_hint_specialized(hint, chain="base")
        assert reason == "OK"
        assert out.dex_id == "uniswap_v3"
        assert out.verify_method == "factory_getPool"
        mock_factory.assert_called_once()


def _aero_config():
    return {
        "dexes": {
            "aerodrome": {
                "adapter_type": "uniswap_v2",
                "factory": "0x420dd381b31aef6683db6b902084cb0ffece40da",
                "enabled": True,
            },
            "aerodrome_slipstream": {
                "adapter_type": "uniswap_v3",
                "factory": "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a",
                "enabled": True,
            },
            "aerodrome_v2_stable": {
                "adapter_type": "uniswap_v2",
                "factory": "0x420dd381b31aef6683db6b902084cb0ffece40da",
                "enabled": True,
            },
        }
    }


def _aero_pair(labels=None, pair_type=None, fee_tier=None):
    p = {
        "chainId": "base",
        "dexId": "aerodrome",
        "pairAddress": "0x" + "a" * 40,
        "baseToken": {"address": "0x" + "1" * 40},
        "quoteToken": {"address": "0x" + "2" * 40},
        "liquidity": {"usd": 5000},
    }
    if labels:
        p["labels"] = labels
    if pair_type:
        p["type"] = pair_type
    if fee_tier is not None:
        p["feeTier"] = fee_tier
    return p


def test_pair_to_hint_aerodrome_ve33_factory_from_config():
    """Default Aerodrome (ve33) gets factory_address from config."""
    h = _pair_to_hint(
        _aero_pair(),
        chain="base",
        focus_token="0x" + "1" * 40,
        max_recall=True,
        dex_config=_aero_config(),
    )
    assert h is not None
    assert h.dex_id == "aerodrome"
    assert h.factory_address == "0x420dd381b31aef6683db6b902084cb0ffece40da"
    assert h.raw.get("factory_address_source") == "config_dexes"


def test_pair_to_hint_aerodrome_slipstream_factory_from_config():
    """Aerodrome Slipstream variant gets correct slipstream factory."""
    h = _pair_to_hint(
        _aero_pair(labels=["slipstream"]),
        chain="base",
        focus_token="0x" + "1" * 40,
        max_recall=True,
        dex_config=_aero_config(),
    )
    assert h is not None
    assert h.dex_id == "aerodrome_slipstream"
    assert h.factory_address == "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a"


def test_pair_to_hint_aerodrome_stable_factory_from_config():
    """Aerodrome stable variant gets correct factory (same as ve33)."""
    h = _pair_to_hint(
        _aero_pair(labels=["stable"]),
        chain="base",
        focus_token="0x" + "1" * 40,
        max_recall=True,
        dex_config=_aero_config(),
    )
    assert h is not None
    assert h.dex_id == "aerodrome_v2_stable"
    assert h.factory_address == "0x420dd381b31aef6683db6b902084cb0ffece40da"


def test_pair_to_hint_no_factory_when_config_missing():
    """When config doesn't have factory for dex, factory_address stays empty."""
    cfg = {"dexes": {"aerodrome": {"adapter_type": "uniswap_v2", "enabled": True}}}
    h = _pair_to_hint(
        _aero_pair(),
        chain="base",
        focus_token="0x" + "1" * 40,
        max_recall=True,
        dex_config=cfg,
    )
    assert h is not None
    assert h.factory_address == ""
    assert h.raw.get("factory_address_source") == ""


def test_aerodrome_ve33_miss_falls_back_to_slipstream():
    """When ve33 factory.getPool returns no pool, verifier tries slipstream.

    DexScreener may label Slipstream pools as generic 'aerodrome' without
    labels. The verifier should try the slipstream factory with V3 fee tiers
    when the ve33 factory returns no pool.
    """
    from m8.discovery.hint_verifier import verify_hint_specialized

    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="aerodrome",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        factory_address="0x420dd381b31aef6683db6b902084cb0ffece40da",
        raw={"support_status": "supported", "raw_dex_id": "aerodrome"},
    )

    with patch(
        "m8.discovery.hint_verifier.verify_factory_pool",
        return_value=(False, "FACTORY_NO_POOL"),
    ), patch(
        "m8.discovery.hint_verifier._try_aerodrome_slipstream_fallback",
        return_value=(True, "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a", 3000),
    ) as mock_slip, patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        out, reason = verify_hint_specialized(hint, chain="base")

    assert reason == "OK"
    assert out.dex_id == "aerodrome_slipstream"
    assert out.fee == 3000
    assert out.factory_address == "0x5e7bb104d84c7cb9b682aac2f3d509f5f406809a"
    assert out.verify_method == "factory_getPool"
    assert (out.raw or {}).get("aerodrome_variant_fallback") == "ve33_to_slipstream"
    mock_slip.assert_called_once()


def test_aerodrome_ve33_miss_slipstream_also_misses():
    """When both ve33 and slipstream fail, hint stays as FACTORY_NO_POOL."""
    from m8.discovery.hint_verifier import verify_hint_specialized

    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="aerodrome",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        factory_address="0x420dd381b31aef6683db6b902084cb0ffece40da",
        raw={"support_status": "supported", "raw_dex_id": "aerodrome"},
    )

    with patch(
        "m8.discovery.hint_verifier.verify_factory_pool",
        return_value=(False, "FACTORY_NO_POOL"),
    ), patch(
        "m8.discovery.hint_verifier._try_aerodrome_slipstream_fallback",
        return_value=(False, "", None),
    ), patch(
        "m8.discovery.hint_verifier._rpc_url", return_value=None
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        out, reason = verify_hint_specialized(hint, chain="base")

    assert reason == "FACTORY_NO_POOL"
    assert out.dex_id == "aerodrome"


def test_aerodrome_slipstream_fallback_not_triggered_for_non_aerodrome():
    """Fallback only triggers for dex_id='aerodrome', not other DEXes."""
    from m8.discovery.hint_verifier import verify_hint_specialized

    hint = PoolHint(
        source="dexscreener",
        chain="base",
        dex_id="uniswap_v2",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        factory_address="0x8909dc15e40173ff4699343b6eb8132c65e18ec6",
        raw={"support_status": "supported", "raw_dex_id": "uniswap_v2"},
    )

    with patch(
        "m8.discovery.hint_verifier.verify_factory_pool",
        return_value=(False, "FACTORY_NO_POOL"),
    ), patch(
        "m8.discovery.hint_verifier._try_aerodrome_slipstream_fallback",
    ) as mock_slip, patch(
        "m8.discovery.hint_verifier._rpc_url", return_value=None
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        out, reason = verify_hint_specialized(hint, chain="base")

    assert reason == "FACTORY_NO_POOL"
    mock_slip.assert_not_called()
