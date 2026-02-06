from flask import Blueprint, jsonify

citrap_api_blueprint = Blueprint("citrap_api_blueprint", __name__)


@citrap_api_blueprint.route("/Marti/api/missions/citrap/subscription", methods=["PUT"])
def citrap_subscription():
    return "", 201


@citrap_api_blueprint.route("/Marti/api/citrap")
def citrap():
    return jsonify([])
