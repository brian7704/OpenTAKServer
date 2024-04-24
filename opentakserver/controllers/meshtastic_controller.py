import base64

from meshtastic import mqtt_pb2, portnums_pb2, mesh_pb2, protocols, BROADCAST_NUM
from google.protobuf.json_format import MessageToJson

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from opentakserver.controllers.rabbitmq_client import RabbitMQClient


class MeshtasticController(RabbitMQClient):
    def __init__(self, context, logger, db, socketio):
        super().__init__(context, logger, db, socketio)
        self.node_names = {}
        self.logger.info("Starting Meshtastic controller...")

    def on_channel_open(self, channel):
        self.logger.warning("on_channel_open")
        self.rabbit_channel = channel
        self.rabbit_channel.queue_declare(queue='meshtastic')
        self.rabbit_channel.queue_bind(exchange='amq.topic', queue='meshtastic', routing_key="#")
        self.rabbit_channel.basic_consume(queue='meshtastic', on_message_callback=self.on_message, auto_ack=True)
        self.rabbit_channel.add_on_close_callback(self.on_close)

    def try_decode(self, mp):
        self.logger.warning("decode")
        # Get the channel key from the DB
        key_bytes = base64.b64decode("AQ==".encode('ascii'))

        nonce = getattr(mp, "id").to_bytes(8, "little") + getattr(mp, "from").to_bytes(8, "little")
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(mp, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        mp.decoded.CopyFrom(data)

    def on_message(self, unused_channel, basic_deliver, properties, body):
        self.logger.warning("on_message")
        se = mqtt_pb2.ServiceEnvelope()
        try:
            se.ParseFromString(body)
            mp = se.packet
        except Exception as e:
            self.logger.error(f"ERROR: parsing service envelope: {str(e)}")
            self.logger.error(f"{body}")
            return

        from_id = getattr(mp, 'from')
        from_id = f"{from_id:08x}"
        to_id = mp.to
        if to_id == BROADCAST_NUM:
            to_id = 'all'
        else:
            to_id = f"{to_id:08x}"

        pn = portnums_pb2.PortNum.Name(mp.decoded.portnum)

        prefix = f"{mp.channel} [{from_id}->{to_id}] {pn}:"
        if mp.HasField("encrypted") and not mp.HasField("decoded"):
            try:
                self.try_decode(mp)
                pn = portnums_pb2.PortNum.Name(mp.decoded.portnum)
                prefix = f"{mp.channel} [{from_id}->{to_id}] {pn}:"
            except Exception as e:
                self.logger.warning(f"{prefix} could not be decrypted")
                return

        handler = protocols.get(mp.decoded.portnum)
        if handler is None:
            self.logger.warning(f"{prefix} no handler came from protocols")
            return

        if handler.protobufFactory is None:
            self.logger.info(f"{prefix} {mp.decoded.payload}")
        else:
            pb = handler.protobufFactory()
            pb.ParseFromString(mp.decoded.payload)
            p = MessageToJson(pb)
            if mp.decoded.portnum == portnums_pb2.PortNum.NODEINFO_APP:
                self.logger.info(f"node {getattr(mp, 'from'):x} has short_name {pb.short_name}")
                self.node_names[getattr(mp, "from")] = pb.short_name
                from_id = f"{getattr(mp, 'from'):x}[{self.node_names.get(getattr(mp, 'from'))}]"
                prefix = f"{mp.channel} [{from_id}->{to_id}] {pn}:"
            self.logger.info(f"{prefix} {p}")
