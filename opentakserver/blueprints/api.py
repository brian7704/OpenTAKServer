import datetime

import bleach
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import auth_required
from extensions import logger, db

from opentakserver.models.Alert import Alert
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.CoT import CoT
from opentakserver.models.EUD import EUD
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.point import Point

api_blueprint = Blueprint('api_blueprint', __name__)


def search(query, model, field):
    arg = request.args.get(field)
    if arg:
        arg = bleach.clean(arg)
        return query.where(getattr(model, field) == arg)
    return query


@api_blueprint.route('/api/cot', methods=['GET'])
def query_cot():
    logger.info(request.args)
    query = db.session.query(CoT)
    query = search(query, CoT, 'how')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'type')
    query = search(query, CoT, 'sender_callsign')
    query = search(query, CoT, 'sender_uid')

    rows = db.session.execute(query).scalars()

    return jsonify([row.serialize() for row in rows])


@api_blueprint.route("/api/eud", methods=['GET'])
def query_euds():
    query = db.session.query(EUD)

    query = search(query, EUD, 'uid')
    query = search(query, EUD, 'callsign')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/alert", methods=['GET'])
def query_alerts():
    query = (db.session.query(Alert, CoT, EUD, Point)
             .join(CoT, CoT.id == Alert.cot_id)
             .join(EUD, EUD.uid == Alert.sender_uid)
             .join(Point, Point.id == Alert.point_id))

    query = search(query, Alert, 'uid')
    query = search(query, Alert, 'sender_uid')
    query = search(query, Alert, 'alert_type')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/point", methods=['GET'])
def query_points():
    query = (db.session.query(Point, CoT, EUD)
             .join(CoT, CoT.id == Point.cot_id)
             .join(EUD, EUD.uid == Point.device_uid))

    query = search(query, EUD, 'uid')
    query = search(query, EUD, 'callsign')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)


@api_blueprint.route("/api/casevac", methods=['GET'])
def query_casevac():
    query = (db.session.query(CasEvac, CoT, EUD, Point)
             .join(CoT, CoT.id == CasEvac.cot_id)
             .join(EUD, EUD.uid == CasEvac.sender_uid)
             .join(Point, Point.id == CasEvac.point_id))

    query = search(query, EUD, 'callsign')
    query = search(query, CasEvac, 'sender_uid')
    query = search(query, CasEvac, 'uid')

    rows = db.session.execute(query)

    result = []
    if rows:
        for row in rows:
            for r in row:
                result.append(r.serialize())

    return jsonify(result)
