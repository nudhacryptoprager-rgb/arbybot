"""
Tests for scan ↔ reject_histogram accounting invariants.

v2.1.0: These invariants MUST hold between scan and reject_histogram artifacts:
1. reject_histogram.rejects_total == scan.stats.quotes_rejected
2. reject_histogram.price_sanity_failed == scan.stats.price_sanity_failed
3. len(reject_histogram.rejects) == reject_histogram.rejects_total
"""

import pytest
from strategy.artifacts import build_scan_data, build_reject_data


class TestScanRejectInvariants:
    """Tests for scan ↔ reject_histogram consistency."""

    def test_rejects_total_equals_scan_quotes_rejected(self):
        """reject_histogram.rejects_total must equal scan.stats.quotes_rejected."""
        # Arrange: mock data
        config = {"chain_id": 42161}
        current_block = 123456
        
        # Create rejected_quotes list (canonical source)
        rejected_quotes = [
            {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED", "dex": "uniswap_v3"},
            {"pair": "WETH/USDT", "reason": "POOL_MISSING", "dex": "sushiswap_v3"},
            {"pair": "ARB/WETH", "reason": "PRICE_OUTLIER", "dex": "uniswap_v3"},
        ]
        
        # sanity_rejects is SUBSET of rejected_quotes (filtered by reason)
        sanity_rejects = [r for r in rejected_quotes if r.get("reason") == "PRICE_SANITY_FAILED"]
        
        stats = {
            "quotes_rejected": len(rejected_quotes),  # 3
            "price_sanity_failed": len(sanity_rejects),  # 1
            "pool_missing_count": 1,
            "v3_slot0_failed_count": 0,
        }
        
        infra_payload = {}
        
        # Act
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload
        )
        
        # Assert invariant 1: rejects_total == quotes_rejected
        assert reject_data["rejects_total"] == stats["quotes_rejected"], (
            f"INVARIANT VIOLATED: rejects_total={reject_data['rejects_total']} != "
            f"quotes_rejected={stats['quotes_rejected']}"
        )

    def test_price_sanity_failed_equals_scan_stats(self):
        """reject_histogram.price_sanity_failed must equal scan.stats.price_sanity_failed."""
        # Arrange
        config = {"chain_id": 42161}
        current_block = 123456
        
        rejected_quotes = [
            {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED", "dex": "uniswap_v3"},
            {"pair": "WETH/USDT", "reason": "PRICE_SANITY_FAILED", "dex": "sushiswap_v3"},
            {"pair": "ARB/WETH", "reason": "PRICE_OUTLIER", "dex": "uniswap_v3"},
            {"pair": "LINK/WETH", "reason": "POOL_MISSING", "dex": "uniswap_v3"},
        ]
        
        sanity_rejects = [r for r in rejected_quotes if r.get("reason") == "PRICE_SANITY_FAILED"]
        
        stats = {
            "quotes_rejected": len(rejected_quotes),
            "price_sanity_failed": len(sanity_rejects),  # 2
        }
        
        infra_payload = {}
        
        # Act
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload
        )
        
        # Assert invariant 2: price_sanity_failed consistency
        assert reject_data["price_sanity_failed"] == stats["price_sanity_failed"], (
            f"INVARIANT VIOLATED: reject_histogram.price_sanity_failed={reject_data['price_sanity_failed']} != "
            f"scan.stats.price_sanity_failed={stats['price_sanity_failed']}"
        )

    def test_rejects_list_length_equals_rejects_total(self):
        """len(reject_histogram.rejects) must equal reject_histogram.rejects_total."""
        # Arrange
        config = {"chain_id": 42161}
        current_block = 123456
        
        rejected_quotes = [
            {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED"},
            {"pair": "WETH/USDT", "reason": "PRICE_OUTLIER"},
            {"pair": "ARB/USDC", "reason": "POOL_MISSING"},
            {"pair": "LINK/WETH", "reason": "PRICE_SANITY_FAILED"},
            {"pair": "GMX/WETH", "reason": "QUOTE_FAILED"},
        ]
        
        sanity_rejects = [r for r in rejected_quotes if r.get("reason") == "PRICE_SANITY_FAILED"]
        stats = {"quotes_rejected": len(rejected_quotes), "price_sanity_failed": len(sanity_rejects)}
        infra_payload = {}
        
        # Act
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload
        )
        
        # Assert invariant 3: list length == total count
        assert len(reject_data["rejects"]) == reject_data["rejects_total"], (
            f"INVARIANT VIOLATED: len(rejects)={len(reject_data['rejects'])} != "
            f"rejects_total={reject_data['rejects_total']}"
        )

    def test_no_double_counting_sanity_rejects(self):
        """sanity_rejects must NOT be double-counted in rejects list.
        
        Since sanity_rejects is a subset of rejected_quotes, the rejects list
        should only contain rejected_quotes (not concatenation).
        """
        # Arrange
        config = {"chain_id": 42161}
        current_block = 123456
        
        # Create specific test case where double-counting would be obvious
        rejected_quotes = [
            {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED", "id": 1},
            {"pair": "WETH/USDT", "reason": "PRICE_SANITY_FAILED", "id": 2},
            {"pair": "ARB/WETH", "reason": "PRICE_OUTLIER", "id": 3},
        ]
        
        # sanity_rejects filtered from rejected_quotes
        sanity_rejects = [r for r in rejected_quotes if r.get("reason") == "PRICE_SANITY_FAILED"]
        # sanity_rejects has 2 items, rejected_quotes has 3
        
        stats = {"quotes_rejected": 3, "price_sanity_failed": 2}
        infra_payload = {}
        
        # Act
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, infra_payload
        )
        
        # Assert: should NOT be 5 (2 + 3), should be 3
        assert reject_data["rejects_total"] == 3, (
            f"DOUBLE-COUNT BUG: rejects_total={reject_data['rejects_total']} "
            f"(expected 3, got {reject_data['rejects_total']} which suggests concatenation)"
        )
        assert len(reject_data["rejects"]) == 3, (
            f"DOUBLE-COUNT BUG: len(rejects)={len(reject_data['rejects'])} "
            f"(expected 3, got duplicates from concatenation)"
        )

    def test_sanity_rejects_count_field_present(self):
        """v2.1.0: sanity_rejects_count field must be present for diagnostics."""
        config = {"chain_id": 42161}
        current_block = 123456
        
        rejected_quotes = [
            {"pair": "WETH/USDC", "reason": "PRICE_SANITY_FAILED"},
            {"pair": "WETH/USDT", "reason": "PRICE_OUTLIER"},
        ]
        sanity_rejects = [r for r in rejected_quotes if r.get("reason") == "PRICE_SANITY_FAILED"]
        stats = {"quotes_rejected": 2, "price_sanity_failed": 1}
        
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, {}
        )
        
        assert "sanity_rejects_count" in reject_data, "sanity_rejects_count field missing from v2.1.0"
        assert reject_data["sanity_rejects_count"] == 1

    def test_empty_rejects_invariants(self):
        """All invariants must hold when there are no rejects."""
        config = {"chain_id": 42161}
        current_block = 123456
        
        rejected_quotes = []
        sanity_rejects = []
        stats = {"quotes_rejected": 0, "price_sanity_failed": 0}
        
        reject_data = build_reject_data(
            config, current_block, sanity_rejects, rejected_quotes, stats, {}
        )
        
        # All invariants should hold
        assert reject_data["rejects_total"] == 0
        assert len(reject_data["rejects"]) == 0
        assert reject_data["price_sanity_failed"] == 0
        assert reject_data["no_rejects"] is True
