from core.auto_size import clamp_size, autosize_step


def test_clamp_size():
    assert clamp_size(5, 1, 10) == 5
    assert clamp_size(0.1, 1, 10) == 1
    assert clamp_size(20, 1, 10) == 10


def test_autosize_reduce_on_slippage():
    """Reduce size when slippage exceeds threshold."""
    size = 10
    state = None
    new, state, reason = autosize_step(size, last_slippage_bps=100, last_ticks_crossed=0, min_size=1, max_size=20)
    assert new == 5
    assert reason == "reduced_on_slippage_or_ticks"
    # cooldown prevents immediate restore
    new2, state, reason2 = autosize_step(new, last_slippage_bps=0, last_ticks_crossed=0, min_size=1, max_size=20, state=state)
    assert reason2 == "cooldown"


def test_autosize_reduce_on_ticks_crossed():
    """Reduce size when ticks_crossed exceeds threshold (t1=2).
    
    This is the M5 DoD requirement: at least one proven scenario 
    where ticks_crossed > threshold triggers size reduction.
    """
    size = 1000  # base_size_usd
    state = None
    
    # ticks_crossed=3 > t1=2 (default threshold)
    new, state, reason = autosize_step(
        size, 
        last_slippage_bps=0,  # no slippage
        last_ticks_crossed=3,  # exceeds threshold
        min_size=100, 
        max_size=5000
    )
    
    # Expect 50% reduction
    assert new == 500, f"Expected 500, got {new}"
    assert reason == "reduced_on_slippage_or_ticks"
    
    # Verify cooldown is active
    assert state.get("cooldown", 0) == 2
    assert state.get("consecutive_good", 0) == 0


def test_autosize_reduce_on_high_impact():
    """Reduce size when impact (slippage) is high.
    
    M5 DoD: high_impact scenario with reduction.
    """
    size = 1000
    state = None
    
    # impact_bps=60 > s1=50 (default threshold)
    new, state, reason = autosize_step(
        size,
        last_slippage_bps=60,  # exceeds threshold
        last_ticks_crossed=0,
        min_size=100,
        max_size=5000
    )
    
    assert new == 500
    assert reason == "reduced_on_slippage_or_ticks"


def test_autosize_restore_after_good_cycles():
    size = 5
    state = {"cooldown": 0, "consecutive_good": 0}
    for i in range(3):
        size, state, reason = autosize_step(size, last_slippage_bps=0, last_ticks_crossed=0, min_size=1, max_size=10, state=state)
    assert reason == "restored_after_good_cycles"


def test_autosize_no_change_when_below_threshold():
    """No change when both slippage and ticks are below thresholds."""
    size = 1000
    state = {"cooldown": 0, "consecutive_good": 0}
    
    new, state, reason = autosize_step(
        size,
        last_slippage_bps=30,  # below s1=50
        last_ticks_crossed=1,  # below t1=2
        min_size=100,
        max_size=5000,
        state=state
    )
    
    # Should not reduce, just increment consecutive_good
    assert new == 1000
    assert state["consecutive_good"] == 1
