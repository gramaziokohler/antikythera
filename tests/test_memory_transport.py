"""`antikythera.InMemoryTransport` delivers messages the way a broker does."""

import threading

from compas_eve import Message
from compas_eve import Publisher
from compas_eve import Subscriber
from compas_eve import Topic

from antikythera.transports.memory import InMemoryTransport


def test_reply_arrives_after_the_message_it_answers():
    transport = InMemoryTransport()
    question, answer = Topic("test/question"), Topic("test/answer")
    seen = []
    done = threading.Event()
    answers = Publisher(answer, transport=transport)

    # The first subscriber answers at once; the second must still get the question first.
    Subscriber(question, lambda message: answers.publish(Message(text="answer")), transport=transport).subscribe()
    Subscriber(question, lambda message: seen.append("question"), transport=transport).subscribe()

    def on_answer(message):
        seen.append("answer")
        done.set()

    Subscriber(answer, on_answer, transport=transport).subscribe()

    Publisher(question, transport=transport).publish(Message(text="question"))

    assert done.wait(5)
    assert seen == ["question", "answer"]


def test_publish_returns_before_delivery():
    transport = InMemoryTransport()
    topic = Topic("test/slow")
    delivered = threading.Event()
    release = threading.Event()

    def slow(message):
        release.wait(5)
        delivered.set()

    Subscriber(topic, slow, transport=transport).subscribe()
    Publisher(topic, transport=transport).publish(Message(text="hi"))

    assert not delivered.is_set()
    release.set()
    assert delivered.wait(5)
