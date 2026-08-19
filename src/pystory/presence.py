from dataclasses import dataclass, field


@dataclass
class PresenceTracker:
    """Debounces face-recognition results across ticks.

    A single bad frame (glare, brief look-away, misfire) shouldn't flip the
    lock state. Require `confirm_ticks` consecutive same-direction results
    before reporting a decision.
    """

    confirm_ticks: int = 2
    _hit_streak: int = field(default=0, init=False, repr=False)
    _miss_streak: int = field(default=0, init=False, repr=False)

    def observe(self, recognized: bool | None) -> None:
        """recognized: True = your face seen, False/None = not seen or not you."""
        if recognized:
            self._hit_streak += 1
            self._miss_streak = 0
        else:
            self._miss_streak += 1
            self._hit_streak = 0

    @property
    def should_be_locked(self) -> bool | None:
        """True: lock now. False: unlock now. None: not enough signal yet.

        A decision needs at least one OBSERVATION behind it, not just a streak
        that clears `confirm_ticks`. Both streaks start at 0, so with
        `confirm_ticks <= 0` the miss comparison is satisfied unconditionally:
        the tracker reported True before `observe` had ever been called, and
        kept reporting True while a recognised face was in frame, because
        `observe(True)` resets `_miss_streak` to 0 and `0 >= 0` still holds.
        That locks the desk on no evidence, which is the one direction this
        class exists to prevent.
        """
        if self._miss_streak > 0 and self._miss_streak >= self.confirm_ticks:
            return True
        if self._hit_streak > 0 and self._hit_streak >= self.confirm_ticks:
            return False
        return None
