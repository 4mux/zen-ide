"""Thread-safe dispatch to the GTK main thread.

GLib 2.86+ has stricter assertions that crash when GLib.idle_add() is called
from non-main threads. This module provides a safe alternative using a
queue + main-thread poll timer.

Setup (call once from main thread during app init):
    from shared.main_thread import start_main_thread_poll
    start_main_thread_poll()

Usage (from any thread):
    from shared.main_thread import main_thread_call
    main_thread_call(my_callback, arg1, arg2)
"""

import queue

from gi.repository import GLib

_queue: queue.SimpleQueue = queue.SimpleQueue()
_poll_id: int | None = None
_POLL_INTERVAL_MS = 50


def _poll_queue() -> bool:
    """Main-thread timer callback that drains the queue."""
    while True:
        try:
            func, args, kwargs = _queue.get_nowait()
        except queue.Empty:
            break
        try:
            func(*args, **kwargs)
        except Exception:
            import logging

            logging.getLogger("zen.main_thread").exception(
                "Exception in main_thread_call callback %s", getattr(func, "__name__", func)
            )
    return True  # keep the timer alive


def start_main_thread_poll() -> None:
    """Start the poll timer. Must be called from the main thread."""
    global _poll_id
    if _poll_id is None:
        _poll_id = GLib.timeout_add(_POLL_INTERVAL_MS, _poll_queue)


def main_thread_call(func, *args, **kwargs) -> None:
    """Schedule *func* to run on the GTK main thread (thread-safe).

    Only enqueues — never touches GLib — so safe from any thread.
    Requires start_main_thread_poll() to have been called first.
    """
    _queue.put((func, args, kwargs))
