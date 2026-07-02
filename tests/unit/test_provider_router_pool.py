"""Tests for ProviderRouter polyglot pool extension (todo_RPC_blockers Phase 1)."""
import os
from unittest.mock import patch

import pytest

from m9.graph_arb.provider_router import ProviderRouter


def test_router_extras_added_to_stats():
    r = ProviderRouter(
        primary="https://primary.example",
        secondary="https://secondary.example",
        extras=["https://e1.example", "https://e2.example"],
    )
    snap = r.snapshot()
    assert snap["extras_count"] == 2
    # Stats tracked for every endpoint
    assert len(snap["providers"]) == 4


def test_router_extras_deduplicated():
    r = ProviderRouter(
        primary="https://primary.example",
        secondary="https://secondary.example",
        extras=[
            "https://primary.example",   # duplicate of primary
            "https://secondary.example", # duplicate of secondary
            "https://e1.example",
            "https://e1.example",        # internal duplicate
        ],
    )
    assert r.snapshot()["extras_count"] == 1


def test_router_no_extras_no_secondary_returns_primary():
    r = ProviderRouter(primary="https://primary.example")
    assert r.get_url() == "https://primary.example"
    assert r.snapshot()["extras_count"] == 0


def test_router_failover_rotates_through_extras():
    r = ProviderRouter(
        primary="https://primary.example",
        secondary="https://secondary.example",
        extras=["https://e1.example", "https://e2.example"],
        failover_threshold=3,
        cooldown_s=60.0,
    )
    # Trigger primary failover.
    for _ in range(3):
        r.record_429("https://primary.example")
    first = r.get_url()
    # Should be one of the non-primary endpoints.
    assert first in {"https://secondary.example", "https://e1.example", "https://e2.example"}


def test_router_get_url_rotates_extras_when_all_saturated():
    """When secondary is also over threshold, rotate to extras."""
    r = ProviderRouter(
        primary="https://primary.example",
        secondary="https://secondary.example",
        extras=["https://e1.example", "https://e2.example"],
        failover_threshold=2,
        cooldown_s=60.0,
    )
    # Saturate primary
    for _ in range(2):
        r.record_429("https://primary.example")
    # Saturate secondary
    for _ in range(2):
        r.record_429("https://secondary.example")
    # Now get_url must prefer a healthy extra.
    url = r.get_url()
    assert url in {"https://e1.example", "https://e2.example"}


def test_from_env_reads_pool_var(monkeypatch):
    monkeypatch.setenv("BASE_RPC", "https://my-primary.example")
    monkeypatch.delenv("BASE_RPC_SECONDARY", raising=False)
    monkeypatch.setenv(
        "BASE_RPC_POOL",
        "https://pool-a.example, https://pool-b.example",
    )
    monkeypatch.delenv("ARBY_USE_PUBLIC_POOL", raising=False)
    r = ProviderRouter.from_env(chain="base")
    snap = r.snapshot()
    assert snap["extras_count"] == 2


def test_from_env_use_public_pool(monkeypatch):
    monkeypatch.setenv("BASE_RPC", "https://my-primary.example")
    monkeypatch.delenv("BASE_RPC_SECONDARY", raising=False)
    monkeypatch.delenv("BASE_RPC_POOL", raising=False)
    monkeypatch.setenv("ARBY_USE_PUBLIC_POOL", "1")
    r = ProviderRouter.from_env(chain="base")
    snap = r.snapshot()
    # At least 5 public Base endpoints should be loaded (minus the primary if duplicate).
    assert snap["extras_count"] >= 4


def test_sweep_level_failover_threshold_1():
    """Regression for BUG-N1: threshold=1 (sweep-level default) must trigger failover
    after a single record_429() call within the 30s window.

    Root cause of BUG-N1: window_s=30s << sweep_duration≈130s, so with the old default
    threshold=5, the global deque count never accumulated to 5 (each sweep's signal
    expired before the next one arrived). With threshold=1, a single bad sweep's signal
    is enough to switch to an extra endpoint.
    """
    r = ProviderRouter(
        primary="https://drpc.example",
        extras=["https://publicnode.example", "https://llamarpc.example"],
        failover_threshold=1,   # sweep-level: now the default in runner.py (was: 5)
        cooldown_s=9999.0,      # never auto-recover during this test
    )
    assert r.get_url() == "https://drpc.example"   # starts on primary
    # One sweep's worth of 429s: single record_429 call (mimics how the runner reports)
    r.record_429("https://drpc.example")
    url = r.get_url()
    assert url in {"https://publicnode.example", "https://llamarpc.example"}, (
        f"Expected failover to extras after threshold=1 record_429(), got {url!r}"
    )
    assert r.snapshot()["is_failed_over"] is True


def test_http_5xx_triggers_failover_like_429():
    """A broken public RPC returning 5xx must not stay in rotation as healthy."""
    r = ProviderRouter(
        primary="https://drpc.example",
        extras=["https://publicnode.example"],
        failover_threshold=1,
        cooldown_s=9999.0,
    )
    r.record_http_error("https://drpc.example", 521)
    assert r.get_url() == "https://publicnode.example"
    snap = r.snapshot()
    assert snap["is_failed_over"] is True
    assert snap["providers"]["https://drpc.example"]["http_5xx_total"] == 1


def test_failed_extra_is_skipped_when_healthy_extra_exists():
    r = ProviderRouter(
        primary="https://drpc.example",
        extras=["https://broken.example", "https://healthy.example"],
        failover_threshold=1,
        cooldown_s=9999.0,
    )
    r.record_http_error("https://drpc.example", 429)
    r.record_http_error("https://broken.example", 521)
    assert r.get_url() == "https://healthy.example"


def test_sweep_level_failover_threshold_5_does_not_trigger():
    """Contrast test: threshold=5 with one record_429 must NOT trigger failover.

    This documents why BUG-N1 existed: the runner only calls record_429() once per
    sweep, so with threshold=5 the count stays at 1 and failover never fires.
    """
    r = ProviderRouter(
        primary="https://drpc.example",
        extras=["https://publicnode.example"],
        failover_threshold=5,   # old (broken) default
        cooldown_s=9999.0,
    )
    r.record_429("https://drpc.example")   # one sweep signal
    # Still on primary because count=1 < threshold=5
    assert r.get_url() == "https://drpc.example"
    assert r.snapshot()["is_failed_over"] is False


def test_runner_extracts_http_status_from_raw_error():
    from m9.graph_arb.runner import _http_status_from_raw_error

    assert _http_status_from_raw_error("HTTP 429: Too Many Requests") == 429
    assert _http_status_from_raw_error("HTTP 521: Origin Down") == 521
    assert _http_status_from_raw_error("provider_throttle_cooldown") is None


# ---------------------------------------------------------------------------
# Step 3 regressions: leg quote backend receives failover URL (GPT session-14)
# ---------------------------------------------------------------------------

def test_probe_leg_raw_http_uses_rpc_url_not_w3():
    """Step 3 regression: _probe_leg with raw_http must use rpc_url, not w3.

    This is the core contract that lets ProviderRouter failover govern every leg
    quote: the runner passes rpc_url=_active_rpc (current router URL) to
    schedule_cycle_quotes → quote_cycle_sync → _probe_leg, so if the router has
    failed over to an extra, leg quotes automatically target that extra.

    The test confirms that the raw_http path in _probe_leg ignores the w3 argument
    and calls probe_quote_raw_http with the supplied rpc_url.
    """
    from dataclasses import dataclass
    from unittest.mock import patch

    from m9.graph_arb.quoter import _probe_leg, _make_dex_route, _make_token_info, BACKEND_RAW_HTTP
    from m9.graph_arb.models import GraphEdge

    edge = GraphEdge(
        token_in_sym="USDC", token_out_sym="WETH",
        token_in_addr="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token_out_addr="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        token_in_decimals=6, token_out_decimals=18,
        route_id="r1", dex_id="uniswap_v3", adapter_type="uniswap_v3",
        fee=500, tick_spacing=10,
        quoter_addr="0x" + "0" * 40,
        pool_address="0x" + "1" * 40,
        fee_bps=5.0, factory_class="v3", pair_id="USDC_WETH",
    )
    route = _make_dex_route(edge)
    token_in = _make_token_info("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6)
    token_out = _make_token_info("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18)

    captured: list = []

    def _fake_raw_http(url, route, token_in, token_out, amount_in, **kwargs):
        captured.append(url)
        # Return a minimal failed QuoteResult so _probe_leg completes
        from m8_1.stable_anchor.quote_probe import QuoteResult
        return QuoteResult(
            route_id="test", size_usd=100.0, amount_in=amount_in,
            amount_out=0, ok=False, reject_reason="mock",
            gas_estimate=None, raw_error="mock-not-real",
        )

    failover_url = "https://extra.publicnode.com"

    with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=_fake_raw_http):
        _probe_leg(
            w3=None,  # w3 is irrelevant for raw_http — must be ignored
            route=route,
            token_in=token_in,
            token_out=token_out,
            amount_in=1_000_000,
            quote_backend=BACKEND_RAW_HTTP,
            rpc_url=failover_url,
            use_cache=False,
        )

    assert captured == [failover_url], (
        f"raw_http backend must forward rpc_url to probe_quote_raw_http; "
        f"expected {failover_url!r}, got {captured}"
    )


def test_probe_leg_raw_http_initial_url_not_leaked():
    """After ProviderRouter failover, leg quotes must not reach the initial primary URL.

    This mirrors the session-14 root-cause fix: runner.py now passes
    rpc_url=_active_rpc (which may be an extra after failover) to schedule_cycle_quotes.
    _probe_leg(raw_http) forwards that URL verbatim; the initial BASE_RPC (primary) must
    never appear in the call.
    """
    from unittest.mock import patch
    from m9.graph_arb.quoter import _probe_leg, _make_dex_route, _make_token_info, BACKEND_RAW_HTTP
    from m9.graph_arb.models import GraphEdge

    edge = GraphEdge(
        token_in_sym="USDC", token_out_sym="WETH",
        token_in_addr="0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48",
        token_out_addr="0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        token_in_decimals=6, token_out_decimals=18,
        route_id="r2", dex_id="uniswap_v3", adapter_type="uniswap_v3",
        fee=500, tick_spacing=10,
        quoter_addr="0x" + "0" * 40,
        pool_address="0x" + "2" * 40,
        fee_bps=5.0, factory_class="v3", pair_id="USDC_WETH_2",
    )
    route = _make_dex_route(edge)
    token_in = _make_token_info("USDC", "0xa0b86991c6218b36c1d19d4a2e9eb0ce3606eb48", 6)
    token_out = _make_token_info("WETH", "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2", 18)

    initial_base_rpc = "https://lb.drpc.org/ogrpc?network=base&dkey=SECRET"
    failover_url = "https://base.llamarpc.com"
    captured: list = []

    def _fake_raw_http(url, route, token_in, token_out, amount_in, **kwargs):
        captured.append(url)
        from m8_1.stable_anchor.quote_probe import QuoteResult
        return QuoteResult(
            route_id="test", size_usd=50.0, amount_in=amount_in,
            amount_out=0, ok=False, reject_reason="mock",
            gas_estimate=None, raw_error="mock",
        )

    with patch("m9.graph_arb.raw_http_probe.probe_quote_raw_http", side_effect=_fake_raw_http):
        _probe_leg(
            w3=None,
            route=route,
            token_in=token_in,
            token_out=token_out,
            amount_in=500_000,
            quote_backend=BACKEND_RAW_HTTP,
            rpc_url=failover_url,   # <-- runner passes _active_rpc (post-failover)
            use_cache=False,
        )

    assert initial_base_rpc not in captured, "Initial BASE_RPC must not be used after failover"
    assert captured == [failover_url], f"Expected failover URL in call, got {captured}"
