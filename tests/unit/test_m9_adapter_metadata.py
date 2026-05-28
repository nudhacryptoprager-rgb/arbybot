"""Unit tests: config-driven adapter metadata wiring (M9 Issue #3, #4, #5).

Covers:
 - adapter_metadata.yaml loadability
 - Curve coin indices flowing from route fields (not hardcoded)
 - Curve fallback to (0, 1) when indices are None
 - Balancer missing pool_id returns structured error (not exception)
 - AdapterMetadata helper methods: curve_indices(), balancer_pool_meta()
"""
from __future__ import annotations

import textwrap
from typing import Optional
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Helper: build a minimal DexRoute with override fields
# ---------------------------------------------------------------------------

def _make_route(
    adapter_type: str = "curve_stable",
    token_in_index: Optional[int] = None,
    token_out_index: Optional[int] = None,
    pool_id: Optional[str] = None,
    vault_address: Optional[str] = None,
    pool_kind: Optional[str] = None,
):
    from m8_1.stable_anchor.pool_discovery import DexRoute

    return DexRoute(
        dex_id="test_dex",
        adapter_type=adapter_type,
        quoter="0x" + "aa" * 20,
        fee=0,
        tick_spacing=None,
        curve_coin0_sym=None,
        hooks=None,
        token_in_index=token_in_index,
        token_out_index=token_out_index,
        pool_id=pool_id,
        vault_address=vault_address,
        pool_kind=pool_kind,
    )


# ---------------------------------------------------------------------------
# DexRoute / GraphEdge field propagation
# ---------------------------------------------------------------------------

class TestDexRouteNewFields:
    def test_fields_default_to_none(self):
        route = _make_route()
        assert route.token_in_index is None
        assert route.token_out_index is None
        assert route.pool_id is None
        assert route.vault_address is None
        assert route.pool_kind is None

    def test_fields_set_explicitly(self):
        route = _make_route(
            token_in_index=1,
            token_out_index=2,
            pool_id="0xabcd" + "0" * 60,
            vault_address="0xBA12222222228d8Ba445958a75a0704d566BF2C8",
            pool_kind="stable",
        )
        assert route.token_in_index == 1
        assert route.token_out_index == 2
        assert route.pool_kind == "stable"


class TestGraphEdgeNewFields:
    def test_fields_present_on_graph_edge(self):
        from m9.graph_arb.models import GraphEdge

        edge = GraphEdge(
            token_in_sym="USDC",
            token_out_sym="USDT",
            token_in_addr="0x" + "00" * 20,
            token_out_addr="0x" + "11" * 20,
            token_in_decimals=6,
            token_out_decimals=6,
            route_id="r1",
            dex_id="curve",
            adapter_type="curve_stable",
            fee=0,
            tick_spacing=None,
            quoter_addr="0x" + "aa" * 20,
            pool_address="0x" + "cc" * 20,
            fee_bps=1.0,
            factory_class="CurveFactory",
            pair_id="USDC_USDT",
            factory_verified=True,
            hooks=None,
            token_in_index=0,
            token_out_index=1,
            pool_id=None,
            vault_address=None,
            pool_kind="stable",
        )
        assert edge.token_in_index == 0
        assert edge.token_out_index == 1
        assert edge.pool_kind == "stable"


# ---------------------------------------------------------------------------
# Curve: config-driven indices in raw_http_probe calldata
# ---------------------------------------------------------------------------

class TestCurveConfigDrivenIndices:
    """Verify calldata uses route.token_in_index / token_out_index."""

    def _capture_calldata(self, idx_in: Optional[int], idx_out: Optional[int]) -> str:
        """Build a fake raw_http_probe call and capture the calldata passed to eth_call."""
        from m9.graph_arb import raw_http_probe as probe
        from m8_1.stable_anchor.pool_discovery import DexRoute
        from m8_1.stable_anchor.pairs import TokenInfo

        route = _make_route(
            adapter_type="curve_stable",
            token_in_index=idx_in,
            token_out_index=idx_out,
        )
        token_in = TokenInfo(symbol="USDC", address="0x" + "aa" * 20, decimals=6)
        token_out = TokenInfo(symbol="USDT", address="0x" + "bb" * 20, decimals=6)

        captured: list = []

        def fake_eth_call(rpc_url, to, calldata, client):
            captured.append(calldata)
            # Return 32 bytes encoding of amount_out=1000000
            return "0x" + (1_000_000).to_bytes(32, "big").hex()

        with patch.object(probe, "_eth_call_raw", side_effect=fake_eth_call):
            probe.probe_quote_raw_http(
                rpc_url="http://localhost:8545",
                route=route,
                token_in=token_in,
                token_out=token_out,
                amount_in=1_000_000,
            )

        assert captured, "eth_call was not invoked"
        return captured[0]

    def test_explicit_indices_used_in_calldata(self):
        """Non-default indices (1, 2) must appear in calldata."""
        calldata = self._capture_calldata(1, 2)
        # 5e0d443f | i (32 bytes) | j (32 bytes) | dx (32 bytes)
        assert calldata.startswith("0x5e0d443f"), f"Wrong selector: {calldata[:10]}"
        # Index 1 = 0x00...01 at bytes 4-35
        idx_in_hex = calldata[10:74]  # 4 bytes selector skip + 64 chars for 32 bytes
        idx_out_hex = calldata[74:138]
        assert int(idx_in_hex, 16) == 1, f"Expected idx_in=1, got {int(idx_in_hex,16)}"
        assert int(idx_out_hex, 16) == 2, f"Expected idx_out=2, got {int(idx_out_hex,16)}"

    def test_fallback_to_zero_one_when_none(self):
        """When route.token_in_index is None, must fall back to 0/1."""
        calldata = self._capture_calldata(None, None)
        assert calldata.startswith("0x5e0d443f")
        idx_in_hex = calldata[10:74]
        idx_out_hex = calldata[74:138]
        assert int(idx_in_hex, 16) == 0, "Expected fallback idx_in=0"
        assert int(idx_out_hex, 16) == 1, "Expected fallback idx_out=1"

    def test_reversed_direction_indices(self):
        """Index 1→0 (reversed swap) must be encoded correctly."""
        calldata = self._capture_calldata(1, 0)
        idx_in_hex = calldata[10:74]
        idx_out_hex = calldata[74:138]
        assert int(idx_in_hex, 16) == 1
        assert int(idx_out_hex, 16) == 0


# ---------------------------------------------------------------------------
# Balancer: missing pool_id returns structured error (not exception)
# ---------------------------------------------------------------------------

class TestBalancerMissingPoolId:
    def test_raw_http_probe_returns_error_not_exception(self):
        from m9.graph_arb import raw_http_probe as probe
        from m8_1.stable_anchor.pairs import TokenInfo

        route = _make_route(
            adapter_type="balancer_stable",
            pool_id=None,  # missing
        )
        token_in = TokenInfo(symbol="USDC", address="0x" + "aa" * 20, decimals=6)
        token_out = TokenInfo(symbol="USDT", address="0x" + "bb" * 20, decimals=6)

        result = probe.probe_quote_raw_http(
            rpc_url="http://localhost:8545",
            route=route,
            token_in=token_in,
            token_out=token_out,
            amount_in=1_000_000,
        )
        assert not result.ok
        assert result.reject_reason == "QUOTE_CONFIG_MISSING__BALANCER_POOL_ID"

    def test_quote_probe_returns_error_for_missing_pool_id(self):
        """quote_probe (web3 path) swallows ValueError → returns ok=False with error detail."""
        from m8_1.stable_anchor import quote_probe as probe
        from m8_1.stable_anchor.pairs import TokenInfo

        route = _make_route(
            adapter_type="balancer_stable",
            pool_id=None,
        )
        token_in = TokenInfo(symbol="USDC", address="0x" + "aa" * 20, decimals=6)
        token_out = TokenInfo(symbol="USDT", address="0x" + "bb" * 20, decimals=6)

        mock_w3 = MagicMock()

        result = probe.probe_quote(
            w3=mock_w3,
            route=route,
            token_in=token_in,
            token_out=token_out,
            amount_in=1_000_000,
        )
        assert not result.ok
        assert result.raw_error is not None
        assert "pool_id" in result.raw_error or "balancer" in result.raw_error.lower()


# ---------------------------------------------------------------------------
# AdapterMetadata YAML loader
# ---------------------------------------------------------------------------

class TestAdapterMetadataLoader:
    def test_yaml_loadable(self):
        """config/adapter_metadata.yaml must parse without error."""
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata("config/adapter_metadata.yaml")
        assert meta is not None

    def test_empty_registry_on_missing_file(self, tmp_path):
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata(str(tmp_path / "nonexistent.yaml"))
        assert meta.curve_pools == {}
        assert meta.balancer_pools == {}

    def test_malformed_yaml_returns_empty(self, tmp_path):
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        bad = tmp_path / "bad.yaml"
        bad.write_text(": {not valid yaml :", encoding="utf-8")
        meta = load_adapter_metadata(str(bad))
        assert meta.curve_pools == {}

    def test_curve_indices_from_yaml(self, tmp_path):
        """Minimal YAML with a Curve pool returns correct indices."""
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        yaml_content = textwrap.dedent("""
            curve:
              base:
                pools:
                  "0xaaaa000000000000000000000000000000000000":
                    pool_kind: stable
                    coin_indices:
                      USDC: 0
                      USDT: 1
        """)
        f = tmp_path / "meta.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        meta = load_adapter_metadata(str(f))

        idx_in, idx_out = meta.curve_indices(
            "0xaaaa000000000000000000000000000000000000", "USDC", "USDT", chain="base"
        )
        assert idx_in == 0
        assert idx_out == 1

        # Reversed direction
        idx_in_r, idx_out_r = meta.curve_indices(
            "0xaaaa000000000000000000000000000000000000", "USDT", "USDC", chain="base"
        )
        assert idx_in_r == 1
        assert idx_out_r == 0

    def test_curve_unknown_pool_returns_none(self, tmp_path):
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        f = tmp_path / "meta.yaml"
        f.write_text("{}\n", encoding="utf-8")
        meta = load_adapter_metadata(str(f))
        idx_in, idx_out = meta.curve_indices("0xunknown", "USDC", "USDT")
        assert idx_in is None
        assert idx_out is None

    def test_balancer_pool_meta_from_yaml(self, tmp_path):
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        pool_id = "0x" + "ab" * 32
        pool_addr = "0x" + "ab" * 20
        tok0 = "0x" + "aa" * 20
        tok1 = "0x" + "bb" * 20
        yaml_content = textwrap.dedent(f"""
            balancer:
              vault_address: "0xba12222222228d8ba445958a75a0704d566bf2c8"
              base:
                pools:
                  "{pool_id}":
                    pool_address: "{pool_addr}"
                    pool_kind: stable
                    assets:
                      - "{tok0}"
                      - "{tok1}"
        """)
        f = tmp_path / "meta.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        meta = load_adapter_metadata(str(f))

        bpool = meta.balancer_pool_meta(pool_addr, chain="base")
        assert bpool is not None
        assert bpool.pool_id == pool_id.lower()
        assert bpool.pool_kind == "stable"

    def test_balancer_vault_address_canonical(self):
        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        meta = load_adapter_metadata("config/adapter_metadata.yaml")
        vault = meta.balancer_vault_address()
        # Should be canonical Balancer Vault
        assert vault.lower() == "0xba12222222228d8ba445958a75a0704d566bf2c8"


# ---------------------------------------------------------------------------
# quoter._make_dex_route propagation
# ---------------------------------------------------------------------------

class TestMakeDexRoutePropagation:
    def test_all_five_fields_propagated(self):
        from m9.graph_arb.quoter import _make_dex_route
        from m9.graph_arb.models import GraphEdge

        edge = GraphEdge(
            token_in_sym="USDC",
            token_out_sym="USDT",
            token_in_addr="0x" + "00" * 20,
            token_out_addr="0x" + "11" * 20,
            token_in_decimals=6,
            token_out_decimals=6,
            route_id="r1",
            dex_id="curve",
            adapter_type="curve_stable",
            fee=0,
            tick_spacing=None,
            quoter_addr="0x" + "aa" * 20,
            pool_address="0x" + "cc" * 20,
            fee_bps=1.0,
            factory_class="CF",
            pair_id="USDC_USDT",
            factory_verified=True,
            hooks=None,
            token_in_index=0,
            token_out_index=1,
            pool_id="0x" + "dd" * 32,
            vault_address="0x" + "ee" * 20,
            pool_kind="stable",
        )
        route = _make_dex_route(edge)
        assert route.token_in_index == 0
        assert route.token_out_index == 1
        assert route.pool_id == "0x" + "dd" * 32
        assert route.vault_address == "0x" + "ee" * 20
        assert route.pool_kind == "stable"


# ---------------------------------------------------------------------------
# Config validation: check_curve_pools_configured
# ---------------------------------------------------------------------------

class TestCheckCurvePoolsConfigured:
    """Verify that check_curve_pools_configured detects pools missing from metadata."""

    def test_empty_metadata_flags_all_pools(self):
        from m9.graph_arb.adapter_metadata import AdapterMetadata, check_curve_pools_configured

        meta = AdapterMetadata()  # no pools
        pools = ["0x70d410b739da81303a76169cdd406a746bde8b34"]
        missing = check_curve_pools_configured(meta, pools)
        assert "0x70d410b739da81303a76169cdd406a746bde8b34" in missing

    def test_configured_pool_not_in_missing_list(self, tmp_path):
        import textwrap
        from m9.graph_arb.adapter_metadata import load_adapter_metadata, check_curve_pools_configured

        yaml_content = textwrap.dedent("""
            curve:
              base:
                pools:
                  "0x70d410b739da81303a76169cdd406a746bde8b34":
                    pool_kind: stable
                    coin_indices:
                      USDC: 0
                      MONEY: 1
        """)
        f = tmp_path / "meta.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        meta = load_adapter_metadata(str(f))

        pools = ["0x70d410b739da81303a76169cdd406a746bde8b34"]
        missing = check_curve_pools_configured(meta, pools)
        assert missing == [], f"Expected no missing pools, got: {missing}"

    def test_partial_configuration_flags_unconfigured_only(self, tmp_path):
        import textwrap
        from m9.graph_arb.adapter_metadata import load_adapter_metadata, check_curve_pools_configured

        yaml_content = textwrap.dedent("""
            curve:
              base:
                pools:
                  "0x70d410b739da81303a76169cdd406a746bde8b34":
                    pool_kind: stable
                    coin_indices:
                      USDC: 0
                      MONEY: 1
        """)
        f = tmp_path / "meta.yaml"
        f.write_text(yaml_content, encoding="utf-8")
        meta = load_adapter_metadata(str(f))

        # One known pool + one unknown pool
        pools = [
            "0x70d410b739da81303a76169cdd406a746bde8b34",  # configured
            "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef",  # not configured
        ]
        missing = check_curve_pools_configured(meta, pools)
        assert "0x70d410b739da81303a76169cdd406a746bde8b34" not in missing
        assert "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef" in missing

    def test_address_normalised_to_lowercase(self):
        from m9.graph_arb.adapter_metadata import AdapterMetadata, check_curve_pools_configured

        meta = AdapterMetadata()
        # Pass mixed-case address — result should be lowercase
        missing = check_curve_pools_configured(meta, ["0xDEADBEEFDEADBEEFDEADBEEFDEADBEEFDEADBEEF"])
        assert "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef" in missing

    def test_empty_pool_list_returns_empty(self):
        from m9.graph_arb.adapter_metadata import AdapterMetadata, check_curve_pools_configured

        meta = AdapterMetadata()
        assert check_curve_pools_configured(meta, []) == []

    def test_real_config_adapter_metadata_has_curve_pools(self):
        """Smoke-check: config/adapter_metadata.yaml now has real Curve pool entries."""
        from m9.graph_arb.adapter_metadata import load_adapter_metadata

        meta = load_adapter_metadata("config/adapter_metadata.yaml")
        # Two pools should be present after Step 1
        assert "base" in meta.curve_pools, "No 'base' chain in curve_pools"
        assert len(meta.curve_pools["base"]) >= 2, (
            f"Expected >=2 Curve pools on Base, got {len(meta.curve_pools['base'])}"
        )

