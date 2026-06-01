"""Unit tests for M9 pool depth probe pricing helpers."""
from __future__ import annotations

from m9.graph_arb import pool_depth_probe as probe


def _encoded_reserves(reserve0: int, reserve1: int) -> str:
    return "0x" + reserve0.to_bytes(32, "big").hex() + reserve1.to_bytes(32, "big").hex() + (0).to_bytes(32, "big").hex()


class TestV2FeeAwareAmountOut:
    def test_v2_fee_bps_changes_amount_out(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        token0 = "0x" + "00" * 19 + "01"
        token1 = "0x" + "00" * 19 + "02"

        out_30_bps = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=30,
        )
        out_20_bps = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=20,
        )

        assert out_20_bps is not None
        assert out_30_bps is not None
        assert out_20_bps > out_30_bps

    def test_v2_reverse_token_order_uses_reverse_reserves(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        token0 = "0x" + "00" * 19 + "01"
        token1 = "0x" + "00" * 19 + "02"

        forward = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token0,
            token1,
            10_000,
            "http://rpc",
            fee_bps=30,
        )
        reverse = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            token1,
            token0,
            10_000,
            "http://rpc",
            fee_bps=30,
        )

        assert forward is not None
        assert reverse is not None
        assert forward > reverse

    def test_invalid_v2_fee_returns_none(self, monkeypatch):
        monkeypatch.setattr(
            probe,
            "_raw_eth_call",
            lambda rpc_url, to, data: _encoded_reserves(1_000_000, 2_000_000),
        )

        amount_out = probe._v2_amount_out_from_reserves(
            "0x" + "aa" * 20,
            "0x" + "00" * 19 + "01",
            "0x" + "00" * 19 + "02",
            10_000,
            "http://rpc",
            fee_bps=10_000,
        )

        assert amount_out is None


class TestRouteV2FeeBps:
    def test_route_fee_takes_precedence(self):
        assert probe._route_v2_fee_bps({"fee": 25, "fee_bps": 30.0}) == 25

    def test_route_fee_bps_fallback(self):
        assert probe._route_v2_fee_bps({"fee": 0, "fee_bps": 20.0}) == 20

    def test_route_fee_default(self):
        assert probe._route_v2_fee_bps({"fee": 0}) == 30

    def test_route_fee_adapter_type_lookup(self):
        """Per-adapter-type map used when neither fee nor fee_bps present."""
        assert probe._route_v2_fee_bps({"adapter_type": "uniswap_v2"}) == 30
        assert probe._route_v2_fee_bps({"adapter_type": "sushiswap_v2"}) == 30
        assert probe._route_v2_fee_bps({"adapter_type": "baseswap_v2"}) == 30

    def test_route_fee_unknown_adapter_uses_global_default(self):
        """Unknown adapter type falls back to _DEFAULT_V2_FEE_BPS."""
        assert probe._route_v2_fee_bps({"adapter_type": "some_v2_fork"}) == 30


class TestVe33AdapterTypes:
    """Verify that _VE33_ADAPTER_TYPES includes all Solidly variants."""

    def test_generic_ve33_in_set(self):
        assert "ve33" in probe._VE33_ADAPTER_TYPES

    def test_ve33_stable_in_set(self):
        assert "ve33_stable" in probe._VE33_ADAPTER_TYPES

    def test_aerodrome_stable_in_set(self):
        """aerodrome_stable pools use the same getAmountOut(amount, tokenIn) interface."""
        assert "aerodrome_stable" in probe._VE33_ADAPTER_TYPES

    def test_solidly_stable_in_set(self):
        assert "solidly_stable" in probe._VE33_ADAPTER_TYPES

    def test_uniswap_v3_not_in_ve33_set(self):
        """uniswap_v3 uses a different quoter; must not be in VE33 adapter set."""
        assert "uniswap_v3" not in probe._VE33_ADAPTER_TYPES

    def test_uniswap_v2_not_in_ve33_set(self):
        """uniswap_v2 uses getReserves; must not be in VE33 adapter set."""
        assert "uniswap_v2" not in probe._VE33_ADAPTER_TYPES


# ---------------------------------------------------------------------------
# Package #8: M8 long-tail anchor-side marginal depth enrichment
# ---------------------------------------------------------------------------


def _u256(value: int) -> str:
    return "0x" + value.to_bytes(32, "big").hex()


class TestComputeMarginalDepth:
    """Price-agnostic two-point marginal depth math (no RPC, no decimals)."""

    def test_no_impact_full_depth(self):
        # Linear pool: probe rate equals ref rate → impact 0 → full probe depth.
        res = probe.compute_marginal_depth(
            ref_in=2_000_000, ref_out=2_000,
            probe_in=100_000_000, probe_out=100_000,
            probe_size_usd=100.0,
        )
        assert res["probe_ok"] is True
        assert res["price_impact_at_100usd"] == 0.0
        assert res["effective_depth_usd"] == 100.0
        assert res["depth_reject_reason"] is None
        assert res["depth_method"] == "marginal_anchor"

    def test_low_effective_depth(self):
        # 20% degradation of marginal rate → LOW_EFFECTIVE_DEPTH.
        res = probe.compute_marginal_depth(
            ref_in=2_000_000, ref_out=2_000,
            probe_in=100_000_000, probe_out=80_000,
            probe_size_usd=100.0,
        )
        assert res["probe_ok"] is True
        assert abs(res["price_impact_at_100usd"] - 0.2) < 1e-6
        assert res["depth_reject_reason"] == "LOW_EFFECTIVE_DEPTH"
        # est_depth = 100 * 0.10 / 0.20 = 50
        assert res["effective_depth_usd"] == 50.0

    def test_toxic_price_impact(self):
        # 50% degradation → TOXIC_PRICE_IMPACT.
        res = probe.compute_marginal_depth(
            ref_in=2_000_000, ref_out=2_000,
            probe_in=100_000_000, probe_out=50_000,
            probe_size_usd=100.0,
        )
        assert res["depth_reject_reason"] == "TOXIC_PRICE_IMPACT"
        assert res["effective_depth_usd"] == 20.0

    def test_negative_impact_clamped(self):
        # Probe rate better than ref (rounding/tiny pool) → impact clamped to 0.
        res = probe.compute_marginal_depth(
            ref_in=2_000_000, ref_out=2_000,
            probe_in=100_000_000, probe_out=110_000,
            probe_size_usd=100.0,
        )
        assert res["price_impact_at_100usd"] == 0.0
        assert res["effective_depth_usd"] == 100.0

    def test_zero_amount_in_error(self):
        res = probe.compute_marginal_depth(
            ref_in=0, ref_out=2_000,
            probe_in=100_000_000, probe_out=100_000,
            probe_size_usd=100.0,
        )
        assert res["probe_ok"] is False
        assert res["probe_error"] == "ZERO_AMOUNT_IN"

    def test_zero_amount_out_error(self):
        res = probe.compute_marginal_depth(
            ref_in=2_000_000, ref_out=2_000,
            probe_in=100_000_000, probe_out=0,
            probe_size_usd=100.0,
        )
        assert res["probe_ok"] is False
        assert res["probe_error"] == "ZERO_AMOUNT_OUT"


class TestAnchorLeg:
    def test_anchor_is_token0(self):
        route = {"token0": "USDC", "token1": "MEME",
                 "token0_addr": "0xaa", "token1_addr": "0xbb"}
        assert probe._anchor_leg(route) == ("USDC", "0xaa", "0xbb")

    def test_anchor_is_token1(self):
        route = {"token0": "MEME", "token1": "WETH",
                 "token0_addr": "0xaa", "token1_addr": "0xbb"}
        assert probe._anchor_leg(route) == ("WETH", "0xbb", "0xaa")

    def test_no_anchor(self):
        route = {"token0": "MEME", "token1": "PEPE",
                 "token0_addr": "0xaa", "token1_addr": "0xbb"}
        assert probe._anchor_leg(route) is None


class TestProbeRouteMarginalDepth:
    _USDC = "0x" + "00" * 19 + "11"
    _MEME = "0x" + "00" * 19 + "22"

    def _v3_route(self):
        return {
            "token0": "USDC", "token1": "MEME",
            "token0_addr": self._USDC, "token1_addr": self._MEME,
            "adapter_type": "uniswap_v3", "dex_id": "uniswap_v3", "fee": 3000,
            "pool_address": "0x" + "cc" * 20,
        }

    def test_v3_linear_no_impact(self, monkeypatch):
        # Stub quoter: return amount_in 1:1 → no marginal degradation.
        def _stub(rpc_url, to, data):
            raw = data[2:]
            amount = int(raw[136:200], 16)  # selector(8)+addr(64)+addr(64)=136
            return _u256(amount)

        monkeypatch.setattr(probe, "_raw_eth_call", _stub)
        res = probe.probe_route_marginal_depth(
            self._v3_route(), rpc_url="http://rpc",
            dex_quoters={"uniswap_v3": "0x" + "99" * 20},
        )
        assert res["probe_ok"] is True
        assert res["effective_depth_usd"] == 100.0
        assert res["depth_reject_reason"] is None

    def test_v3_sublinear_low_depth(self, monkeypatch):
        # Stub quoter: out grows as sqrt(amount) → bigger trade has worse rate.
        import math

        def _stub(rpc_url, to, data):
            raw = data[2:]
            amount = int(raw[136:200], 16)
            out = int(math.isqrt(amount) * 1000)
            return _u256(out)

        monkeypatch.setattr(probe, "_raw_eth_call", _stub)
        res = probe.probe_route_marginal_depth(
            self._v3_route(), rpc_url="http://rpc",
            dex_quoters={"uniswap_v3": "0x" + "99" * 20},
        )
        assert res["probe_ok"] is True
        # sqrt pool always has positive impact at larger size
        assert res["price_impact_at_100usd"] > 0

    def test_v4_no_longer_skipped(self):
        """After V4 depth support was added, uniswap_v4 routes are no longer
        early-exited with V4_DEPTH_UNSUPPORTED. Without tick_spacing or quoter
        the probe fails with REF_QUOTE_FAILED (quote returns None), not the old
        V4_DEPTH_UNSUPPORTED sentinel."""
        route = self._v3_route()
        route["adapter_type"] = "uniswap_v4"
        res = probe.probe_route_marginal_depth(route, rpc_url="http://rpc")
        assert res["probe_ok"] is False
        # Must NOT return old "unsupported" error — V4 depth is now supported
        assert res["probe_error"] != "V4_DEPTH_UNSUPPORTED"
        # Expected: no quoter addr → NO_QUOTER, or quote fails → REF_QUOTE_FAILED
        assert res["probe_error"] in ("NO_QUOTER", "REF_QUOTE_FAILED")

    def test_no_anchor_error(self):
        route = self._v3_route()
        route["token0"], route["token1"] = "MEME", "PEPE"
        res = probe.probe_route_marginal_depth(route, rpc_url="http://rpc")
        assert res["probe_error"] == "NO_ANCHOR_FOR_DEPTH"

    def test_no_quoter_error(self):
        # v3 route with no quoter available → NO_QUOTER
        res = probe.probe_route_marginal_depth(
            self._v3_route(), rpc_url="http://rpc", dex_quoters={},
        )
        assert res["probe_error"] == "NO_QUOTER"


class TestEnrichRoutesMissingDepth:
    def test_skips_already_enriched(self, monkeypatch):
        calls = {"n": 0}

        def _stub(*a, **k):
            calls["n"] += 1
            return {"probe_ok": True, "effective_depth_usd": 42.0,
                    "price_impact_at_100usd": 0.0, "depth_reject_reason": None,
                    "depth_method": "marginal_anchor"}

        monkeypatch.setattr(probe, "probe_route_marginal_depth", _stub)
        routes = [
            {"effective_depth_usd": 500.0, "pool_address": "0x" + "11" * 20},
            {"effective_depth_usd": None, "pool_address": "0x" + "22" * 20,
             "token0": "USDC", "token1": "MEME"},
        ]
        counts = probe.enrich_routes_missing_depth(routes, rpc_url="http://rpc", sleep_s=0)
        assert counts["candidates"] == 1
        assert counts["probed_ok"] == 1
        assert routes[0]["effective_depth_usd"] == 500.0  # untouched
        assert routes[1]["effective_depth_usd"] == 42.0   # enriched

    def test_skips_placeholder_pool(self, monkeypatch):
        monkeypatch.setattr(
            probe, "probe_route_marginal_depth",
            lambda *a, **k: (_ for _ in ()).throw(AssertionError("should not probe")),
        )
        routes = [{"effective_depth_usd": None, "pool_address": "0x" + "0" * 40}]
        counts = probe.enrich_routes_missing_depth(routes, rpc_url="http://rpc", sleep_s=0)
        assert counts["candidates"] == 0

    def test_v4_missing_quoter_writes_visible_probe_error(self):
        routes = [{
            "effective_depth_usd": None,
            "pool_address": "0x" + "44" * 20,
            "adapter_type": "uniswap_v4",
            "dex_id": "uniswap_v4",
            "token0": "USDC",
            "token1": "MEME",
            "token0_addr": "0x" + "00" * 19 + "11",
            "token1_addr": "0x" + "00" * 19 + "22",
            "fee": 3000,
            "tick_spacing": 60,
        }]

        counts = probe.enrich_routes_missing_depth(
            routes,
            rpc_url="http://rpc",
            dex_quoters={},
            sleep_s=0,
        )

        assert counts["candidates"] == 1
        assert counts["v4_depth_candidates"] == 1
        assert counts["v4_depth_probe_ok"] == 0
        assert counts["v4_depth_probe_failed"] == 1
        assert counts["skipped_v4"] == 0
        assert routes[0]["depth_probe_ok"] is False
        assert routes[0]["depth_probe_error"] == "REF_QUOTE_FAILED"

    def test_v4_success_updates_v4_depth_counters(self, monkeypatch):
        def _stub(*a, **k):
            return {
                "probe_ok": True,
                "probe_error": None,
                "effective_depth_usd": 100.0,
                "price_impact_at_100usd": 0.0,
                "depth_reject_reason": None,
                "depth_method": "marginal_anchor",
            }

        monkeypatch.setattr(probe, "probe_route_marginal_depth", _stub)
        routes = [{
            "effective_depth_usd": None,
            "pool_address": "0x" + "55" * 20,
            "adapter_type": "uniswap_v4",
            "dex_id": "uniswap_v4",
            "token0": "USDC",
            "token1": "MEME",
        }]

        counts = probe.enrich_routes_missing_depth(routes, rpc_url="http://rpc", sleep_s=0)

        assert counts["v4_depth_candidates"] == 1
        assert counts["v4_depth_probe_ok"] == 1
        assert counts["v4_depth_probe_failed"] == 0
        assert routes[0]["depth_probe_error"] is None
