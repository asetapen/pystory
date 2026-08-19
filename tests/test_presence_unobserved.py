"""A lock decision needs an observation behind it (issue st-f456h5).

`should_be_locked` compared both streaks against `confirm_ticks` with no
requirement that anything had been observed. Both streaks start at 0, so any
`confirm_ticks <= 0` satisfied `_miss_streak >= confirm_ticks` unconditionally
and the property answered True forever:

    confirm_ticks=0, zero observations        -> True   (locks before any frame)
    confirm_ticks=0, observe(True) x4         -> True   (locks with your face in frame)
    confirm_ticks=2, zero observations        -> None   (control, shipped default)

The second line is the expensive one and is why this is not merely a bad-input
bug. `observe(True)` resets `_miss_streak` to 0, and `0 >= 0` still holds, so a
recognised face never produced an unlock: the miss branch is evaluated first and
answered True on every tick. `--presence-confirm-ticks 0` therefore locked the
desk repeatedly while the user sat at it.

Two layers are bound here because they fail independently:

  * the CLI refuses anything below 1, so `0` cannot reach the field. `1` is the
    floor the README already documented ("lower it (to `1`) for instant
    response"); `0` was never a documented request.
  * `PresenceTracker` itself no longer decides on an empty streak, which covers
    every caller that is not argparse. `AppState` assigns the field directly
    (`main.py:265`), so the CLI bound alone would leave the class wrong for a
    config-file or default change.

The class tests do NOT go through the CLI on purpose: with the bound in place
`confirm_ticks=0` is unreachable from argv, so a CLI-only test of the predicate
fix would be vacuous.
"""

import pytest

import pystory.main as main
from pystory.presence import PresenceTracker


def parse(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pystory", *argv])
    return main.parse_args()


# --------------------------------------------------------------------------
# Layer 1: the predicate. No decision without an observation.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("confirm_ticks", [-1, 0, 1, 2, 3])
def test_no_decision_before_anything_is_observed(confirm_ticks):
    """THE DEFECT, and it is parametrized over the whole range rather than over
    the two broken values: "None until observed" must hold for EVERY
    confirm_ticks, so a fix that special-cases 0 does not pass. The <= 0 cases
    are the ones that were True."""
    t = PresenceTracker(confirm_ticks=confirm_ticks)

    assert t.should_be_locked is None


@pytest.mark.parametrize("confirm_ticks", [-1, 0])
def test_recognised_face_is_never_reported_as_locked(confirm_ticks):
    """THE EXPENSIVE HALF. Locking before the first frame is recoverable; the
    shipped behaviour also answered True on every tick WITH a recognised face,
    so the desk locked while in use and no amount of presence fixed it."""
    t = PresenceTracker(confirm_ticks=confirm_ticks)

    for tick in range(4):
        t.observe(True)
        assert t.should_be_locked is not True, (
            f"tick {tick + 1}: recognised face reported as lock-worthy at "
            f"confirm_ticks={confirm_ticks}"
        )


@pytest.mark.parametrize("confirm_ticks", [-1, 0])
def test_a_real_miss_still_locks_with_no_debouncing(confirm_ticks):
    """DIRECTIONAL CONTROL, and the one that stops this fix from becoming a
    lock-path regression. Requiring an observation must not turn the tracker
    into one that never locks: one genuine miss at confirm_ticks <= 0 still
    locks, because zero debouncing is what such a value asks for. Without this
    arm, `should_be_locked -> None` always would pass every other test here
    while silently disabling the lock."""
    t = PresenceTracker(confirm_ticks=confirm_ticks)

    t.observe(False)

    assert t.should_be_locked is True


@pytest.mark.parametrize("confirm_ticks", [-1, 0])
def test_a_real_hit_unlocks_with_no_debouncing(confirm_ticks):
    """The unlock direction of the same control. Both directions are required by
    the repo's lock-path rule, and one alone passes for a tracker stuck on a
    single answer."""
    t = PresenceTracker(confirm_ticks=confirm_ticks)

    t.observe(True)

    assert t.should_be_locked is False


def test_default_debouncing_is_unchanged():
    """CONTROL on the shipped default, asserted rather than assumed. The guard
    is `streak > 0 AND streak >= confirm_ticks`, and for any confirm_ticks >= 1
    the first conjunct is implied by the second, so nothing about the default
    path may move. A fix that changed it would still pass every arm above."""
    t = PresenceTracker()
    assert t.confirm_ticks == 2, "the default must be 2 or the arms below prove nothing"

    assert t.should_be_locked is None
    t.observe(False)
    assert t.should_be_locked is None, "one miss must not lock at the default"
    t.observe(False)
    assert t.should_be_locked is True

    t2 = PresenceTracker()
    t2.observe(True)
    assert t2.should_be_locked is None, "one hit must not unlock at the default"
    t2.observe(True)
    assert t2.should_be_locked is False


# --------------------------------------------------------------------------
# Layer 2: the CLI bound. 0 and negatives cannot reach the field.
# --------------------------------------------------------------------------

@pytest.mark.parametrize("value", ["0", "-1"])
def test_below_the_floor_is_refused_by_name(monkeypatch, capsys, value):
    """Refused at exit 2 naming the flag AND the value, matching what landed for
    the four numeric flags in st-dqfz5j. Naming both is load-bearing: a bare
    "invalid value" refusal is indistinguishable from an unrecognised flag."""
    with pytest.raises(SystemExit) as exit_info:
        parse(monkeypatch, ["--presence-confirm-ticks", value])

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--presence-confirm-ticks" in stderr, f"must name the flag; got: {stderr!r}"
    assert value in stderr, f"must name the value; got: {stderr!r}"


def test_the_floor_itself_is_accepted(monkeypatch):
    """CONTROL on the bound. Refusing 0 and -1 is equally satisfied by a bound
    of 2 or 3, which would reject the value the README tells you to use for
    instant response, and the refusal arms cannot see that."""
    config = parse(monkeypatch, ["--presence-confirm-ticks", "1"])

    assert config.presence_confirm_ticks == 1


def test_a_workable_value_still_reaches_the_field(monkeypatch):
    """POSITIVE CONTROL. Without it, "0 is refused" is equally satisfied by a
    flag that refuses everything, which is a different defect."""
    default = main.Config().presence_confirm_ticks
    assert default != 7, "7 must differ from the default or this cannot discriminate"

    config = parse(monkeypatch, ["--presence-confirm-ticks", "7"])

    assert config.presence_confirm_ticks == 7


def test_absent_flag_keeps_the_default(monkeypatch):
    """DIRECTIONAL CONTROL. A bound implemented by rewriting the value would
    satisfy the arms above and break the default, and that breakage looks
    exactly like the fix working."""
    config = parse(monkeypatch, [])

    assert config.presence_confirm_ticks == 2
