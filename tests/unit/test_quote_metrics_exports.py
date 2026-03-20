# PATH: tests/unit/test_quote_metrics_exports.py
"""Tests for strategy.quote_metrics module exports and contracts."""


def test_init_quote_counts_has_all_keys():
    from strategy.quote_metrics import init_quote_counts
    counts = init_quote_counts()
    required = {
        "quotes_fetched", "pool_missing", "pool_disabled",
        "runtime_disabled", "liquidity_zero", "quarantined",
        "v3_slot0_failed", "ve33_quote_failed", "price_calc_failed",
        "no_onchain_price", "no_usd_price", "algebra_needs_quoter",
        "quoter_v2_failed",
    }
    assert required.issubset(counts.keys())
    assert all(v == 0 for v in counts.values())


def test_init_quoter_matrix_empty():
    from strategy.quote_metrics import init_quoter_matrix
    mx = init_quoter_matrix()
    assert isinstance(mx, dict)
    assert len(mx) == 0


def test_finalize_quote_counts_attaches():
    from strategy.quote_metrics import init_quote_counts, finalize_quote_counts
    counts = init_quote_counts()
    failed = [{"pool_address": "0x1", "reason": "test"}]
    missing = ["key_1", "key_2"]
    matrix = {"uni_500": {"dex": "uniswap_v3", "fee": 500, "attempted": 1, "quoter_success": 1}}
    finalize_quote_counts(counts, failed, missing, matrix)
    assert counts["failed_pool_addresses"] == failed
    assert counts["pool_missing_keys"] == missing
    assert counts["pool_missing_keys_total"] == 2
    assert counts["quoter_matrix"] == matrix


def test_finalize_truncates_pool_missing_keys():
    from strategy.quote_metrics import init_quote_counts, finalize_quote_counts
    counts = init_quote_counts()
    big_list = [f"key_{i}" for i in range(50)]
    finalize_quote_counts(counts, [], big_list, {})
    assert len(counts["pool_missing_keys"]) == 20
    assert counts["pool_missing_keys_total"] == 50
