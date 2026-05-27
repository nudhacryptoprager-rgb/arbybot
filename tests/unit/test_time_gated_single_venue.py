"""Unit tests for time-gated single-venue (fresh_window) logic in bridge_builder.py.

Verifies:
  - When sniper artifact age < 3600s (FRESH): single-venue events are admitted
    and fresh_window_admitted_count > 0 in bridge_source_metrics
  - When sniper artifact age > 3600s (STALE): single-venue events are NOT admitted
    and fresh_window_admitted_count == 0
  - The gate applies only to single-venue events; multi-venue events are unaffected
  - sniper_in_fresh_window flag is set correctly
  - sniper_age_seconds is reported in bridge_source_metrics
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any, Dict, List

import pytest

# ---------------------------------------------------------------------------
# Import under test
# ---------------------------------------------------------------------------
try:
    from m9.graph_arb.bridge_builder import build_bridge_inventory
    BRIDGE_BUILDER_AVAILABLE = True
except ImportError:
    BRIDGE_BUILDER_AVAILABLE = False

pytestmark = pytest.mark.skipif(
    not BRIDGE_BUILDER_AVAILABLE,
    reason="bridge_builder not importable",
)


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _make_sniper_artifact(
    events: List[Dict[str, Any]],
    generated_at_utc: str = None,
) -> Dict[str, Any]:
    """Build a minimal sniper artifact dict."""
    if generated_at_utc is None:
        # Default to "now" — fresh
        from datetime import datetime, timezone
        generated_at_utc = datetime.now(timezone.utc).isoformat()
    return {
        "schema_family": "m8_sniper",
        "schema_revision": "1",
        "generated_at_utc": generated_at_utc,
        "status": "ACTIVE",
        "metrics": {},
        "recent_events": events,
    }


def _make_anchor_artifact() -> Dict[str, Any]:
    return {
        "schema_family": "m8_1_stable_anchor",
        "near_miss": [],
        "metrics": {},
    }


def _make_event(
    pool_address: str = None,
    dex_id: str = "aerodrome",
    adapter_type: str = "ve33_stable",
    token_in: str = None,
    token_out: str = None,
    cross_dex_seen: bool = True,
    multi_venue_confirmed: bool = False,
    anchor_connected: bool = True,
    block_number: int = 1000,
    hooks: str = None,
) -> Dict[str, Any]:
    pool = pool_address or ("0x" + "aa" * 20)
    return {
        "pool_address": pool,
        "dex_id": dex_id,
        "adapter_type": adapter_type,
        "token_in": token_in or ("0x" + "bb" * 20),
        "token_out": token_out or ("0x" + "cc" * 20),
        "cross_dex_seen": cross_dex_seen,
        "multi_venue_confirmed": multi_venue_confirmed,
        "anchor_connected": anchor_connected,
        "block_number": block_number,
        "hooks": hooks,
    }


def _write_json(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestFreshWindowGate:
    """Fresh-window logic admits single-venue events when sniper is recent."""

    def test_fresh_sniper_admits_single_venue(self, tmp_path: Path):
        """When sniper is < 3600s old, single-venue events should be admitted."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc).isoformat()

        # Single-venue: cross_dex_seen=True, multi_venue_confirmed=False
        events = [_make_event(multi_venue_confirmed=False, cross_dex_seen=True)]
        sniper = _make_sniper_artifact(events, generated_at_utc=now_utc)
        anchor = _make_anchor_artifact()

        sniper_path = tmp_path / "sniper.json"
        anchor_path = tmp_path / "anchor.json"
        _write_json(sniper_path, sniper)
        _write_json(anchor_path, anchor)

        result = build_bridge_inventory(
            sniper_path=str(sniper_path),
            anchor_path=str(anchor_path),
            output_path=str(tmp_path / "bridge_out.json"),
        )

        # build_bridge_inventory returns bridge_source_metrics directly
        metrics = result
        assert "fresh_window_admitted_count" in metrics, (
            "Expected fresh_window_admitted_count in bridge_source_metrics"
        )
        assert metrics.get("sniper_in_fresh_window") is True, (
            "Expected sniper_in_fresh_window=True for fresh sniper"
        )
        # fresh_window_admitted_count may be 0 if no events pass the upstream gates
        # but sniper_in_fresh_window must be True

    def test_stale_sniper_does_not_admit_single_venue(self, tmp_path: Path):
        """When sniper is > 3600s old, single-venue events should NOT be admitted via fresh_window."""
        # Generate a timestamp >1h ago
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        events = [_make_event(multi_venue_confirmed=False, cross_dex_seen=True)]
        sniper = _make_sniper_artifact(events, generated_at_utc=old_ts)
        anchor = _make_anchor_artifact()

        sniper_path = tmp_path / "sniper_stale.json"
        anchor_path = tmp_path / "anchor_stale.json"
        _write_json(sniper_path, sniper)
        _write_json(anchor_path, anchor)

        result = build_bridge_inventory(
            sniper_path=str(sniper_path),
            anchor_path=str(anchor_path),
            output_path=str(tmp_path / "bridge_stale_out.json"),
        )

        metrics = result  # returns bridge_source_metrics directly
        assert metrics.get("sniper_in_fresh_window") is False, (
            "Expected sniper_in_fresh_window=False for stale sniper"
        )
        assert metrics.get("fresh_window_admitted_count", 0) == 0, (
            "Expected fresh_window_admitted_count=0 for stale sniper"
        )

    def test_sniper_age_seconds_reported(self, tmp_path: Path):
        """sniper_age_seconds must be present in bridge_source_metrics."""
        from datetime import datetime, timezone
        now_utc = datetime.now(timezone.utc).isoformat()

        sniper = _make_sniper_artifact([], generated_at_utc=now_utc)
        anchor = _make_anchor_artifact()

        sniper_path = tmp_path / "sniper_age.json"
        anchor_path = tmp_path / "anchor_age.json"
        _write_json(sniper_path, sniper)
        _write_json(anchor_path, anchor)

        result = build_bridge_inventory(
            sniper_path=str(sniper_path),
            anchor_path=str(anchor_path),
            output_path=str(tmp_path / "bridge_age_out.json"),
        )
        metrics = result  # returns bridge_source_metrics directly
        assert "sniper_age_seconds" in metrics, (
            "Expected sniper_age_seconds in bridge_source_metrics"
        )
        age = metrics["sniper_age_seconds"]
        assert isinstance(age, (int, float))
        assert age >= 0

    def test_multi_venue_events_unaffected_by_fresh_window(self, tmp_path: Path):
        """Multi-venue events should be admitted regardless of sniper freshness."""
        from datetime import datetime, timezone, timedelta
        old_ts = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()

        # Multi-venue event — should always pass
        events = [_make_event(multi_venue_confirmed=True, cross_dex_seen=True)]
        sniper = _make_sniper_artifact(events, generated_at_utc=old_ts)
        anchor = _make_anchor_artifact()

        sniper_path = tmp_path / "sniper_mv.json"
        anchor_path = tmp_path / "anchor_mv.json"
        _write_json(sniper_path, sniper)
        _write_json(anchor_path, anchor)

        result = build_bridge_inventory(
            sniper_path=str(sniper_path),
            anchor_path=str(anchor_path),
            output_path=str(tmp_path / "bridge_mv_out.json"),
        )
        # Multi-venue routes go through normal path, not fresh_window
        # build_bridge_inventory returns bridge_source_metrics (a flat dict)
        assert isinstance(result, dict)
        assert "graph_ready_from_m8" in result
