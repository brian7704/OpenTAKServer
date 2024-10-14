from datetime import timedelta
import json
from uuid import UUID

import pika
import sqlalchemy.exc
from flask import Blueprint, request, jsonify, current_app as app
from flask_security import auth_required
from sqlalchemy import insert, update
from xml.etree.ElementTree import tostring, Element, SubElement

from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.extensions import db, logger, socketio
from opentakserver.forms.casevac_form import CasEvacForm
from opentakserver.forms.zmist_form import ZmistForm
from opentakserver.functions import *
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.Point import Point
from opentakserver.models.ZMIST import ZMIST

casevac_api_blueprint = Blueprint('casevac_api_blueprint', __name__)


@casevac_api_blueprint.route("/api/casevac", methods=['GET'])
@auth_required()
def query_casevac():
    query = db.session.query(CasEvac)

    query = search(query, EUD, 'callsign')
    query = search(query, CasEvac, 'sender_uid')
    query = search(query, CasEvac, 'uid')

    return paginate(query)


@casevac_api_blueprint.route("/api/casevac", methods=['POST'])
@auth_required()
def add_casevac():
    form = CasEvacForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    zmist = None
    if 'zmist' in request.json.keys():
        logger.warning(request.json['zmist'])
        zmist_form = ZmistForm(formdata=ImmutableMultiDict(request.json['zmist']))
        if not zmist_form.validate():
            return jsonify({'success': False, 'errors': form.errors}), 400
        zmist = ZMIST()
        zmist.from_wtform(zmist_form)

    casevac = CasEvac()
    casevac.from_wtforms(form)
    casevac.sender_uid = app.config.get("OTS_NODE_ID")
    if zmist:
        casevac.zmist = zmist

    point = Point()
    point.from_wtform(form)
    point.device_uid = app.config.get("OTS_NODE_ID")

    casevac.point = point

    cot = CoT()
    cot.how = "h-g-i-g-o"
    cot.type = "b-r-f-h-c"
    cot.sender_uid = app.config.get("OTS_NODE_ID")
    cot.sender_callsign = app.config.get("OTS_NODE_ID")
    cot.timestamp = point.timestamp
    cot.start = point.timestamp
    cot.stale = point.timestamp + timedelta(days=365)
    cot.xml = tostring(casevac.to_cot()).decode('utf-8')

    cot_result = db.session.execute(insert(CoT).values(**cot.serialize()))
    db.session.commit()

    cot_pk = cot_result.inserted_primary_key[0]
    point.cot_id = cot_pk
    casevac.cot_id = cot_pk

    point_result = db.session.execute(insert(Point).values(**point.serialize()))
    db.session.commit()
    point_pk = point_result.inserted_primary_key[0]

    casevac.point_id = point_pk

    try:
        db.session.add(casevac)

        if zmist:
            zmist.casevac_uid = casevac.uid
            db.session.add(zmist)
        db.session.commit()
        logger.debug(f"Saved new CasEvac {casevac.uid}")

    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        db.session.execute(update(CasEvac).where(CasEvac.uid == casevac.uid).values(
            point_id=point_pk,
            cot_id=casevac.cot_id,
            **casevac.serialize()
        ))
        db.session.commit()
        logger.debug(f"Updated CasEvac {casevac.uid}")

    rabbit_connection = pika.BlockingConnection(
        pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange='cot', routing_key='', body=json.dumps({'cot': cot.xml, 'uid': app.config['OTS_NODE_ID']}),
                          properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
    channel.close()
    rabbit_connection.close()

    casevac.zmist = zmist
    socketio.emit('casevac', casevac.to_json(), namespace="/socket.io")

    return jsonify({'success': True}), 200


@casevac_api_blueprint.route("/api/casevac", methods=['DELETE'])
@auth_required()
def delete_casevac():
    uid = request.args.get('uid')
    if not uid:
        return jsonify({'success': False, 'error': 'Please specify a UID'}), 400

    try:
        UUID(uid, version=4)
    except ValueError:
        return jsonify({'success': False, 'error': f"Invalid UID: {uid}"}), 400

    query = db.session.query(CasEvac)
    query = search(query, CasEvac, 'uid')
    casevac = db.session.execute(query).first()
    if not casevac:
        return jsonify({'success': False, 'error': f'Unknown UID: {uid}'}), 404

    casevac = casevac[0]

    now = datetime.now()
    event = Element('event', {'how': 'h-g-i-g-o', 'type': 't-x-d-d', 'version': '2.0',
                              'uid': casevac.uid, 'start': iso8601_string_from_datetime(now),
                              'time': iso8601_string_from_datetime(now),
                              'stale': iso8601_string_from_datetime(now)})
    SubElement(event, 'point', {'ce': '9999999', 'le': '9999999', 'hae': '0', 'lat': '0',
                                'lon': '0'})
    detail = SubElement(event, 'detail')
    SubElement(detail, 'link', {'relation': 'p-p', 'uid': casevac.uid, 'type': casevac.cot.type})
    SubElement(detail, '_flow-tags_',
               {'TAK-Server-f1a8159ef7804f7a8a32d8efc4b773d0': iso8601_string_from_datetime(now)})

    rabbit_connection = pika.BlockingConnection(
        pika.ConnectionParameters(app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")))
    channel = rabbit_connection.channel()
    channel.basic_publish(exchange='cot', routing_key='', body=json.dumps(
        {'cot': tostring(event).decode('utf-8'), 'uid': app.config['OTS_NODE_ID']}),
                          properties=pika.BasicProperties(expiration=app.config.get("OTS_RABBITMQ_TTL")))
    channel.close()
    rabbit_connection.close()

    db.session.delete(casevac)
    db.session.commit()

    return jsonify({'success': True})
