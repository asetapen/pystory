import logging
import queue
import threading
import tkinter as tk

from pystory.config import Config

log = logging.getLogger("pystory.lockscreen")


class LockOverlay:
    """A fullscreen, always-on-top Tk window that makes the desk unusable.

    Not a real session lock (no `loginctl`/greeter involved) — it's a
    grabbed, topmost window that eats keyboard/mouse focus. That's enough to
    stop casual use, and unlike a real lock it can never leave you stuck
    behind a login screen if face recognition misbehaves: the panic hotkey
    and passphrase both bypass it instantly, and killing the pystory process
    (e.g. via SSH) removes it outright.

    Runs its own Tk mainloop on a dedicated thread; `show()`/`hide()` are
    called from the capture-loop thread and hop over via a thread-safe queue.
    """

    def __init__(self, config: Config):
        self.config = config
        self._cmd_queue: queue.Queue[str] = queue.Queue()
        self._root: tk.Tk | None = None
        self._entry: tk.Entry | None = None
        self._visible = False
        self._thread = threading.Thread(target=self._run, daemon=True)

    def start(self) -> None:
        self._thread.start()

    def show(self) -> None:
        self._cmd_queue.put("show")

    def hide(self) -> None:
        self._cmd_queue.put("hide")

    def _run(self) -> None:
        root = tk.Tk()
        self._root = root
        root.withdraw()
        root.title("pystory")
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
        self._poll_queue()
        root.mainloop()

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
        self._root.deiconify()
        self._root.attributes("-topmost", True)
        self._root.grab_set_global()
        if self._entry is not None:
            self._entry.delete(0, tk.END)
            self._entry.focus_force()
        log.warning("Lock overlay shown")

    def _do_hide(self) -> None:
        if not self._visible or self._root is None:
            return
        self._visible = False
        self._root.grab_release()
        self._root.withdraw()
        log.info("Lock overlay hidden")

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
