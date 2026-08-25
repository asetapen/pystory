"""`--output` must not be silently dropped on the default `--type both` (issue
st-8gpxr8, D2), and `--fps` must not reach 0 (D1's other trigger).

`main.py` line 73 read `if args.output and args.type != "both"`, and `--type`
defaults to `"both"`, so `pystory-timelapse --output x.mp4` -- the plainest
possible use of the flag, no other flag needed -- silently wrote
`timelapse_webcam.mp4` and `timelapse_screenshot.mp4` instead and left
`x.mp4` absent at exit 0. The fix refuses the combination by name at parse
time, the same shape `bounded_int`/`non_empty` already use elsewhere in this
repo for a value that cannot work, rather than letting it through to be
dropped later without a word.
"""

import pytest

import pystory.timelapse as timelapse


def parse(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pystory-timelapse", *argv])
    return timelapse.parse_args()


def test_output_with_default_type_both_is_refused(monkeypatch, capsys):
    """THE DEFECT. No --type at all: --output alone must not be swallowed."""
    with pytest.raises(SystemExit) as exit_info:
        parse(monkeypatch, ["--output", "x.mp4"])

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--output" in stderr
    assert "both" in stderr


def test_output_with_explicit_type_both_is_refused(monkeypatch, capsys):
    with pytest.raises(SystemExit):
        parse(monkeypatch, ["--output", "x.mp4", "--type", "both"])


@pytest.mark.parametrize("type_", ["webcam", "screenshot"])
def test_control_output_with_a_single_type_is_accepted(monkeypatch, type_):
    """CONTROL. The refusal must be scoped to --type both, not to --output
    itself -- the ordinary single-type use of the flag must keep working."""
    args = parse(monkeypatch, ["--output", "x.mp4", "--type", type_])

    assert str(args.output) == "x.mp4"
    assert args.type == type_


def test_control_type_both_without_output_is_accepted(monkeypatch):
    """CONTROL. Only the --output + both COMBINATION is refused."""
    args = parse(monkeypatch, [])

    assert args.output is None
    assert args.type == "both"


@pytest.mark.parametrize("value", ["0", "-1"])
def test_fps_unworkable_value_is_refused(monkeypatch, capsys, value):
    """D1's other trigger: --fps 0 (or negative) cannot open a VideoWriter."""
    with pytest.raises(SystemExit) as exit_info:
        parse(monkeypatch, ["--fps", value])

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert "--fps" in stderr
    assert value in stderr


def test_fps_default_is_unaffected(monkeypatch):
    args = parse(monkeypatch, [])

    assert args.fps == 30
