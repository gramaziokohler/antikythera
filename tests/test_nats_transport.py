import threading

import pytest

pytest.importorskip("nats")

from compas_eve import Message  # noqa: E402
from compas_eve import Publisher  # noqa: E402
from compas_eve import Subscriber  # noqa: E402
from compas_eve import Topic  # noqa: E402
from compas_eve.codecs import ProtobufMessageCodec  # noqa: E402

from antikythera.models import TaskClaimRequest  # noqa: E402
from antikythera.transports.nats import NatsTransport  # noqa: E402
from antikythera.transports.nats import subject_for_topic  # noqa: E402


@pytest.mark.parametrize(
    "topic, subject",
    [
        ("antikythera/task/start", "antikythera.task.start"),
        ("/leading/and/trailing/", "leading.and.trailing"),
        ("plain", "plain"),
        ("a/+/c", "a.*.c"),
        ("a/#", "a.>"),
    ],
)
def test_topic_names_map_to_subjects_like_the_nats_mqtt_gateway(topic, subject):
    assert subject_for_topic(topic) == subject


@pytest.fixture
def transports(nats_url):
    created = []

    def make(**kwargs):
        created.append(NatsTransport(nats_url, **kwargs))
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


def test_messages_reach_subscribers_on_other_connections(transports):
    sender, receiver = transports(), transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/nats/hello"), callback, transport=receiver).subscribe()

    Publisher(Topic("test/nats/hello"), transport=sender).publish(Message(text="hi"))

    assert event.wait(5)
    assert received[0]["text"] == "hi"


def test_wildcard_subscription(transports):
    transport = transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/nats/+/status"), callback, transport=transport).subscribe()

    Publisher(Topic("test/nats/robot/status"), transport=transport).publish(Message(ok=True))

    assert event.wait(5)


def test_protobuf_messages_round_trip(transports):
    transport = transports(codec=ProtobufMessageCodec())
    received, event, callback = _receiver()
    Subscriber(Topic("test/nats/claim", TaskClaimRequest), callback, transport=transport).subscribe()

    Publisher(Topic("test/nats/claim", TaskClaimRequest), transport=transport).publish(TaskClaimRequest(task_id="bp.t", actor_id="a1"))

    assert event.wait(5)
    assert isinstance(received[0], TaskClaimRequest)
    assert received[0].actor_id == "a1"


def test_callbacks_can_publish_and_subscribe(transports):
    transport = transports()
    received, event, callback = _receiver()
    Subscriber(Topic("test/nats/pong"), callback, transport=transport).subscribe()

    def reply(message):
        # Runs on the delivery thread: publishing and subscribing from here must not deadlock.
        Subscriber(Topic("test/nats/other"), lambda m: None, transport=transport).subscribe()
        Publisher(Topic("test/nats/pong"), transport=transport).publish(Message(n=message["n"] + 1))

    Subscriber(Topic("test/nats/ping"), reply, transport=transport).subscribe()
    Publisher(Topic("test/nats/ping"), transport=transport).publish(Message(n=1))

    assert event.wait(5)
    assert received[0]["n"] == 2


def test_unsubscribe_stops_delivery_and_is_idempotent(transports):
    transport = transports()
    received, event, callback = _receiver()
    subscriber = Subscriber(Topic("test/nats/off"), callback, transport=transport)
    subscriber.subscribe()

    subscriber.unsubscribe()
    subscriber.unsubscribe()
    transport.unsubscribe_by_id("not-a-subscription")
    Publisher(Topic("test/nats/off"), transport=transport).publish(Message(n=1))

    assert not event.wait(0.5)


def test_retain_is_not_supported(transports):
    with pytest.raises(TypeError, match="retained"):
        transports().publish(Topic("test/nats/retain"), Message(), retain=True)


def test_close_is_idempotent(transports):
    transport = transports()
    transport.close()
    transport.close()

    assert not transport.is_connected
