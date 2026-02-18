# PATH: tests/unit/test_provenance_unification.py
"""Unit tests for v2.3.0 provenance unification contract.

Validates that:
1. All artifact builders accept run_timestamp parameter
2. run_context.run_timestamp is emitted in scan, truth_report, reject_histogram
3. When same run_timestamp passed, all artifacts have identical provenance
"""

import pytest
from datetime import datetime, timezone

from strategy.artifacts import build_scan_data, build_truth_data, build_reject_data


class TestProvenanceUnification:
    """Test v2.3.0 provenance unification across artifacts."""
    
    def test_build_scan_data_accepts_run_timestamp(self):
        """build_scan_data should accept run_timestamp parameter."""
        ts = "2026-02-18T12:00:00Z"
        data = build_scan_data(
            config={"chain_id": 42161},
            current_block=123456,
            stats={"quotes_total": 10, "quotes_fetched": 5, "dexes_active": 2,
                   "price_sanity_passed": 4, "price_sanity_failed": 1},
            quotes_sample=[],
            infra_payload={},
            run_timestamp=ts,
        )
        assert data.get("run_context", {}).get("run_timestamp") == ts
    
    def test_build_truth_data_accepts_run_timestamp(self):
        """build_truth_data should accept run_timestamp parameter."""
        ts = "2026-02-18T12:00:00Z"
        data = build_truth_data(
            config={"chain_id": 42161},
            stats={"quotes_total": 10, "quotes_fetched": 5, "dexes_active": 2,
                   "price_sanity_passed": 4, "price_sanity_failed": 1,
                   "execution_ready_count": 0, "would_execute_count": 0},
            current_block=123456,
            spread_signals=[],
            suspect_examples=[],
            infra_payload={},
            raw_bps=100,
            spread_threshold_bps=50,
            run_timestamp=ts,
        )
        assert data.get("run_context", {}).get("run_timestamp") == ts
    
    def test_build_reject_data_accepts_run_timestamp(self):
        """build_reject_data should accept run_timestamp parameter."""
        ts = "2026-02-18T12:00:00Z"
        data = build_reject_data(
            config={"chain_id": 42161},
            current_block=123456,
            sanity_rejects=[],
            rejected_quotes=[],
            stats={},
            infra_payload={},
            run_timestamp=ts,
        )
        assert data.get("run_context", {}).get("run_timestamp") == ts
    
    def test_unified_timestamp_matches_across_all_artifacts(self):
        """When same run_timestamp passed, all artifacts have identical provenance."""
        ts = datetime.now(timezone.utc).isoformat()
        
        config = {"chain_id": 42161}
        stats = {"quotes_total": 10, "quotes_fetched": 5, "dexes_active": 2,
                 "price_sanity_passed": 4, "price_sanity_failed": 1,
                 "execution_ready_count": 0, "would_execute_count": 0}
        
        scan = build_scan_data(config, 123456, stats, [], {}, run_timestamp=ts)
        truth = build_truth_data(config, stats, 123456, [], [], {}, 100, 50, run_timestamp=ts)
        reject = build_reject_data(config, 123456, [], [], {}, {}, run_timestamp=ts)
        
        scan_ts = scan.get("run_context", {}).get("run_timestamp")
        truth_ts = truth.get("run_context", {}).get("run_timestamp")
        reject_ts = reject.get("run_context", {}).get("run_timestamp")
        
        assert scan_ts == ts, f"scan run_timestamp mismatch: {scan_ts} != {ts}"
        assert truth_ts == ts, f"truth run_timestamp mismatch: {truth_ts} != {ts}"
        assert reject_ts == ts, f"reject run_timestamp mismatch: {reject_ts} != {ts}"
        
        # All must match each other
        assert scan_ts == truth_ts == reject_ts, "Provenance not unified across artifacts"
    
    def test_run_context_present_in_all_artifacts(self):
        """run_context dict required in all artifact types (v2.3.0)."""
        ts = "2026-02-18T12:00:00Z"
        config = {"chain_id": 42161}
        stats = {"quotes_total": 10, "quotes_fetched": 5, "dexes_active": 2,
                 "price_sanity_passed": 4, "price_sanity_failed": 1,
                 "execution_ready_count": 0, "would_execute_count": 0}
        
        scan = build_scan_data(config, 123456, stats, [], {}, run_timestamp=ts)
        truth = build_truth_data(config, stats, 123456, [], [], {}, 100, 50, run_timestamp=ts)
        reject = build_reject_data(config, 123456, [], [], {}, {}, run_timestamp=ts)
        
        assert "run_context" in scan, "scan missing run_context"
        assert "run_context" in truth, "truth missing run_context"
        assert "run_context" in reject, "reject missing run_context"
        
        assert "run_timestamp" in scan["run_context"], "scan.run_context missing run_timestamp"
        assert "run_timestamp" in truth["run_context"], "truth.run_context missing run_timestamp"
        assert "run_timestamp" in reject["run_context"], "reject.run_context missing run_timestamp"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
