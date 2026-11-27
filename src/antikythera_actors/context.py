import logging
import threading
from typing import Callable
from typing import List

logger = logging.getLogger(__name__)


class ExecutionContext:
    """
    Provides runtime context and lifecycle hooks for the currently executing task.

    Currently, only `on_cancel` is available as lifecycle event, but in the future,
    more events will be added to this context class.
    """

    def __init__(self):
        self._cancel_event = threading.Event()
        self._callbacks: List[Callable[[], None]] = []
        self._lock = threading.Lock()
        self._is_cancelled = False

    @property
    def is_cancelled(self) -> bool:
        """Returns True if the task has been requested to cancel."""
        return self._cancel_event.is_set()

    def cancel(self) -> None:
        """
        Marks the context as cancelled and executes all registered callbacks.
        This method is called by the runtime/launcher, not by the tool itself.
        """
        with self._lock:
            if self._is_cancelled:
                return
            self._is_cancelled = True
            self._cancel_event.set()

        # Execute callbacks outside the lock to avoid deadlocks
        for callback in self._callbacks:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in on_cancel callback: {e}")

    def on_cancel(self, callback: Callable[[], None]) -> None:
        """
        Register a callback to be executed when the task is cancelled.
        Useful for cleaning up external resources (sockets, file handles).

        If the context is already cancelled, the callback is executed immediately.
        """
        run_now = False
        with self._lock:
            if self._is_cancelled:
                run_now = True
            else:
                self._callbacks.append(callback)

        if run_now:
            try:
                callback()
            except Exception as e:
                logger.error(f"Error in on_cancel callback (immediate execution): {e}")
