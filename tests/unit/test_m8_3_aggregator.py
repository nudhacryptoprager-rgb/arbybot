"""Unit tests for M8.3 root metadata aggregator."""
from __future__ import annotations

from m8.metadata.acceptance import evaluate_m8_3_acceptance
from m8.metadata.aggregator import build_aggregated_registry, get_token_registry
from m8.metadata.registry import SCHEMA_VERSION


def test_aggregated_registry_schema_sections():
    bridge = {
        "active_routes": [
            {
                "route_id": "crv_r1",
                "adapter_type": "curve_stable",
                "dex_id": "curve_stable",
                "pool_address": "0x" + "1" * 40,
                "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token1_addr": "0x4200000000000000000000000000000000000006",
                "coin_indices": {"USDC": 0, "WETH": 1},
            },
            {
                "route_id": "v4_r1",
                "adapter_type": "uniswap_v4",
                "dex_id": "uniswap_v4",
                "pool_address": "0x" + "2" * 40,
                "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "token1_addr": "0x4200000000000000000000000000000000000006",
                "fee": 500,
                "tick_spacing": 10,
                "hooks": "0x" + "0" * 40,
            },
        ]
    }
    doc = build_aggregated_registry(bridge=bridge, with_dex_workers=True, w3=None)
    assert doc["schema_version"] == SCHEMA_VERSION
    assert doc["authority_contract"] == "m8_3_aggregated_metadata_authority"
    assert "token_registry" in doc
    assert "dex_route_metadata" in doc
    assert "task_funnel" in doc
    assert "token_execution_preflight" in doc
    assert "token_risk_flags" in doc
    assert "proxy_metadata" in doc
    assert doc["preflight_contract"] == "metadata_risk_pool_identity_v2"
    assert "unsupported_metadata_workers" in doc
    tokens = get_token_registry(doc)
    assert len(tokens) >= 2
    dex = doc["dex_route_metadata"]["by_route_id"]
    assert dex["crv_r1"]["worker_id"] == "curve"
    assert dex["v4_r1"]["worker_id"] == "uniswap_v4"


def test_aggregated_acceptance_split_gates():
    doc = {
        "schema_version": SCHEMA_VERSION,
        "token_registry": {},
        "tokens": {},
        "coverage": {"decimals_conflict_count": 0},
        "route_coverage": {
            "cycle_participating_routes": {
                "legs_total": 10,
                "economics_grade_known_rate": 0.96,
            },
            "econ_capacity_routes": {"routes_count": 0},
        },
        "dex_route_metadata": {
            "coverage": {
                "cycle_participating_routes": {
                    "routes_count": 5,
                    "dex_metadata_ready_rate": 0.96,
                }
            }
        },
    }
    report = evaluate_m8_3_acceptance(doc, strict=True)
    assert "token_metadata_gates" in report
    assert "dex_route_metadata_gates" in report
    assert report["token_metadata_gates"]["cycle_participating_token_metadata_rate"] == 0.96


def test_aggregator_registry_refresh_no_fee_on_transfer_for_standard_erc20():
    from unittest.mock import MagicMock

    from m8.metadata.aggregator import build_aggregated_registry

    w3 = MagicMock()
    code = bytes.fromhex("63a9059cbb" + "00" * 12 + "63095ea7b3" + "00" * 12)
    w3.eth.get_code.return_value = code
    w3.to_checksum_address.side_effect = lambda a: a

    usdc = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
    doc = build_aggregated_registry(
        bridge={
            "active_routes": [
                {
                    "route_id": "r1",
                    "adapter_type": "uniswap_v3",
                    "token0_addr": usdc,
                    "token1_addr": "0x4200000000000000000000000000000000000006",
                    "pool_address": "0x" + "1" * 40,
                    "fee": 500,
                }
            ]
        },
        with_dex_workers=False,
        w3=w3,
        onchain_unresolved_only=False,
    )
    flags = (doc.get("token_risk_flags") or {}).get("by_address") or {}
    assert flags.get(usdc.lower(), {}).get("fee_on_transfer_suspected") is False


def test_prior_code_unchanged_rejects_same_length_different_hash():
    import hashlib
    from unittest.mock import MagicMock, patch

    from m8.metadata.aggregator import _prior_code_unchanged

    w3 = MagicMock()
    addr = "0x" + "c" * 40
    code_a = b"\x01" * 120
    code_b = b"\x02" * 120
    prior_hash = "0x" + hashlib.sha256(code_a).hexdigest()
    prior = {"code_hash": prior_hash, "code_length": 120}

    with patch("m8.metadata.token_risk._fetch_code", return_value=code_b):
        assert _prior_code_unchanged(w3, addr, prior) is False
    with patch("m8.metadata.token_risk._fetch_code", return_value=code_a):
        assert _prior_code_unchanged(w3, addr, prior) is True


def test_worker_diagnostics_in_acceptance():
    doc = build_aggregated_registry(
        bridge={
            "active_routes": [
                {
                    "route_id": "mav_r1",
                    "adapter_type": "maverick_v2",
                    "pool_address": "0x" + "3" * 40,
                    "token0_addr": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                    "token1_addr": "0x4200000000000000000000000000000000000006",
                }
            ]
        },
        with_dex_workers=True,
        w3=None,
    )
    report = evaluate_m8_3_acceptance(doc, strict=False)
    assert "token_risk_warnings" in report
    assert report["token_risk_warnings"].get("warning_only") is True
    assert "risk_metadata_warnings" in report
    assert "pool_identity_gates" in report
    diag = report["diagnostics"]
    assert "tasks_assigned" in diag
    assert "worker_error_histogram" in diag
    assert "per_dex_route_metadata_ready" in diag
    assert "token_task_funnel" in diag
    assert "dex_route_task_funnel" in diag


def test_aggregator_reprobes_cached_token_when_code_changes(monkeypatch):
    from m8.metadata import aggregator as agg
    from m8.metadata.contracts import TokenMetadataResult

    token = "0x" + "a" * 40
    calls: list[str] = []

    class StubWorker:
        worker_id = "erc20_token"

        def build_task(self, address, **_kwargs):
            from m8.metadata.contracts import MetadataTask

            return MetadataTask(
                task_id=f"erc20:{address}",
                kind="token_erc20",
                worker_id=self.worker_id,
                address=address,
            )

        def process(self, task, **_kwargs):
            calls.append(task.address)
            return TokenMetadataResult(
                address=task.address,
                decimals=18,
                source="erc20_call",
                economics_grade="verified_onchain",
                code_length=2,
            )

    monkeypatch.setattr(agg, "Erc20TokenWorker", lambda: StubWorker())
    monkeypatch.setattr(agg, "_prior_code_unchanged", lambda *_args: False)
    monkeypatch.setattr(
        "m8.metadata.erc20_multicall_prefetch.prefetch_erc20_metadata",
        lambda *_args, **_kwargs: {},
    )
    monkeypatch.setattr(
        "m8.metadata.token_risk.build_token_preflight_bundle",
        lambda *_args, **_kwargs: {
            "token_execution_preflight": {},
            "token_risk_flags": {},
            "proxy_metadata": {},
            "token_risk_metadata": {},
        },
    )

    doc = agg.build_aggregated_registry(
        bridge={"active_routes": [{"route_id": "r1", "token0_addr": token}]},
        prior_registry={
            "token_registry": {
                token: {
                    "address": token,
                    "decimals": 18,
                    "source": "erc20_call",
                    "economics_grade": "verified_onchain",
                    "code_length": 1,
                }
            }
        },
        w3=object(),
        with_dex_workers=False,
    )

    assert token in calls
    assert doc["token_registry"][token]["code_length"] == 2
