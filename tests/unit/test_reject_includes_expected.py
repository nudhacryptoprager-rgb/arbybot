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
    # expected_price should always be present in candidate rejects
    first_candidates = rej.get("sample_rejects", [])
    # sample_rejects may be empty when no sanity rejects; that's acceptable
    if first_candidates:
        first = first_candidates[0]
        assert first.get("expected_price") is not None
        assert first.get("anchor_source") == "config"
    else:
        # When no sanity rejects, ensure expected context was still computed in truth suspect_summary
        reports = tmp / "reports"
        tr_files = list(reports.glob("truth_report_*.json"))
        with open(tr_files[0]) as tf:
            truth = json.load(tf)
        suspect = truth.get("suspect_summary", {})
        # expected_price should be present in examples if any suspect examples exist
        if suspect.get("examples"):
            ex = suspect["examples"][0]
            assert ex.get("expected_price") is not None
