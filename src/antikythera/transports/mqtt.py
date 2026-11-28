from typing import Optional

from compas_eve.codecs import MessageCodec
from compas_eve.codecs import ProtobufMessageCodec
from compas_eve.mqtt import MqttTransport as _MqttTransport


class MqttTransport(_MqttTransport):
    """A transport over an MQTT broker, the default of Antikythera.

    It is `compas_eve.mqtt.MqttTransport` with the protobuf codec Antikythera's messages
    need, so only the broker address is required.

    Parameters
    ----------
    host : str
        Host of the MQTT broker.
    port : int, optional
        Port of the MQTT broker.
    codec : compas_eve.codecs.MessageCodec, optional
        Defaults to `compas_eve.codecs.ProtobufMessageCodec`.
    **kwargs
        Passed on to `compas_eve.mqtt.MqttTransport`: ``transport="websockets"``,
        ``tls=True``, ``client_id``, ``tls_options``.
    """

    def __init__(self, host: str, port: int = 1883, codec: Optional[MessageCodec] = None, **kwargs):
        super().__init__(host, port, codec=codec or ProtobufMessageCodec(), **kwargs)
