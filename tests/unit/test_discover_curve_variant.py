"""Unit tests for Curve pool variant classification in discover_curve_indices.

Locks the pure get_dy ABI-shape decision (stable=int128 vs crypto=uint256)
and the variant/probe_status fields emitted into the rolling indices artifact.
"""
from __future__ import annotations

from scripts.discover_curve_indices import (
    _classify_curve_variant,
    _iter_symbol_probe_pairs,
    _pool_entry,
    probe_curve_variant_best,
)


class TestClassifyCurveVariant:
    def test_int128_ok_is_stable(self):
        assert _classify_curve_variant(True, False) == ("stable", "QUOTE_OK_INT128")

    def test_int128_ok_wins_even_if_uint256_ok(self):
        # Stable ABI is the safe default selector when both answer.
        assert _classify_curve_variant(True, True) == ("stable", "QUOTE_OK_INT128")

    def test_uint256_only_is_crypto(self):
        assert _classify_curve_variant(False, True) == ("crypto", "QUOTE_OK_UINT256")

    def test_both_revert_is_none(self):
        assert _classify_curve_variant(False, False) == (None, "QUOTE_REVERT_BOTH")


class TestPoolEntryVariantFields:
    def _known(self):
        return {
            "0x" + "aa" * 20: "USDC",
            "0x" + "bb" * 20: "USDT",
        }

    def test_entry_carries_variant_and_probe_status(self):
        coins = {"0x" + "aa" * 20: 0, "0x" + "bb" * 20: 1}
        entry = _pool_entry(
            coins, self._known(), pool_kind="crypto", probe_status="QUOTE_OK_UINT256"
        )
        assert entry["pool_kind"] == "crypto"
        assert entry["curve_variant"] == "crypto"
        assert entry["probe_status"] == "QUOTE_OK_UINT256"
        assert entry["coin_indices"] == {"USDC": 0, "USDT": 1}

    def test_entry_defaults_to_stable_not_probed(self):
        coins = {"0x" + "aa" * 20: 0, "0x" + "bb" * 20: 1}
        entry = _pool_entry(coins, self._known())
        assert entry["pool_kind"] == "stable"
        assert entry["probe_status"] == "NOT_PROBED"


class TestProbePairSelection:
    def test_route_pairs_preferred_over_sorted_indices(self):
        """Multi-coin pools must probe the bridge token pair, not coin[0]->coin[1]."""
        coin_indices = {"WETH": 0, "crvUSD": 1, "USDC": 2}
        route_pairs = [("USDC", "WETH"), ("WETH", "USDC")]
        ordered = _iter_symbol_probe_pairs(coin_indices, route_pairs)
        assert ordered[0] == ("USDC", "WETH")

    def test_crypto_artifact_flows_to_metadata_and_quoter(self, tmp_path):
        """pool_kind=crypto in rolling artifact -> metadata -> uint256 selector."""
        import json

        from m9.graph_arb.adapter_metadata import load_adapter_metadata
        from tests.unit.test_m9_adapter_metadata import TestCurveConfigDrivenIndices

        rolling = tmp_path / "indices.json"
        pool = "0xcccc000000000000000000000000000000000003"
        rolling.write_text(
            json.dumps(
                {
                    "schema_version": "m9_curve_pool_indices.1",
                    "chain": "base",
                    "pools": {
                        pool: {
                            "pool_kind": "crypto",
                            "coin_indices": {"USDC": 0, "WETH": 1},
                            "probe_status": "QUOTE_OK_UINT256",
                        }
                    },
                }
            ),
            encoding="utf-8",
        )
        meta = load_adapter_metadata(
            "config/adapter_metadata.yaml",
            curve_pool_indices_path=str(rolling),
        )
        assert meta.curve_pool_kind(pool, chain="base") == "crypto"
        assert TestCurveConfigDrivenIndices()._capture_calldata_kind("crypto").startswith(
            "0x556d6e9f"
        )


class TestProbeCurveVariantBest:
    def test_mocked_best_picks_winning_route_pair(self, monkeypatch):
        pool = "0x" + "11" * 20
        coin_indices = {"USDC": 2, "WETH": 0, "crvUSD": 1}
        calls: list[tuple[int, int]] = []

        def fake_probe(_pool: str, idx_in: int, idx_out: int):
            calls.append((idx_in, idx_out))
            if (idx_in, idx_out) == (2, 0):
                return "stable", "QUOTE_OK_INT128", {}
            return None, "QUOTE_REVERT_BOTH", {}

        monkeypatch.setattr(
            "scripts.discover_curve_indices.probe_curve_variant",
            fake_probe,
        )
        kind, status, _dbg = probe_curve_variant_best(
            pool,
            coin_indices,
            [("USDC", "WETH")],
        )
        assert kind == "stable"
        assert status == "QUOTE_OK_INT128"
        assert (2, 0) in calls
