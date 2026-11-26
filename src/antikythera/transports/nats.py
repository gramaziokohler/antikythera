"""NATS transport for compas_eve.

Lives in Antikythera while it settles; it only depends on compas_eve and nats-py, so it can
move to ``compas_eve.nats`` as is.
"""

from __future__ import annotations

import asyncio
import logging
import queue
import threading
from typing import Any
from typing import Callable
from typing import Coroutine
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from compas_eve import Message
from compas_eve import Topic
from compas_eve import Transport
from compas_eve.codecs import MessageCodec

try:
    import nats
except ImportError as e:  # pragma: no cover
    raise ImportError("The NATS transport needs nats-py: pip install 'antikythera-sdk[nats]'") from e

LOG = logging.getLogger(__name__)

DEFAULT_SERVERS = "nats://127.0.0.1:4222"


def subject_for_topic(name: str) -> str:
    """The NATS subject for a compas_eve topic name.

    Topic names follow MQTT conventions, so they are mapped the way the NATS server maps
    MQTT topics: levels separated by ``/`` become tokens separated by ``.``, and the
    ``+`` and ``#`` wildcards become ``*`` and ``>``. An MQTT client connected to the NATS
    server's MQTT listener therefore exchanges messages with this transport.

    Parameters
    ----------
    name : str
        The topic name, e.g. ``"antikythera/task/start"``.

    Returns
    -------
    str
        The subject, e.g. ``"antikythera.task.start"``.

    Examples
    --------
    >>> subject_for_topic("antikythera/task/+")
    'antikythera.task.*'
    >>> subject_for_topic("sensors/#")
    'sensors.>'
    """
    tokens = name.strip("/").split("/")
    return ".".join("*" if token == "+" else ">" if token == "#" else token for token in tokens)


class AsyncioThread:
    """An asyncio event loop running in a daemon thread, for driving asyncio clients from synchronous code."""

    def __init__(self, name: str = "nats") -> None:
        self.loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run, name=f"{name}-loop", daemon=True)
        self._thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        try:
            self.loop.run_forever()
        finally:
            self.loop.close()

    def run(self, coroutine: Coroutine, timeout: Optional[float] = None) -> Any:
        """Run ``coroutine`` on the loop and wait for its result. Must not be called from the loop's own thread."""
        if threading.current_thread() is self._thread:
            raise RuntimeError("AsyncioThread.run() would deadlock when called from the loop thread")
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop).result(timeout)

    def submit(self, coroutine: Coroutine) -> "asyncio.Future":
        """Schedule ``coroutine`` on the loop without waiting for it."""
        return asyncio.run_coroutine_threadsafe(coroutine, self.loop)

    def stop(self) -> None:
        if self.loop.is_running():
            self.loop.call_soon_threadsafe(self.loop.stop)
        if threading.current_thread() is not self._thread:
            self._thread.join(timeout=5)


class NatsTransport(Transport):
    """NATS transport allows sending and receiving messages through a NATS server.

    nats-py is asyncio based; this transport runs its own event loop in a background
    thread, so it is used from synchronous code like any other compas_eve transport.
    Messages are delivered to subscription callbacks one at a time on a separate thread,
    so a callback may block, publish or subscribe without stalling the connection.

    Parameters
    ----------
    servers : str or list of str, optional
        URL(s) of the NATS server(s). Defaults to ``nats://127.0.0.1:4222``.
    codec : MessageCodec, optional
        The codec to use for encoding and decoding messages.
        If not provided, defaults to ``compas_eve.codecs.JsonMessageCodec``.
    connect_timeout : float, optional
        Seconds to wait for the connection before raising.
    **connect_options
        Further keyword arguments for ``nats.connect``, e.g. ``user_credentials``,
        ``token`` or ``tls``.

    Examples
    --------
    >>> from compas_eve import Message, Publisher, Subscriber, Topic
    >>> transport = NatsTransport("nats://localhost:4222")  # doctest: +SKIP
    >>> Subscriber(Topic("hello/world"), print, transport=transport).subscribe()  # doctest: +SKIP
    >>> Publisher(Topic("hello/world"), transport=transport).publish(Message(text="Hi"))  # doctest: +SKIP
    """

    def __init__(
        self,
        servers: Union[str, List[str]] = DEFAULT_SERVERS,
        codec: Optional[MessageCodec] = None,
        connect_timeout: float = 5.0,
        **connect_options: Any,
    ) -> None:
        super(NatsTransport, self).__init__(codec=codec)
        self.servers = servers
        self._lock = threading.Lock()
        self._subscriptions: Dict[str, Any] = {}  # subscribe_id -> nats Subscription
        self._topics: Dict[str, List[str]] = {}  # topic name -> subscribe ids
        self._closed = False

        self._deliveries: "queue.Queue" = queue.Queue()
        self._dispatcher = threading.Thread(target=self._dispatch, name="nats-dispatch", daemon=True)
        self._dispatcher.start()

        self._loop = AsyncioThread()
        try:
            self.client = self._loop.run(nats.connect(servers, connect_timeout=connect_timeout, **connect_options), timeout=connect_timeout + 5)
        except Exception:
            self._shutdown_threads()
            raise

    def _dispatch(self) -> None:
        while True:
            item = self._deliveries.get()
            if item is None:
                return
            callback, topic, payload = item
            try:
                callback(self.codec.decode(payload, topic.message_type))
            except Exception:
                LOG.exception(f"Error in subscriber callback for topic '{topic.name}'")

    def _shutdown_threads(self) -> None:
        self._deliveries.put(None)
        self._loop.stop()

    def close(self) -> None:
        """Flush pending messages and close the connection."""
        if self._closed:
            return
        self._closed = True
        try:
            self._loop.run(self.client.drain(), timeout=10)
        except Exception:
            LOG.debug("Draining the NATS connection failed", exc_info=True)
        self._shutdown_threads()

    @property
    def is_connected(self) -> bool:
        return self.client.is_connected

    def on_ready(self, callback: Callable) -> None:
        """Invoke ``callback`` once connected. The connection is established in the constructor, so this calls it right away."""
        callback()

    def publish(self, topic: Topic, message: Union[Message, dict], **options: Any) -> None:
        """Publish a message to a topic.

        Parameters
        ----------
        topic : Topic
            Instance of the topic to publish to.
        message : Message
            Instance of the message to publish.
        """
        if options.pop("retain", False):
            raise TypeError("NatsTransport does not support retained messages")
        if options:
            raise TypeError("publish() got unexpected options for NatsTransport: {}".format(", ".join(options)))

        payload = self.codec.encode(message)
        if isinstance(payload, str):
            payload = payload.encode("utf-8")

        future = self._loop.submit(self.client.publish(subject_for_topic(topic.name), payload))
        future.add_done_callback(_log_failure(f"publish to '{topic.name}'"))

    def subscribe(self, topic: Topic, callback: Callable) -> str:
        """Subscribe to a topic.

        Every time a new message is received on the topic, the callback is invoked with
        the decoded message. When this returns, the server knows about the subscription,
        so messages published afterwards are not missed.

        Parameters
        ----------
        topic : Topic
            Instance of the topic to subscribe to.
        callback : callable
            Callback to invoke whenever a new message arrives, with the message as its
            only argument.

        Returns
        -------
        str
            Identifier of the subscription.
        """
        subscribe_id = "event:{}:{}:{}".format(topic.name, id(callback), self.id_counter)

        async def handler(msg):
            self._deliveries.put((callback, topic, msg.data))

        async def _subscribe():
            subscription = await self.client.subscribe(subject_for_topic(topic.name), cb=handler)
            await self.client.flush()
            return subscription

        subscription = self._loop.run(_subscribe(), timeout=10)
        with self._lock:
            self._subscriptions[subscribe_id] = subscription
            self._topics.setdefault(topic.name, []).append(subscribe_id)
        return subscribe_id

    def unsubscribe_by_id(self, subscribe_id: str) -> None:
        """Unsubscribe based on the subscription id. Unknown or already removed ids are ignored.

        Parameters
        ----------
        subscribe_id : str
            Identifier returned by [subscribe][antikythera.transports.nats.NatsTransport.subscribe].
        """
        with self._lock:
            subscription = self._subscriptions.pop(subscribe_id, None)
            for ids in self._topics.values():
                if subscribe_id in ids:
                    ids.remove(subscribe_id)
        if subscription is not None and not self._closed:
            self._loop.run(subscription.unsubscribe(), timeout=10)

    def unsubscribe(self, topic: Topic) -> None:
        """Remove every subscription to a topic.

        Parameters
        ----------
        topic : Topic
            Instance of the topic to unsubscribe from.
        """
        with self._lock:
            ids = list(self._topics.get(topic.name, []))
        for subscribe_id in ids:
            self.unsubscribe_by_id(subscribe_id)

    def advertise(self, topic: Topic) -> str:
        """Announce this code will publish to ``topic``. Has no effect on NATS."""
        return "advertise:{}:{}".format(topic.name, self.id_counter)

    def unadvertise(self, topic: Topic) -> None:
        """Announce this code stops publishing to ``topic``. Has no effect on NATS."""


def _log_failure(what: str) -> Callable:
    def callback(future) -> None:
        if not future.cancelled() and future.exception() is not None:
            LOG.error(f"NATS {what} failed: {future.exception()}")

    return callback
