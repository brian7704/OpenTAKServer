import hashlib
import os
import traceback
import uuid
import bleach
import zipfile
from io import BytesIO

import sqlalchemy
from bs4 import BeautifulSoup
from flask_babel import gettext
from sqlalchemy import insert, update
from werkzeug.utils import secure_filename

from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request

from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.extensions import logger, db
from opentakserver.models.CITrap import CITrap
from opentakserver.models.Point import Point

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

    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)

    return jsonify([])


# noinspection bad-assignment
@citrap_api_blueprint.route("/Marti/api/citrap", methods=["POST"])
def add_citrap():
    client_uid = request.args.get("clientUid")

    if not client_uid:
        return jsonify({"success": False, "error": gettext("client_uid not found")}), 400

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "reports"), exist_ok=True)

    zipf = zipfile.ZipFile(
        BytesIO(request.data),
        "r",
        zipfile.ZIP_DEFLATED,
        False,
    )

    report_filename = None
    for filename in zipf.namelist():
        if filename.endswith("report.xml"):
            report_filename = filename
            break

    if not report_filename:
        return jsonify({"success": False, "error": gettext("report.xml not found")}), 400

    manifest = zipf.read(report_filename).decode("utf-8")

    soup = BeautifulSoup(manifest, "xml")
    report = soup.find("report")

    if not report:
        return jsonify({"success": False, "error": gettext("Invalid report file")}), 400

    filename = f"{secure_filename(str(report.attrs.get('title') or uuid.uuid4()))}.zip"

    f = open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "reports", filename), "wb")
    f.write(request.data)
    f.close()

    sha256 = hashlib.sha256()
    sha256.update(request.data)

    point = Point()
    point.uid = report.attrs.get("id") or str(uuid.uuid4())
    point.device_uid = client_uid

    point_wkt = report.attrs.get("location")
    latitude = 0
    longitude = 0
    if point_wkt:
        longitude = str(point_wkt).replace("POINT (", "").split(" ")[0]
        latitude = str(point_wkt).replace("POINT (", "").split(" ")[1].replace(")", "")
        point.point = point_wkt

    point.latitude = latitude
    point.longitude = longitude
    point.timestamp = datetime_from_iso8601_string(report.attrs.get("dateTime"))

    point_result = db.session.execute(insert(Point).values(**point.serialize()))
    db.session.commit()
    point_pk = point_result.inserted_primary_key[0]

    citrap = CITrap()
    citrap.id = report.attrs.get("id")
    citrap.type = report.attrs.get("type")
    citrap.title = report.attrs.get("title")
    citrap.visible = report.attrs.get("visibilityStatus").lower() == "true"
    citrap.delimiter = report.attrs.get("delimiter")
    citrap.user_callsign = report.attrs.get("userCallsign")
    citrap.user_description = report.attrs.get("userDescription")
    citrap.date_time = datetime_from_iso8601_string(report.attrs.get("dateTime"))
    citrap.date_time_description = report.attrs.get("dateTimeDescription")
    citrap.point_id = point_pk
    citrap.location_description = report.attrs.get("locationDescription")
    citrap.tags = report.attrs.get("tags")
    citrap.event_scale = report.attrs.get("eventScale")
    citrap.scale_description = report.attrs.get("scaleDescription")
    citrap.importance = report.attrs.get("importance")
    citrap.status = report.attrs.get("status")
    citrap.file_name = filename
    citrap.hash = sha256.hexdigest()

    try:
        db.session.add(citrap)
        db.session.commit()

    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        db.session.execute(
            update(CITrap).where(CITrap.id == citrap.id).values(**citrap.serialize())
        )
        db.session.commit()

    except Exception as e:
        logger.error(f"Failed to add citrap: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": gettext("Failed to add report")}), 500

    return jsonify({"id": citrap.id}), 201


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["GET"])
def get_citrap(id):
    client_uid = request.args.get("clientUid")
    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["PUT"])
def put_citrap(id):
    client_uid = request.args.get("clientUid")
    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["DELETE"])
def delete_citrap(id):
    client_uid = request.args.get("clientUid")
    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)
    return ""


@citrap_api_blueprint.route("/Marti/api/citrap/attachment", methods=["POST"])
def add_attachment():
    client_uid = request.args.get("clientUid")
    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)
    # body is JSON
    return ""
