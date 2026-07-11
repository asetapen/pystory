from pystory.presence import PresenceTracker


def test_no_decision_until_confirm_ticks_reached():
    t = PresenceTracker(confirm_ticks=2)
    t.observe(False)
    assert t.should_be_locked is None


def test_locks_after_consecutive_misses():
    t = PresenceTracker(confirm_ticks=2)
    t.observe(False)
    t.observe(False)
    assert t.should_be_locked is True


def test_unlocks_after_consecutive_hits():
    t = PresenceTracker(confirm_ticks=2)
    t.observe(False)
    t.observe(False)
    assert t.should_be_locked is True
    t.observe(True)
    t.observe(True)
    assert t.should_be_locked is False


def test_single_bad_frame_does_not_flip_decision():
    t = PresenceTracker(confirm_ticks=2)
    t.observe(True)
    t.observe(True)
    assert t.should_be_locked is False
    t.observe(False)  # one bad frame
    assert t.should_be_locked is None  # not enough to flip yet
    t.observe(True)
    assert t.should_be_locked is None  # streak reset by the miss, needs 2 more hits


def test_none_result_counts_as_a_miss():
    t = PresenceTracker(confirm_ticks=1)
    t.observe(None)
    assert t.should_be_locked is True
