"""Contract tests for the staged strategy.quote_rpc extraction."""


def test_quotes_reexports_slot0_reader():
    import strategy.quote_rpc as qr
    import strategy.quotes as sq

    assert sq.read_slot0_v3 is qr.read_slot0_v3


def test_quotes_reexports_quoter_v2_reader():
    import strategy.quote_rpc as qr
    import strategy.quotes as sq

    assert sq.read_quoter_v2 is qr.read_quoter_v2


def test_quotes_reexports_multicall_helpers():
    import strategy.quote_rpc as qr
    import strategy.quotes as sq

    assert sq.prefetch_slot0_multicall is qr.prefetch_slot0_multicall
    assert sq.get_cached_liquidity is qr.get_cached_liquidity
    assert sq.get_cached_slot0 is qr.get_cached_slot0
    assert sq.clear_multicall_cache is qr.clear_multicall_cache
