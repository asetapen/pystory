"""The lock overlay must block every monitor, not only the one Tk's single
fullscreen window lands on.

The Tk double here stands in for tkinter so the tests run headless and never
take a real global grab (see CLAUDE.md). It records exactly what lockscreen.py
asks of each window: its geometry, whether it is mapped, and its bindings.
"""

import pytest

import pystory.lockscreen as lockscreen
from pystory.config import Config


class FakeWidget:
    def __init__(self, *_a, **_kw):
        self.bindings = {}
        self.focused = 0
        self.text = ""

    def pack(self, **_kw):
        pass

    def bind(self, seq, fn):
        self.bindings[seq] = fn

    def delete(self, *_a):
        self.text = ""

    def get(self):
        return self.text

    def focus_force(self):
        self.focused += 1


class FakeWindow(FakeWidget):
    def __init__(self, *_a, **_kw):
        super().__init__()
        self.geom = None
        self.mapped = False
        self.attrs = {}
        self.override = False
        self.grabbed = False

    def withdraw(self):
        self.mapped = False

    def deiconify(self):
        self.mapped = True

    def lift(self):
        pass

    def title(self, _t):
        pass

    def geometry(self, g):
        self.geom = g

    def attributes(self, name, value):
        self.attrs[name] = value

    def configure(self, **_kw):
        pass

    def overrideredirect(self, flag):
        self.override = flag

    def protocol(self, *_a):
        pass

    def grab_set_global(self):
        self.grabbed = True

    def grab_release(self):
        self.grabbed = False


class FakeTk:
    END = "end"

    def __init__(self):
        self.windows = []
        self.entries = []

    def Tk(self):
        w = FakeWindow()
        self.windows.append(w)
        return w

    def Toplevel(self, _master):
        w = FakeWindow()
        self.windows.append(w)
        return w

    def Label(self, *a, **kw):
        return FakeWidget()

    def Entry(self, *a, **kw):
        e = FakeWidget()
        self.entries.append(e)
        return e


THREE = [(1920, 0, 3840, 2160), (0, 960, 1920, 1200), (5760, 0, 1440, 2560)]


def build(monkeypatch, geometries):
    fake = FakeTk()
    monkeypatch.setattr(lockscreen, "tk", fake)
    monkeypatch.setattr(lockscreen, "monitor_geometries", lambda: list(geometries))
    config = Config()
    config.lock_passphrase = "pw"
    overlay = lockscreen.LockOverlay(config)
    overlay._build()
    return overlay, fake


def test_every_monitor_gets_a_window_exactly_over_it(monkeypatch):
    overlay, fake = build(monkeypatch, THREE)
    assert [w.geom for w in fake.windows] == ["3840x2160+1920+0", "1920x1200+0+960", "1440x2560+5760+0"]
    root, *blinds = fake.windows
    assert root.attrs["-fullscreen"] is True
    assert all(b.override and b.attrs["-topmost"] for b in blinds)


def test_show_maps_every_window_and_hide_unmaps_them(monkeypatch):
    overlay, fake = build(monkeypatch, THREE)
    assert not any(w.mapped for w in fake.windows)
    overlay._do_show()
    assert all(w.mapped for w in fake.windows)
    assert fake.windows[0].grabbed
    overlay._do_hide()
    assert not any(w.mapped for w in fake.windows)
    assert not fake.windows[0].grabbed


def test_correct_passphrase_unmaps_the_other_screens_too(monkeypatch):
    overlay, fake = build(monkeypatch, THREE)
    overlay._do_show()
    fake.entries[0].text = "pw"
    overlay._check_passphrase()
    assert not any(w.mapped for w in fake.windows)


def test_wrong_passphrase_keeps_every_screen_blocked(monkeypatch):
    overlay, fake = build(monkeypatch, THREE)
    overlay._do_show()
    fake.entries[0].text = "nope"
    overlay._check_passphrase()
    assert all(w.mapped for w in fake.windows)


@pytest.mark.parametrize("index", [1, 2])
def test_panic_hotkey_works_from_any_screen(monkeypatch, index):
    overlay, fake = build(monkeypatch, THREE)
    overlay._do_show()
    fake.windows[index].bindings[overlay.config.lock_panic_hotkey](None)
    assert not any(w.mapped for w in fake.windows)


@pytest.mark.parametrize("event", ["<Button>", "<FocusIn>"])
def test_clicking_another_screen_gives_the_keyboard_back_to_the_passphrase(monkeypatch, event):
    overlay, fake = build(monkeypatch, THREE)
    overlay._do_show()
    entry = fake.entries[0]
    before = entry.focused
    fake.windows[2].bindings[event](None)
    assert entry.focused == before + 1


def test_unknown_layout_falls_back_to_one_fullscreen_window(monkeypatch):
    overlay, fake = build(monkeypatch, [])
    assert len(fake.windows) == 1
    assert fake.windows[0].geom is None
    assert fake.windows[0].attrs["-fullscreen"] is True
    overlay._do_show()
    assert fake.windows[0].mapped


class FakeMss:
    def __init__(self, monitors=None, error=None):
        self.monitors = monitors
        self.error = error

    def mss(self):
        if self.error:
            raise self.error
        return self

    def __enter__(self):
        return self

    def __exit__(self, *_a):
        return False


def mon(left, top, width, height, **extra):
    return {"left": left, "top": top, "width": width, "height": height, **extra}


def test_monitor_geometries_skips_the_union_and_puts_the_primary_first(monkeypatch):
    monitors = [
        mon(0, 0, 7200, 2560),
        mon(0, 960, 1920, 1200, is_primary=False),
        mon(1920, 0, 3840, 2160, is_primary=True),
        mon(5760, 0, 1440, 2560, is_primary=False),
    ]
    monkeypatch.setattr(lockscreen, "mss", FakeMss(monitors))
    assert lockscreen.monitor_geometries() == [(1920, 0, 3840, 2160), (0, 960, 1920, 1200), (5760, 0, 1440, 2560)]


def test_monitor_geometries_keeps_mss_order_when_it_reports_no_primary(monkeypatch):
    # mss before 10.x does not report is_primary at all.
    monitors = [mon(0, 0, 3000, 1000), mon(0, 0, 1000, 1000), mon(1000, 0, 2000, 1000)]
    monkeypatch.setattr(lockscreen, "mss", FakeMss(monitors))
    assert lockscreen.monitor_geometries() == [(0, 0, 1000, 1000), (1000, 0, 2000, 1000)]


def test_monitor_geometries_is_empty_when_the_layout_cannot_be_read(monkeypatch):
    monkeypatch.setattr(lockscreen, "mss", FakeMss(error=RuntimeError("no display")))
    assert lockscreen.monitor_geometries() == []
