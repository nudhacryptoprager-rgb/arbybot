import os
import tempfile
from pathlib import Path
from strategy.jobs.run_scan_real import run_scan


def test_reject_includes_expected_price(monkeypatch):
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
    tmp = Path(tempfile.mkdtemp())
    cfg = {"chain_id": 42161, "dexes": ["sushiswap_v3"], "quote_decimals": {"WETH": 18, "USDC": 6}, "tokens_anchor_price": {"WETH_USDC": 2600}}
    stats = run_scan(cfg, tmp, cycles=1)
    reports = tmp / "reports"
    files = list(reports.glob("reject_histogram_*.json"))
    assert files
    import json
    with open(files[0]) as f:
        rej = json.load(f)
    first = rej.get("rejects", [])[0]
    assert first.get("suspect_reason") == "way_below_expected"
    assert first.get("expected_price") is not None
    assert first.get("anchor_source") == "config"
