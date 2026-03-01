import os
import tempfile
from pathlib import Path
from strategy.jobs.run_scan_real import run_scan


def test_no_suspect_when_implied_equals_expected(monkeypatch):
    monkeypatch.setenv("ARBY_SKIP_RPC", "1")
    monkeypatch.setenv("ARBY_FAKE_BLOCK", "123")
    tmp = Path(tempfile.mkdtemp())
    # Set tokens_anchor_price equal to the implied calculation so implied == expected
    # Must include pool addresses to avoid POOL_MISSING rejects
    cfg = {
        "chain_id": 42161,
        "chain": "arbitrum_one",
        "dexes": ["uniswap_v3"],
        "pairs": [{"token_in": "WETH", "token_out": "USDC", "fee_tiers": [3000]}],
        "pools": {
            "uniswap_v3_WETH_USDC_3000": "0xC31E54c7a869B9FcBEcc14363CF510d1c41fa443",
        },
        "quote_decimals": {"WETH": 18, "USDC": 6},
        "tokens_anchor_price": {"WETH_USDC": 2600},
        # v3.2.2: Set higher drift threshold to avoid NOTIONAL_DRIFT rejects in this test
        # The test focuses on price sanity, not notional drift
        "drift_warning_pct": 50.0,
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
 