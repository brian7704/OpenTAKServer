import bleach
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request
from opentakserver.extensions import logger

citrap_api_blueprint = Blueprint("citrap_api_blueprint", __name__)


@citrap_api_blueprint.route("/Marti/api/missions/citrap/subscription", methods=["PUT"])
def citrap_subscription():
    uid = bleach.clean(request.args.get("uid"))
    response = {"version": 3, "type": "com.bbn.marti.sync.model.MissionSubscription", "data": {}}
    return "", 201


@citrap_api_blueprint.route("/Marti/api/citrap")
def citrap():
    return jsonify([])


@citrap_api_blueprint.route("/Marti/api/citrap", methods=["POST"])
def post_citrap():
    client_uid = request.args.get("clientUid")

    f = open("/home/administrator/citrap.zip", "wb")
    f.write(request.data)
    f.close()

    return jsonify([])
