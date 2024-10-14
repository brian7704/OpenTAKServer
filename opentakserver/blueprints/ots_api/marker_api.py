import traceback
from datetime import timedelta
import json
from uuid import UUID, uuid4

import bleach
import pika
from flask import Blueprint, request, jsonify, current_app as app
from flask_security import auth_required, current_user
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
import xml.etree.ElementTree as ET

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.extensions import db, logger, socketio
from opentakserver.functions import *
from opentakserver.models.CoT import CoT
from opentakserver.models.Marker import Marker
from opentakserver.models.Point import Point

marker_api_blueprint = Blueprint('marker_api_blueprint', __name__)


@marker_api_blueprint.route('/api/markers', methods=['GET'])
@auth_required()
def get_markers():
    query = db.session.query(Marker)
    query = search(query, Marker, 'uid')
    query = search(query, Marker, 'affiliation')
    query = search(query, Marker, 'callsign')

    return paginate(query)


@marker_api_blueprint.route('/api/markers', methods=['POST'])
@auth_required()
def add_marker():
    marker = Marker()
    point = Point()

    try:
        if 'latitude' not in request.json.keys() or 'longitude' not in request.json.keys():
            return jsonify({'success': False, 'error': 'Please provide a latitude and longitude'}), 400
        elif float(request.json['latitude']) < -90 or float(request.json['latitude']) > 90:
            return jsonify({'success': False, 'error': f"Invalid latitude: {request.json['latitude']}"}), 400
        elif float(request.json['longitude']) < -180 or float(request.json['longitude']) > 180:
            return jsonify({'success': False, 'error': f"Invalid longitude: {request.json['longitude']}"}), 400
    except BaseException as e:
        logger.error(f"Failed to parse lat/lon: {e}")
        return jsonify({'success': False, 'error': f"Failed to parse lat/lon: {e}"}), 400

    if 'uid' not in request.json.keys():
        return jsonify({'success': False, 'error': 'Please provide a UID'}), 400
    elif 'name' not in request.json.keys():
        return jsonify({'success': False, 'error': 'Please provide a name'}), 400

    try:
        UUID(request.json['uid'], version=4)
        marker.uid = request.json['uid']
    except ValueError:
        return jsonify({'success': False, 'error': "Invalid UID. UIDs need to be in UUID4 format"}), 400

    cot_type = request.json['type'] if 'type' in request.json.keys() else 'a-u-G'

    marker.affiliation = get_affiliation(cot_type)
    marker.battle_dimension = get_battle_dimension(cot_type)
    marker.mil_std_2525c = cot_type_to_2525c(cot_type)

    if not marker.affiliation or not marker.battle_dimension:
        return jsonify({'success': False, 'error': f"Invalid type: {cot_type}"}), 400

    if 'name' in request.json.keys():
        marker.callsign = bleach.clean(request.json['name'])

    try:
        point.uid = str(uuid4())
        point.device_uid = app.config.get('OTS_NODE_ID')
        point.location_source = bleach.clean(
            request.json['location_source']) if 'location_source' in request.json.keys() else ""
        point.latitude = float(request.json['latitude'])
        point.longitude = float(request.json['longitude'])
        point.course = float(request.json['course']) if 'course' in request.json.keys() else 0
        point.azimuth = float(request.json['azimuth']) if 'azimuth' in request.json.keys() else 0
        point.speed = float(request.json['speed']) if 'speed' in request.json.keys() else 0
        point.battery = float(request.json['battery']) if 'battery' in request.json.keys() else None
        point.fov = float(request.json['fov']) if 'fov' in request.json.keys() else None
        point.ce = float(request.json['ce']) if 'ce' in request.json.keys() else 9999999.0
        point.hae = float(request.json['hae']) if 'hae' in request.json.keys() else 9999999.0
        point.le = float(request.json['le']) if 'le' in request.json.keys() else 9999999.0
        point.timestamp = datetime.now()

        with app.app_context():
            event = ET.Element("event")
            event.set("type", cot_type)
            event.set("version", "2.0")
            event.set("how", "m-g")
            event.set("uid", marker.uid)
            event.set("time", iso8601_string_from_datetime(point.timestamp))
            event.set("start", iso8601_string_from_datetime(point.timestamp))
            event.set("stale", iso8601_string_from_datetime(point.timestamp + timedelta(days=1)))

            cot_point = ET.SubElement(event, "point")
            cot_point.set("ce", str(point.ce))
            cot_point.set("hae", str(point.hae))
            cot_point.set("le", str(point.le))
            cot_point.set("lat", str(point.latitude))
            cot_point.set("lon", str(point.longitude))

            detail = ET.SubElement(event, "detail")
            detail.set("uid", marker.uid)

            contact = ET.SubElement(detail, "contact")
            contact.set("callsign", marker.callsign)

            track = ET.SubElement(detail, "track")
            track.set("course", str(point.course))
            track.set("speed", str(point.speed))

            if point.azimuth or point.fov:
                sensor = ET.SubElement(detail, "sensor")
                sensor.set("azimuth", str(point.azimuth))
                sensor.set("fov", str(point.fov))
                sensor.set("fovBlue", "1.0")
                sensor.set("fovGreen", "1.0")
                sensor.set("fovRed", "1.0")
                sensor.set("range", "100.0")

            rabbit_connection = pika.BlockingConnection(
                pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
            channel = rabbit_connection.channel()
            channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
                {'cot': ET.tostring(event).decode('utf-8'), 'uid': app.config['OTS_NODE_ID']}),
                                  properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
            channel.close()
            rabbit_connection.close()

            cot = db.session.execute(insert(CoT).values(
                how="m-g", type=cot_type, timestamp=point.timestamp, xml=ET.tostring(event), start=point.timestamp,
                stale=point.timestamp + timedelta(days=1), sender_callsign=current_user.username
            ))
            db.session.commit()
            marker.cot_id = cot.inserted_primary_key[0]

            p = db.session.execute(insert(Point).values(
                uid=point.uid, device_uid=point.device_uid, ce=point.ce, hae=point.hae, le=point.le,
                latitude=point.latitude,
                longitude=point.longitude, timestamp=point.timestamp, location_source=point.location_source,
                course=point.course, speed=point.speed, battery=point.battery, fov=point.fov, azimuth=point.azimuth,
                cot_id=cot.inserted_primary_key[0]
            ))
            # Commit here to get the point's auto increment primary key
            db.session.commit()

            marker.point_id = p.inserted_primary_key[0]
            try:
                db.session.add(marker)
                db.session.commit()
            except IntegrityError:
                db.session.rollback()
                db.session.execute(update(Marker).where(Marker.uid == marker.uid).values(
                    point_id=marker.point_id,
                    cot_id=marker.cot_id,
                    **marker.serialize()
                ))
                db.session.commit()

            # Get the marker with its associated point and cot data
            marker = db.session.execute(db.session.query(Marker).filter_by(uid=marker.uid)).first()[0]
            socketio.emit('marker', marker.to_json(), namespace='/socket.io')

            return jsonify({'success': True})

    except BaseException as e:
        logger.error(f"Failed to parse data: {e}")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': f"Failed to parse data: {e}"}), 400


@marker_api_blueprint.route('/api/markers', methods=['DELETE'])
@auth_required()
def delete_marker():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'success': False, 'error': 'Please provide the UID of the marker to delete'}), 400

    with app.app_context():
        query = db.session.query(Marker)
        query = search(query, Marker, 'uid')
        marker = db.session.execute(query).first()
        if not marker:
            return jsonify({'success': False, 'error': 'Unknown UID'}), 404

        marker = marker[0]
        now = datetime.now()
        event = ET.Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-d-d', 'version': '2.0',
                                     'uid': marker.uid, 'start': iso8601_string_from_datetime(now),
                                     'time': iso8601_string_from_datetime(now),
                                     'stale': iso8601_string_from_datetime(now + timedelta(minutes=10))})
        ET.SubElement(event, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                       'lon': '0'})
        detail = ET.SubElement(event, 'detail')
        ET.SubElement(detail, 'link', {'relation': 'p-p', 'uid': marker.uid, 'type': marker.cot.type})
        ET.SubElement(detail, '_flow-tags_', {'TAK-Server-f1a8159ef7804f7a8a32d8efc4b773d0': iso8601_string_from_datetime(now)})

        rabbit_connection = pika.BlockingConnection(
            pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
        channel = rabbit_connection.channel()
        channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
            {'cot': ET.tostring(event).decode('utf-8'), 'uid': app.config['OTS_NODE_ID']}),
                              properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
        channel.close()
        rabbit_connection.close()

        db.session.delete(marker)
        db.session.commit()

        return jsonify({'success': True})
