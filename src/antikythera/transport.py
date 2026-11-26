from compas_eve import Transport
from compas_eve.codecs import ProtobufMessageCodec


def check_transport(transport: Transport) -> Transport:
    """Check that ``transport`` can carry Antikythera's messages.

    The orchestrator and the agent launchers exchange protobuf messages, so the
    transport they share must use `compas_eve.codecs.ProtobufMessageCodec`.
    compas_eve transports default to JSON, which fails only once the first message is sent.

    Parameters
    ----------
    transport : compas_eve.Transport
        The transport to check.

    Returns
    -------
    compas_eve.Transport
        The same transport.

    Raises
    ------
    ValueError
        If the transport does not use a protobuf codec.
    """
    if not isinstance(getattr(transport, "codec", None), ProtobufMessageCodec):
        raise ValueError(
            "Antikythera exchanges protobuf messages: create the transport with codec=ProtobufMessageCodec(), "
            "e.g. InMemoryTransport(codec=ProtobufMessageCodec())."
        )
    return transport
