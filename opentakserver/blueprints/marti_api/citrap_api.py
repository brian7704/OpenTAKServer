import bleach
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request

citrap_api_blueprint = Blueprint("citrap_api_blueprint", __name__)


@citrap_api_blueprint.route("/Marti/api/citrap")
def search_citrap():
    keywords = request.args.get("keywords")
    bbox = request.args.get("bbox")
    start_time = request.args.get("startTime")
    end_time = request.args.get("endTime")
    max_report_count = request.args.get("maxReportCount")
    report_type = request.args.get("type")
    callsign = request.args.get("callsign")
    subscribe = request.args.get("subscribe")
    client_uid = request.args.get("clientUid")
    return jsonify([])


@citrap_api_blueprint.route("/Marti/api/citrap")
def add_citrap():
    client_uid = request.args.get("clientUid")
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["GET"])
def get_citrap(id):
    client_uid = request.args.get("clientUid")
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["PUT"])
def put_citrap(id):
    client_uid = request.args.get("clientUid")
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["DELETE"])
def delete_citrap(id):
    client_uid = request.args.get("clientUid")
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/attachment", methods=["POST"])
def add_attachment():
    client_uid = request.args.get("clientUid")
    # body is JSON
    return ""
