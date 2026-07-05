"""Unit tests for on-chain factory mirror discovery."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path
from unittest.mock import patch

from m8.discovery.dexscreener_cache import cache_ttl_s
from m8.discovery.mirror_candidate_score import (
    DISPOSITION_SELECTED_FOR_VERIFY,
    classify_verify_disposition,
)
from m8.discovery.onchain_factory_mirror_discovery import (
    FACTORY_LOG_CONFIG_PATH,
    _enrich_hints_from_subset,
    _resolve_block_timestamps,
    compute_mirror_venue_metrics,
    load_expand_subset_tokens,
    run_mirror_discovery,
)
from m8.discovery.pool_hints import PoolHint
from m9.graph_arb.narrow_universe_gate import route_has_eligible_mirror_discovery

_REPO = Path(__file__).resolve().parents[2]

def test_fresh_delta_cache_ttl_is_short():
    assert cache_ttl_s(lane="fresh_delta_lane") == 180.0
    assert cache_ttl_s(hot=True) == 1800.0


def test_onchain_disposition_not_no_radar_pool():
    hint = PoolHint(
        source="onchain_factory",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr="0x" + "1" * 40,
        token1_addr="0x" + "2" * 40,
        focus_token="0x" + "1" * 40,
        radar_reason="new_pool_seen",
    )
    disp, _ = classify_verify_disposition(
        "0x" + "1" * 40,
        [hint],
        in_verify_subset=True,
        in_verify_cap=True,
        priority_score=80.0,
    )
    assert disp == DISPOSITION_SELECTED_FOR_VERIFY


def test_narrow_bridge_rejects_dexscreener_only_without_verify():
    route = {
        "source": "dexscreener",
        "hint_source": "dexscreener",
        "factory_verified": False,
    }
    assert route_has_eligible_mirror_discovery(route) is False
    route_ok = {
        "resolve_source": "onchain_factory",
        "factory_verified": True,
    }
    assert route_has_eligible_mirror_discovery(route_ok) is True


def test_run_mirror_discovery_dry_run_writes_artifacts(tmp_path: Path):
    subset = tmp_path / "subset.json"
    subset.write_text(
        json.dumps(
            {
                "tokens": [
                    {"token": "0x" + "1" * 40, "source": "fresh_delta_lane"},
                ]
            }
        ),
        encoding="utf-8",
    )
    hints = tmp_path / "hints.json"
    radar = tmp_path / "radar.json"
    scan = tmp_path / "scan.json"
    budget = tmp_path / "budget.json"

    result = run_mirror_discovery(
        token_subset_path=str(subset),
        max_tokens=5,
        hints_path=str(hints),
        radar_path=str(radar),
        scan_artifact_path=str(scan),
        verify_budget_path=str(budget),
        dry_run=True,
        skip_factory_log=True,
    )
    assert result.tokens_scanned == 1
    assert scan.is_file()
    assert budget.is_file()
    budget_doc = json.loads(budget.read_text(encoding="utf-8"))
    assert "onchain_factory_candidates" in budget_doc
    assert "factory_log_candidates" in budget_doc


def test_load_expand_subset_tokens_missing_file():
    assert load_expand_subset_tokens("/nonexistent/path.json") == []


def test_cli_accepts_token_subset_file(tmp_path: Path):
    subset = tmp_path / "subset.json"
    subset.write_text(
        json.dumps({"tokens": [{"token": "0x" + "3" * 40}]}),
        encoding="utf-8",
    )
    scan = tmp_path / "scan.json"
    hints = tmp_path / "hints.json"
    radar = tmp_path / "radar.json"
    rc = subprocess.run(
        [
            sys.executable,
            str(_REPO / "scripts/m8_onchain_factory_mirror_scan.py"),
            "--dry-run",
            "--skip-factory-log",
            "--token-subset-file",
            str(subset),
            "--scan-artifact",
            str(scan),
            "--hints-output",
            str(hints),
            "--radar-output",
            str(radar),
            "--max-tokens",
            "1",
        ],
        cwd=str(_REPO),
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert rc.returncode == 0, rc.stderr
    assert "tokens=1" in rc.stdout


def test_factory_log_config_path_is_path_object():
    assert isinstance(FACTORY_LOG_CONFIG_PATH, Path)
    assert FACTORY_LOG_CONFIG_PATH.name == "new_pool_factories.yaml"


def test_compute_mirror_venue_metrics_splits_first_pool_and_second_venue():
    weth = "0x4200000000000000000000000000000000000006"
    tok_a = "0x" + "a" * 40
    tok_b = "0x" + "b" * 40
    hints = [
        PoolHint(
            source="onchain_factory",
            chain="base",
            dex_id="uniswap_v2",
            pool_address="0x" + "1" * 40,
            token0_addr=tok_a,
            token1_addr=weth,
            focus_token=tok_a,
            hint_status="HINT_ONCHAIN_VERIFIED",
        ),
        PoolHint(
            source="onchain_factory",
            chain="base",
            dex_id="sushiswap_v2",
            pool_address="0x" + "2" * 40,
            token0_addr=tok_a,
            token1_addr=weth,
            focus_token=tok_a,
            hint_status="HINT_ONCHAIN_VERIFIED",
        ),
        PoolHint(
            source="onchain_factory",
            chain="base",
            dex_id="uniswap_v2",
            pool_address="0x" + "3" * 40,
            token0_addr=tok_b,
            token1_addr=weth,
            focus_token=tok_b,
            hint_status="HINT_ONCHAIN_VERIFIED",
        ),
    ]
    m = compute_mirror_venue_metrics(hints)
    assert m["first_pool_found"] == 2
    assert m["second_venue_found"] == 1
    assert m["verified_pool_count"] == 3
    assert tok_a in m["tokens_with_second_venue"]


def test_factory_log_scan_from_uses_earliest_per_token_window():
    from m8.discovery.onchain_factory_mirror_discovery import _factory_log_scan_from_blocks

    tokens = [
        {"token": "0x" + "1" * 40, "first_seen_block": 100},
        {"token": "0x" + "2" * 40, "first_seen_block": 4900},
    ]
    scan_from, per_token = _factory_log_scan_from_blocks(tokens, head=5000, max_blocks=5000)
    assert scan_from == 0
    assert len(per_token) == 2
    assert per_token["0x" + "1" * 40] == 100
    assert per_token["0x" + "2" * 40] == 4900


def test_factory_log_scan_from_not_shared_max_across_tokens():
    from m8.discovery.onchain_factory_mirror_discovery import _factory_log_scan_from_blocks

    tokens = [
        {"token": "0x" + "1" * 40, "first_seen_block": 100},
        {"token": "0x" + "2" * 40, "first_seen_block": 4900},
    ]
    # Old bug used max(100, 4900)=4900 as sole lower bound.
    scan_from, _ = _factory_log_scan_from_blocks(tokens, head=5000, max_blocks=100)
    assert scan_from == 4900
    scan_from_wide, _ = _factory_log_scan_from_blocks(tokens, head=5000, max_blocks=5000)
    assert scan_from_wide == 0


def test_factory_log_chunk_ranges_splits_wide_window():
    from m8.discovery.onchain_factory_mirror_discovery import (
        FACTORY_LOG_HOT_CHUNK_BLOCKS,
        _factory_log_chunk_ranges,
    )

    ranges = _factory_log_chunk_ranges(0, 5000, chunk_blocks=FACTORY_LOG_HOT_CHUNK_BLOCKS)
    assert len(ranges) == 26
    assert ranges[0] == (0, FACTORY_LOG_HOT_CHUNK_BLOCKS - 1)
    assert ranges[-1][1] == 5000


def test_factory_log_wide_window_fetch_splits_and_fetches_logs():
    from m8.discovery.onchain_factory_mirror_discovery import (
        _empty_factory_log_stats,
        _factory_log_chunk_ranges,
        _fetch_factory_logs_chunked,
    )

    class _Lane:
        def __init__(self):
            self.calls: list = []

        def get_logs(self, params):
            self.calls.append(dict(params))
            span = int(params["toBlock"]) - int(params["fromBlock"]) + 1
            if span > 250:
                return [], True, "400 Bad Request: block range too large"
            return [{"block": params["fromBlock"]}], False, ""

    stats = _empty_factory_log_stats()
    lane = _Lane()
    ranges = _factory_log_chunk_ranges(0, 5000, chunk_blocks=200)
    logs = _fetch_factory_logs_chunked(
        lane,
        factory="0x" + "f" * 40,
        topic0="0x" + "a" * 64,
        from_block=0,
        to_block=5000,
        chunk_blocks=200,
        stats=stats,
        checksum_fn=lambda x: x,
    )
    assert logs
    assert len(logs) == len(ranges)
    assert stats["log_chunks_ok"] == len(ranges)
    assert stats["log_fetch_errors"] == 0
    assert len(lane.calls) == len(ranges)


def test_factory_log_get_logs_failover_after_alchemy_400():
    from unittest.mock import MagicMock

    from monitoring.sniper_funnel import FunnelTracker
    from m8.discovery.onchain_factory_mirror_discovery import (
        _empty_factory_log_stats,
        _factory_log_get_logs,
        _merge_funnel_into_factory_log_stats,
    )
    from m8.runtime.smoke_run import SniperRpcLane

    funnel = FunnelTracker()
    w3_pri = MagicMock()
    w3_pri.eth.get_logs.side_effect = [Exception("400 Bad Request: block range too large")]
    w3_sec = MagicMock()
    w3_sec.eth.get_logs.return_value = [{"log": "secondary"}]
    lane = SniperRpcLane(
        w3_primary=w3_pri,
        w3_secondary=w3_sec,
        primary_provider="alchemy",
        secondary_provider="drpc",
        funnel=funnel,
    )
    stats = _empty_factory_log_stats()
    logs = _factory_log_get_logs(
        lane,
        {"fromBlock": 100, "toBlock": 199, "address": "0x" + "a" * 40},
        stats,
    )
    _merge_funnel_into_factory_log_stats(stats, funnel)
    assert logs == [{"log": "secondary"}]
    assert stats["log_chunks_ok"] == 1


def test_raw_factory_log_discovers_anchor_sided_untracked_token():
    """Raw factory scan returns focus_token = non-anchor token when anchor is present."""
    from unittest.mock import MagicMock, patch
    from dataclasses import replace

    from discovery.new_pool_listener import FactoryConfig
    from m8.discovery.onchain_factory_mirror_discovery import (
        scan_raw_factory_logs_for_anchor_pools,
    )

    anchor_addr = "0x" + "a" * 40
    untracked_addr = "0x" + "u" * 40
    pool_addr = "0x" + "p" * 40

    cfg = FactoryConfig(
        chain="base",
        dex="uniswap_v3",
        adapter_type="uniswap_v3",
        factory="0x" + "f" * 40,
        event_name="PoolCreated",
        event_signature="PoolCreated(address,address,uint24,int24,address)",
        log_layout="v3_pool_created",
        topic0="0x" + "t" * 64,
        topic0_verified=True,
        verification_from_block=10000,
        verification_to_block=11000,
    )

    class _FakeEvent:
        def __init__(self, token0, token1, pool):
            self.token0 = token0
            self.token1 = token1
            self.pool = pool
            self.block_number = 12345
            self.tx_hash = "0x" + "x" * 64
            self.log_index = 0
            self.fee = 3000
            self.tick_spacing = None
            self.stable = None
            self.hooks = None

    fake_lane = MagicMock()
    fake_lane.w3.is_connected.return_value = True
    fake_lane.w3.eth.block_number = 13000
    fake_lane.w3.to_checksum_address = lambda x: x
    fake_lane.get_logs.return_value = ([{"raw": "log1"}], False, "")

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._anchor_pairs",
        return_value=[("USDC", anchor_addr)],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._p0_dex_rows",
        return_value=[{"dex_id": "uniswap_v3", "enabled_for_productive": True, "factory": "0x" + "f" * 40}],
    ), patch(
        "discovery.new_pool_listener.load_factory_config",
        return_value=[cfg],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._build_factory_log_rpc_lane",
        return_value=(fake_lane, MagicMock(), {}),
    ), patch(
        "discovery.new_pool_listener.parse_raw_log",
        return_value=_FakeEvent(anchor_addr, untracked_addr, pool_addr),
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        events, stats = scan_raw_factory_logs_for_anchor_pools(
            chain="base",
            config={"anchor_tokens": ["USDC"]},
            max_blocks=1000,
        )

    assert len(events) == 1
    assert events[0]["focus_token"] == untracked_addr.lower()
    assert events[0]["anchor_token"] == anchor_addr.lower()
    assert events[0]["anchor_sym"] == "USDC"
    assert events[0]["pool"] == pool_addr.lower()
    assert events[0]["dex_id"] == "uniswap_v3"
    assert stats["raw_anchor_pools_seen"] == 1
    assert stats["raw_factory_new_focus_tokens_total"] == 1


def test_raw_factory_log_skips_non_anchor_pairs():
    """Raw scan ignores events where neither token is a known anchor."""
    from unittest.mock import MagicMock, patch

    from discovery.new_pool_listener import FactoryConfig
    from m8.discovery.onchain_factory_mirror_discovery import (
        scan_raw_factory_logs_for_anchor_pools,
    )

    cfg = FactoryConfig(
        chain="base",
        dex="uniswap_v3",
        adapter_type="uniswap_v3",
        factory="0x" + "f" * 40,
        event_name="PoolCreated",
        event_signature="PoolCreated(address,address,uint24,int24,address)",
        log_layout="v3_pool_created",
        topic0="0x" + "t" * 64,
        topic0_verified=True,
        verification_from_block=10000,
        verification_to_block=11000,
    )

    class _FakeEvent:
        def __init__(self):
            self.token0 = "0x" + "a" * 40
            self.token1 = "0x" + "b" * 40
            self.pool = "0x" + "p" * 40
            self.block_number = 12345
            self.tx_hash = "0x" + "x" * 64
            self.log_index = 0
            self.fee = 3000
            self.tick_spacing = None
            self.stable = None
            self.hooks = None

    fake_lane = MagicMock()
    fake_lane.w3.is_connected.return_value = True
    fake_lane.w3.eth.block_number = 13000
    fake_lane.w3.to_checksum_address = lambda x: x
    fake_lane.get_logs.return_value = ([{"raw": "log1"}], False, "")

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._anchor_pairs",
        return_value=[("USDC", "0x" + "c" * 40)],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._p0_dex_rows",
        return_value=[{"dex_id": "uniswap_v3", "enabled_for_productive": True, "factory": "0x" + "f" * 40}],
    ), patch(
        "discovery.new_pool_listener.load_factory_config",
        return_value=[cfg],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._build_factory_log_rpc_lane",
        return_value=(fake_lane, MagicMock(), {}),
    ), patch(
        "discovery.new_pool_listener.parse_raw_log",
        return_value=_FakeEvent(),
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        events, stats = scan_raw_factory_logs_for_anchor_pools(
            chain="base",
            config={"anchor_tokens": ["USDC"]},
            max_blocks=1000,
        )

    assert events == []
    assert stats["raw_anchor_pools_seen"] == 0


def test_raw_factory_log_skips_v4_pool_id():
    """Raw scan ignores V4-style 66-char poolIds (not EVM pool addresses)."""
    from unittest.mock import MagicMock, patch

    from discovery.new_pool_listener import FactoryConfig
    from m8.discovery.onchain_factory_mirror_discovery import (
        scan_raw_factory_logs_for_anchor_pools,
    )

    anchor_addr = "0x" + "a" * 40
    untracked_addr = "0x" + "u" * 40
    v4_pool_id = "0x" + "p" * 64

    cfg = FactoryConfig(
        chain="base",
        dex="uniswap_v4",
        adapter_type="uniswap_v4",
        factory="0x" + "f" * 40,
        event_name="Initialize",
        event_signature="Initialize(bytes32,address,address,uint24,int24,address,uint160,int24)",
        log_layout="v4_initialize",
        topic0="0x" + "t" * 64,
        topic0_verified=True,
        verification_from_block=10000,
        verification_to_block=11000,
        discovery_only=False,
    )

    class _FakeEvent:
        def __init__(self):
            self.token0 = anchor_addr
            self.token1 = untracked_addr
            self.pool = v4_pool_id
            self.block_number = 12345
            self.tx_hash = "0x" + "x" * 64
            self.log_index = 0
            self.fee = 3000
            self.tick_spacing = None
            self.stable = None
            self.hooks = None

    fake_lane = MagicMock()
    fake_lane.w3.is_connected.return_value = True
    fake_lane.w3.eth.block_number = 13000
    fake_lane.w3.to_checksum_address = lambda x: x
    fake_lane.get_logs.return_value = ([{"raw": "log1"}], False, "")

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._anchor_pairs",
        return_value=[("USDC", anchor_addr)],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._p0_dex_rows",
        return_value=[{"dex_id": "uniswap_v4", "enabled_for_productive": True, "factory": "0x" + "f" * 40}],
    ), patch(
        "discovery.new_pool_listener.load_factory_config",
        return_value=[cfg],
    ), patch(
        "m8.discovery.onchain_factory_mirror_discovery._build_factory_log_rpc_lane",
        return_value=(fake_lane, MagicMock(), {}),
    ), patch(
        "discovery.new_pool_listener.parse_raw_log",
        return_value=_FakeEvent(),
    ), patch.dict("os.environ", {"ARBY_SKIP_RPC": "0"}, clear=False):
        events, stats = scan_raw_factory_logs_for_anchor_pools(
            chain="base",
            config={"anchor_tokens": ["USDC"]},
            max_blocks=1000,
        )

    assert events == []
    assert stats["raw_anchor_pools_seen"] == 0
    assert stats["log_fetch_errors"] == 0
    assert stats["log_provider_fallbacks"] >= 1


def test_overlay_verify_budget_preserves_onchain_scan(tmp_path: Path):
    from m8.discovery.onchain_factory_mirror_discovery import (
        overlay_verify_budget_with_onchain_scan,
    )

    scan = tmp_path / "scan.json"
    scan.write_text(
        json.dumps(
            {
                "onchain_factory_candidates": 4,
                "verified_second_pool_by_source": {"onchain_factory": 4},
                "first_pool_found": 4,
                "second_venue_found": 0,
                "verified_pool_count": 4,
                "verified_second_pool_count": 0,
            }
        ),
        encoding="utf-8",
    )
    out = overlay_verify_budget_with_onchain_scan(
        {"onchain_verified": 0, "pipeline_mode": "verify_subset"},
        scan_path=scan,
    )
    assert out["onchain_factory_verified"] == 4
    assert out["first_pool_found"] == 4
    assert out["second_venue_found"] == 0
    assert out["onchain_verified"] == 4


def test_build_mirror_yield_funnel_reads_onchain_scan(tmp_path: Path, monkeypatch):
    from m8.discovery.time_to_mirror_lane import build_mirror_yield_funnel_artifact

    scan = tmp_path / "scan.json"
    scan.write_text(
        json.dumps(
            {
                "onchain_factory_candidates": 3,
                "verified_second_pool_by_source": {"onchain_factory": 3},
                "first_pool_found": 3,
                "second_venue_found": 0,
                "verified_pool_count": 3,
                "verified_second_pool_count": 0,
                "verified_pools": [{"focus_token": "0x" + "1" * 40}],
            }
        ),
        encoding="utf-8",
    )
    budget = tmp_path / "budget.json"
    budget.write_text(json.dumps({"onchain_verified": 0}), encoding="utf-8")
    narrow = tmp_path / "narrow.json"
    narrow.write_text(
        json.dumps(
            {
                "quote_ready_token_count": 0,
                "fresh_long_tail_quote_ready_tokens": 0,
                "target_universe_gate_blocked": True,
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "m8.discovery.onchain_factory_mirror_discovery.load_onchain_scan_funnel_fields",
        lambda scan_path=None: {
            "onchain_factory_candidates": 3,
            "onchain_factory_verified": 3,
            "first_pool_found": 3,
            "second_venue_found": 0,
            "verified_pool_count": 3,
            "verified_second_pool_count": 0,
            "verified_second_pool_by_source": {"onchain_factory": 3},
            "verified_pools": [{"focus_token": "0x" + "1" * 40}],
        },
    )
    payload = build_mirror_yield_funnel_artifact(
        pending_path=tmp_path / "missing.json",
        verify_budget_path=budget,
        narrow_path=narrow,
        output_path=tmp_path / "funnel.json",
    )
    assert payload["onchain_factory_verified"] == 3
    assert payload["onchain_verified"] == 3
    assert payload["first_pool_found"] == 3
    assert payload["second_venue_found"] == 0


def test_load_factory_recall_hints_preserves_token_addresses(tmp_path, monkeypatch):
    """Scan artifact must preserve token0/token1 for factory recall hints.

    Without this, verify_factory_pool returns FACTORY_MISSING_TOKENS because
    it cannot call factory.getPool(token0, token1, fee).
    """
    import json as _json

    from m8.discovery.token_pool_universe import load_factory_recall_hints

    scan = {
        "chain": "base",
        "verified_pools": [
            {
                "focus_token": "0x" + "1" * 40,
                "dex_id": "uniswap_v3",
                "pool_address": "0x" + "a" * 40,
                "token0_addr": "0x" + "1" * 40,
                "token1_addr": "0x" + "2" * 40,
                "fee": 3000,
                "factory_address": "0x" + "f" * 40,
                "created_at": "2026-07-01T00:00:00Z",
                "hint_status": "HINT_FACTORY_VERIFIED",
                "source": "onchain_factory",
            }
        ],
    }
    scan_path = tmp_path / "scan.json"
    scan_path.write_text(_json.dumps(scan), encoding="utf-8")

    hints_path = tmp_path / "hints.json"
    hints_path.write_text(
        _json.dumps({"schema_version": "m8_external_pool_hints_v2", "hints": []}),
        encoding="utf-8",
    )

    fresh_tokens = {"0x" + "1" * 40}
    hints = load_factory_recall_hints(
        fresh_tokens,
        scan_path=str(scan_path),
        hints_path=str(hints_path),
    )
    assert len(hints) == 1
    h = hints[0]
    assert h.token0_addr == "0x" + "1" * 40
    assert h.token1_addr == "0x" + "2" * 40
    assert h.fee == 3000
    assert h.factory_address == "0x" + "f" * 40
    assert h.created_at == "2026-07-01T00:00:00Z"


def test_load_factory_recall_hints_preserves_provenance(tmp_path, monkeypatch):
    """created_at_source and first_seen_block survive scan artifact round-trip."""
    import json as _json

    from m8.discovery.token_pool_universe import load_factory_recall_hints

    scan = {
        "chain": "base",
        "verified_pools": [
            {
                "focus_token": "0x" + "1" * 40,
                "dex_id": "uniswap_v3",
                "pool_address": "0x" + "a" * 40,
                "token0_addr": "0x" + "1" * 40,
                "token1_addr": "0x" + "2" * 40,
                "fee": 3000,
                "factory_address": "0x" + "f" * 40,
                "created_at": "2026-06-07T10:34:21Z",
                "created_at_source": "first_seen_block_proxy",
                "first_seen_block": 47019463,
                "hint_status": "HINT_FACTORY_VERIFIED",
                "source": "onchain_factory",
            }
        ],
    }
    scan_path = tmp_path / "scan_prov.json"
    scan_path.write_text(_json.dumps(scan), encoding="utf-8")

    hints_path = tmp_path / "hints_prov.json"
    hints_path.write_text(
        _json.dumps({"schema_version": "m8_external_pool_hints_v2", "hints": []}),
        encoding="utf-8",
    )

    hints = load_factory_recall_hints(
        {"0x" + "1" * 40},
        scan_path=str(scan_path),
        hints_path=str(hints_path),
    )
    assert len(hints) == 1
    h = hints[0]
    assert (h.raw or {}).get("created_at_source") == "first_seen_block_proxy"
    assert (h.raw or {}).get("first_seen_block") == 47019463


def test_load_factory_recall_hints_empty_tokens_when_scan_missing_fields(tmp_path):
    """Backward compat: scan artifact without token fields still loads (empty)."""
    import json as _json

    from m8.discovery.token_pool_universe import load_factory_recall_hints

    scan = {
        "chain": "base",
        "verified_pools": [
            {
                "focus_token": "0x" + "1" * 40,
                "dex_id": "uniswap_v3",
                "pool_address": "0x" + "a" * 40,
                "source": "onchain_factory",
            }
        ],
    }
    scan_path = tmp_path / "scan_old.json"
    scan_path.write_text(_json.dumps(scan), encoding="utf-8")

    hints_path = tmp_path / "hints_old.json"
    hints_path.write_text(
        _json.dumps({"schema_version": "m8_external_pool_hints_v2", "hints": []}),
        encoding="utf-8",
    )

    hints = load_factory_recall_hints(
        {"0x" + "1" * 40},
        scan_path=str(scan_path),
        hints_path=str(hints_path),
    )
    assert len(hints) == 1
    assert hints[0].token0_addr == ""
    assert hints[0].token1_addr == ""


def test_enrich_hints_from_subset_populates_created_at_from_first_seen_block():
    """Factory hints without created_at get timestamp from first_seen_block."""
    from datetime import datetime, timezone

    token_addr = "0x" + "1" * 40
    hint = PoolHint(
        source="onchain_factory",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr=token_addr,
        token1_addr="0x" + "2" * 40,
        focus_token=token_addr,
    )

    tokens = [{"token": token_addr, "first_seen_block": 47019463}]
    block_ts = "2025-05-23T10:00:00Z"

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._resolve_block_timestamps",
        return_value={47019463: block_ts},
    ), patch(
        "m8.discovery.token_watchlist.load_watchlist", return_value={"tokens": {}}
    ):
        result = _enrich_hints_from_subset([hint], tokens, chain="base")

    assert len(result) == 1
    assert result[0].created_at == block_ts
    assert result[0].raw.get("created_at_source") == "first_seen_block_proxy"
    assert result[0].raw.get("first_seen_block") == 47019463


def test_enrich_hints_from_subset_no_first_seen_block_keeps_stale():
    """Hints without first_seen_block remain stale (created_at=None)."""
    token_addr = "0x" + "1" * 40
    hint = PoolHint(
        source="onchain_factory",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr=token_addr,
        token1_addr="0x" + "2" * 40,
        focus_token=token_addr,
    )

    tokens = [{"token": token_addr}]  # no first_seen_block

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._resolve_block_timestamps",
        return_value={},
    ), patch(
        "m8.discovery.token_watchlist.load_watchlist", return_value={"tokens": {}}
    ):
        result = _enrich_hints_from_subset([hint], tokens, chain="base")

    assert len(result) == 1
    assert result[0].created_at is None
    assert "created_at_source" not in (result[0].raw or {})


def test_enrich_hints_preserves_existing_created_at():
    """Hints with existing created_at are not overwritten by proxy."""
    token_addr = "0x" + "1" * 40
    existing_ts = "2025-06-01T12:00:00Z"
    hint = PoolHint(
        source="factory_log",
        chain="base",
        dex_id="uniswap_v3",
        pool_address="0x" + "a" * 40,
        token0_addr=token_addr,
        token1_addr="0x" + "2" * 40,
        focus_token=token_addr,
        created_at=existing_ts,
    )

    tokens = [{"token": token_addr, "first_seen_block": 47019463}]

    with patch(
        "m8.discovery.onchain_factory_mirror_discovery._resolve_block_timestamps",
        return_value={47019463: "2025-05-23T10:00:00Z"},
    ), patch(
        "m8.discovery.token_watchlist.load_watchlist", return_value={"tokens": {}}
    ):
        result = _enrich_hints_from_subset([hint], tokens, chain="base")

    assert result[0].created_at == existing_ts
    assert "created_at_source" not in (result[0].raw or {})
