"""Unit tests for new infra telemetry fields in M9 artifact schema.

Validates that build_artifact accepts and correctly serialises:
  - quote_backend, quote_workers
  - provider_throttle_snapshot / http_429_count
  - ws_freshness
"""
from __future__ import annotations

import pytest

from m9.graph_arb.artifacts import build_artifact
from m9.graph_arb.models import GraphTopology


# ---------------------------------------------------------------------------
# Minimal stubs for build_artifact call
# ---------------------------------------------------------------------------

def _make_topology() -> GraphTopology:
    return GraphTopology(
        token_count=3,
        edge_count=6,
        route_count=2,
        hub_tokens=["USDC"],
        dead_end_tokens=[],
        missing_edges_for_3cycle=[],
        adjacency_summary={},
    )


def _base_kwargs() -> dict:
    return dict(
        chain="base",
        duration_minutes=1.0,
        cycle_results=[],
        topology=_make_topology(),
        sizes_usd=(1000.0,),
        run_timestamp="2025-01-01T00:00:00Z",
        started_at_mono=0.0,
        elapsed_s=60.0,
    )


# ---------------------------------------------------------------------------
# Tests: infra_telemetry block always present
# ---------------------------------------------------------------------------

class TestInfraTelemetryDefaults:

    def test_infra_telemetry_key_present(self):
        art = build_artifact(**_base_kwargs())
        assert "infra_telemetry" in art

    def test_default_quote_backend_is_direct_http(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["quote_backend"] == "direct_http"

    def test_default_quote_workers_is_4(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["quote_workers"] == 4

    def test_default_http_429_count_is_0(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_default_provider_throttle_snapshot_is_none(self):
        art = build_artifact(**_base_kwargs())
        assert art["infra_telemetry"]["provider_throttle_snapshot"] is None

    def test_ws_freshness_absent_when_not_provided(self):
        art = build_artifact(**_base_kwargs())
        assert "ws_freshness" not in art["infra_telemetry"]


# ---------------------------------------------------------------------------
# Tests: explicit infra telemetry values are preserved
# ---------------------------------------------------------------------------

class TestInfraTelemetryExplicit:

    def test_raw_http_backend_stored(self):
        art = build_artifact(**_base_kwargs(), quote_backend="raw_http")
        assert art["infra_telemetry"]["quote_backend"] == "raw_http"

    def test_anvil_fork_backend_stored(self):
        art = build_artifact(**_base_kwargs(), quote_backend="anvil_fork")
        assert art["infra_telemetry"]["quote_backend"] == "anvil_fork"

    def test_quote_workers_stored(self):
        art = build_artifact(**_base_kwargs(), quote_workers=1)
        assert art["infra_telemetry"]["quote_workers"] == 1

    def test_provider_throttle_snapshot_stored(self):
        snap = {
            "calls": {
                "total_429": 42,
                "total_408": 3,
                "total_ok": 100,
                "breaker_open": False,
                "cooldown_remaining_s": 0.0,
            }
        }
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["provider_throttle_snapshot"] == snap
        # http_429_count derived from calls bucket
        assert art["infra_telemetry"]["http_429_count"] == 42

    def test_http_429_count_zero_when_no_429s(self):
        snap = {"calls": {"total_429": 0, "total_ok": 50}}
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_http_429_count_missing_calls_key(self):
        """If snapshot has no 'calls' key, http_429_count defaults to 0."""
        snap = {"logs": {"total_429": 5}}
        art = build_artifact(**_base_kwargs(), provider_throttle_snapshot=snap)
        assert art["infra_telemetry"]["http_429_count"] == 0

    def test_ws_freshness_stored(self):
        ws = {
            "connected": True,
            "latest_block": 1234567,
            "block_age_s": 2.3,
            "stale": False,
            "error": None,
        }
        art = build_artifact(**_base_kwargs(), ws_freshness=ws)
        assert art["infra_telemetry"]["ws_freshness"] == ws

    def test_ws_freshness_none_not_stored(self):
        art = build_artifact(**_base_kwargs(), ws_freshness=None)
        assert "ws_freshness" not in art["infra_telemetry"]


# ---------------------------------------------------------------------------
# Tests: backward compat — existing callers without infra params still work
# ---------------------------------------------------------------------------

def test_build_artifact_no_infra_params_no_error():
    """Callers that do not pass infra params must not break."""
    art = build_artifact(**_base_kwargs())
    assert art["schema_family"] == "m9_graph_arb"
    assert "infra_telemetry" in art


def test_build_artifact_all_infra_params():
    """Callers that pass all infra params get a fully populated block."""
    snap = {"calls": {"total_429": 10, "total_ok": 200}}
    ws = {"connected": True, "latest_block": 99, "block_age_s": 1.0, "stale": False, "error": None}
    art = build_artifact(
        **_base_kwargs(),
        quote_backend="raw_http",
        quote_workers=2,
        provider_throttle_snapshot=snap,
        ws_freshness=ws,
    )
    it = art["infra_telemetry"]
    assert it["quote_backend"] == "raw_http"
    assert it["quote_workers"] == 2
    assert it["http_429_count"] == 10
    assert it["provider_throttle_snapshot"] == snap
    assert it["ws_freshness"] == ws


# ---------------------------------------------------------------------------
# Tests: ws_monitor module is importable and snapshot() returns dict
# ---------------------------------------------------------------------------

def test_ws_monitor_importable():
    from m9.graph_arb.ws_monitor import WsMonitor, start_ws_monitor
    assert callable(start_ws_monitor)
    monitor = WsMonitor()
    snap = monitor.snapshot()
    assert isinstance(snap, dict)
    assert "connected" in snap
    assert snap["connected"] is False  # not started


def test_ws_monitor_snapshot_not_stale_when_no_data():
    from m9.graph_arb.ws_monitor import WsMonitor
    monitor = WsMonitor()
    snap = monitor.snapshot()
    assert snap["block_age_s"] is None  # no data yet
    assert snap["stale"] is False  # can't be stale with no data


# ---------------------------------------------------------------------------
# Tests: quoter backend constants are stable
# ---------------------------------------------------------------------------

def test_quoter_backend_constants():
    from m9.graph_arb.quoter import (
        BACKEND_DIRECT_HTTP,
        BACKEND_RAW_HTTP,
        BACKEND_ANVIL_FORK,
        _VALID_BACKENDS,
    )
    assert BACKEND_DIRECT_HTTP == "direct_http"
    assert BACKEND_RAW_HTTP == "raw_http"
    assert BACKEND_ANVIL_FORK == "anvil_fork"
    assert "direct_http" in _VALID_BACKENDS
    assert "raw_http" in _VALID_BACKENDS
    assert "anvil_fork" in _VALID_BACKENDS


def test_schedule_cycle_quotes_accepts_backend_params():
    """schedule_cycle_quotes signature must accept max_workers, quote_backend, rpc_url."""
    import inspect
    from m9.graph_arb.quoter import schedule_cycle_quotes
    sig = inspect.signature(schedule_cycle_quotes)
    params = sig.parameters
    assert "max_workers" in params
    assert "quote_backend" in params
    assert "rpc_url" in params
    assert "dynamic_sizes" in params
    assert "dynamic_size_limit" in params


def test_schedule_cycle_quotes_dynamic_sizes_selects_best(monkeypatch):
    """Opt-in dynamic sizing must return the best gross_bps quote by size."""
    from unittest.mock import MagicMock
    from m9.graph_arb.models import CycleQuoteResult
    from m9.graph_arb import quoter

    cycle = MagicMock()
    cycle.edges = []

    def _fake_quote_cycle_sync(cycle_arg, size_usd, *_args, **_kwargs):
        gross_by_size = {100.0: -5.0, 250.0: 12.0, 500.0: 8.0}
        gross = gross_by_size[float(size_usd)]
        return CycleQuoteResult(
            cycle=cycle_arg,
            size_usd=float(size_usd),
            amount_in=int(size_usd),
            amount_out=int(size_usd),
            gross_bps=gross,
            status="POSITIVE_GROSS" if gross > 0 else "NEGATIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.01,
        )

    monkeypatch.setattr(quoter, "quote_cycle_sync", _fake_quote_cycle_sync)
    results = quoter.schedule_cycle_quotes(
        [cycle],
        w3=None,
        sizes_usd=(100.0, 250.0, 500.0),
        max_workers=1,
        dynamic_sizes=True,
    )
    assert len(results) == 1
    result = results[0]
    assert result.size_usd == 250.0
    assert result.dynamic_size_usd == 250.0
    assert result.size_candidates_usd == (100.0, 250.0, 500.0)
    assert result.depth_curve is not None
    assert [row["size_usd"] for row in result.depth_curve] == [100.0, 250.0, 500.0]
    assert result.dynamic_size_source == "multi_size_quote"


def test_schedule_cycle_quotes_dynamic_size_limit(monkeypatch):
    """Only the prioritized prefix should consume multi-size RPC budget."""
    from unittest.mock import MagicMock
    from m9.graph_arb.models import CycleQuoteResult
    from m9.graph_arb import quoter

    cycles = [MagicMock(), MagicMock(), MagicMock()]

    def _fake_quote_cycle_sync(cycle_arg, size_usd, *_args, **_kwargs):
        return CycleQuoteResult(
            cycle=cycle_arg,
            size_usd=float(size_usd),
            amount_in=int(size_usd),
            amount_out=int(size_usd),
            gross_bps=1.0,
            status="POSITIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.01,
        )

    monkeypatch.setattr(quoter, "quote_cycle_sync", _fake_quote_cycle_sync)
    results = quoter.schedule_cycle_quotes(
        cycles,
        w3=None,
        sizes_usd=(100.0, 250.0),
        max_workers=1,
        dynamic_sizes=True,
        dynamic_size_limit=1,
    )
    assert results[0].dynamic_size_usd == 100.0
    assert results[0].size_candidates_usd == (100.0, 250.0)
    assert results[1].dynamic_size_usd is None
    assert results[1].size_candidates_usd == ()
    assert results[2].dynamic_size_usd is None


def test_schedule_cycle_quotes_dynamic_size_limit_zero_means_all(monkeypatch):
    """dynamic_size_limit<=0 must not disable dynamic sizing (config uses 0 = unlimited)."""
    from unittest.mock import MagicMock
    from m9.graph_arb.models import CycleQuoteResult
    from m9.graph_arb import quoter

    cycles = [MagicMock(), MagicMock()]

    def _fake_dynamic(cycle_arg, sizes, *_args, **_kwargs):
        return CycleQuoteResult(
            cycle=cycle_arg,
            size_usd=float(sizes[0]),
            amount_in=1,
            amount_out=1,
            gross_bps=1.0,
            status="NEGATIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.01,
            dynamic_size_usd=float(sizes[0]),
            size_candidates_usd=tuple(sizes),
            dynamic_size_source="multi_size_quote",
        )

    monkeypatch.setattr(quoter, "quote_cycle_dynamic_sync", _fake_dynamic)
    results = quoter.schedule_cycle_quotes(
        cycles,
        w3=None,
        sizes_usd=(1.0, 5.0, 10.0),
        max_workers=1,
        dynamic_sizes=True,
        dynamic_size_limit=0,
    )
    assert all(r.dynamic_size_usd is not None for r in results)


# ---------------------------------------------------------------------------
# Tests: rpc_provider identity fields in infra_telemetry
# ---------------------------------------------------------------------------

class TestRpcProviderFields:
    """build_artifact must store rpc_provider, rpc_source, rpc_public_fallback_used."""

    def test_rpc_provider_defaults_to_unknown(self):
        art = build_artifact(**_base_kwargs())
        it = art["infra_telemetry"]
        assert it["rpc_provider"] == "unknown"
        assert it["rpc_source"] == "unknown"
        assert it["rpc_public_fallback_used"] is False

    def test_drpc_provider_stored(self):
        art = build_artifact(**_base_kwargs(), rpc_provider="drpc", rpc_source="chain_env_BASE_RPC")
        it = art["infra_telemetry"]
        assert it["rpc_provider"] == "drpc"
        assert it["rpc_source"] == "chain_env_BASE_RPC"
        assert it["rpc_public_fallback_used"] is False

    def test_public_fallback_flag_set(self):
        art = build_artifact(
            **_base_kwargs(),
            rpc_provider="public_fallback",
            rpc_source="public_fallback",
            rpc_public_fallback_used=True,
        )
        it = art["infra_telemetry"]
        assert it["rpc_provider"] == "public_fallback"
        assert it["rpc_public_fallback_used"] is True


# ---------------------------------------------------------------------------
# Tests: RPC resolution uses BASE_RPC env var (not public fallback)
# ---------------------------------------------------------------------------

class TestRpcResolutionFromEnv:
    """resolve_rpc_http must pick BASE_RPC over public_fallback when env is set."""

    def test_base_rpc_env_gives_drpc_provider(self):
        """When BASE_RPC is set, resolve_rpc_http returns drpc provider, not public."""
        from core.rpc_urls import resolve_rpc_http
        fake_drpc_url = "https://lb.drpc.live/ogrpc?network=base&dkey=FAKE_KEY"
        env = {"BASE_RPC": fake_drpc_url}
        url, provider, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        assert url == fake_drpc_url
        assert provider == "drpc"
        assert diag["source"] == "chain_env_BASE_RPC"

    def test_no_base_rpc_falls_back_to_public(self):
        """Without BASE_RPC, resolve_rpc_http uses public_fallback (mainnet.base.org)."""
        from core.rpc_urls import resolve_rpc_http
        url, provider, diag = resolve_rpc_http(chain_id=8453, network="base", env={})
        assert provider in ("public", "public_fallback")
        assert diag["source"] == "public_fallback"
        assert "mainnet.base.org" in (url or "")

    def test_alchemy_key_env_gives_alchemy_provider(self):
        """ALCHEMY_API_KEY in env gives alchemy provider for Base."""
        from core.rpc_urls import resolve_rpc_http
        env = {"ALCHEMY_API_KEY": "FAKE_ALCHEMY_KEY"}
        url, provider, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        assert provider == "alchemy"
        assert "alchemy.com" in (url or "")
        assert diag["source"] == "alchemy_api_key"

    def test_base_rpc_takes_priority_over_alchemy_key(self):
        """BASE_RPC (chain-scoped) takes priority over ALCHEMY_API_KEY."""
        from core.rpc_urls import resolve_rpc_http
        fake_drpc_url = "https://lb.drpc.live/ogrpc?network=base&dkey=FAKE_KEY"
        env = {
            "BASE_RPC": fake_drpc_url,
            "ALCHEMY_API_KEY": "FAKE_ALCHEMY_KEY",
        }
        url, provider, diag = resolve_rpc_http(chain_id=8453, network="base", env=env)
        assert url == fake_drpc_url
        assert provider == "drpc"
        assert diag["source"] == "chain_env_BASE_RPC"


# ---------------------------------------------------------------------------
# Tests: quote_revert_rate is leg-level (not cycle-level histogram)
# ---------------------------------------------------------------------------

class TestCycleOriginAnnotation:
    """cycle_origin field in top_cycles: 'm8' | 'base' | None."""

    def _make_qr(self, pool_address: str, gross_bps: float = 0.5):
        from unittest.mock import MagicMock
        from m9.graph_arb.models import CycleQuoteResult
        edge = MagicMock()
        edge.pool_address = pool_address
        edge.dex_id = "uniswap_v3"
        edge.factory_class = "EFFICIENT_BASELINE"
        edge.factory_verified = True
        edge.fee_bps = 5.0
        edge.token_in_sym = "USDC"
        edge.token_out_sym = "WETH"
        edge.token_in_decimals = 6
        edge.token_out_decimals = 18
        edge2 = MagicMock()
        edge2.pool_address = "0xbase0002"
        edge2.dex_id = "uniswap_v3"
        edge2.factory_class = "EFFICIENT_BASELINE"
        edge2.factory_verified = True
        edge2.fee_bps = 5.0
        edge2.token_in_sym = "WETH"
        edge2.token_out_sym = "EURC"
        edge2.token_in_decimals = 18
        edge2.token_out_decimals = 6
        edge3 = MagicMock()
        edge3.pool_address = "0xbase0003"
        edge3.dex_id = "uniswap_v2"
        edge3.factory_class = "EFFICIENT_BASELINE"
        edge3.factory_verified = True
        edge3.fee_bps = 5.0
        edge3.token_in_sym = "EURC"
        edge3.token_out_sym = "USDC"
        edge3.token_in_decimals = 6
        edge3.token_out_decimals = 6
        cycle = MagicMock()
        cycle.edges = [edge, edge2, edge3]
        cycle.cycle_id = "testcycle01"
        cycle.length = 3
        cycle.token_path = ["USDC", "WETH", "EURC"]
        cycle.start_token_sym = "USDC"
        cycle.total_fee_bps = 15.0
        cycle.min_factory_class = "EFFICIENT_BASELINE"
        return CycleQuoteResult(
            cycle=cycle,
            size_usd=1000.0,
            amount_in=1_000_000,
            amount_out=1_000_500,
            gross_bps=gross_bps,
            status="POSITIVE_GROSS",
            reject_reason=None,
            leg_results=[],
            elapsed_s=0.05,
        )

    def test_cycle_origin_none_when_no_m8_addrs(self):
        """When m8_pool_addrs_for_annotation is None, cycle_origin must be None."""
        qr = self._make_qr("0xbase0001")
        kwargs = _base_kwargs()
        kwargs["cycle_results"] = [qr]
        art = build_artifact(**kwargs)
        top = art.get("top_cycles", [])
        assert len(top) == 1
        assert top[0]["cycle_origin"] is None

    def test_cycle_origin_base_when_pool_not_in_m8(self):
        """Pool not in m8_pool_addrs → cycle_origin='base'."""
        qr = self._make_qr("0xbase0001")
        m8_addrs = frozenset({"0xm8pool0001"})
        kwargs = _base_kwargs()
        kwargs["cycle_results"] = [qr]
        art = build_artifact(**kwargs, m8_pool_addrs_for_annotation=m8_addrs)
        top = art.get("top_cycles", [])
        assert len(top) == 1
        assert top[0]["cycle_origin"] == "base"

    def test_cycle_origin_m8_when_pool_in_m8(self):
        """First edge pool in m8_pool_addrs → cycle_origin='m8'."""
        m8_addr = "0xm8pool0001"
        qr = self._make_qr(m8_addr)
        m8_addrs = frozenset({m8_addr.lower()})
        kwargs = _base_kwargs()
        kwargs["cycle_results"] = [qr]
        art = build_artifact(**kwargs, m8_pool_addrs_for_annotation=m8_addrs)
        top = art.get("top_cycles", [])
        assert len(top) == 1
        assert top[0]["cycle_origin"] == "m8"

    def test_cycle_origin_case_insensitive(self):
        """Comparison is case-insensitive for pool addresses."""
        m8_addr = "0xM8POOL0001"
        qr = self._make_qr(m8_addr)
        m8_addrs = frozenset({"0xm8pool0001"})  # lowercase in set
        kwargs = _base_kwargs()
        kwargs["cycle_results"] = [qr]
        art = build_artifact(**kwargs, m8_pool_addrs_for_annotation=m8_addrs)
        top = art.get("top_cycles", [])
        assert top[0]["cycle_origin"] == "m8"


class TestQuoteRevertRateLegLevel:
    """quote_revert_rate must be computed from leg_results.reject_reason, not from
    the cycle-level histogram (which never carries 'QUOTE_REVERT' since cycles
    fail as CYCLE_QUOTE_FAILED at the cycle level)."""

    def _make_leg(self, reject_reason: "str | None", ok: bool = False):
        from m8_1.stable_anchor.quote_probe import QuoteResult
        return QuoteResult(
            route_id="r1",
            size_usd=1000.0,
            amount_in=1_000_000,
            amount_out=0,
            ok=ok,
            reject_reason=reject_reason,
            gas_estimate=None,
            raw_error=None,
        )

    def _make_qr(self, legs: list):
        from unittest.mock import MagicMock
        from m9.graph_arb.models import CycleQuoteResult
        m = MagicMock()
        m.cycle_id = "test"
        m.length = len(legs)
        m.token_path = ["USDC", "WETH", "USDT"][: len(legs) + 1]
        m.start_token_sym = "USDC"
        m.total_fee_bps = 9.0
        m.min_factory_class = "EFFICIENT_BASELINE"
        edge = MagicMock()
        edge.dex_id = "uniswap_v3"
        edge.factory_class = "EFFICIENT_BASELINE"
        edge.pool_address = "0xaaaa"
        edge.pair_id = "USDC/WETH"
        edge.fee_bps = 5.0
        edge.token_in_sym = "USDC"
        edge.token_out_sym = "WETH"
        m.edges = [edge] * len(legs)
        return CycleQuoteResult(
            cycle=m,
            size_usd=1000.0,
            amount_in=1_000_000,
            amount_out=0,
            gross_bps=0.0,
            status="QUOTE_FAILED",
            reject_reason="CYCLE_QUOTE_FAILED",
            leg_results=legs,
            elapsed_s=0.1,
        )

    def test_zero_legs_gives_zero_rate(self):
        art = build_artifact(**_base_kwargs())
        assert art["quote_revert_rate"] == 0.0

    def test_all_revert_legs_gives_rate_1(self):
        leg = self._make_leg("QUOTE_REVERT")
        qr = self._make_qr([leg, leg, leg])
        art = build_artifact(**{**_base_kwargs(), "cycle_results": [qr]})
        assert art["quote_revert_rate"] == 1.0

    def test_partial_revert_legs_gives_correct_rate(self):
        revert = self._make_leg("QUOTE_REVERT")
        other = self._make_leg("QUOTE_RPC_ERROR")
        # 1 revert + 3 other = 4 legs total -> rate = 0.25
        qr = self._make_qr([revert, other, other, other])
        art = build_artifact(**{**_base_kwargs(), "cycle_results": [qr]})
        assert abs(art["quote_revert_rate"] - 0.25) < 1e-6

    def test_no_revert_legs_gives_zero_rate(self):
        other = self._make_leg("QUOTE_RPC_ERROR")
        qr = self._make_qr([other, other])
        art = build_artifact(**{**_base_kwargs(), "cycle_results": [qr]})
        assert art["quote_revert_rate"] == 0.0

    def test_quote_revert_rate_consistent_in_infra_telemetry(self):
        """infra_telemetry.quote_revert_rate must match top-level quote_revert_rate."""
        revert = self._make_leg("QUOTE_REVERT")
        other = self._make_leg("QUOTE_RPC_ERROR")
        qr = self._make_qr([revert, other])
        art = build_artifact(**{**_base_kwargs(), "cycle_results": [qr]})
        assert art["infra_telemetry"]["quote_revert_rate"] == art["quote_revert_rate"]

    def test_cycle_level_histogram_quote_revert_does_not_inflate_rate(self):
        """Cycles with reject_reason='QUOTE_REVERT' at CYCLE level (empty legs)
        must NOT contribute to quote_revert_rate."""
        from unittest.mock import MagicMock
        from m9.graph_arb.models import CycleQuoteResult
        m = MagicMock()
        m.cycle_id = "x"
        m.length = 2
        m.token_path = ["USDC", "WETH", "USDT"]
        m.start_token_sym = "USDC"
        m.total_fee_bps = 9.0
        m.min_factory_class = "EFFICIENT_BASELINE"
        edge = MagicMock()
        edge.dex_id = "uni"
        edge.factory_class = "EFFICIENT_BASELINE"
        edge.pool_address = "0xaaa"
        edge.pair_id = "X/Y"
        edge.fee_bps = 5.0
        edge.token_in_sym = "USDC"
        edge.token_out_sym = "WETH"
        m.edges = [edge, edge]
        qr = CycleQuoteResult(
            cycle=m, size_usd=1000.0, amount_in=1_000_000, amount_out=0,
            gross_bps=0.0, status="QUOTE_FAILED", reject_reason="QUOTE_REVERT",
            leg_results=[],
            elapsed_s=0.1,
        )
        art = build_artifact(**{**_base_kwargs(), "cycle_results": [qr]})
        # quote_revert_rate must be 0 (no leg-level QUOTE_REVERT)
        assert art["quote_revert_rate"] == 0.0
        # cycle histogram still has QUOTE_REVERT from cycle.reject_reason
        assert art["cycle_reject_histogram"].get("QUOTE_REVERT", 0) == 1
