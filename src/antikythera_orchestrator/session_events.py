"""Lightweight session event bus for push-based UI updates.

The :class:`SessionEventBus` provides a per-session publish/subscribe
mechanism backed by :class:`asyncio.Queue` instances.  The orchestrator
(or the API layer) publishes :class:`SessionEvent` notifications whenever
session state mutates — task state changes, data store updates, etc.
SSE (Server-Sent Events) subscribers consume these events to push
real-time updates to the frontend, eliminating the need for polling.

Thread-safety
-------------
Publishers call from synchronous worker threads (e.g. MQTT handlers),
while subscribers run inside the asyncio event loop.  We bridge the two
worlds via :func:`asyncio.get_event_loop().call_soon_threadsafe` so that
the ``asyncio.Queue.put_nowait`` is always called from the loop thread.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import contextmanager
from dataclasses import dataclass
from dataclasses import field
from enum import StrEnum
from threading import Lock
from typing import Any
from typing import AsyncIterator
from typing import Dict
from typing import Set

LOG = logging.getLogger(__name__)


class SessionEventType(StrEnum):
    """Types of events that the frontend can react to."""

    TASK_STATE_CHANGED = "task_state_changed"
    """One or more tasks changed state (e.g. PENDING → READY → RUNNING → SUCCEEDED)."""

    SESSION_STATE_CHANGED = "session_state_changed"
    """The overall session state changed (e.g. RUNNING → COMPLETED)."""

    DATA_STORE_UPDATED = "data_store_updated"
    """Data was written to the session data store."""

    BLUEPRINT_UPDATED = "blueprint_updated"
    """The blueprint structure changed (e.g. dynamic expansion)."""


@dataclass
class SessionEvent:
    """A single event emitted by the orchestrator / API layer."""

    type: SessionEventType
    session_id: str
    data: Dict[str, Any] = field(default_factory=dict)


class _Subscriber:
    """Internal subscriber wrapping an asyncio.Queue and its event loop."""

    __slots__ = ("queue", "loop")

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self.queue: asyncio.Queue[SessionEvent] = asyncio.Queue(maxsize=256)
        self.loop = loop


class SessionEventBus:
    """Global, singleton event bus for session-level notifications.

    Publishers call :meth:`publish` from any thread.
    Async consumers iterate over events using :meth:`subscribe`.
    """

    _instance: SessionEventBus | None = None
    _instance_lock = Lock()

    def __init__(self) -> None:
        self._lock = Lock()
        # session_id → set of _Subscriber
        self._subscribers: Dict[str, Set[_Subscriber]] = {}

    @classmethod
    def get_instance(cls) -> SessionEventBus:
        if cls._instance is None:
            with cls._instance_lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    # ------------------------------------------------------------------
    # Publisher side (called from any thread)
    # ------------------------------------------------------------------

    def publish(self, event: SessionEvent) -> None:
        """Push an event to all subscribers of the given session.

        Thread-safe — can be called from the orchestrator's worker threads.
        Uses ``call_soon_threadsafe`` to schedule the ``put_nowait`` on the
        subscriber's event loop.
        """
        with self._lock:
            subs = self._subscribers.get(event.session_id)
            if not subs:
                return
            # Snapshot to avoid modifying the set while iterating
            subs_snapshot = list(subs)

        for sub in subs_snapshot:
            try:
                sub.loop.call_soon_threadsafe(self._enqueue, sub, event)
            except RuntimeError:
                # Event loop is closed — subscriber is stale, will be
                # cleaned up when _unregister runs.
                pass

    @staticmethod
    def _enqueue(sub: _Subscriber, event: SessionEvent) -> None:
        """Put event into a subscriber's queue (runs on the loop thread)."""
        try:
            sub.queue.put_nowait(event)
        except asyncio.QueueFull:
            # Drop oldest event to prevent unbounded growth
            try:
                sub.queue.get_nowait()
                sub.queue.put_nowait(event)
            except (asyncio.QueueEmpty, asyncio.QueueFull):
                pass

    # ------------------------------------------------------------------
    # Subscriber side (async — used by SSE endpoint)
    # ------------------------------------------------------------------

    @contextmanager
    def _register(self, session_id: str, sub: _Subscriber):
        """Context manager that registers / unregisters a subscriber."""
        with self._lock:
            self._subscribers.setdefault(session_id, set()).add(sub)
        LOG.debug(f"SSE subscriber registered for session {session_id}")
        try:
            yield
        finally:
            with self._lock:
                subs = self._subscribers.get(session_id)
                if subs:
                    subs.discard(sub)
                    if not subs:
                        del self._subscribers[session_id]
            LOG.debug(f"SSE subscriber unregistered for session {session_id}")

    async def subscribe(self, session_id: str) -> AsyncIterator[SessionEvent]:
        """Async generator that yields events for a session.

        The generator runs until the caller cancels (i.e. the client
        disconnects from the SSE stream).
        """
        loop = asyncio.get_running_loop()
        sub = _Subscriber(loop)

        with self._register(session_id, sub):
            while True:
                event = await sub.queue.get()
                yield event
