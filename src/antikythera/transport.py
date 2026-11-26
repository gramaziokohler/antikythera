from typing import Optional

from compas_eve import Transport
from compas_eve.codecs import ProtobufMessageCodec

from antikythera import config


def check_transport(transport: Transport) -> Transport:
    """Check that ``transport`` can carry Antikythera's messages.

    The orchestrator and the actor launchers exchange protobuf messages, so the
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


def create_transport(
    kind: Optional[str] = None,
    broker_host: Optional[str] = None,
    broker_port: Optional[int] = None,
    nats_url: Optional[str] = None,
    mqtt_transport: str = "tcp",
    tls: bool = False,
) -> Transport:
    """Create the transport the orchestrator and actors talk over, as configured.

    Parameters
    ----------
    kind : str, optional
        ``"mqtt"`` or ``"nats"``. Defaults to the ``ANTIKYTHERA_TRANSPORT`` environment
        variable, or ``"mqtt"``.
    broker_host : str, optional
        MQTT broker host. Defaults to ``MQTT_BROKER_HOST``.
    broker_port : int, optional
        MQTT broker port. Defaults to ``MQTT_BROKER_PORT``.
    nats_url : str, optional
        NATS server URL. Defaults to ``NATS_URL``.
    mqtt_transport : str, optional
        The MQTT socket transport, ``"tcp"`` or ``"websockets"``.
    tls : bool, optional
        Connect to the MQTT broker over TLS. For NATS, use a ``tls://`` URL.

    Returns
    -------
    compas_eve.Transport
        A transport using ``ProtobufMessageCodec``.
    """
    kind = (kind or config.TRANSPORT).lower()
    codec = ProtobufMessageCodec()
    if kind == "nats":
        from antikythera.transports.nats import NatsTransport

        return NatsTransport(nats_url or config.NATS_URL, codec=codec)
    if kind == "mqtt":
        from compas_eve.mqtt import MqttTransport

        return MqttTransport(
            host=broker_host or config.MQTT_BROKER_HOST,
            port=broker_port or config.MQTT_BROKER_PORT,
            codec=codec,
            transport=mqtt_transport,
            tls=tls,
        )
    raise ValueError(f"Unknown transport '{kind}': use 'mqtt' or 'nats'")
