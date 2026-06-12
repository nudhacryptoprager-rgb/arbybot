"""Unit tests for M8.2 candidate DEX smoke (mocked resolver)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from m8.discovery.cross_dex_expand import _resolve_via_factory


def _base_config():
    return {
        "tokens": {
            "WETH": {"address": "0x4200000000000000000000000000000000000006"},
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
        },
        "dexes": {
            "quickswap_algebra": {
                "adapter_type": "algebra",
                "factory": "0xc5396866754799b9720125b104ae01d935ab9c7b",
            },
            "iziswap_base": {
                "adapter_type": "iziswap",
                "factory": "0x8c7d3063579bdb0b90997e18a770eae32e1ebb08",
            },
        },
    }


def test_algebra_resolver_smoke():
    resolver = MagicMock()
    resolver.resolve.return_value = "0xabc12300000000000000000000000000000001"
    pool, reason = _resolve_via_factory(
        "base",
        "quickswap_algebra",
        "WETH",
        "USDC",
        exotic_address="0x4200000000000000000000000000000000000006",
        anchor_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        dry_run=False,
        resolver=resolver,
        config=_base_config(),
    )
    assert reason == "OK"
    assert pool is not None
    resolver.resolve.assert_called()


@patch("m8.discovery.candidate_dex_registry.query_iziswap_pool")
@patch("core.rpc_urls.get_rpc_url")
def test_iziswap_factory_query_smoke(mock_rpc, mock_izi_query):
    mock_rpc.return_value = "http://localhost:8545"
    mock_izi_query.return_value = "0xdef45600000000000000000000000000000002"
    pool, reason = _resolve_via_factory(
        "base",
        "iziswap_base",
        "WETH",
        "USDC",
        exotic_address="0x4200000000000000000000000000000000000006",
        anchor_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        dry_run=False,
        resolver=None,
        config=_base_config(),
    )
    assert reason == "OK"
    assert pool is not None
    mock_izi_query.assert_called()
