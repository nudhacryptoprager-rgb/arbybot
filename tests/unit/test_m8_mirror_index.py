"""Unit tests for M8.2 specialized mirror index loaders."""
from __future__ import annotations

import json
from pathlib import Path

from m8.discovery.cross_dex_expand import expand_cross_dex
from m8.discovery.mirror_index import MirrorIndex, probe_is_quotable


def test_probe_is_quotable_prefix():
    assert probe_is_quotable("QUOTE_OK_STABLE")
    assert probe_is_quotable(None)
    assert not probe_is_quotable("QUOTE_REVERT")


def test_curve_rolling_index_match(tmp_path: Path):
    discovery = tmp_path / "curve_discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "schema_version": "m9_curve_discovery.1",
                "chain": "base",
                "discovered_pools": [
                    {
                        "pool_address": "0x70d410b739da81303a76169cdd406a746bde8b34",
                        "pool_kind": "stable",
                        "coin_indices": {"USDC": 0, "MONEY": 1},
                        "coin_addresses": [
                            "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                            "0x69420f9e38a4e60a62224c489be4bf7a94402496",
                        ],
                        "probe_status": "QUOTE_OK_STABLE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    idx = MirrorIndex.load(
        "base",
        curve_discovery_path=discovery,
        curve_indices_path=tmp_path / "missing_indices.json",
        balancer_index_path=tmp_path / "missing_bal.json",
        maverick_index_path=tmp_path / "missing_mav.json",
    )
    found, reason = idx.resolve_curve(
        "MONEY",
        "USDC",
        exotic_address="0x69420f9e38a4e60a62224c489be4bf7a94402496",
        anchor_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    )
    assert reason == "OK"
    assert found is not None
    assert found["resolve_source"] == "curve_rolling_index"
    assert found["pool_kind"] == "stable"
    assert found["coin_indices"] == {"USDC": 0, "MONEY": 1}


def test_balancer_pool_id_required(tmp_path: Path):
    bal = tmp_path / "balancer.json"
    bal.write_text(
        json.dumps(
            {
                "schema_version": "m8_balancer_pool_index.1",
                "chain": "base",
                "vault_address": "0xba12222222228d8ba445958a75a0704d566bf2c8",
                "pools": [
                    {
                        "pool_id": "0x79fe0750be76913e83a0f0eb60ba1ab7fa6fda5d00020000000000000000019f",
                        "pool_address": "0x79fe0750be76913e83a0f0eb60ba1ab7fa6fda5d",
                        "pool_kind": "stable",
                        "assets": [
                            "0x4ea71a20e655794051d1ee8b6e4a3269b13ccacc",
                            "0xca5d8f8a8d49439357d3cf46ca2e720702f132b8",
                        ],
                        "probe_status": "QUOTE_OK_VAULT_VERIFY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    idx = MirrorIndex.load(
        "base",
        curve_discovery_path=tmp_path / "c.json",
        curve_indices_path=tmp_path / "ci.json",
        balancer_index_path=bal,
        maverick_index_path=tmp_path / "m.json",
    )
    found, reason = idx.resolve_balancer(
        "GYD",
        "AaveUSDC",
        exotic_address="0xca5d8f8a8d49439357d3cf46ca2e720702f132b8",
        anchor_address="0x4ea71a20e655794051d1ee8b6e4a3269b13ccacc",
    )
    assert reason == "OK"
    assert found["pool_id"].startswith("0x79fe")
    assert found["resolve_source"] == "balancer_pool_index"


def test_maverick_pending_when_not_quoteable(tmp_path: Path):
    mav = tmp_path / "maverick.json"
    mav.write_text(
        json.dumps(
            {
                "schema_version": "m8_maverick_pool_index.1",
                "chain": "base",
                "pools": [
                    {
                        "pool_address": "0xabc1234567890123456789012345678901234567",
                        "token_a": "0x1111111111111111111111111111111111111111",
                        "token_b": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                        "probe_status": "INDEXED_ONLY",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    idx = MirrorIndex.load(
        "base",
        curve_discovery_path=tmp_path / "c.json",
        curve_indices_path=tmp_path / "ci.json",
        balancer_index_path=tmp_path / "b.json",
        maverick_index_path=mav,
    )
    found, reason = idx.resolve_maverick(
        "FOO",
        "USDC",
        exotic_address="0x1111111111111111111111111111111111111111",
        anchor_address="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
    )
    assert found is None
    assert reason == "MAVERICK_INDEXED_BUT_NOT_QUOTEABLE"


def test_expand_curve_resolves_without_adapter_pending(monkeypatch, tmp_path: Path):
    discovery = tmp_path / "curve_discovery.json"
    discovery.write_text(
        json.dumps(
            {
                "schema_version": "m9_curve_discovery.1",
                "chain": "base",
                "discovered_pools": [
                    {
                        "pool_address": "0x70d410b739da81303a76169cdd406a746bde8b34",
                        "pool_kind": "stable",
                        "coin_indices": {"USDC": 0, "MONEY": 1},
                        "probe_status": "QUOTE_OK_STABLE",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    import m8.discovery.mirror_index as mi

    monkeypatch.setattr(mi, "DEFAULT_CURVE_DISCOVERY", discovery)
    monkeypatch.setattr(mi, "DEFAULT_CURVE_INDICES", tmp_path / "ci.json")
    monkeypatch.setattr(mi, "DEFAULT_BALANCER_INDEX", tmp_path / "b.json")
    monkeypatch.setattr(mi, "DEFAULT_MAVERICK_INDEX", tmp_path / "m.json")

    registry = {
        "tokens": {
            "0x69420f9e38a4e60a62224c489be4bf7a94402496": {
                "symbol": "MONEY",
                "anchors": ["USDC"],
                "venues": {
                    "u::0xpool1": {
                        "dex": "uniswap_v3",
                        "pool": "0xpool1",
                        "token0_symbol": "MONEY",
                        "token1_symbol": "USDC",
                        "token0": "0x69420f9e38a4e60a62224c489be4bf7a94402496",
                        "token1": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    },
                },
            }
        }
    }
    cfg = {
        "chain": "base",
        "tokens": {
            "USDC": {"address": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"},
            "MONEY": {"address": "0x69420f9e38a4e60a62224c489be4bf7a94402496"},
        },
        "dexes": {
            "uniswap_v3": {"adapter_type": "uniswap_v3", "enabled": True},
            "curve_stable": {"adapter_type": "curve_stable", "enabled": True},
        },
        "m9_dex_productivity": {
            "uniswap_v3": {
                "enabled_for_discovery": True,
                "enabled_for_productive": True,
            },
            "curve_stable": {
                "enabled_for_discovery": True,
                "enabled_for_productive": False,
            },
        },
    }
    art = expand_cross_dex(
        chain="base",
        config=cfg,
        registry=registry,
        anchor_artifact=None,
        dry_run=False,
    )
    hist = art.get("reject_reason_histogram") or {}
    assert hist.get("ADAPTER_RESOLVE_PENDING", 0) == 0
    curve_routes = [r for r in art["routes_admitted"] if r["dex_id"] == "curve_stable"]
    assert curve_routes
    assert curve_routes[0].get("resolve_source") == "curve_rolling_index"
