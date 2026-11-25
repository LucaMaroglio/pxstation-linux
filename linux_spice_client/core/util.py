from __future__ import annotations

import logging
import threading

from gi.repository import GLib

log = logging.getLogger(__name__)


def run_in_thread(work, done=None) -> None:
    """Runs ``work()`` on a worker thread, then ``done(result, error)`` on the main loop."""

    def runner():
        try:
            result, error = work(), None
        except Exception as exc:  # reported to the caller
            result, error = None, exc
            log.debug("worker error", exc_info=True)
        if done is not None:
            GLib.idle_add(lambda: (done(result, error), False)[1])

    threading.Thread(target=runner, daemon=True).start()


def error_text(error: BaseException) -> str:
    text = str(error)
    return text or error.__class__.__name__
