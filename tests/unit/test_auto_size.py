from core.auto_size import clamp_size, reduce_on_slippage, restore_size


def test_clamp_size():
    assert clamp_size(5, 1, 10) == 5
    assert clamp_size(0.1, 1, 10) == 1
    assert clamp_size(20, 1, 10) == 10


def test_reduce_on_slippage():
    size = 10
    new = reduce_on_slippage(size, slippage_bps=100, ticks_crossed=0, s1=50, t1=2, min_size=1)
    assert new == 5
    new2 = reduce_on_slippage(size, slippage_bps=10, ticks_crossed=0, s1=50, t1=2, min_size=1)
    assert new2 == 10


def test_restore_size():
    size = 5
    r = restore_size(size, consecutive_good=3, required=3, factor=1.2, max_size=10)
    assert abs(r - 6.0) < 1e-6
    r2 = restore_size(size, consecutive_good=1, required=3, factor=1.2, max_size=10)
    assert r2 == size
