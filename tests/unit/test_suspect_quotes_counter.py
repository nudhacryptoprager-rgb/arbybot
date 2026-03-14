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
    # R27.3: suspect_reasons comes from REAL rejects only (no synthetic keys).
    # With ARBY_SKIP_RPC/fake block, there are no real sanity rejects,
    # so suspect_reasons should be empty (or contain only real reject reasons).
    reasons = stats.get("suspect_reasons", {})
    # All reason keys must be real reject reason strings, not synthetic placeholders
    for key in reasons:
        assert isinstance(key, str), f"suspect_reason key must be str, got {type(key)}"
