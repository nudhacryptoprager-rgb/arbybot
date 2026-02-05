from core.auto_size import clamp_size, autosize_step


def test_clamp_size():
    assert clamp_size(5, 1, 10) == 5
    assert clamp_size(0.1, 1, 10) == 1
    assert clamp_size(20, 1, 10) == 10


def test_autosize_reduce_and_cooldown():
    size = 10
    state = None
    new, state, reason = autosize_step(size, last_slippage_bps=100, last_ticks_crossed=0, min_size=1, max_size=20)
    assert new == 5
    assert reason == "reduced_on_slippage_or_ticks"
    # cooldown prevents immediate restore
    new2, state, reason2 = autosize_step(new, last_slippage_bps=0, last_ticks_crossed=0, min_size=1, max_size=20, state=state)
    assert reason2 == "cooldown"


def test_autosize_restore_after_good_cycles():
    size = 5
    state = {"cooldown": 0, "consecutive_good": 0}
    for i in range(3):
        size, state, reason = autosize_step(size, last_slippage_bps=0, last_ticks_crossed=0, min_size=1, max_size=10, state=state)
    assert reason == "restored_after_good_cycles"
