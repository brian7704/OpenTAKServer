import base64
import datetime
import json
import traceback
import uuid

import pika
import unishox2
import os

from meshtastic import mqtt_pb2, portnums_pb2, mesh_pb2, protocols, BROADCAST_NUM

from opentakserver.models.Meshtastic import MeshtasticChannel
from opentakserver.proto import atak_pb2
from google.protobuf.json_format import MessageToJson
from xml.etree.ElementTree import Element, SubElement, tostring

from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.backends import default_backend

from opentakserver.controllers.rabbitmq_client import RabbitMQClient
from opentakserver.models.EUD import EUD


class MeshtasticController(RabbitMQClient):
    def __init__(self, context, logger, db, socketio):
        super().__init__(context, logger, db, socketio)
        self.node_names = {}
        self.logger.info("Starting Meshtastic controller...")
        self.meshtastic_devices = {}
        self.get_euds()
        self.get_channels()

    def get_euds(self):
        with self.context:
            euds = self.db.session.execute(self.db.session.query(EUD)).scalars()
            for eud in euds:
                meshtastic_id = eud.meshtastic_id
                if not eud.meshtastic_id:
                    eud.meshtastic_id = int.from_bytes(os.urandom(4), 'big')
                    self.db.session.add(eud)
                    self.db.session.commit()
                self.meshtastic_devices[eud.uid] = {'hw_model': eud.device, 'long_name': eud.callsign, 'short_name': '',
                                                    'firmware_version': eud.version, 'last_lat': "0.0",
                                                    'last_lon': "0.0",
                                                    'battery': 0, 'meshtastic_id': '{:x}'.format(eud.meshtastic_id),
                                                    'voltage': 0,
                                                    'uptime': 0, 'last_alt': "9999999.0", 'course': '0.0',
                                                    'speed': '0.0', 'team': 'Cyan', 'role': 'Team Member',
                                                    'uid': eud.uid,
                                                    'macaddr': eud.meshtastic_macaddr}

    def get_channels(self):
        with self.context:
            channels = self.db.session.execute(self.db.session.query(MeshtasticChannel)).scalars()
            downlink_channels = []
            for channel in channels:
                if channel.downlink_enabled:
                    downlink_channels.append(channel.name)
            self.context.app.config.update({"OTS_MESHTASTIC_DOWNLINK_CHANNELS": downlink_channels})

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
        # Don't process outgoing message from TAK EUDs to the Meshtastic Network, only messages from the Meshtastic
        # network to TAK EUDs
        if basic_deliver.routing_key.endswith('outgoing'):
            return

        # Forward this Meshtastic message to other Meshtastic channels which have downlink enabled
        for channel in self.context.app.config.get("OTS_MESHTASTIC_DOWNLINK_CHANNELS"):
            routing_key = "{}.2.e.{}.".format(self.context.app.config.get("OTS_MESHTASTIC_TOPIC"), channel)
            if not basic_deliver.routing_key.startswith(routing_key):
                self.rabbit_channel.basic_publish(exchange='amq.topic', routing_key=routing_key + "outgoing", body=body,
                                                  properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))

        se = mqtt_pb2.ServiceEnvelope()
        try:
            se.ParseFromString(body)
            mp = se.packet
        except Exception as e:
            self.logger.error(f"ERROR: parsing service envelope: {str(e)}")
            self.logger.error(f"{body}")
            return

        meshtastic_id = getattr(mp, 'from')
        meshtastic_id = f"{meshtastic_id:08x}"
        to_id = mp.to
        if to_id == BROADCAST_NUM:
            to_id = 'all'
        else:
            to_id = f"{to_id:08x}"

        pn = portnums_pb2.PortNum.Name(mp.decoded.portnum)

        prefix = f"{mp.channel} [{meshtastic_id}->{to_id}] {pn}:"
        if mp.HasField("encrypted") and not mp.HasField("decoded"):
            try:
                self.try_decode(mp)
                pn = portnums_pb2.PortNum.Name(mp.decoded.portnum)
                prefix = f"{mp.channel} [{meshtastic_id}->{to_id}] {pn}:"
            except Exception as e:
                self.logger.warning(f"{prefix} could not be decrypted")
                return

        handler = protocols.get(mp.decoded.portnum)
        if handler is None:
            try:
                if portnums_pb2.PortNum.Name(mp.decoded.portnum) == "ATAK_PLUGIN":
                    tak_packet = atak_pb2.TAKPacket()
                    tak_packet.ParseFromString(mp.decoded.payload)
                    self.protobuf_to_cot(tak_packet, meshtastic_id, to_id, pn, meshtastic_id)
                    self.logger.info(tak_packet)
            except:
                self.logger.error(traceback.format_exc())

            return

        if handler.protobufFactory is None:
            self.logger.debug(f"{prefix} {mp}")
            self.protobuf_to_cot(mp.decoded.payload, meshtastic_id, to_id, pn, meshtastic_id)
            self.logger.info(mp.decoded.payload)
        else:
            try:
                pb = handler.protobufFactory()
                pb.ParseFromString(mp.decoded.payload)
                p = MessageToJson(pb)
                if mp.decoded.portnum == portnums_pb2.PortNum.NODEINFO_APP:
                    self.node_names[getattr(mp, "from")] = pb.short_name
                    prefix = f"{mp.channel} [{meshtastic_id}->{to_id}] {pn}:"
                    self.rabbit_channel.queue_declare(queue=meshtastic_id)
                self.logger.debug(f"{prefix} {p}")
                self.protobuf_to_cot(pb, meshtastic_id, to_id, pn, meshtastic_id)
                self.logger.info(pb)
            except:
                self.logger.error(traceback.format_exc())

    def cot(self, pb, from_id, to_id, portnum, how='m-g', cot_type='a-f-G-U-C', uid=None):
        if not uid and from_id in self.meshtastic_devices and self.meshtastic_devices[from_id]['uid']:
            uid = self.meshtastic_devices[from_id]['uid']
        elif not uid:
            uid = from_id

        now = datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ")
        stale = (datetime.datetime.now() + datetime.timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")

        event = Element('event', {'how': how, 'type': cot_type, 'version': '2.0',
                                  'uid': uid, 'start': now, 'time': now, 'stale': stale})

        SubElement(event, 'point', {'ce': '9999999.0', 'le': '9999999.0',
                                    'hae': str(self.meshtastic_devices[from_id]['last_alt']),
                                    'lat': str(self.meshtastic_devices[from_id]['last_lat']),
                                    'lon': str(self.meshtastic_devices[from_id]['last_lon'])})

        detail = SubElement(event, 'detail')
        if portnum == "TEXT_MESSAGE_APP" or (portnum == "ATAK_PLUGIN" and pb.HasField('chat')):
            return event, detail
        else:
            SubElement(detail, 'takv', {'device': self.meshtastic_devices[from_id]['hw_model'],
                                        'version': self.meshtastic_devices[from_id]['firmware_version'],
                                        'platform': 'Meshtastic', 'os': 'Meshtastic',
                                        'macaddr': self.meshtastic_devices[from_id]['macaddr'],
                                        'meshtastic_id': self.meshtastic_devices[from_id]['meshtastic_id']})
            SubElement(detail, 'contact',
                       {'callsign': self.meshtastic_devices[from_id]['long_name'], 'endpoint': 'MQTT'})
            SubElement(detail, 'uid', {'Droid': self.meshtastic_devices[from_id]['long_name']})
            SubElement(detail, 'precisionlocation', {'altsrc': 'GPS', 'geopointsrc': 'GPS'})
            SubElement(detail, 'status', {'battery': str(self.meshtastic_devices[from_id]['battery'])})
            SubElement(detail, 'track', {'course': '0.0', 'speed': '0.0'})
            SubElement(detail, '__group', {'name': self.meshtastic_devices[from_id]['team'],
                                           'role': self.meshtastic_devices[from_id]['role']})
        return event

    def position(self, pb, from_id, to_id, portnum):
        try:
            if portnum == "MAP_REPORT_APP" and pb.firmware_version != self.meshtastic_devices[from_id]['firmware_version']:
                try:
                    with self.context:
                        eud = self.db.session.execute(self.db.session.query(EUD).filter_by(uid=from_id)).first()[0]
                        eud.version = pb.firmware_version
                        eud.device = pb.hw_model
                        eud.callsign = pb.long_name
                        self.db.session.add(eud)
                        self.db.session.commit()
                        if from_id not in self.meshtastic_devices:
                            self.meshtastic_devices[from_id] = {'hw_model': '', 'long_name': '', 'short_name': '',
                                                                'macaddr': '',
                                                                'firmware_version': '', 'last_lat': "0.0",
                                                                'last_lon': "0.0",
                                                                'battery': 0, 'meshtastic_id': '',
                                                                'voltage': 0, 'uptime': 0, 'last_alt': "9999999.0",
                                                                'course': '0.0',
                                                                'speed': '0.0', 'team': 'Cyan', 'role': 'Team Member',
                                                                'uid': None}

                        self.meshtastic_devices[from_id]['firmware_version'] = pb.firmware_version
                        self.meshtastic_devices[from_id]['hw_model'] = mesh_pb2.HardwareModel.Name(pb.hw_model)
                        self.meshtastic_devices[from_id]['long_name'] = pb.long_name
                        self.meshtastic_devices[from_id]['short_name'] = pb.short_name
                except BaseException as e:
                    self.logger.error("Failed to update {}'s firmware version: {}".format(from_id, e))

            self.meshtastic_devices[from_id]['last_lat'] = pb.latitude_i * .0000001
            self.meshtastic_devices[from_id]['last_lon'] = pb.longitude_i * .0000001
            self.meshtastic_devices[from_id]['last_alt'] = pb.altitude
            if portnum == "POSITION_APP":
                self.meshtastic_devices[from_id]['course'] = pb.ground_track if pb.ground_track else "0.0"
                self.meshtastic_devices[from_id]['speed'] = pb.ground_speed if pb.ground_speed else "0.0"

            return self.cot(pb, from_id, to_id, portnum)
        except BaseException as e:
            self.logger.error("Failed to create CoT: {}".format(str(e)))
            self.logger.error(traceback.format_exc())
            return

    def text_message(self, pb, from_id, to_id, portnum):
        callsign = from_id
        if from_id in self.meshtastic_devices:
            callsign = self.meshtastic_devices[from_id]['long_name']

        chatroom = "All Chat Rooms"
        for meshtastic_device in self.meshtastic_devices:
            meshtastic_device = self.meshtastic_devices[meshtastic_device]
            if meshtastic_device['meshtastic_id'] == to_id:
                chatroom = meshtastic_device['uid']
                break

        if from_id in self.meshtastic_devices and self.meshtastic_devices[from_id]['uid']:
            from_uid = self.meshtastic_devices[from_id]['uid']
        else:
            from_uid = from_id

        message_uid = str(uuid.uuid4())
        event, detail = self.cot(pb, from_uid, chatroom, portnum, how='h-g-i-g-o', cot_type='b-t-f',
                                 uid="GeoChat.{}.{}.{}".format(from_uid, chatroom, message_uid))

        chat = SubElement(detail, '__chat',
                          {'chatroom': chatroom, 'groupOwner': "false", 'id': chatroom,
                           'messageId': message_uid, 'parent': 'RootContactGroup',
                           'senderCallsign': callsign})
        SubElement(chat, 'chatgrp', {'id': chatroom, 'uid0': from_uid, 'uid1': chatroom})
        SubElement(detail, 'link', {'relation': 'p-p', 'type': 'a-f-G-U-C', 'uid': from_uid})
        remarks = SubElement(detail, 'remarks', {'source': 'BAO.F.ATAK.{}'.format(from_uid),
                                                 'time': datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                 'to': chatroom})

        remarks.text = pb.decode('utf-8', 'replace')

        return event

    def node_info(self, pb, from_id, to_id, portnum):
        if portnum == "ATAK_PLUGIN":
            uid = unishox2.decompress(pb.contact.device_callsign, len(pb.contact.device_callsign))
            self.meshtastic_devices[from_id]['uid'] = uid
            self.meshtastic_devices[from_id]['long_name'] = unishox2.decompress(pb.contact.callsign,
                                                                                len(pb.contact.callsign))
            self.meshtastic_devices[from_id]['short_name'] = uid[-4:]
            self.meshtastic_devices[from_id]['battery'] = pb.status.battery
            if pb.group.team != 0:
                self.meshtastic_devices[from_id]['team'] = atak_pb2.Team.Name(pb.group.team)
            if pb.group.role != 0:
                self.meshtastic_devices[from_id]['role'] = atak_pb2.MemberRole.Name(pb.group.role)
        else:
            hw_model = mesh_pb2.HardwareModel.Name(pb.hw_model)
            self.meshtastic_devices[from_id]['hw_model'] = hw_model if hw_model else ""
            self.meshtastic_devices[from_id]['long_name'] = str(pb.long_name) if pb.long_name else ""
            self.meshtastic_devices[from_id]['short_name'] = str(pb.short_name) if pb.short_name else ""
            self.meshtastic_devices[from_id]['macaddr'] = base64.b64encode(pb.macaddr).decode(
                'ascii') if pb.macaddr else ""

        return self.cot(pb, from_id, to_id, portnum)

    def telemetry(self, pb, from_id, to_id, portnum):
        if pb.HasField('device_metrics'):
            self.meshtastic_devices[from_id]['battery'] = pb.device_metrics.battery_level
            self.meshtastic_devices[from_id]['voltage'] = pb.device_metrics.voltage
            self.meshtastic_devices[from_id]['uptime'] = pb.device_metrics.uptime_seconds
        elif pb.HasField('environment_metrics'):
            self.meshtastic_devices[from_id]['temperature'] = pb.environment_metrics.temperature
            self.meshtastic_devices[from_id]['relative_humidity'] = pb.environment_metrics.relative_humidity
            self.meshtastic_devices[from_id]['barometric_pressure'] = pb.environment_metrics.barometric_pressure
            self.meshtastic_devices[from_id]['gas_resistance'] = pb.environment_metrics.gas_resistance
            self.meshtastic_devices[from_id]['voltage'] = pb.environment_metrics.voltage
            self.meshtastic_devices[from_id]['current'] = pb.environment_metrics.current
            self.meshtastic_devices[from_id]['iaq'] = pb.environment_metrics.iaq

    def atak_plugin(self, pb, from_id, to_id, portnum):
        self.node_info(pb, from_id, to_id, portnum)

        if pb.HasField('status'):
            self.meshtastic_devices[from_id]['battery'] = pb.status.battery

        if pb.HasField('pli'):
            self.meshtastic_devices[from_id]['last_lat'] = pb.pli.latitude_i * .0000001
            self.meshtastic_devices[from_id]['last_lon'] = pb.pli.longitude_i * .0000001
            self.meshtastic_devices[from_id]['last_alt'] = pb.pli.altitude
            self.meshtastic_devices[from_id]['course'] = pb.pli.course
            self.meshtastic_devices[from_id]['speed'] = pb.pli.speed
            return self.cot(pb, from_id, to_id, portnum)
        elif pb.HasField('chat'):
            self.logger.debug(
                "Got chat: {} {}->{}: {}".format(unishox2.decompress(pb.chat.to, len(pb.chat.to)), from_id, to_id,
                                                 unishox2.decompress(pb.chat.message, len(pb.chat.message))))

            chatroom = unishox2.decompress(pb.chat.to, len(pb.chat.to))
            message_uid = str(uuid.uuid4())

            from_uid = sender_callsign = from_id
            if from_uid in self.meshtastic_devices:
                from_uid = self.meshtastic_devices[from_id]['uid']
                sender_callsign = self.meshtastic_devices[from_id]['long_name']

            uid = "GeoChat.{}.{}.{}".format(from_uid, chatroom, message_uid)

            event, detail = self.cot(pb, from_uid, to_id, portnum, how='h-g-i-g-o', cot_type='b-t-f', uid=uid)

            chat = SubElement(detail, '__chat',
                              {'chatroom': 'All Chat Rooms', 'groupOwner': "false", 'id': chatroom,
                               'messageId': message_uid, 'parent': 'RootContactGroup',
                               'senderCallsign': sender_callsign})
            SubElement(chat, 'chatgrp', {'id': chatroom, 'uid0': from_uid, 'uid1': chatroom})
            SubElement(detail, 'link', {'relation': 'p-p', 'type': 'a-f-G-U-C', 'uid': from_uid})
            remarks = SubElement(detail, 'remarks', {'source': 'BAO.F.ATAK.{}'.format(from_uid),
                                                     'time': datetime.datetime.now().strftime("%Y-%m-%dT%H:%M:%SZ"),
                                                     'to': chatroom})
            remarks.text = unishox2.decompress(pb.chat.message, len(pb.chat.message))

            return event

    def protobuf_to_cot(self, pb, from_id, to_id, portnum, meshtastic_id):
        self.logger.debug(from_id + " " + to_id + " " + portnum + " " + meshtastic_id)
        event = None

        if from_id not in self.meshtastic_devices:
            self.meshtastic_devices[from_id] = {'hw_model': '', 'long_name': '', 'short_name': '', 'macaddr': '',
                                                'firmware_version': '', 'last_lat': "0.0", 'last_lon': "0.0",
                                                'battery': 0, 'meshtastic_id': meshtastic_id,
                                                'voltage': 0, 'uptime': 0, 'last_alt': "9999999.0", 'course': '0.0',
                                                'speed': '0.0', 'team': 'Cyan', 'role': 'Team Member', 'uid': None}

        if portnum == "MAP_REPORT_APP" or (portnum == "POSITION_APP" and pb.latitude_i):
            event = self.position(pb, from_id, to_id, portnum)
        elif portnum == "NODEINFO_APP":
            event = self.node_info(pb, from_id, to_id, portnum)
        elif portnum == "TEXT_MESSAGE_APP":
            event = self.text_message(pb, from_id, to_id, portnum)
        elif portnum == "ATAK_PLUGIN":
            event = self.atak_plugin(pb, from_id, to_id, portnum)
        elif portnum == "TELEMETRY_APP":
            self.telemetry(pb, from_id, to_id, portnum)

        try:
            if event:
                uid = self.meshtastic_devices[from_id]['uid']
                if not uid:
                    uid = from_id
                message = json.dumps({'uid': uid, 'cot': tostring(event).decode('utf-8')})
                if portnum == "TEXT_MESSAGE_APP":
                    try:
                        if to_id == "all":
                            self.rabbit_channel.basic_publish(exchange='chatrooms', routing_key='All Chat Rooms',
                                                              body=message,
                                                              properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))
                        else:
                            for meshtastic_device in self.meshtastic_devices:
                                meshtastic_device = self.meshtastic_devices[meshtastic_device]
                                if meshtastic_device['meshtastic_id'] == to_id:
                                    self.rabbit_channel.basic_publish(exchange='dms',
                                                                      routing_key=meshtastic_device['uid'],
                                                                      body=message,
                                                                      properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))
                    except BaseException as e:
                        self.logger.error("Failed to publish chat message: {}".format(e))
                elif portnum == "ATAK_PLUGIN" and pb.HasField('chat'):
                    try:
                        to = unishox2.decompress(pb.chat.to, len(pb.chat.to))
                        if to in self.meshtastic_devices:
                            self.rabbit_channel.basic_publish(exchange='dms', routing_key=to, body=message)
                        else:
                            self.rabbit_channel.basic_publish(exchange='chatrooms',
                                                              routing_key=to,
                                                              body=message,
                                                              properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))
                    except BaseException as e:
                        self.logger.error("Failed to publish chat message to {}: {}".format(
                            unishox2.decompress(pb.chat.to, len(pb.chat.to)), e))
                        self.logger.error(traceback.format_exc())
                else:
                    self.rabbit_channel.basic_publish(exchange='cot_controller', routing_key='', body=message,
                                                      properties=pika.BasicProperties(expiration=self.context.app.config.get("OTS_RABBITMQ_TTL")))
        except BaseException as e:
            self.logger.error(str(e))
            self.logger.error(traceback.format_exc())
