from __future__ import annotations

from m8.metadata.contracts import MetadataTask
from typing import Dict
from m8.metadata.dex.erc20 import Erc20TokenWorker
from m8.metadata.negative_cache import (
    TokenNegativeCache,
    collect_cycle_scope_token_addresses,
    is_negative_cache_eligible,
)
from m8.metadata.registry import ERROR_NON_ERC20, is_economics_grade_entry


def test_negative_cache_ttl_hit():
    cache = TokenNegativeCache(ttl_s=3600.0)
    cache.put("base", "0xabc", ERROR_NON_ERC20, code_length=0)
    assert cache.get("base", "0xabc", code_length=0) == ERROR_NON_ERC20


def test_cycle_scope_bypasses_negative_cache():
    cache = TokenNegativeCache()
    scope = {"0xabc"}
    assert cache.should_bypass("0xabc", scope) is True
    assert cache.should_bypass("0xdef", scope) is False


def test_collect_cycle_scope_token_addresses_from_bridge():
    bridge = {
        "active_routes": [
            {
                "route_id": "r1",
                "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token1_addr": "0x4200000000000000000000000000000000000006",
            }
        ]
    }
    capacity = {
        "enrichment_targets": {"route_ids": ["r1"]},
    }
    addrs = collect_cycle_scope_token_addresses(bridge, capacity=capacity)
    assert "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913" in addrs


def test_negative_cache_does_not_hide_economics_grade_prior():
    prior = {
        "decimals": 18,
        "source": "erc20_call",
        "economics_grade": "verified_onchain",
    }
    assert is_economics_grade_entry(prior) is True
    assert is_negative_cache_eligible(ERROR_NON_ERC20) is True


def test_aggregator_negative_cache_skips_reprobe(monkeypatch):
    from m8.metadata import aggregator as agg

    calls: Dict[str, int] = {}

    class _StubWorker:
        worker_id = "erc20_token"

        def build_task(self, address, **kwargs):
            return MetadataTask(
                task_id=f"erc20:{address}",
                kind="token_erc20",
                worker_id=self.worker_id,
                address=address,
            )

        def process(self, task, **kwargs):
            calls[task.address] = calls.get(task.address, 0) + 1
            from m8.metadata.contracts import TokenMetadataResult

            return TokenMetadataResult(address=task.address, error_code=ERROR_NON_ERC20)

    monkeypatch.setattr(agg, "Erc20TokenWorker", lambda: _StubWorker())
    monkeypatch.setattr(agg, "all_dex_workers", lambda: [])
    monkeypatch.setattr(agg, "assign_route_worker", lambda *a, **k: None)

    _DEAD = "0x" + "d" * 40
    prior = {
        "negative_cache": {
            "entries": {
                f"base:{_DEAD}:len:0": {
                    "error_code": ERROR_NON_ERC20,
                    "cached_at_epoch_s": 9_999_999_999.0,
                }
            },
            "ttl_s": 999999,
        }
    }
    bridge = {
        "active_routes": [
            {
                "route_id": "r_dead",
                "token0_addr": _DEAD,
                "token1_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
            }
        ]
    }
    monkeypatch.setattr(
        "m8.metadata.token_risk.build_token_preflight_bundle",
        lambda *a, **k: {
            "token_execution_preflight": {},
            "token_risk_flags": {},
            "proxy_metadata": {},
            "token_risk_metadata": {},
        },
    )
    doc = agg.build_aggregated_registry(
        bridge=bridge,
        prior_registry=prior,
        with_dex_workers=False,
        w3=object(),
    )
    row = doc["token_registry"][_DEAD]
    assert row.get("negative_cache_hit") is True
    assert calls.get(_DEAD, 0) == 0
