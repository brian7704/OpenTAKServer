import base64
import json
import os
import traceback

import bleach
import pika
import sqlalchemy
from meshtastic import mesh_pb2, portnums_pb2
from sqlalchemy import update

from opentakserver.extensions import socketio
from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.EUD import EUD
from opentakserver.models.Team import Team


def parse_device_info(uid, soup, event, online_euds, online_callsigns, context, db, logger, rabbit_channel):
    link = event.find('link')
    fileshare = event.find('fileshare')

    # Don't parse server generated messages
    with context:
        if uid == context.app.config.get("OTS_NODE_ID"):
            return

    callsign = None
    phone_number = None

    # EUDs running the Meshtastic and dmrcot plugins can relay messages from their RF networks to the server
    # so we want to use the UID of the "off grid" EUD, not the relay EUD
    takv = event.find('takv')
    if takv:
        uid = event.attrs.get('uid')

    # Only assume it's an EUD if it's got a <takv> tag
    if takv and uid and uid not in online_euds and not uid.endswith('ping'):
        logger.info("Got PLI " + uid)
        device = takv.attrs['device'] if 'device' in takv.attrs else ""
        operating_system = takv.attrs['os'] if 'os' in takv.attrs else ""
        platform = takv.attrs['platform'] if 'platform' in takv.attrs else ""
        version = takv.attrs['version'] if 'version' in takv.attrs else ""

        contact = event.find('contact')
        if contact:
            if 'callsign' in contact.attrs:
                callsign = contact.attrs['callsign']

                if uid not in online_euds:
                    online_euds[uid] = {'cot': str(soup), 'callsign': callsign, 'last_meshtastic_publish': 0}

                if callsign not in online_callsigns:
                    online_callsigns[callsign] = {'uid': uid, 'cot': soup, 'last_meshtastic_publish': 0}

                # Declare a RabbitMQ Queue for this uid and join the 'dms' and 'cot' exchanges
                if rabbit_channel and rabbit_channel.is_open and platform != "OpenTAK ICU" and platform != "Meshtastic" and platform != "DMRCOT":
                    rabbit_channel.queue_bind(exchange='dms', queue=uid, routing_key=uid)
                    rabbit_channel.queue_bind(exchange='chatrooms', queue=uid,
                                                   routing_key='All Chat Rooms')

                    for eud in online_euds:
                        rabbit_channel.basic_publish(exchange='dms',
                                                          routing_key=uid,
                                                          body=json.dumps(
                                                              {'cot': str(online_euds[eud]['cot']),
                                                               'uid': None}),
                                                          properties=pika.BasicProperties(
                                                              expiration=context.app.config.get(
                                                                  "OTS_RABBITMQ_TTL")))

            if 'phone' in contact.attrs and contact.attrs['phone']:
                phone_number = contact.attrs['phone']

        with context:
            group = event.find('__group')
            team = Team()

            if group:
                # Declare an exchange for each group and bind the callsign's queue
                if rabbit_channel.is_open and group.attrs[
                    'name'] not in exchanges and platform != "Meshtastic" and platform != "DMRCOT":
                    logger.debug("Declaring exchange {}".format(group.attrs['name']))
                    rabbit_channel.exchange_declare(exchange=group.attrs['name'])
                    rabbit_channel.queue_bind(queue=uid, exchange='chatrooms',
                                                   routing_key=group.attrs['name'])
                    exchanges.append(group.attrs['name'])

                team.name = bleach.clean(group.attrs['name'])

                try:
                    chatroom = db.session.execute(db.session.query(Chatroom)
                                                       .filter(Chatroom.name == team.name)).first()[0]
                    team.chatroom_id = chatroom.id
                except TypeError:
                    chatroom = None

                try:
                    db.session.add(team)
                    db.session.commit()
                except sqlalchemy.exc.IntegrityError:
                    db.session.rollback()
                    team = db.session.execute(db.session.query(Team)
                                                   .filter(Team.name == group.attrs['name'])).first()[0]
                    if not team.chatroom_id and chatroom:
                        team.chatroom_id = chatroom.id
                        db.session.execute(update(Team).filter(Team.name).values(chatroom_id=chatroom.id))

            try:
                eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()[0]
            except:
                eud = EUD()

            eud.uid = uid
            if callsign:
                eud.callsign = callsign
            if device:
                eud.device = device

            eud.os = operating_system
            eud.platform = platform
            eud.version = version
            eud.phone_number = phone_number
            eud.last_event_time = datetime_from_iso8601_string(event.attrs['start'])
            eud.last_status = 'Connected'

            # Set a Meshtastic ID for TAK EUDs to be identified by in the Meshtastic network
            if not eud.meshtastic_id and eud.platform != "Meshtastic":
                meshtastic_id = '{:x}'.format(int.from_bytes(os.urandom(4), 'big'))
                while len(meshtastic_id) < 8:
                    meshtastic_id = "0" + meshtastic_id
                eud.meshtastic_id = int(meshtastic_id, 16)
            elif not eud.meshtastic_id and eud.platform == "Meshtastic":
                try:
                    eud.meshtastic_id = int(takv.attrs['meshtastic_id'], 16)
                except:
                    meshtastic_id = '{:x}'.format(int.from_bytes(os.urandom(4), 'big'))
                    while len(meshtastic_id) < 8:
                        meshtastic_id = "0" + meshtastic_id
                    eud.meshtastic_id = int(meshtastic_id, 16)

            # Get the Meshtastic device's mac address or generate a random one for TAK EUDs
            if takv and 'macaddr' in takv.attrs:
                eud.meshtastic_macaddr = takv.attrs['macaddr']
            else:
                eud.meshtastic_macaddr = base64.b64encode(os.urandom(6)).decode('ascii')

            if group:
                eud.team_id = team.id
                eud.team_role = bleach.clean(group.attrs['role'])

            try:
                db.session.add(eud)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError:
                logger.info("Already have this eud: " + eud.callsign)
                logger.info(traceback.format_exc())
                db.session.rollback()
                db.session.execute(update(EUD).where(EUD.uid == eud.uid).values(**eud.serialize()))
                db.session.commit()

            if context.app.config.get("OTS_ENABLE_MESHTASTIC") and eud.platform != "Meshtastic":
                user_info = mesh_pb2.User()
                setattr(user_info, "id", "!{:x}".format(eud.meshtastic_id))
                user_info.long_name = eud.callsign
                # Use the last 4 characters of the UID as the short name
                user_info.short_name = eud.uid[-4:]
                user_info.hw_model = mesh_pb2.HardwareModel.PRIVATE_HW

                node_info = mesh_pb2.NodeInfo()
                node_info.user.CopyFrom(user_info)

                encoded_message = mesh_pb2.Data()
                encoded_message.portnum = portnums_pb2.NODEINFO_APP
                user_info_bytes = user_info.SerializeToString()
                encoded_message.payload = user_info_bytes

                publish_to_meshtastic(get_protobuf(encoded_message, from_id=eud.meshtastic_id))

            socketio.emit('eud', eud.to_json(), namespace='/socket.io')

    # Update the CoT stored in memory which contains the new stale time
    elif takv:
        online_euds[uid]['cot'] = str(soup)
