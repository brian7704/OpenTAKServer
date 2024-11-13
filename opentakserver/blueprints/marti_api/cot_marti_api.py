import datetime
from xml.etree.ElementTree import Element, fromstring, tostring

import sqlalchemy.orm
from flask import Blueprint, request, jsonify

from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.extensions import db, logger
from opentakserver.models.CoT import CoT

cot_marti_api = Blueprint('cot_api', __name__)

"""
Right now OpenTAKServer only uses a few of these for Data Sync. The rest were added as place holders 
based on the API docs until I find an example of them actually being used by a TAK client 
"""


@cot_marti_api.route('/Marti/api/cot')
def get_cots():
    logger.info(request.headers)
    logger.info(request.args)

    return '', 200


@cot_marti_api.route('/Marti/api/cot/xml/<uid>')
def get_cot(uid):
    logger.info(request.headers)
    logger.info(request.args)

    cot = db.session.execute(db.session.query(CoT).filter_by(uid=uid)).first()
    if not cot:
        return jsonify({'success': False, 'error': f"No CoT found for UID {uid}"}), 404

    return cot[0].xml


@cot_marti_api.route('/Marti/api/cot/xml/<uid>/all')
def get_all_cot(uid):
    logger.info(request.headers)
    logger.info(request.args)

    sec_ago = request.args.get('secago')
    start = request.args.get('start')
    end = request.args.get('end')

    query = db.session.query(CoT).filter_by(uid=uid)
    if sec_ago:
        query = query.filter(CoT.start >= datetime.timedelta(seconds=sec_ago))
    if start:
        query = query.filter(CoT.start >= datetime_from_iso8601_string(start))
    if end:
        query = query.filter(CoT.stale <= datetime_from_iso8601_string(end))

    cots = db.session.execute(query)

    events = Element("events")
    for cot in cots:
        events.append(fromstring(cot[0].xml))

    return tostring(events).decode('utf-8'), 200


@cot_marti_api.route('/Marti/api/cot/sa')
def get_cot_by_time_and_bbox():
    logger.info(request.headers)
    logger.info(request.args)

    start = request.args.get('start')
    end = request.args.get('end')
    left = request.args.get('left')
    bottom = request.args.get('bottom')
    right = request.args.get('right')
    top = request.args.get('top')

    return '', 200
