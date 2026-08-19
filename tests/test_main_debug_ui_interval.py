"""`--interval 0` must not park the debug UI forever (issue st-dqfz5j).

`cv2.waitKey`'s documented contract is that a delay <= 0 waits INFINITELY, so
`main()`'s debug-UI branch passing `interval_seconds * 1000` straight through
means `--interval 0` says "as fast as possible" on the `time.sleep` path and
"wait until a key is pressed" on the `--debug-ui` path. The is-not-None gate fix
is what makes 0 reachable at all, so the divergence is newly live rather than
pre-existing.

These bind the CALL SITE inside `main()`'s loop, not a clamp helper: a
direct-call test of a helper stays green while the real loop keeps passing the
raw interval. The contract is read from the documentation and asserted against
the recorded delay -- never by calling the real `waitKey(0)`, which hangs by
definition.
"""

import pytest

import pystory.main as main


class FakeCv2:
    """Records the delay every waitKey call is given, and drives the loop.

    Returned keys are consumed in order; the default tail is `q`, which is the
    loop's own quit path, so a test cannot hang even if the clamp is wrong.
    """

    def __init__(self, keys=()):
        self.delays = []
        self.destroy_calls = 0
        self._keys = list(keys)

    def waitKey(self, delay):
        self.delays.append(delay)
        return self._keys.pop(0) if self._keys else ord("q")

    def destroyAllWindows(self):
        self.destroy_calls += 1


def run_main(monkeypatch, tmp_path, argv, keys=()):
    """Drive the real main() loop with the capture work stubbed out.

    `ticks` is asserted by every test: "waitKey was never called" is also what
    an exception before the loop body prints, and that is the reassuring
    direction, so a delay list is only meaningful alongside evidence the loop
    body ran.
    """
    fake = FakeCv2(keys)
    ticks = []
    monkeypatch.setattr(main, "cv2", fake)
    monkeypatch.setattr(main, "tick", lambda config, state: ticks.append(1))
    monkeypatch.setattr("sys.argv", ["pystory", "--storage-dir", str(tmp_path), *argv])

    main.main()

    return fake, ticks


def test_interval_zero_waits_a_positive_delay(monkeypatch, tmp_path):
    """THE DEFECT. 0 * 1000 == 0, and waitKey(0) waits forever."""
    fake, ticks = run_main(monkeypatch, tmp_path, ["--debug-ui", "--interval", "0"])

    assert ticks == [1]
    assert fake.delays == [1]
    assert all(d > 0 for d in fake.delays), "a delay <= 0 waits forever by contract"


def test_every_wait_stays_positive_across_ticks(monkeypatch, tmp_path):
    """The clamp is on the call site, so it must hold on every iteration and not
    only on the first. 0 from waitKey means "no key was pressed"."""
    fake, ticks = run_main(
        monkeypatch, tmp_path, ["--debug-ui", "--interval", "0"], keys=[0, 0, ord("q")]
    )

    assert ticks == [1, 1, 1]
    assert fake.delays == [1, 1, 1]


def test_control_nonzero_interval_is_passed_through_unchanged(monkeypatch, tmp_path):
    """CONTROL. Without it the clamp is satisfied by a constant 1, which would
    turn every debug-UI run into a busy loop."""
    fake, ticks = run_main(monkeypatch, tmp_path, ["--debug-ui", "--interval", "5"])

    assert ticks == [1]
    assert fake.delays == [5000]


def test_control_default_interval_is_passed_through_unchanged(monkeypatch, tmp_path):
    fake, ticks = run_main(monkeypatch, tmp_path, ["--debug-ui"])

    assert ticks == [1]
    assert fake.delays == [5000]
    assert fake.destroy_calls == 1


def test_control_the_sleep_path_gets_zero_unclamped(monkeypatch, tmp_path):
    """DIRECTIONAL CONTROL. The clamp belongs to the waitKey call site only.
    `time.sleep(0)` returns immediately, which is what `--interval 0` asks for,
    so clamping there would slow down the path that was already correct."""
    sleeps = []

    def fake_sleep(seconds):
        sleeps.append(seconds)
        if len(sleeps) == 2:
            raise KeyboardInterrupt

    fake = FakeCv2()
    monkeypatch.setattr(main, "cv2", fake)
    monkeypatch.setattr(main.time, "sleep", fake_sleep)
    monkeypatch.setattr(main, "tick", lambda config, state: None)
    monkeypatch.setattr("sys.argv", ["pystory", "--storage-dir", str(tmp_path), "--interval", "0"])

    with pytest.raises(KeyboardInterrupt):
        main.main()

    assert sleeps == [0, 0]
    assert fake.delays == [], "waitKey has no business on the non-debug-ui path"
