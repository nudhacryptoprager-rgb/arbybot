"""E1.83 — Unit tests for m7.scouts.factory_scout.

All tests are offline (no RPC calls):
  - scan_factories_for_pairs() is exercised with ARBY_SKIP_RPC=1 (returns []).
  - build_pool_family_truth() is exercised with synthetic FactoryPoolEntry objects.
  - _canonical_pair() ordering is verified.
  - Per-adapter logic is verified via injected mock calls.
"""

from __future__ import annotations

import os
from typing import List
from unittest.mock import MagicMock, patch

import pytest

from m7.scouts.factory_scout import (
    BASE_FACTORIES,
    FactoryPoolEntry,
    PoolFamilyTruth,
    ZERO_ADDRESS,
    BASE_TARGET_PAIRS,
    _canonical_pair,
    _query_v2_factory,
    _query_v3_factory,
    _query_ve33_factory,
    _query_slipstream_factory,
    build_pool_family_truth,
    scan_factories_for_pairs,
    write_pool_family_truth,
    load_pool_family_truth,
    _POOL_FAMILY_TRUTH_PATH,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

WETH = "0x4200000000000000000000000000000000000006"
USDC = "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913"
VIRTUAL = "0x0b3e328455c4059EEb9e3f84b5543F74E24e7E1b"
AERO = "0x940181a94A35A4569E4529A3CDfB74e38FD98631"

DUMMY_POOL = "0xdeadbeefdeadbeefdeadbeefdeadbeefdeadbeef"


def _make_entry(
    dex: str = "uniswap_v3",
    adapter: str = "uniswap_v3",
    pool: str = DUMMY_POOL,
    sym_a: str = "USDC",
    sym_b: str = "WETH",
    addr_a: str = USDC,
    addr_b: str = WETH,
    fee: int | None = 500,
    tick_spacing: int | None = None,
    stable: bool | None = None,
) -> FactoryPoolEntry:
    return FactoryPoolEntry(
        chain="base",
        dex=dex,
        adapter_type=adapter,
        pool_address=pool,
        token_a=sym_a,
        token_b=sym_b,
        addr_a=addr_a,
        addr_b=addr_b,
        fee_tier=fee,
        tick_spacing=tick_spacing,
        stable=stable,
    )


# ---------------------------------------------------------------------------
# _canonical_pair
# ---------------------------------------------------------------------------


class TestCanonicalPair:
    def test_alphabetical_usdc_weth(self):
        key, a, b = _canonical_pair("WETH", "USDC")
        assert key == "USDC/WETH"
        assert a == "USDC"
        assert b == "WETH"

    def test_already_ordered(self):
        key, a, b = _canonical_pair("AERO", "WETH")
        assert key == "AERO/WETH"
        assert a == "AERO"
        assert b == "WETH"

    def test_same_symbols(self):
        key, a, b = _canonical_pair("WETH", "WETH")
        assert key == "WETH/WETH"

    def test_lowercase_normalised(self):
        key, a, b = _canonical_pair("usdc", "weth")
        assert key == "USDC/WETH"


# ---------------------------------------------------------------------------
# build_pool_family_truth — pure aggregation
# ---------------------------------------------------------------------------


class TestBuildPoolFamilyTruth:
    def test_empty_input(self):
        result = build_pool_family_truth([])
        assert result == {}

    def test_single_pool(self):
        entries = [_make_entry()]
        result = build_pool_family_truth(entries)
        assert "USDC/WETH" in result
        fam = result["USDC/WETH"]
        assert fam.pool_count == 1
        assert fam.dex_count == 1
        assert "uniswap_v3" in fam.dex_set
        assert fam.fee_tiers == [500]

    def test_two_pools_same_pair_different_dex(self):
        entries = [
            _make_entry(dex="uniswap_v3", pool=DUMMY_POOL, fee=500),
            _make_entry(dex="aerodrome_slipstream", adapter="aerodrome_slipstream",
                        pool="0xcafe" + "0" * 36, fee=None, tick_spacing=200),
        ]
        result = build_pool_family_truth(entries)
        fam = result["USDC/WETH"]
        assert fam.pool_count == 2
        assert fam.dex_count == 2
        assert "uniswap_v3" in fam.dex_set
        assert "aerodrome_slipstream" in fam.dex_set
        assert 500 in fam.fee_tiers
        assert 200 in fam.tick_spacings

    def test_two_pools_same_dex_different_fee(self):
        entries = [
            _make_entry(dex="uniswap_v3", pool=DUMMY_POOL, fee=500),
            _make_entry(dex="uniswap_v3", pool="0xcafe" + "0" * 36, fee=3000),
        ]
        result = build_pool_family_truth(entries)
        fam = result["USDC/WETH"]
        assert fam.pool_count == 2
        assert fam.dex_count == 1  # same DEX
        assert sorted(fam.fee_tiers) == [500, 3000]

    def test_ve33_stable_flag(self):
        entries = [
            _make_entry(dex="aerodrome", adapter="ve33", fee=None, stable=False),
            _make_entry(dex="aerodrome", adapter="ve33",
                        pool="0xcafe" + "0" * 36, fee=None, stable=True),
        ]
        result = build_pool_family_truth(entries)
        fam = result["USDC/WETH"]
        assert fam.has_stable_pool is True
        assert fam.has_volatile_pool is True

    def test_different_pairs_separate_families(self):
        entries = [
            _make_entry(sym_a="USDC", sym_b="WETH", addr_a=USDC, addr_b=WETH),
            _make_entry(dex="aerodrome", sym_a="AERO", sym_b="WETH",
                        addr_a=AERO, addr_b=WETH, pool="0xcafe" + "0" * 36),
        ]
        result = build_pool_family_truth(entries)
        assert "USDC/WETH" in result
        assert "AERO/WETH" in result
        assert result["USDC/WETH"].pool_count == 1
        assert result["AERO/WETH"].pool_count == 1

    def test_canonical_ordering_reversed_input(self):
        """Input with sym_a=WETH, sym_b=USDC should merge into USDC/WETH family."""
        entries = [
            _make_entry(sym_a="WETH", sym_b="USDC", addr_a=WETH, addr_b=USDC),
            _make_entry(sym_a="USDC", sym_b="WETH", addr_a=USDC, addr_b=WETH,
                        pool="0xcafe" + "0" * 36),
        ]
        result = build_pool_family_truth(entries)
        assert len(result) == 1  # same canonical pair
        fam = result["USDC/WETH"]
        assert fam.pool_count == 2

    def test_to_dict_serialisable(self):
        import json
        entries = [_make_entry()]
        result = build_pool_family_truth(entries)
        d = result["USDC/WETH"].to_dict()
        # Must be JSON-serialisable (no raw sets)
        json.dumps(d)  # should not raise

    def test_factory_pool_count_multi_dex(self):
        """Three pools across 3 DEXes → dex_count=3."""
        entries = [
            _make_entry(dex="uniswap_v3", pool=DUMMY_POOL, fee=500),
            _make_entry(dex="sushiswap_v3", pool="0xcafe" + "0" * 36, fee=3000),
            _make_entry(dex="pancakeswap_v3", pool="0xbabe" + "0" * 36, fee=2500),
        ]
        result = build_pool_family_truth(entries)
        fam = result["USDC/WETH"]
        assert fam.dex_count == 3
        assert fam.pool_count == 3


# ---------------------------------------------------------------------------
# scan_factories_for_pairs — offline (ARBY_SKIP_RPC=1)
# ---------------------------------------------------------------------------


class TestScanFactoriesOffline:
    def test_skip_rpc_returns_empty(self, monkeypatch):
        monkeypatch.setenv("ARBY_SKIP_RPC", "1")
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
        )
        assert result == []

    def test_empty_rpc_url_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="",
        )
        assert result == []

    def test_unknown_network_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        result = scan_factories_for_pairs(
            network="fantasy_chain",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
        )
        assert result == []

    def test_empty_pairs_returns_empty(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        result = scan_factories_for_pairs(
            network="base",
            pairs=[],
            rpc_url="http://localhost:8545",
        )
        assert result == []


# ---------------------------------------------------------------------------
# scan_factories_for_pairs — with mock RPC (unit-level)
# ---------------------------------------------------------------------------


class TestScanFactoriesWithMock:
    """Mock the underlying query_* helpers to avoid real RPC calls."""

    def _mock_v3_returns_pool(self, rpc_url, factory_addr, token_a, token_b, fee):
        """Only return a pool for fee=500."""
        if fee == 500:
            return DUMMY_POOL
        return None

    def test_v3_factory_mock_finds_pool(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_v3_factory",
            self._mock_v3_returns_pool,
        )
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_slipstream_factory",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_ve33_factory",
            lambda *a, **kw: None,
        )
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_v2_factory",
            lambda *a, **kw: None,
        )

        factory_overrides = [
            {
                "dex": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
                "fee_tiers": [100, 500, 3000],
            }
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert len(result) == 1
        assert result[0].fee_tier == 500
        assert result[0].dex == "uniswap_v3"
        assert result[0].pool_address == DUMMY_POOL

    def test_slipstream_mock_finds_pool(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_slipstream_factory",
            lambda rpc, faddr, ta, tb, ts: DUMMY_POOL if ts == 200 else None,
        )

        factory_overrides = [
            {
                "dex": "aerodrome_slipstream",
                "adapter_type": "aerodrome_slipstream",
                "factory": "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A",
                "tick_spacings": [1, 50, 200],
            }
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "VIRTUAL", "symbol_b": "WETH",
                    "addr_a": VIRTUAL, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert len(result) == 1
        assert result[0].tick_spacing == 200
        assert result[0].adapter_type == "aerodrome_slipstream"

    def test_ve33_mock_finds_volatile_pool(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_ve33_factory",
            lambda rpc, faddr, ta, tb, stable: DUMMY_POOL if not stable else None,
        )

        factory_overrides = [
            {
                "dex": "aerodrome",
                "adapter_type": "ve33",
                "factory": "0x420DD381b31aEf6683db6B902084cB0FFECe40Da",
            }
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "VIRTUAL", "symbol_b": "WETH",
                    "addr_a": VIRTUAL, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert len(result) == 1
        assert result[0].stable is False

    def test_v2_mock_finds_pair(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)
        monkeypatch.setattr(
            "m7.scouts.factory_scout._query_v2_factory",
            lambda rpc, faddr, ta, tb: DUMMY_POOL,
        )

        factory_overrides = [
            {
                "dex": "sushiswap_v2",
                "adapter_type": "uniswap_v2",
                "factory": "0x71524B4f93c58fcbF659783284E38825f0622859",
            }
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert len(result) == 1
        assert result[0].fee_tier is None
        assert result[0].stable is None
        assert result[0].tick_spacing is None

    def test_unknown_adapter_type_skipped(self, monkeypatch):
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)

        factory_overrides = [
            {
                "dex": "mystery_dex",
                "adapter_type": "algebra",
                "factory": "0x1234" + "0" * 36,
            }
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[{"symbol_a": "USDC", "symbol_b": "WETH",
                    "addr_a": USDC, "addr_b": WETH}],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert result == []

    def test_multi_pair_multi_factory(self, monkeypatch):
        """USDC/WETH on uniswap_v3 (fee=500) + VIRTUAL/WETH on aerodrome_slipstream."""
        monkeypatch.delenv("ARBY_SKIP_RPC", raising=False)

        def mock_v3(rpc, faddr, ta, tb, fee):
            if ta.lower() == USDC.lower() and fee == 500:
                return DUMMY_POOL
            return None

        def mock_slipstream(rpc, faddr, ta, tb, ts):
            if ta.lower() == VIRTUAL.lower() and ts == 200:
                return "0xcafe" + "0" * 36
            return None

        monkeypatch.setattr("m7.scouts.factory_scout._query_v3_factory", mock_v3)
        monkeypatch.setattr("m7.scouts.factory_scout._query_slipstream_factory",
                            mock_slipstream)
        monkeypatch.setattr("m7.scouts.factory_scout._query_ve33_factory",
                            lambda *a, **kw: None)
        monkeypatch.setattr("m7.scouts.factory_scout._query_v2_factory",
                            lambda *a, **kw: None)

        factory_overrides = [
            {
                "dex": "uniswap_v3",
                "adapter_type": "uniswap_v3",
                "factory": "0x33128a8fC17869897dcE68Ed026d694621f6FDfD",
                "fee_tiers": [500],
            },
            {
                "dex": "aerodrome_slipstream",
                "adapter_type": "aerodrome_slipstream",
                "factory": "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A",
                "tick_spacings": [200],
            },
        ]
        result = scan_factories_for_pairs(
            network="base",
            pairs=[
                {"symbol_a": "USDC", "symbol_b": "WETH",
                 "addr_a": USDC, "addr_b": WETH},
                {"symbol_a": "VIRTUAL", "symbol_b": "WETH",
                 "addr_a": VIRTUAL, "addr_b": WETH},
            ],
            rpc_url="http://localhost:8545",
            factory_overrides=factory_overrides,
        )
        assert len(result) == 2
        pairs_found = {(r.token_a, r.token_b, r.dex) for r in result}
        assert ("USDC", "WETH", "uniswap_v3") in pairs_found
        assert ("VIRTUAL", "WETH", "aerodrome_slipstream") in pairs_found


# ---------------------------------------------------------------------------
# BASE_FACTORIES config sanity
# ---------------------------------------------------------------------------


class TestBaseFactoriesConfig:
    def test_has_required_dexes(self):
        dex_names = {f["dex"] for f in BASE_FACTORIES}
        assert "uniswap_v3" in dex_names
        assert "aerodrome_slipstream" in dex_names
        assert "aerodrome" in dex_names
        assert "sushiswap_v3" in dex_names
        assert "pancakeswap_v3" in dex_names

    def test_all_have_adapter_type(self):
        for f in BASE_FACTORIES:
            assert "adapter_type" in f, f"Missing adapter_type in {f['dex']}"

    def test_v3_factories_have_fee_tiers(self):
        for f in BASE_FACTORIES:
            if f["adapter_type"] == "uniswap_v3":
                assert "fee_tiers" in f and len(f["fee_tiers"]) > 0, (
                    f"{f['dex']} missing fee_tiers"
                )

    def test_slipstream_has_tick_spacings(self):
        slipstream = next(f for f in BASE_FACTORIES
                          if f["adapter_type"] == "aerodrome_slipstream")
        assert "tick_spacings" in slipstream
        assert 200 in slipstream["tick_spacings"]

    def test_factory_addresses_non_zero(self):
        for f in BASE_FACTORIES:
            addr = f.get("factory", "")
            assert addr and addr != ZERO_ADDRESS, f"{f['dex']} has zero/missing factory"


# ---------------------------------------------------------------------------
# PPM integration: factory_truth parameter
# ---------------------------------------------------------------------------


class TestPPMFactoryTruthIntegration:
    """Verify build_pair_pool_matrix uses factory_truth when provided."""

    def _make_pool_dict(self, symbol: str = "USDC-WETH",
                        project: str = "uniswap-v3",
                        pool: str = DUMMY_POOL,
                        tvl: float = 1_000_000.0) -> dict:
        return {
            "symbol": symbol,
            "pool_address": pool,
            "project": project,
            "tvl_usd": tvl,
            "volume_24h_usd": 1000.0,
        }

    def test_factory_pool_count_zero_without_truth(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [self._make_pool_dict()]
        result = build_pair_pool_matrix(pools)
        pair = result["pairs"][0]
        assert pair["factory_pool_count"] == 0
        assert pair["factory_dex_count"] == 0

    def test_factory_pool_count_populated_from_truth(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [self._make_pool_dict()]
        # USDC/WETH has 4 pools across 3 DEXes on-chain
        factory_truth = {
            "USDC/WETH": {
                "pool_count": 4,
                "dex_count": 3,
                "dex_set": ["uniswap_v3", "aerodrome_slipstream", "sushiswap_v3"],
            }
        }
        result = build_pair_pool_matrix(pools, factory_truth=factory_truth)
        pair = result["pairs"][0]
        assert pair["factory_pool_count"] == 4
        assert pair["factory_dex_count"] == 3

    def test_reference_only_false_when_factory_dex_count_gt1(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        # Scout sees only 1 DEX, but factory confirms 2
        pools = [self._make_pool_dict()]
        factory_truth = {
            "USDC/WETH": {"pool_count": 2, "dex_count": 2}
        }
        result = build_pair_pool_matrix(pools, factory_truth=factory_truth)
        pair = result["pairs"][0]
        assert pair["reference_only"] is False

    def test_reference_only_true_when_factory_dex_count_1(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [self._make_pool_dict()]
        factory_truth = {
            "USDC/WETH": {"pool_count": 1, "dex_count": 1}
        }
        result = build_pair_pool_matrix(pools, factory_truth=factory_truth)
        pair = result["pairs"][0]
        assert pair["reference_only"] is True

    def test_factory_truth_unmatched_pair_gets_zero(self):
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        pools = [self._make_pool_dict()]
        # factory_truth has AERO/WETH, not USDC/WETH
        factory_truth = {
            "AERO/WETH": {"pool_count": 3, "dex_count": 2}
        }
        result = build_pair_pool_matrix(pools, factory_truth=factory_truth)
        pair = result["pairs"][0]
        assert pair["factory_pool_count"] == 0
        assert pair["factory_dex_count"] == 0

    def test_factory_truth_with_pool_family_truth_object(self):
        """PoolFamilyTruth dataclass objects also accepted as values."""
        from m7.scouts.pair_pool_matrix import build_pair_pool_matrix
        from m7.scouts.factory_scout import PoolFamilyTruth
        pools = [self._make_pool_dict()]
        pft = PoolFamilyTruth(
            pair="USDC/WETH", token_a="USDC", token_b="WETH",
            addr_a=USDC, addr_b=WETH, pool_count=5, dex_count=3,
        )
        pft.dex_set.add("uniswap_v3")
        pft.dex_set.add("aerodrome_slipstream")
        pft.dex_set.add("pancakeswap_v3")
        factory_truth = {"USDC/WETH": pft}
        result = build_pair_pool_matrix(pools, factory_truth=factory_truth)
        pair = result["pairs"][0]
        assert pair["factory_pool_count"] == 5
        assert pair["factory_dex_count"] == 3


# ---------------------------------------------------------------------------
# Artifact I/O: write_pool_family_truth / load_pool_family_truth
# ---------------------------------------------------------------------------


class TestArtifactIO:
    """write/load pool_family_truth.json round-trip (offline, tmp paths)."""

    def _make_entry(self, dex: str = "uniswap_v3", fee: int = 500) -> FactoryPoolEntry:
        return FactoryPoolEntry(
            chain="base",
            dex=dex,
            adapter_type="uniswap_v3",
            pool_address="0xaaaa",
            token_a="USDC",
            token_b="WETH",
            addr_a=USDC,
            addr_b=WETH,
            fee_tier=fee,
            tick_spacing=None,
            stable=None,
        )

    def test_write_creates_file(self, tmp_path):
        path = str(tmp_path / "pool_family_truth.json")
        entries = [self._make_entry()]
        write_pool_family_truth(entries, path=path)
        assert os.path.exists(path)

    def test_write_schema_fields(self, tmp_path):
        import json as _json
        path = str(tmp_path / "pool_family_truth.json")
        entries = [self._make_entry()]
        write_pool_family_truth(entries, path=path)
        data = _json.loads(open(path).read())
        assert data["schema"] == "pool_family_truth_v1"
        assert "generated_utc" in data
        assert "pairs" in data
        assert data["pair_count"] == 1

    def test_roundtrip_pair_count(self, tmp_path):
        path = str(tmp_path / "pool_family_truth.json")
        entries = [
            self._make_entry(dex="uniswap_v3", fee=500),
            self._make_entry(dex="sushiswap_v3", fee=3000),
        ]
        write_pool_family_truth(entries, path=path)
        pairs = load_pool_family_truth(path=path, max_age_s=float("inf"))
        assert "USDC/WETH" in pairs
        assert pairs["USDC/WETH"]["pool_count"] == 2
        assert pairs["USDC/WETH"]["dex_count"] == 2

    def test_load_missing_file_returns_empty(self, tmp_path):
        path = str(tmp_path / "nonexistent.json")
        result = load_pool_family_truth(path=path)
        assert result == {}

    def test_load_stale_file_returns_empty(self, tmp_path):
        import time as _time
        path = str(tmp_path / "pool_family_truth.json")
        entries = [self._make_entry()]
        write_pool_family_truth(entries, path=path)
        # Patch time.time() to be far in the future so any file is stale
        with patch("m7.scouts.factory_scout.time.time", return_value=_time.time() + 700):
            result = load_pool_family_truth(path=path, max_age_s=600.0)
        assert result == {}

    def test_load_fresh_file_returns_pairs(self, tmp_path):
        path = str(tmp_path / "pool_family_truth.json")
        entries = [self._make_entry()]
        write_pool_family_truth(entries, path=path)
        result = load_pool_family_truth(path=path, max_age_s=float("inf"))
        assert "USDC/WETH" in result

    def test_write_idempotent(self, tmp_path):
        path = str(tmp_path / "pool_family_truth.json")
        entries = [self._make_entry()]
        write_pool_family_truth(entries, path=path)
        mtime1 = os.path.getmtime(path)
        import time as _time; _time.sleep(0.01)
        write_pool_family_truth(entries, path=path)
        # File should still exist and be valid
        result = load_pool_family_truth(path=path, max_age_s=float("inf"))
        assert "USDC/WETH" in result


# ---------------------------------------------------------------------------
# BASE_TARGET_PAIRS config validation
# ---------------------------------------------------------------------------


class TestBaseTargetPairs:
    """Validate BASE_TARGET_PAIRS contents."""

    def test_required_pairs_present(self):
        keys = {f"{p['symbol_a']}/{p['symbol_b']}" for p in BASE_TARGET_PAIRS}
        assert "VIRTUAL/WETH" in keys
        assert "USDC/WETH" in keys
        assert "AERO/USDC" in keys or "AERO/WETH" in keys

    def test_all_pairs_have_addresses(self):
        for p in BASE_TARGET_PAIRS:
            assert p.get("addr_a"), f"{p.get('symbol_a')} missing addr_a"
            assert p.get("addr_b"), f"{p.get('symbol_b')} missing addr_b"
            assert p["addr_a"].startswith("0x"), p
            assert p["addr_b"].startswith("0x"), p

    def test_weth_address_consistent(self):
        """All WETH entries use the same canonical Base WETH address."""
        weth_canon = "0x4200000000000000000000000000000000000006"
        for p in BASE_TARGET_PAIRS:
            if p["symbol_b"] == "WETH":
                assert p["addr_b"].lower() == weth_canon.lower(), p
            if p["symbol_a"] == "WETH":
                assert p["addr_a"].lower() == weth_canon.lower(), p

    def test_pool_family_truth_path_defined(self):
        assert _POOL_FAMILY_TRUTH_PATH.endswith("pool_family_truth.json")
        assert "_rolling" in _POOL_FAMILY_TRUTH_PATH
