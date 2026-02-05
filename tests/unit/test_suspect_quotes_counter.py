import os
import tempfile
from pathlib import Path
from strategy.jobs.run_scan_real import run_scan


def test_suspect_quotes_counter_and_reasons(monkeypatch):
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
    tmp = Path(tempfile.mkdtemp())
    cfg = {"chain_id": 42161, "dexes": ["uniswap_v2"], "quote_decimals": {"WETH": 18, "USDC": 6}}
    stats = run_scan(cfg, tmp, cycles=1)
    assert "suspect_quotes" in stats
    assert stats.get("suspect_quotes") >= 0
    assert isinstance(stats.get("suspect_reasons"), dict)
    # Expect our sample reject to include 'way_below_expected'
    reasons = stats.get("suspect_reasons", {})
    assert "way_below_expected" in reasons
