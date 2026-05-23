"""Unit tests for ProviderRouter (m9/graph_arb/provider_router.py)."""
from __future__ import annotations

import time

import pytest

from m9.graph_arb.provider_router import ProviderRouter, _mask


PRIMARY = "https://lb.drpc.live/ogrpc?network=base&dkey=testkey"
SECONDARY = "https://mainnet.base.org/secondary"


class TestProviderRouter:
    def test_returns_primary_when_healthy(self):
        router = ProviderRouter(primary=PRIMARY)
        assert router.get_url() == PRIMARY

    def test_returns_primary_when_no_secondary(self):
        router = ProviderRouter(primary=PRIMARY, secondary=None)
        for _ in range(20):
            router.record_429(PRIMARY)
        # No secondary configured → always primary
        assert router.get_url() == PRIMARY

    def test_failover_to_secondary_after_threshold(self):
        router = ProviderRouter(
            primary=PRIMARY,
            secondary=SECONDARY,
            failover_threshold=5,
            window_s=30.0,
            cooldown_s=60.0,
        )
        for _ in range(5):
            router.record_429(PRIMARY)
        assert router.get_url() == SECONDARY
        assert router.is_failed_over

    def test_no_failover_below_threshold(self):
        router = ProviderRouter(
            primary=PRIMARY,
            secondary=SECONDARY,
            failover_threshold=5,
        )
        for _ in range(4):
            router.record_429(PRIMARY)
        assert router.get_url() == PRIMARY
        assert not router.is_failed_over

    def test_primary_recovery_after_cooldown(self):
        router = ProviderRouter(
            primary=PRIMARY,
            secondary=SECONDARY,
            failover_threshold=1,
            cooldown_s=0.05,  # very short cooldown for testing
            window_s=30.0,
        )
        router.record_429(PRIMARY)
        assert router.get_url() == SECONDARY  # failed over
        time.sleep(0.1)
        # After cooldown, primary should be retried
        assert router.get_url() == PRIMARY
        assert not router.is_failed_over

    def test_record_success_tracked(self):
        router = ProviderRouter(primary=PRIMARY, secondary=SECONDARY)
        router.record_success(PRIMARY)
        snap = router.snapshot()
        primary_masked = _mask(PRIMARY)
        assert snap["providers"][primary_masked]["success_total"] == 1

    def test_snapshot_has_expected_keys(self):
        router = ProviderRouter(primary=PRIMARY, secondary=SECONDARY)
        snap = router.snapshot()
        assert "primary" in snap
        assert "secondary" in snap
        assert "is_failed_over" in snap
        assert "providers" in snap

    def test_secondary_not_counted_by_primary_429s(self):
        router = ProviderRouter(
            primary=PRIMARY,
            secondary=SECONDARY,
            failover_threshold=5,
        )
        # Record 429s for SECONDARY (not primary) — primary should not failover
        for _ in range(10):
            router.record_429(SECONDARY)
        assert router.get_url() == PRIMARY

    def test_mask_removes_api_key(self):
        url = "https://lb.drpc.live/ogrpc?network=base&dkey=mysecretkey"
        masked = _mask(url)
        assert "mysecretkey" not in masked
        # Should still contain domain
        assert "drpc.live" in masked

    def test_mask_empty_string(self):
        assert _mask("") == ""

    def test_properties(self):
        router = ProviderRouter(primary=PRIMARY, secondary=SECONDARY)
        assert router.primary == PRIMARY
        assert router.secondary == SECONDARY

    def test_snapshot_does_not_deadlock(self):
        """Regression: _ProviderStats.snapshot() must not deadlock by calling
        recent_429_count() while holding self._lock (non-reentrant lock)."""
        router = ProviderRouter(primary=PRIMARY, secondary=SECONDARY)
        router.record_429(PRIMARY)
        router.record_success(PRIMARY)
        # This call previously deadlocked because snapshot() acquired self._lock
        # then called recent_429_count() which tried to acquire self._lock again.
        snap = router.snapshot()
        primary_masked = _mask(PRIMARY)
        assert snap["providers"][primary_masked]["recent_429"] >= 1
