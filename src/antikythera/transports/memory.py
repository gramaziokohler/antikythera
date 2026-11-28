import logging
import queue
import threading
from typing import Optional

from compas_eve.codecs import MessageCodec
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport as _InMemoryTransport

LOG = logging.getLogger(__name__)


class InMemoryTransport(_InMemoryTransport):
    """A transport inside the current Python process, for tests and small programs.

    It is `compas_eve.memory.InMemoryTransport` with two differences, so that the
    orchestrator and the actors behave as they do over a network:

    - It uses the protobuf codec Antikythera's messages need, so it takes no arguments.
    - It delivers messages the way a broker does: after `publish` returns, one at a time,
      in the order they were published, on a delivery thread of its own. compas_eve's
      transport calls the subscribers inside `publish`, so a reply sent from a subscriber
      reaches the others before the message it answers, which never happens over a network.

    Parameters
    ----------
    codec : compas_eve.codecs.MessageCodec, optional
        Defaults to `compas_eve.codecs.ProtobufMessageCodec`.
    """

    def __init__(self, codec: Optional[MessageCodec] = None, *args, **kwargs):
        super().__init__(codec or ProtobufMessageCodec(), *args, **kwargs)
        self._deliveries: queue.Queue = queue.Queue()
        self._delivery_thread = threading.Thread(target=self._deliver, name="InMemoryTransport", daemon=True)
        self._delivery_thread.start()

    def publish(self, topic, message, **options):
        retain = options.pop("retain", False)
        if options:
            raise TypeError("publish() got unexpected options for InMemoryTransport: {}".format(", ".join(options)))
        # Encode now, so changes to the message after publishing are not sent.
        encoded = self.codec.encode(message)
        encoded = encoded if isinstance(encoded, bytes) else encoded.encode("utf-8")
        if retain:
            self._retained[topic.name] = encoded
        self._deliveries.put(("event:{}".format(topic.name), encoded))

    def _deliver(self) -> None:
        while True:
            event_key, encoded = self._deliveries.get()
            try:
                self.emit(event_key, encoded)
            except Exception:
                # Like a broker, a failing subscriber does not stop the delivery of later messages.
                LOG.exception(f"A subscriber of {event_key} failed")
