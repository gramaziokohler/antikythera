from typing import Optional

from compas_eve.codecs import MessageCodec
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.memory import InMemoryTransport as _InMemoryTransport


class InMemoryTransport(_InMemoryTransport):
    """A transport inside the current Python process, for tests and small programs.

    It is `compas_eve.memory.InMemoryTransport` with the protobuf codec Antikythera's
    messages need, so it can be created without arguments.

    Parameters
    ----------
    codec : compas_eve.codecs.MessageCodec, optional
        Defaults to `compas_eve.codecs.ProtobufMessageCodec`.
    """

    def __init__(self, codec: Optional[MessageCodec] = None, *args, **kwargs):
        super().__init__(codec or ProtobufMessageCodec(), *args, **kwargs)
