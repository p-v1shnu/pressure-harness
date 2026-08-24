"""A native approval window, built on Tk.

Tk because it ships with Python on Windows and macOS, so the prompt needs no
extra dependency and no packaging work -- and a prompt that fails to appear is
a permission system that silently stops working.

Three requirements come from PRD 10.7 and shape everything here:

* the window shows the literal payload, never a summary of it;
* it is separate from the console, so it appears whether or not the console is
  open, and it comes to the front on its own;
* it counts down and refuses on its own, because an unattended machine must
  fail closed.
"""

from __future__ import annotations

import contextlib
import threading
from collections.abc import Callable

from pharness.core.approvals import ApprovalRequest, Outcome

Respond = Callable[..., None]

BUTTONS = (
    ("Deny", Outcome.DENY),
    ("Allow once", Outcome.ONCE),
    ("Allow this conversation", Outcome.SESSION),
    ("Remember this exact request", Outcome.REMEMBER),
)


def tk_available() -> bool:
    """Whether a window can actually be opened here.

    Importing tkinter succeeds on machines with no display, so this goes as far
    as creating and destroying a root window -- the only honest test.
    """
    try:
        import tkinter
    except ImportError:
        return False
    try:
        root = tkinter.Tk()
    except Exception:
        return False
    root.destroy()
    return True


class TkNotifier:
    """Shows one window per request, each in its own thread.

    Tk requires every call to happen on the thread that created the root, so a
    dialog owns its root and nothing is shared between them.
    """

    name = "tk"
    interactive = True

    def __init__(self) -> None:
        self._windows: dict[str, object] = {}
        self._lock = threading.Lock()

    def present(self, request: ApprovalRequest, respond: Respond) -> None:
        thread = threading.Thread(
            target=self._show,
            args=(request, respond),
            daemon=True,
            name=f"approval-{request.id}",
        )
        thread.start()

    def withdraw(self, request_id: str) -> None:
        with self._lock:
            window = self._windows.pop(request_id, None)
        if window is not None:
            # The window may already be gone; withdrawing a closed prompt is fine.
            with contextlib.suppress(Exception):
                window.after(0, window.destroy)  # type: ignore[attr-defined]

    def notify(self, title: str, body: str) -> None:
        def show() -> None:
            import tkinter
            from tkinter import messagebox

            root = tkinter.Tk()
            root.withdraw()
            root.attributes("-topmost", True)
            messagebox.showinfo(title, body, parent=root)
            root.destroy()

        threading.Thread(target=show, daemon=True).start()

    # -- the window --------------------------------------------------------

    def _show(self, request: ApprovalRequest, respond: Respond) -> None:
        import tkinter
        from tkinter import scrolledtext, ttk

        answered = threading.Event()

        def answer(outcome: Outcome, note: str) -> None:
            if answered.is_set():
                return
            answered.set()
            with self._lock:
                self._windows.pop(request.id, None)
            with contextlib.suppress(Exception):  # closing twice is harmless
                root.destroy()
            respond(outcome, note)

        root = tkinter.Tk()
        root.title("Pressure Harness needs permission")
        root.attributes("-topmost", True)
        root.lift()
        root.resizable(True, True)
        # Closing the window is a refusal, not a dismissal.
        root.protocol("WM_DELETE_WINDOW", lambda: answer(Outcome.DENY, "window closed"))

        with self._lock:
            self._windows[request.id] = root

        frame = ttk.Frame(root, padding=12)
        frame.pack(fill="both", expand=True)

        heading = ttk.Label(
            frame,
            text=f"{request.tool}{'.' + request.op if request.op else ''}"
            f"  ·  {request.workspace}  ·  tier {request.tier.label}",
            font=("TkDefaultFont", 10, "bold"),
        )
        heading.pack(anchor="w")
        ttk.Label(frame, text=request.reason, wraplength=560).pack(anchor="w", pady=(2, 8))

        body = scrolledtext.ScrolledText(frame, width=72, height=12, wrap="word")
        body.insert("1.0", request.render())
        body.configure(state="disabled", font=("TkFixedFont", 9))
        body.pack(fill="both", expand=True)

        countdown = ttk.Label(frame, text="")
        countdown.pack(anchor="w", pady=(8, 4))

        row = ttk.Frame(frame)
        row.pack(fill="x")
        for label, outcome in BUTTONS:
            ttk.Button(
                row,
                text=label,
                command=lambda o=outcome, label=label: answer(o, f"chose {label!r}"),
            ).pack(side="left", padx=(0, 6))

        def tick() -> None:
            if answered.is_set():
                return
            from pharness.core.approvals import utc_now

            left = request.seconds_left(utc_now())
            countdown.configure(text=f"refused automatically in {left:.0f}s if unanswered")
            if left <= 0:
                answer(Outcome.TIMED_OUT, "the window timed out")
                return
            root.after(500, tick)

        tick()
        root.mainloop()
