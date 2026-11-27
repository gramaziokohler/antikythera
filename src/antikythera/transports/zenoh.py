"""Zenoh transport for compas_eve.

compas_eve ships a ``ZenohTransport`` as well; this one differs where Antikythera depends on
it: every subscription has its own Zenoh subscriber, so removing one leaves the others on the
topic working; callbacks run in order on a thread of their own, so a slow one does not
stall Zenoh's network threads;
MQTT-style wildcards are mapped; and publishing blocks rather than drops under congestion.
It only depends on compas_eve and eclipse-zenoh, so it can replace compas_eve's as is.
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any
from typing import Callable
from typing import Dict
from typing import List
from typing import Optional
from typing import Union

from compas_eve import Message
from compas_eve import Topic
from compas_eve import Transport
from compas_eve.codecs import MessageCodec

try:
    import zenoh
except ImportError as e:  # pragma: no cover
    raise ImportError("The Zenoh transport needs eclipse-zenoh: pip install 'antikythera-sdk[zenoh]'") from e

LOG = logging.getLogger(__name__)

DEFAULT_ENDPOINTS = "tcp/127.0.0.1:7447"


def key_expr_for_topic(name: str) -> str:
    """The Zenoh key expression for a compas_eve topic name.

    Topic names follow MQTT conventions. Zenoh key expressions also separate levels with
    ``/``, so names stay as they are, except that leading and trailing slashes are dropped
    and the ``+`` and ``#`` wildcards become ``*`` and ``**``. This is the mapping of
    Zenoh's MQTT plugin, so MQTT clients connected through it exchange messages with this
    transport.

    Parameters
    ----------
    name : str
        The topic name, e.g. ``"antikythera/task/+"``.

    Returns
    -------
    str
        The key expression, e.g. ``"antikythera/task/*"``.

    Examples
    --------
    >>> key_expr_for_topic("antikythera/task/+")
    'antikythera/task/*'
    >>> key_expr_for_topic("/sensors/#")
    'sensors/**'
    """
    chunks = name.strip("/").split("/")
    return "/".join("*" if chunk == "+" else "**" if chunk == "#" else chunk for chunk in chunks)


def zenoh_config(
    connect: Optional[Union[str, List[str]]] = None,
    mode: Optional[str] = None,
    config_file: Optional[str] = None,
    multicast_scouting: Optional[bool] = None,
) -> "zenoh.Config":
    """Build a Zenoh configuration.

    Parameters
    ----------
    connect : str or list of str, optional
        Endpoint(s) to connect to, e.g. ``"tcp/127.0.0.1:7447"``. A string may list several,
        separated by commas.
    mode : str, optional
        ``"peer"`` (Zenoh's default) or ``"client"``.
    config_file : str, optional
        A Zenoh JSON5 configuration file to start from.
    multicast_scouting : bool, optional
        Discover peers on the local network by multicast. Zenoh enables it by default.

    Returns
    -------
    zenoh.Config
    """
    config = zenoh.Config.from_file(config_file) if config_file else zenoh.Config()
    if isinstance(connect, str):
        connect = [endpoint.strip() for endpoint in connect.split(",") if endpoint.strip()]
    if connect:
        config.insert_json5("connect/endpoints", _json5_list(connect))
    if mode:
        config.insert_json5("mode", f'"{mode}"')
    if multicast_scouting is not None:
        config.insert_json5("scouting/multicast/enabled", "true" if multicast_scouting else "false")
    return config


def _json5_list(items: List[str]) -> str:
    return "[" + ", ".join(f'"{item}"' for item in items) + "]"


class ZenohTransport(Transport):
    """Zenoh transport allows sending and receiving messages over Zenoh.

    Messages are delivered to subscription callbacks one at a time on a separate thread, so
    a callback may block, publish or subscribe without stalling the Zenoh session.

    Parameters
    ----------
    config : zenoh.Config or str or list of str, optional
        A Zenoh configuration, or the endpoint(s) to connect to. Defaults to connecting to a
        router on ``tcp/127.0.0.1:7447``; see [zenoh_config][antikythera.transports.zenoh.zenoh_config].
    codec : MessageCodec, optional
        The codec to use for encoding and decoding messages.
        If not provided, defaults to ``compas_eve.codecs.JsonMessageCodec``.

    Examples
    --------
    >>> from compas_eve import Message, Publisher, Subscriber, Topic
    >>> transport = ZenohTransport("tcp/127.0.0.1:7447")  # doctest: +SKIP
    >>> Subscriber(Topic("hello/world"), print, transport=transport).subscribe()  # doctest: +SKIP
    >>> Publisher(Topic("hello/world"), transport=transport).publish(Message(text="Hi"))  # doctest: +SKIP
    """

    def __init__(self, config: Optional[Union["zenoh.Config", str, List[str]]] = None, codec: Optional[MessageCodec] = None) -> None:
        super(ZenohTransport, self).__init__(codec=codec)
        if config is None or isinstance(config, (str, list)):
            config = zenoh_config(connect=config or DEFAULT_ENDPOINTS)
        self._lock = threading.Lock()
        self._subscriptions: Dict[str, Any] = {}  # subscribe_id -> zenoh Subscriber
        self._topics: Dict[str, List[str]] = {}  # topic name -> subscribe ids
        self._publishers: Dict[str, Any] = {}  # key expression -> zenoh Publisher
        self._closed = False

        self._deliveries: "queue.Queue" = queue.Queue()
        self._dispatcher = threading.Thread(target=self._dispatch, name="zenoh-dispatch", daemon=True)
        self._dispatcher.start()

        try:
            self.session = zenoh.open(config)
        except Exception:
            self._deliveries.put(None)
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

    def close(self) -> None:
        """Close the Zenoh session."""
        if self._closed:
            return
        self._closed = True
        with self._lock:
            subscriptions = list(self._subscriptions.values())
            self._subscriptions.clear()
            self._topics.clear()
        for subscription in subscriptions:
            _quietly(subscription.undeclare)
        _quietly(self.session.close)
        self._deliveries.put(None)

    @property
    def is_connected(self) -> bool:
        return not self._closed and not self.session.is_closed()

    def on_ready(self, callback: Callable) -> None:
        """Invoke ``callback`` once connected. The session opens in the constructor, so this calls it right away."""
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
            raise TypeError("ZenohTransport does not support retained messages")
        if options:
            raise TypeError("publish() got unexpected options for ZenohTransport: {}".format(", ".join(options)))

        key_expr = key_expr_for_topic(topic.name)
        with self._lock:
            publisher = self._publishers.get(key_expr)
            if publisher is None:
                # Zenoh drops messages under congestion by default; a lost claim or
                # completion stalls a session, so wait instead.
                publisher = self.session.declare_publisher(key_expr, congestion_control=zenoh.CongestionControl.BLOCK)
                self._publishers[key_expr] = publisher
        publisher.put(self.codec.encode(message))

    def subscribe(self, topic: Topic, callback: Callable) -> str:
        """Subscribe to a topic.

        Every time a new message is received on the topic, the callback is invoked with
        the decoded message.

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

        def handler(sample) -> None:
            self._deliveries.put((callback, topic, sample.payload.to_bytes()))

        subscription = self.session.declare_subscriber(key_expr_for_topic(topic.name), handler)
        with self._lock:
            self._subscriptions[subscribe_id] = subscription
            self._topics.setdefault(topic.name, []).append(subscribe_id)
        return subscribe_id

    def unsubscribe_by_id(self, subscribe_id: str) -> None:
        """Unsubscribe based on the subscription id. Unknown or already removed ids are ignored.

        Parameters
        ----------
        subscribe_id : str
            Identifier returned by [subscribe][antikythera.transports.zenoh.ZenohTransport.subscribe].
        """
        with self._lock:
            subscription = self._subscriptions.pop(subscribe_id, None)
            for ids in self._topics.values():
                if subscribe_id in ids:
                    ids.remove(subscribe_id)
        if subscription is not None and not self._closed:
            subscription.undeclare()

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
        """Announce this code will publish to ``topic``. Has no effect on Zenoh."""
        return "advertise:{}:{}".format(topic.name, self.id_counter)

    def unadvertise(self, topic: Topic) -> None:
        """Announce this code stops publishing to ``topic``. Has no effect on Zenoh."""


def _quietly(action: Callable) -> None:
    try:
        action()
    except Exception:
        LOG.debug("Ignoring an error while closing the Zenoh session", exc_info=True)
