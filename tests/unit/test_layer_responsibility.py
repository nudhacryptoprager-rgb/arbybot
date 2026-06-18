"""Layer responsibility and M8.3 authority tests."""
from __future__ import annotations

from m8.metadata.registry import M8_3_DECIMALS_SOURCE_PREFIX, apply_registry_to_route
from m9.graph_arb.token_decimals import (
    enrich_route_decimals,
    is_economics_grade_decimals_source,
    is_m8_3_decimals_source,
)


def test_m8_3_provenance_not_overwritten_by_legacy_enrich():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    route = {
        "token0_addr": addr,
        "token1_addr": "0x4200000000000000000000000000000000000006",
        "token0_decimals": 6,
        "token0_decimals_source": f"{M8_3_DECIMALS_SOURCE_PREFIX}erc20_call",
        "token1_decimals": None,
    }
    enrich_route_decimals(route, missing_only=True, preserve_m8_3=True)
    assert route["token0_decimals"] == 6
    assert route["token0_decimals_source"] == f"{M8_3_DECIMALS_SOURCE_PREFIX}erc20_call"
    assert route["token1_decimals"] == 18


def test_m8_3_source_is_economics_grade():
    src = f"{M8_3_DECIMALS_SOURCE_PREFIX}erc20_call"
    assert is_m8_3_decimals_source(src)
    assert is_economics_grade_decimals_source(src)
    hint = f"{M8_3_DECIMALS_SOURCE_PREFIX}external_hint"
    assert not is_economics_grade_decimals_source(hint)


def test_apply_registry_sets_m8_3_provenance():
    addr = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    registry = {
        "tokens": {
            addr.lower(): {
                "decimals": 6,
                "source": "erc20_call",
                "economics_grade": "verified_onchain",
            }
        }
    }
    route = {"token0_addr": addr, "token1_addr": "0x4200000000000000000000000000000000000006"}
    apply_registry_to_route(route, registry)
    assert route["token0_decimals_source"].startswith(M8_3_DECIMALS_SOURCE_PREFIX)


def test_audit_layer_responsibility_passes():
    from scripts.audit_layer_responsibility import run_audit

    result = run_audit(strict=True)
    assert result["ok"] is True
