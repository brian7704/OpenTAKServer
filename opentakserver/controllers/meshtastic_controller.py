import base64
import datetime
import json
import traceback
import uuid

from meshtastic import mqtt_pb2, portnums_pb2, mesh_pb2, protocols, BROADCAST_NUM
from google.protobuf.json_format import MessageToJson
from xml.etree.ElementTree import Element, SubElement, tostring

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from opentakserver.controllers.rabbitmq_client import RabbitMQClient


class MeshtasticController(RabbitMQClient):
    def __init__(self, context, logger, db, socketio):
        super().__init__(context, logger, db, socketio)
        self.node_names = {}
        self.logger.info("Starting Meshtastic controller...")
        self.meshtastic_devices = {}

    def on_channel_open(self, channel):
        self.rabbit_channel = channel
        self.rabbit_channel.queue_declare(queue='meshtastic')
        self.rabbit_channel.queue_bind(exchange='amq.topic', queue='meshtastic', routing_key="#")
        self.rabbit_channel.basic_consume(queue='meshtastic', on_message_callback=self.on_message, auto_ack=True)
        self.rabbit_channel.add_on_close_callback(self.on_close)

    def try_decode(self, mp):
        # Get the channel key from the DB
        key_bytes = base64.b64decode("1PG7OiApB1nwvP+rz05pAQ==".encode('ascii'))

        nonce = getattr(mp, "id").to_bytes(8, "little") + getattr(mp, "from").to_bytes(8, "little")
        cipher = Cipher(algorithms.AES(key_bytes), modes.CTR(nonce), backend=default_backend())
        decryptor = cipher.decryptor()
        decrypted_bytes = decryptor.update(getattr(mp, "encrypted")) + decryptor.finalize()

        data = mesh_pb2.Data()
        data.ParseFromString(decrypted_bytes)
        mp.decoded.CopyFrom(data)

    def on_message(self, unused_channel, basic_deliver, properties, body):
        if basic_deliver.routing_key.endswith('outgoing'):
            return

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
            self.logger.info(f"{prefix} {mp}")
            self.protobuf_to_cot(mp.decoded.payload, from_id, to_id, pn)
        else:
            try:
                pb = handler.protobufFactory()
                pb.ParseFromString(mp.decoded.payload)
                p = MessageToJson(pb)
                if mp.decoded.portnum == portnums_pb2.PortNum.NODEINFO_APP:
                    self.logger.info(f"node {getattr(mp, 'from'):x} has short_name {pb.short_name}")
                    self.node_names[getattr(mp, "from")] = pb.short_name
                    #from_id = f"{getattr(mp, 'from'):x}[{self.node_names.get(getattr(mp, 'from'))}]"
                    from_id = '{:x}'.format(getattr(mp, "from"))
                    prefix = f"{mp.channel} [{from_id}->{to_id}] {pn}:"
                    self.rabbit_channel.queue_declare(queue=from_id)
                self.logger.info(f"{prefix} {p}")
                self.protobuf_to_cot(pb, from_id, to_id, pn)
            except:
                self.logger.error(traceback.format_exc())

    def cot(self, pb, from_id, to_id, portnum, how='m-g', cot_type='a-f-G-U-C', uid=None):
        from_id = from_id.split("[")[0]

        if not uid:
            uid = from_id

        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        stale = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        event = Element('event', {'how': how, 'type': cot_type, 'version': '2.0',
                                  'uid': uid, 'start': now, 'time': now, 'stale': stale})

        if portnum == "MAP_REPORT_APP" or portnum == "POSITION_APP":
            SubElement(event, 'point', {'ce': '9999999.0', 'le': '9999999.0', 'hae': str(pb.altitude),
                                        'lat': str(pb.latitude_i * .0000001), 'lon': str(pb.longitude_i * .0000001)})
        else:
            SubElement(event, 'point', {'ce': '0', 'le': '9999999.0', 'hae': '0',
                                        'lat': '0', 'lon': '0'})

        detail = SubElement(event, 'detail')
        return event, detail

    def position(self, pb, from_id, to_id, portnum):
        try:
            event, detail = self.cot(pb, from_id, to_id, portnum)
            if portnum == "MAP_REPORT_APP":
                SubElement(detail, 'takv', {'device': str(pb.hw_model), 'version': str(pb.firmware_version),
                                            'platform': 'Meshtastic', 'os': 'Meshtastic'})

            if portnum == "MAP_REPORT_APP":
                SubElement(detail, 'contact', {'callsign': str(pb.long_name), 'endpoint': 'MQTT'})
                SubElement(detail, 'uid', {'Droid': str(pb.long_name)})

            SubElement(detail, 'precisionlocation', {'altsrc': 'GPS', 'geopointsrc': 'GPS'})
            SubElement(detail, '__group', {'name': 'Cyan', 'role': 'Team Member'})
            SubElement(detail, 'track', {'course': "0", "speed": "0.0"})

            return event
        except BaseException as e:
            self.logger.error("Failed to create CoT: {}".format(str(e)))
            self.logger.error(traceback.format_exc())
            return

    def node_info(self, pb, from_id, to_id, portnum):
        event, detail = self.cot(pb, from_id, to_id, portnum)

        hw_model = mesh_pb2.HardwareModel.Name(pb.hw_model)
        SubElement(detail, 'takv', {'device': hw_model, 'version': 'Meshtastic',
                                    'platform': 'Meshtastic', 'os': 'Meshtastic', 'macaddr': base64.b64encode(pb.macaddr).decode('ascii')})
        SubElement(detail, 'contact', {'callsign': str(pb.long_name), 'endpoint': 'MQTT'})
        SubElement(detail, 'uid', {'Droid': str(pb.long_name)})
        SubElement(detail, 'precisionlocation', {'altsrc': 'GPS', 'geopointsrc': 'GPS'})
        SubElement(detail, 'status', {'battery': '100'})
        SubElement(detail, 'track', {'course': '0.0', 'speed': '0.0'})
        SubElement(detail, '__group', {'name': 'Cyan', 'role': 'Team Member'})

        self.meshtastic_devices[from_id] = {'hw_model': hw_model, 'long_name': pb.long_name}

        return event

    def text_message(self, pb, from_id, to_id, portnum):
        callsign = from_id
        if from_id in self.meshtastic_devices:
            callsign = self.meshtastic_devices[from_id]['long_name']

        # GeoChat.ANDROID-e3a3c5d176263d80.All Chat Rooms.236d35af-9bee-4812-891a-0b21f34ca864
        message_uid = str(uuid.uuid4())
        uid = "GeoChat.{}.All Chat Rooms.{}".format(from_id, message_uid)
        event, detail = self.cot(pb, from_id, to_id, portnum, how='h-g-i-g-o', cot_type='b-t-f', uid=uid)
        chat = SubElement(detail, '__chat',
                          {'chatroom': 'All Chat Rooms', 'groupOwner': "false", 'id': 'All Chat Rooms',
                           'messageId': message_uid, 'parent': 'RootContactGroup',
                           'senderCallsign': callsign})
        SubElement(chat, 'chatgrp', {'id': 'All Chat Rooms', 'uid0': from_id, 'uid1': 'All Chat Rooms'})
        SubElement(detail, 'link', {'relation': 'p-p', 'type': 'a-f-G-U-C', 'uid': from_id})
        remarks = SubElement(detail, 'remarks', {'source': 'BAO.F.ATAK.{}'.format(from_id),
                                                 'time': datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                 'to': 'All Chat Rooms'})
        remarks.text = pb.decode('utf-8')
        return event

    def protobuf_to_cot(self, pb, from_id, to_id, portnum):
        event = None

        if portnum == "MAP_REPORT_APP" or portnum == "POSITION_APP":
            event = self.position(pb, from_id, to_id, portnum)
        elif portnum == "NODEINFO_APP":
            event = self.node_info(pb, from_id, to_id, portnum)
        elif portnum == "TEXT_MESSAGE_APP":
            event = self.text_message(pb, from_id, to_id, portnum)

        try:
            if event:
                self.logger.warning(tostring(event).decode('utf-8'))
                message = json.dumps({'uid': from_id, 'cot': tostring(event).decode('utf-8')})
                if portnum == "TEXT_MESSAGE_APP":
                    try:
                        self.rabbit_channel.basic_publish(exchange='chatrooms', routing_key='All Chat Rooms',
                                                                 body=message)
                    except BaseException as e:
                        self.logger.error("Failed to publish chat message: {}".format(e))
                else:
                    self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='', body=message)
        except BaseException as e:
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
