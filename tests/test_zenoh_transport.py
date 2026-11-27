"""ZenohTransport, peer to peer: the sessions connect to each other, with no router."""

import socket
import threading
import time

import pytest

pytest.importorskip("zenoh")

from compas_eve import Message  # noqa: E402
from compas_eve import Publisher  # noqa: E402
from compas_eve import Subscriber  # noqa: E402
from compas_eve import Topic  # noqa: E402
from compas_eve.codecs import ProtobufMessageCodec  # noqa: E402

from antikythera.models import TaskClaimRequest  # noqa: E402
from antikythera.transports.zenoh import ZenohTransport  # noqa: E402
from antikythera.transports.zenoh import key_expr_for_topic  # noqa: E402
from tests.conftest import zenoh_test_config  # noqa: E402

# Zenoh propagates subscriptions asynchronously; give them a moment before publishing.
SETTLE = 0.3


@pytest.mark.parametrize(
    "topic, key_expr",
    [
        ("antikythera/task/start", "antikythera/task/start"),
        ("/leading/and/trailing/", "leading/and/trailing"),
        ("a/+/c", "a/*/c"),
        ("a/#", "a/**"),
    ],
)
def test_topic_names_map_to_key_expressions_like_the_zenoh_mqtt_plugin(topic, key_expr):
    assert key_expr_for_topic(topic) == key_expr


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture
def transports():
    """Make transports; the first listens and the others connect to it."""
    endpoint = f"tcp/127.0.0.1:{_free_port()}"
    created = []

    def make(**kwargs):
        if created:
            config = zenoh_test_config(connect=endpoint)
        else:
            config = zenoh_test_config(listen=endpoint)
        created.append(ZenohTransport(config, **kwargs))
        if len(created) > 1:
            time.sleep(SETTLE)
        return created[-1]

    yield make
    for transport in created:
        transport.close()


def _receiver():
    received, event = [], threading.Event()

    def callback(message):
        received.append(message)
        event.set()

    return received, event, callback


def test_messages_reach_subscribers_in_other_sessions(transports):
    sender, receiver = transports(), transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/zenoh/hello"), callback, transport=receiver).subscribe()
    time.sleep(SETTLE)

    Publisher(Topic("test/zenoh/hello"), transport=sender).publish(Message(text="hi"))

    assert event.wait(5)
    assert received[0]["text"] == "hi"


def test_wildcard_subscription(transports):
    transport = transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/zenoh/+/status"), callback, transport=transport).subscribe()

    Publisher(Topic("test/zenoh/robot/status"), transport=transport).publish(Message(ok=True))

    assert event.wait(5)


def test_protobuf_messages_round_trip(transports):
    transport = transports(codec=ProtobufMessageCodec())
    received, event, callback = _receiver()
    Subscriber(Topic("test/zenoh/claim", TaskClaimRequest), callback, transport=transport).subscribe()

    Publisher(Topic("test/zenoh/claim", TaskClaimRequest), transport=transport).publish(TaskClaimRequest(task_id="bp.t", actor_id="a1"))

    assert event.wait(5)
    assert isinstance(received[0], TaskClaimRequest)
    assert received[0].actor_id == "a1"


def test_unsubscribing_one_subscriber_keeps_the_others_on_the_topic(transports):
    transport = transports()
    first, _, first_callback = _receiver()
    second, second_event, second_callback = _receiver()
    removed = Subscriber(Topic("test/zenoh/shared"), first_callback, transport=transport)
    removed.subscribe()
    Subscriber(Topic("test/zenoh/shared"), second_callback, transport=transport).subscribe()

    removed.unsubscribe()
    Publisher(Topic("test/zenoh/shared"), transport=transport).publish(Message(n=1))

    assert second_event.wait(5)
    assert first == []


def test_a_blocked_callback_does_not_stop_its_session_sending(transports):
    sender, receiver = transports(), transports()
    release = threading.Event()
    received, event, callback = _receiver()
    Subscriber(Topic("test/zenoh/slow"), lambda m: release.wait(5), transport=receiver).subscribe()
    Subscriber(Topic("test/zenoh/fast"), callback, transport=sender).subscribe()
    time.sleep(SETTLE)

    Publisher(Topic("test/zenoh/slow"), transport=sender).publish(Message())
    Publisher(Topic("test/zenoh/fast"), transport=receiver).publish(Message())

    # The receiver's callbacks wait on the slow one, but its session still sends.
    assert event.wait(5)
    release.set()


def test_callbacks_can_publish_and_subscribe(transports):
    transport = transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/zenoh/pong"), callback, transport=transport).subscribe()

    def reply(message):
        Subscriber(Topic("test/zenoh/other"), lambda m: None, transport=transport).subscribe()
        Publisher(Topic("test/zenoh/pong"), transport=transport).publish(Message(n=message["n"] + 1))

    Subscriber(Topic("test/zenoh/ping"), reply, transport=transport).subscribe()
    Publisher(Topic("test/zenoh/ping"), transport=transport).publish(Message(n=1))

    assert event.wait(5)
    assert received[0]["n"] == 2


def test_unsubscribe_stops_delivery_and_is_idempotent(transports):
    transport = transports()
    received, event, callback = _receiver()
    subscriber = Subscriber(Topic("test/zenoh/off"), callback, transport=transport)
    subscriber.subscribe()

    subscriber.unsubscribe()
    subscriber.unsubscribe()
    transport.unsubscribe_by_id("not-a-subscription")
    Publisher(Topic("test/zenoh/off"), transport=transport).publish(Message(n=1))

    assert not event.wait(0.5)


def test_retain_is_not_supported(transports):
    with pytest.raises(TypeError, match="retained"):
        transports().publish(Topic("test/zenoh/retain"), Message(), retain=True)


def test_close_is_idempotent(transports):
    transport = transports()
    transport.close()
    transport.close()

    assert not transport.is_connected
