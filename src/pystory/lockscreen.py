from __future__ import annotations

import logging
import queue
import threading

import mss

try:
    import tkinter as tk
except ImportError:  # some Python builds (e.g. CI's) ship without Tk
    tk = None

from pystory.config import Config

log = logging.getLogger("pystory.lockscreen")

Geometry = tuple[int, int, int, int]  # x, y, width, height


def monitor_geometries() -> list[Geometry]:
    """Each physical monitor's (x, y, width, height), primary first.

    Empty when the monitors cannot be read, in which case the overlay falls
    back to a single fullscreen window. mss only reports `is_primary` from
    10.x on; without it the order is whatever mss returns.
    """
    try:
        with mss.mss() as sct:
            monitors = sct.monitors[1:]  # [0] is the union of all of them
    except Exception:
        log.exception("Could not read monitor layout; overlay covers one screen only")
        return []
    ordered = sorted(monitors, key=lambda m: not m.get("is_primary", False))
    return [(m["left"], m["top"], m["width"], m["height"]) for m in ordered]


def _geometry_string(g: Geometry) -> str:
    x, y, w, h = g
    return f"{w}x{h}+{x}+{y}"


class LockOverlay:
    """A fullscreen, always-on-top Tk window that makes the desk unusable.

    Not a real session lock (no `loginctl`/greeter involved) — it's a
    grabbed, topmost window that eats keyboard/mouse focus. That's enough to
    stop casual use, and unlike a real lock it can never leave you stuck
    behind a login screen if face recognition misbehaves: the panic hotkey
    and passphrase both bypass it instantly, and killing the pystory process
    (e.g. via SSH) removes it outright.

    The passphrase window sits on the primary monitor; every other monitor
    gets a plain black window, so the whole desk is blocked rather than one
    screen of it.

    Runs its own Tk mainloop on a dedicated thread; `show()`/`hide()` are
    called from the capture-loop thread and hop over via a thread-safe queue.
    """

    def __init__(self, config: Config):
        # Checked here, on the caller's thread, so a missing Tk stops pystory
        # at startup instead of killing the overlay thread and never locking.
        if tk is None:
            raise RuntimeError("--lock-overlay needs tkinter (on Ubuntu: apt install python3-tk)")
        self.config = config
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._root: tk.Tk | None = None
        self._entry: tk.Entry | None = None
        self._blinds: list[tk.Toplevel] = []
        self._visible = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def show(self) -> None:
        self._cmd_queue.put("show")

    def hide(self) -> None:
        self._cmd_queue.put("hide")

    def _run(self) -> None:
        self._build()
        assert self._root is not None
        self._poll_queue()
        self._root.mainloop()

    def _build(self) -> None:
        geometries = monitor_geometries()
        root = tk.Tk()
        self._root = root
        root.withdraw()
        root.title("pystory")
        if geometries:
            # Pin the passphrase window to the primary monitor before it goes
            # fullscreen; window managers fullscreen onto the monitor a window
            # is on, and with no window manager the geometry alone covers it.
            root.geometry(_geometry_string(geometries[0]))
        root.attributes("-fullscreen", True)
        root.attributes("-topmost", True)
        root.configure(bg="black")

        label = tk.Label(
            root,
            text="Desk locked — pystory didn't see you.\nEnter passphrase to unlock:",
            fg="white",
            bg="black",
            font=("sans-serif", 20),
        )
        label.pack(expand=True)

        entry = tk.Entry(root, show="*", font=("sans-serif", 16), justify="center")
        entry.pack(pady=20)
        entry.bind("<Return>", lambda _e: self._check_passphrase())
        self._entry = entry

        # Panic hotkey: always bound, works even while "locked", bypasses
        # recognition entirely in case it's misbehaving.
        root.bind(self.config.lock_panic_hotkey, lambda _e: self._force_unlock())
        root.protocol("WM_DELETE_WINDOW", lambda: None)  # no closing via window manager

        for g in geometries[1:]:
            # override-redirect so the window manager cannot move, tile or
            # decorate it; it is placed exactly over its monitor.
            blind = tk.Toplevel(root)
            blind.withdraw()
            blind.overrideredirect(True)
            blind.geometry(_geometry_string(g))
            blind.attributes("-topmost", True)
            blind.configure(bg="black")
            blind.bind(self.config.lock_panic_hotkey, lambda _e: self._force_unlock())
            # A click on another screen would otherwise take the keyboard
            # away from the passphrase field and strand the typed passphrase.
            blind.bind("<Button>", lambda _e: self._refocus_entry())
            blind.bind("<FocusIn>", lambda _e: self._refocus_entry())
            blind.protocol("WM_DELETE_WINDOW", lambda: None)
            self._blinds.append(blind)

    def _poll_queue(self) -> None:
        assert self._root is not None
        try:
            while True:
                cmd = self._cmd_queue.get_nowait()
                if cmd == "show":
                    self._do_show()
                elif cmd == "hide":
                    self._do_hide()
        except queue.Empty:
            pass
        self._root.after(150, self._poll_queue)

    def _do_show(self) -> None:
        if self._visible or self._root is None:
            return
        self._visible = True
        for blind in self._blinds:
            blind.deiconify()
            blind.lift()
        self._root.deiconify()
        self._root.attributes("-topmost", True)
        self._root.grab_set_global()
        if self._entry is not None:
            self._entry.delete(0, tk.END)
            self._entry.focus_force()
        log.warning("Lock overlay shown on %d screen(s)", 1 + len(self._blinds))

    def _do_hide(self) -> None:
        if not self._visible or self._root is None:
            return
        self._visible = False
        self._root.grab_release()
        self._root.withdraw()
        for blind in self._blinds:
            blind.withdraw()
        log.info("Lock overlay hidden")

    def _refocus_entry(self) -> None:
        if self._visible and self._entry is not None:
            self._entry.focus_force()

    def _check_passphrase(self) -> None:
        if self._entry is None:
            return
        entered = self._entry.get()
        if self.config.lock_passphrase and entered == self.config.lock_passphrase:
            self._do_hide()
        else:
            self._entry.delete(0, tk.END)

    def _force_unlock(self) -> None:
        log.warning("Panic hotkey pressed, forcing unlock")
        self._do_hide()
