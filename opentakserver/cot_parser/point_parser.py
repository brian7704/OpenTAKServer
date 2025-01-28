import time
import traceback

import unishox2

from meshtastic import mesh_pb2, portnums_pb2
from sqlalchemy import update, insert

from opentakserver.extensions import socketio
from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.models.EUD import EUD
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.Point import Point
from opentakserver.proto import atak_pb2


def parse_point(event, uid, cot_id, online_euds, context, db, logger):
    # hae = Height above the WGS ellipsoid in meters
    # ce = Circular 1-sigma or a circular area about the location in meters
    # le = Linear 1-sigma error or an altitude range about the location in meters
    point = event.find('point')
    if point and not point.attrs['lat'].startswith('999'):
        p = Point()
        p.uid = event.attrs['uid']
        p.device_uid = uid
        p.ce = point.attrs['ce']
        p.hae = point.attrs['hae']
        p.le = point.attrs['le']
        p.latitude = float(point.attrs['lat'])
        p.longitude = float(point.attrs['lon'])
        p.timestamp = datetime_from_iso8601_string(event.attrs['time'])
        p.cot_id = cot_id

        # We only really care about the rest of the data if there's a valid lat/lon
        if p.latitude == 0 and p.longitude == 0:
            return None

        track = event.find('track')
        if track:
            if 'course' in track.attrs and track.attrs['course'] != "9999999.0":
                p.course = track.attrs['course']
            else:
                p.course = 0

            if 'speed' in track.attrs and track.attrs['speed'] != "9999999.0":
                p.speed = track.attrs['speed']
            else:
                p.speed = 0

        # For TAK ICU and OpenTAK ICU CoT's with bearing from the compass
        sensor = event.find('sensor')
        if sensor:
            if 'azimuth' in sensor.attrs:
                p.azimuth = sensor.attrs['azimuth']
            # Camera's field of view
            if 'fov' in sensor.attrs:
                p.fov = sensor.attrs['fov']

        precision_location = event.find('precisionlocation')
        if precision_location and 'geolocationsrc' in precision_location.attrs:
            p.location_source = precision_location.attrs['geolocationsrc']
        elif precision_location and 'altsrc' in precision_location.attrs:
            p.location_source = precision_location.attrs['altsrc']
        elif event.attrs['how'] == 'm-g':
            p.location_source = 'GPS'

        status = event.find('status')
        if status:
            if 'battery' in status.attrs:
                p.battery = status.attrs['battery']

        with context:
            res = db.session.execute(insert(Point).values(
                uid=p.uid, device_uid=p.device_uid, ce=p.ce, hae=p.hae, le=p.le, latitude=p.latitude,
                longitude=p.longitude, timestamp=p.timestamp, cot_id=cot_id, location_source=p.location_source,
                course=p.course, speed=p.speed, battery=p.battery, fov=p.fov, azimuth=p.azimuth)
            )

            # iTAK sucks. Instead of sending mission CoTs with a <dest mission="mission_name"> tag, it sends a normal CoT and
            # makes a POST to /Marti/api/missions/mission_name/contents. The POST happens faster than the CoT can be received and parsed,
            # so we're left with a row in the mission_uids table without most of the details that come from the CoT. Fortunately
            # the mission_uids.uid field corresponds to the CoT's event UID, so the row in mission_uids can be updated here.
            usericon = event.find('usericon')
            color = event.find('color')
            contact = event.find('contact')

            iconset_path = None
            if usericon and 'iconsetpath' in usericon.attrs:
                iconset_path = usericon.attrs['iconsetpath']
            elif usericon and 'iconsetPath' in usericon.attrs:
                iconset_path = usericon.attrs['iconsetPath']

            cot_color = None
            if color and 'argb' in color.attrs:
                cot_color = color.attrs['argb']
            if color and 'value' in color.attrs:
                cot_color = color.attrs['value']

            callsign = None
            if contact and 'callsign' in contact.attrs:
                callsign = contact.attrs['callsign']

            db.session.execute(update(MissionUID).where(MissionUID.uid == event.attrs['uid']).values(
                cot_type=event.attrs['type'], latitude=p.latitude, longitude=p.longitude, iconset_path=iconset_path,
                color=cot_color, callsign=callsign
            ))

            db.session.commit()
            # Get the point from the DB with its related CoT
            p = db.session.execute(
                db.session.query(Point).filter(Point.id == res.inserted_primary_key[0])).first()[0]

            # This CoT is a position update for an EUD. Send it to socketio clients so it can be seen on the UI map
            # OpenTAK ICU position updates don't include the <takv> tag, but we still want to send the updated position
            # to the UI's map
            if event.find('takv') or event.find("__video"):
                socketio.emit('point', p.to_json(), namespace='/socket.io')

            now = time.time()
            if uid in online_euds:
                can_transmit = (now - online_euds[uid]['last_meshtastic_publish'] >= context.app.config.get(
                    "OTS_MESHTASTIC_PUBLISH_INTERVAL"))
            else:
                can_transmit = False

            if context.app.config.get("OTS_ENABLE_MESHTASTIC") and can_transmit:
                logger.debug("publishing position to mesh")
                try:
                    online_euds[uid]['last_meshtastic_publish'] = now
                    eud = db.session.execute(db.session.query(EUD).filter_by(uid=uid)).first()[0]

                    if eud.platform != "Meshtastic":
                        mesh_user = mesh_pb2.User()
                        setattr(mesh_user, "id", eud.uid)
                        mesh_user.hw_model = mesh_pb2.HardwareModel.PRIVATE_HW
                        mesh_user.short_name = p.device_uid[-4:]

                        contact = event.find('contact')
                        if contact:
                            mesh_user.long_name = contact.attrs['callsign']

                        position = mesh_pb2.Position()
                        position.latitude_i = int(p.latitude / .0000001)
                        position.longitude_i = int(p.longitude / .0000001)
                        position.altitude = int(p.hae)
                        position.time = int(time.mktime(p.timestamp.timetuple()))
                        position.ground_track = int(p.course) if p.course else 0
                        position.ground_speed = int(p.speed) if p.speed and p.speed >= 0 else 0
                        position.seq_number = 1
                        position.precision_bits = 32

                        node_info = mesh_pb2.NodeInfo()
                        node_info.user.CopyFrom(mesh_user)
                        node_info.position.CopyFrom(position)

                        encoded_message = mesh_pb2.Data()
                        encoded_message.portnum = portnums_pb2.POSITION_APP
                        encoded_message.payload = position.SerializeToString()

                        publish_to_meshtastic(get_protobuf(encoded_message, uid=p.device_uid))

                        tak_packet = atak_pb2.TAKPacket()
                        tak_packet.is_compressed = True
                        tak_packet.contact.device_callsign, size = unishox2.compress(eud.uid)
                        tak_packet.contact.callsign, size = unishox2.compress(eud.callsign)
                        tak_packet.group.team = eud.team.name.replace(" ", "_") if eud.team else "Cyan"
                        tak_packet.group.role = eud.team_role.replace(" ", "") if eud.team_role else "TeamMember"
                        tak_packet.status.battery = int(p.battery) if p.battery else 0
                        tak_packet.pli.latitude_i = int(p.latitude / .0000001)
                        tak_packet.pli.longitude_i = int(p.longitude / .0000001)
                        tak_packet.pli.altitude = int(p.hae) if p.hae else 0
                        tak_packet.pli.speed = int(p.speed) if p.speed else 0
                        tak_packet.pli.course = int(p.course) if p.course else 0

                        encoded_message = mesh_pb2.Data()
                        encoded_message.portnum = portnums_pb2.ATAK_PLUGIN
                        encoded_message.payload = tak_packet.SerializeToString()

                        publish_to_meshtastic(get_protobuf(encoded_message, uid=eud.uid))
                except BaseException as e:
                    logger.error(f"Failed to send publish message to mesh: {e}")
                    logger.debug(traceback.format_exc())

            return res.inserted_primary_key[0]
