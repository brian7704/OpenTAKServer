import datetime
import hashlib
import os
import traceback
import uuid
import zipfile
from io import BytesIO

import sqlalchemy
from bs4 import BeautifulSoup
from cryptography.hazmat._oid import NameOID
from flask_babel import gettext
from sqlalchemy import insert, update
from werkzeug.utils import secure_filename

from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.blueprints.ots_api.api import search
from opentakserver.functions import datetime_from_iso8601_string
from opentakserver.extensions import logger, db
from opentakserver.models.CITrap import CITrap
from opentakserver.models.Group import Group
from opentakserver.models.GroupCITrap import GroupCITrap
from opentakserver.models.GroupMission import GroupMission
from opentakserver.models.GroupUser import GroupUser
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionRole import MissionRole
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

    query = db.session.query(CITrap)
    search(query, CITrap, "keywords")
    search(query, CITrap, "bbox")
    search(query, CITrap, "type")
    search(query, CITrap, "callsign")
    search(query, CITrap, "clientUid")

    reports = db.session.execute(query).scalars()
    retval = []
    for report in reports:
        retval.append(report.to_marti_json())

    return jsonify(retval)


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

    cert = verify_client_cert()
    if not cert:
        return jsonify({"success": False, "error": gettext("Failed to verify certificate")}), 400

    username = cert.subject.get_attributes_for_oid(NameOID.COMMON_NAME)[0].value

    try:
        mission = Mission()
        mission.name = citrap.id
        mission.creator_uid = client_uid
        mission.tool = "citrap"
        mission.create_time = datetime.datetime.now(datetime.timezone.utc)
        mission.guid = str(uuid.uuid4())
        db.session.add(mission)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        # TODO: Should anything be updated?
        db.session.rollback()
        logger.warn(f"Mission {citrap.id} already exists")
        return jsonify({"id": citrap.id}), 201

    role = MissionRole()
    role.clientUid = client_uid
    role.username = username
    role.createTime = mission.create_time
    role.role_type = MissionRole.MISSION_OWNER
    role.mission_name = mission.name
    db.session.add(role)

    change = MissionChange()
    change.isFederatedChange = False
    change.change_type = MissionChange.CREATE_MISSION
    change.mission_name = mission.name
    change.timestamp = mission.create_time
    change.server_time = mission.create_time
    change.creator_uid = client_uid
    db.session.add(change)

    user = app.security.datastore.find_user(username=username)
    if not user:
        return jsonify({"success": False, "error": gettext(f"User not found: {username}")}), 400

    groups = (
        db.session.query(GroupUser)
        .filter(GroupUser.user_id == user.id)
        .filter(GroupUser.direction == Group.IN)
    )
    for group in groups:
        group_mission = GroupMission()
        group_mission.mission_name = mission.name
        group_mission.group_id = group.group_id
        db.session.add(group_mission)

        group_citrap = GroupCITrap()
        group_citrap.citrap_id = citrap.id
        group_citrap.group_id = group.group_id
        db.session.add(group_citrap)

    db.session.commit()
    return jsonify({"id": citrap.id}), 201


@citrap_api_blueprint.route("/Marti/api/citrap/<id>", methods=["GET"])
def get_citrap(id):
    client_uid = request.args.get("clientUid")
    logger.debug(request.args)
    logger.debug(request.data)
    logger.debug(request.headers)
    # downloads the zip
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
