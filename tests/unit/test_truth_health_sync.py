import os
import tempfile
from pathlib import Path
from strategy.jobs.run_scan_real import run_scan


def test_truth_health_is_derived_from_stats(monkeypatch):
    # Ensure no real RPC calls
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")

    tmp = Path(tempfile.mkdtemp())
    cfg = {
        "chain_id": 42161,
        "dexes": ["uniswap_v2", "sushiswap_v3"],
        "quote_decimals": {"WETH": 18, "USDC": 6},
    }
    stats = run_scan(cfg, tmp, cycles=1)
    # read truth_report
    reports = tmp / "reports"
    files = list(reports.glob("truth_report_*.json"))
    assert files, "truth_report not written"
    import json

    with open(files[0]) as f:
        truth = json.load(f)
    health = truth.get("health", {})
    stats_reported = truth.get("stats", {})
    assert health.get("price_sanity_failed") == stats_reported.get("price_sanity_failed")
    assert health.get("quotes_total") == stats_reported.get("quotes_total")
