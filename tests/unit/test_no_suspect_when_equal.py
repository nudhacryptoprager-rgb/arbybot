import os
import tempfile
from pathlib import Path
from strategy.jobs.run_scan_real import run_scan


def test_no_suspect_when_implied_equals_expected(monkeypatch):
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
    tmp = Path(tempfile.mkdtemp())
    # Set tokens_anchor_price equal to the implied calculation so implied == expected
    cfg = {
        "chain_id": 42161,
        "dexes": ["uniswap_v3"],
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 2600},
    }
    stats = run_scan(cfg, tmp, cycles=1)
    # suspect_quotes should be zero when implied == expected
    assert stats.get("suspect_quotes", 0) == 0
    # reject_histogram should only contain sanity rejects (none expected here)
    reports = tmp / "reports"
    files = list(reports.glob("reject_histogram_*.json"))
    assert files
    import json
    with open(files[0]) as f:
        rej = json.load(f)
    assert rej.get("total_rejects", 0) == 0
 