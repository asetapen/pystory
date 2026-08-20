"""String CLI flags must not silently swallow an empty value (issue st-gbjpsc).

`tests/test_main_args_zero.py` fixed this class for the four NUMERIC flags
(st-dqfz5j): they were gated with `if args.x:`, a TRUTHINESS test, so the one
falsy value took the same branch as omitting the flag. The string flags were left
on the same gate, and one of them has a falsy value that WORKS:

    --no-face-hook ""     ->  config.no_face_hook = "loginctl lock-session"
    --no-face-hook "true" ->  config.no_face_hook = "true"        (a value lands)
    (no flag)             ->  config.no_face_hook = "loginctl lock-session"

So asking for NO hook was indistinguishable from not asking, and the direction is
the dangerous one: the default hook is a REAL session lock. An empty command is a
working no-op hook once it reaches the field -- `subprocess.run("", shell=True,
check=True)` exits 0 -- so this was a legitimate value being dropped, not an
invalid one being rejected.

The property bound here is the same one that file states: NO value is silently
ignored. A value that can work reaches the field, and a value that cannot work is
refused BY NAME with exit 2. Which flags fall on which side is a per-flag
judgement, recorded in the tables below rather than left implicit:

  * `--no-face-hook ""` WORKS (a no-op hook), so it must land.
  * `--lock-panic-hotkey ""` cannot work: Tk raises on an empty keysym, so the
    overlay's panic escape would be dead. Refused.
  * `--obsbot-cli-path ""` cannot work: an empty command name cannot exec.
    Refused.
  * `--lock-passphrase ""` is coherent (it is the shipped default: no passphrase,
    panic hotkey only) and is deliberately NOT bound below -- see the comment on
    NOT_DISCRIMINATING.
  * `--camera-failure-grace-ticks` is numeric and was the ONE numeric flag left
    on plain `type=int` after st-dqfz5j, so a negative reached the field. Bound
    here rather than in the zero file because it is the same omission.

The last section drives the real `main.tick` end to end, because a parse-level
test cannot show that the empty hook is what actually gets EXECUTED, and that is
the half a user is exposed to.
"""

import pytest

import pystory.main as main
from pystory.config import Config


def parse(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pystory", *argv])
    return main.parse_args()


# ---------------------------------------------------------------------------
# Parse level
# ---------------------------------------------------------------------------

# (flag, Config field, shipped default). The default is asserted rather than
# assumed, for the reason the zero file gives: a case comparing a field against
# "" cannot discriminate if the default is already "".
STRING_FLAGS = [
    ("--no-face-hook", "no_face_hook", "loginctl lock-session"),
    ("--lock-panic-hotkey", "lock_panic_hotkey", "<Control-Alt-Escape>"),
    ("--obsbot-cli-path", "obsbot_cli_path", "obsbot-cli"),
]

# Flags whose empty value is coherent and must LAND.
EMPTY_IS_COHERENT = [
    ("--no-face-hook", "no_face_hook"),
]

# (flag, value) that cannot work and must be refused by name.
UNWORKABLE = [
    ("--lock-panic-hotkey", ""),
    ("--obsbot-cli-path", ""),
    ("--camera-failure-grace-ticks", "-1"),
]

# NOT BOUND, ON PURPOSE. `--lock-passphrase ""` is a coherent request, but the
# shipped default is ALREADY "", so no assertion over the field can tell a fix
# from the bug: both leave "" there. Binding it would add a green arm with no
# discriminating power, which is the thing this repo's other test files keep
# warning about. Its gate is changed with the rest; what is untested is that the
# change had any effect, and there is nothing to observe.
NOT_DISCRIMINATING = ["--lock-passphrase"]


@pytest.mark.parametrize("flag,attr,default", STRING_FLAGS)
def test_absent_flag_keeps_the_default(monkeypatch, flag, attr, default):
    """DIRECTIONAL CONTROL. A fix that applies "" whenever the flag is ABSENT
    satisfies the empty case below while breaking every default, and that
    breakage looks exactly like the fix working."""
    config = parse(monkeypatch, [])

    assert getattr(config, attr) == default


@pytest.mark.parametrize("flag,attr,default", STRING_FLAGS)
def test_a_real_value_reaches_the_field(monkeypatch, flag, attr, default):
    """POSITIVE CONTROL. Without it, "the empty string was swallowed" is equally
    satisfied by a flag that is simply broken for every input -- a different
    defect with a different fix."""
    value = "<F12>" if flag == "--lock-panic-hotkey" else "/opt/probe-value"
    assert default != value, "the value must differ from the default to discriminate"

    config = parse(monkeypatch, [flag, value])

    assert getattr(config, attr) == value


@pytest.mark.parametrize("flag,attr", EMPTY_IS_COHERENT)
def test_empty_value_reaches_the_field(monkeypatch, flag, attr):
    """THE DEFECT. "" must land, not take the absent-flag branch."""
    default = getattr(Config(), attr)
    assert default != "", "the default must be non-empty or this cannot discriminate"

    config = parse(monkeypatch, [flag, ""])

    assert getattr(config, attr) == ""


@pytest.mark.parametrize("flag,value", UNWORKABLE)
def test_unworkable_value_is_refused(monkeypatch, capsys, flag, value):
    """A value that cannot work must be REFUSED by name, not dropped in silence
    and not passed through to fail obscurely later. The truthiness gate did
    neither: it swallowed the one coherent empty value while `type=int` passed a
    negative grace period straight to the field."""
    with pytest.raises(SystemExit) as exit_info:
        parse(monkeypatch, [flag, value])

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert flag in stderr, f"the refusal must name the flag; got: {stderr!r}"


@pytest.mark.parametrize("value", [0, 3, 10])
def test_grace_ticks_accepts_every_workable_value(monkeypatch, value):
    """CONTROL on the new bound. Refusing -1 is also satisfied by a bound that
    refuses 0, and 0 is a coherent request ("no tolerance at all") that
    tests/test_main_args.py already binds. Repeated here so this file's bound
    cannot tighten without a red."""
    config = parse(monkeypatch, ["--camera-failure-grace-ticks", str(value)])

    assert config.camera_failure_grace_ticks == value


# ---------------------------------------------------------------------------
# End to end: what the hook actually EXECUTES, both directions
# ---------------------------------------------------------------------------
#
# repo/pystory.md requires both directions of the lock path to be exercised and
# named: a face present that must NOT fire, and a face absent that MUST. These
# three arms do that through the real `main.tick` and the real `main.run_hook`,
# with the config built by `parse_args` from argv rather than hand-constructed,
# because the defect lived in argv -> field and a hand-built Config skips it.
# `subprocess.run` is the only thing stubbed, and it is what tells us WHICH
# command a user would have had run.


class HookRecorder:
    def __init__(self, face_in_frame):
        self._face_in_frame = face_in_frame
        self.commands = []
        self.prune_calls = 0

    def subprocess_run(self, command, **kwargs):
        self.commands.append(command)

        class Completed:
            returncode = 0

        return Completed()

    def take_webcam_picture(self, timestamp, config):
        return ("webcam.jpg", "face" if self._face_in_frame else "nobody")

    def is_recognized(self, frame, config):
        return frame == "face"

    def prune_old_files(self, config):
        self.prune_calls += 1
        return 0


def drive(monkeypatch, argv, *, face_in_frame, ticks=2):
    rec = HookRecorder(face_in_frame)
    config = parse(monkeypatch, argv)
    config.screenshot_enabled = False
    config.presence_confirm_ticks = 2
    monkeypatch.setattr(main.subprocess, "run", rec.subprocess_run)
    monkeypatch.setattr(main, "take_webcam_picture", rec.take_webcam_picture)
    monkeypatch.setattr(main, "is_recognized", rec.is_recognized)
    monkeypatch.setattr(main, "prune_old_files", rec.prune_old_files)

    state = main.AppState()
    state.presence.confirm_ticks = config.presence_confirm_ticks
    for _ in range(ticks):
        main.tick(config, state)
    return rec, state


def test_face_absent_with_the_default_hook_runs_loginctl(monkeypatch):
    """CONTROL, and the MUST-FIRE direction: the shipped default still locks."""
    rec, state = drive(monkeypatch, [], face_in_frame=False)

    assert rec.prune_calls == 2, "tick() did not run to completion"
    assert state.locked is True
    assert rec.commands == ["loginctl lock-session"]


def test_face_absent_with_an_empty_hook_runs_nothing_that_locks(monkeypatch):
    """THE DEFECT, end to end. --no-face-hook "" must reach the exec, so what
    runs is an empty command and NOT a session lock. Before the fix this arm
    executed "loginctl lock-session" -- the user asked for no hook and got a
    real lock."""
    rec, state = drive(monkeypatch, ["--no-face-hook", ""], face_in_frame=False)

    assert rec.prune_calls == 2
    assert state.locked is True, "the lock STATE still flips; only the command changes"
    assert rec.commands == [""]


def test_face_present_runs_no_hook_at_all(monkeypatch):
    """The MUST-NOT-FIRE direction. Without it, every arm above is satisfied by
    a build that runs its hook on every tick regardless of who is there."""
    rec, state = drive(monkeypatch, ["--no-face-hook", ""], face_in_frame=True)

    assert rec.prune_calls == 2
    assert state.locked is False
    assert rec.commands == []
