"""The camera-failure flags must reach Config, not just parse.

`parse_args` builds a Config from argparse results by hand, one `if` per flag,
so a flag can be declared and documented while never touching the field it
names. That failure mode is invisible from the CLI: the flag is accepted, the
help text lists it, and nothing changes.
"""

import pytest

import pystory.main as main


def parse(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pystory", *argv])
    return main.parse_args()


def test_camera_failure_defaults(monkeypatch):
    config = parse(monkeypatch, [])

    assert config.camera_failure_locks is True
    assert config.camera_failure_grace_ticks == 3


def test_no_camera_failure_lock_flag_clears_the_field(monkeypatch):
    config = parse(monkeypatch, ["--no-camera-failure-lock"])

    assert config.camera_failure_locks is False
    assert config.camera_failure_grace_ticks == 3  # untouched


@pytest.mark.parametrize("value", [0, 1, 10])
def test_camera_failure_grace_ticks_flag_sets_the_field(monkeypatch, value):
    """Includes 0, which a truthiness check (`if args.x:`) would silently drop.

    The surrounding code uses `if args.x:` for several int flags, so 0 is the
    value most likely to be swallowed, and it is the one that means "lock with
    no tolerance at all".
    """
    config = parse(monkeypatch, ["--camera-failure-grace-ticks", str(value)])

    assert config.camera_failure_grace_ticks == value
    assert config.camera_failure_locks is True  # untouched
