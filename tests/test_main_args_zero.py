"""Numeric CLI flags must not silently swallow a value (issue st-dqfz5j).

Four numeric flags were gated with `if args.x:`, a TRUTHINESS test, so `0` took
the same branch as omitting the flag entirely and the hardcoded default was
applied instead. The flag was accepted, `--help` listed it, nothing was logged,
and the only way to observe it was to read the Config field: `--max-history-mb 0`
("keep nothing") kept 500 MB.

`tests/test_main_args.py` already bound exactly this for
`--camera-failure-grace-ticks`, and its docstring named the class ("The
surrounding code uses `if args.x:` for several int flags, so 0 is the value most
likely to be swallowed"). The four siblings were never bound, so the suite was
green and could not fail on any of them.

The property bound here is that NO value is silently ignored: a value that can
work reaches the field, and a value that cannot is refused BY NAME with exit 2.
Both halves are load-bearing. Binding only "0 reaches the field" is satisfied by
a fix that also lets `--max-history-mb -1` through, and -1 deletes every capture.
"""

import pytest

import pystory.main as main


# (flag, Config field, shipped default) for the four flags that were gated on
# truthiness. The default is carried here and asserted rather than assumed: a
# case comparing a field against 0 cannot discriminate if the default is
# already 0, and one comparing against 7 cannot discriminate if it is already 7.
GATED = [
    ("--interval", "interval_seconds", 5),
    ("--quality", "image_quality", 50),
    ("--max-dimension", "image_max_dimension", 1280),
    ("--max-history-mb", "max_history_mb", 500),
]

# The flags for which 0 is a coherent request, and what it asks for:
#   --interval 0        capture as fast as possible (time.sleep(0) returns)
#   --max-history-mb 0  keep nothing (prune_old_files honours 0)
# --quality 0 and --max-dimension 0 are not here on purpose; they are refused
# instead, and test_unworkable_value_is_refused covers them.
ZERO_IS_COHERENT = [
    ("--interval", "interval_seconds"),
    ("--max-history-mb", "max_history_mb"),
]

# (flag, value) pairs that cannot work and must be refused rather than reach a
# field. --max-dimension 0 raises ZeroDivisionError inside PIL on the first
# capture; --max-history-mb -1 deletes every capture; the --quality bounds are
# the range the flag's own help text documents.
UNWORKABLE = [
    ("--max-dimension", "0"),
    ("--max-dimension", "-1"),
    ("--interval", "-1"),
    ("--max-history-mb", "-1"),
    ("--quality", "0"),
    ("--quality", "101"),
]


def parse(monkeypatch, argv):
    monkeypatch.setattr("sys.argv", ["pystory", *argv])
    return main.parse_args()


@pytest.mark.parametrize("flag,attr,default", GATED)
def test_absent_flag_keeps_the_default(monkeypatch, flag, attr, default):
    """DIRECTIONAL CONTROL. A fix that applies 0 whenever the flag is ABSENT
    satisfies the zero case below and breaks every default, and that breakage
    looks exactly like the fix working."""
    config = parse(monkeypatch, [])

    assert getattr(config, attr) == default


@pytest.mark.parametrize("flag,attr,default", GATED)
def test_nonzero_reaches_the_field(monkeypatch, flag, attr, default):
    """POSITIVE CONTROL. Without it, "0 was swallowed" is equally satisfied by a
    flag that is simply broken for every input, which is a different defect with
    a different fix -- and a fix that hardcodes 0 passes the zero case."""
    assert default != 7, "7 must differ from the default or this cannot discriminate"

    config = parse(monkeypatch, [flag, "7"])

    assert getattr(config, attr) == 7


@pytest.mark.parametrize("flag,attr", ZERO_IS_COHERENT)
def test_zero_reaches_the_field(monkeypatch, flag, attr):
    """THE DEFECT. 0 must land, not take the absent-flag branch."""
    default = getattr(main.Config(), attr)
    assert default != 0, "the default must be nonzero or this cannot discriminate"

    config = parse(monkeypatch, [flag, "0"])

    assert getattr(config, attr) == 0


@pytest.mark.parametrize("flag,value", UNWORKABLE)
def test_unworkable_value_is_refused(monkeypatch, capsys, flag, value):
    """A value that cannot work must be REFUSED by name, not silently dropped
    and not passed through to fail obscurely later. The truthiness gate did the
    opposite of both: it swallowed the one coherent value (0) while passing
    negatives straight to the field."""
    with pytest.raises(SystemExit) as exit_info:
        parse(monkeypatch, [flag, value])

    assert exit_info.value.code == 2
    stderr = capsys.readouterr().err
    assert flag in stderr, f"the refusal must name the flag; got: {stderr!r}"
    assert value in stderr, f"the refusal must name the value; got: {stderr!r}"


@pytest.mark.parametrize("value", [1, 100])
def test_quality_range_endpoints_are_accepted(monkeypatch, value):
    """CONTROL on the bound itself. Refusing 0 and 101 is also satisfied by a
    tighter range (2-99), which would reject documented values, and the
    refusal cases alone cannot see that."""
    config = parse(monkeypatch, ["--quality", str(value)])

    assert config.image_quality == value
