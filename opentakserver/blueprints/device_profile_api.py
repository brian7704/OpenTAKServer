import datetime
import hashlib
import io
import os
import traceback
import uuid
import zipfile
from urllib.parse import urlparse

from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, request, jsonify, current_app as app, Response
from flask_security import auth_required, current_user, roles_required
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename
from werkzeug.wsgi import FileWrapper

import opentakserver
from opentakserver.extensions import db, logger
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.DeviceProfiles import DeviceProfiles

device_profile_api_blueprint = Blueprint('device_profile_api_blueprint', __name__)


def create_profile_zip(enrollment=True):
    # preference.pref
    prefs = Element("preferences")
    pref = SubElement(prefs, "preference", {"version": "1", "name": "com.atakmap.app_preferences"})

    enable_update_server = SubElement(pref, "entry", {"key": "appMgmtEnableUpdateServer", "class": "class java.lang.Boolean"})
    enable_update_server.text = "true"

    update_server_address = SubElement(pref, "entry", {"key": "atakUpdateServerUrl", "class": "class java.lang.String"})
    update_server_address.text = f"https://{urlparse(request.url_root).hostname}:{app.config.get('OTS_MARTI_HTTPS_PORT')}/api/packages"

    startup_sync = SubElement(pref, "entry", {"key": "repoStartupSync"})
    startup_sync.text = "true"

    ca_location = SubElement(pref, "entry", {"key": "updateServerCaLocation", "class": "class java.lang.String"})
    ca_location.text = "/storage/emulated/0/atak/cert/truststore-root.p12"

    ca_password = SubElement(pref, "entry", {"key": "updateServerCaPassword", "class": "class java.lang.String"})
    ca_password.text = app.config.get("OTS_CA_PASSWORD")

    # MANIFEST file
    manifest = Element("MissionPackageManifest")
    config = SubElement(manifest, "Configuration")
    SubElement(config, "Parameter", {"name": "uid", "value": str(uuid.uuid4())})
    SubElement(config, "Parameter", {"name": "name", "value": "Enrollment Profile"})
    SubElement(config, "Parameter", {"name": "onReceiveDelete", "value": "true"})

    contents = SubElement(manifest, "Contents")
    SubElement(contents, "Content", {"ignore": "false", "zipEntry": "5c2bfcae3d98c9f4d262172df99ebac5/preference.pref"})
    SubElement(contents, "Content", {"ignore": "false", "zipEntry": "5c2bfcae3d98c9f4d262172df99ebac5/truststore-root.p12"})

    zip_buffer = io.BytesIO()
    zipf = zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False)

    # Add the maps to the zip
    maps_path = os.path.join(os.path.dirname(opentakserver.__file__), "maps")
    for root, dirs, map_files in os.walk(maps_path):
        for map in map_files:
            zipf.writestr(f"maps/{map}", open(os.path.join(maps_path, map), 'r').read())
            SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"maps/{map}"})

    zipf.writestr("MANIFEST/manifest.xml", tostring(manifest))

    zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/preference.pref", tostring(prefs))

    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12'), 'rb') as truststore:
        zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/truststore-root.p12", truststore.read())

    return zip_buffer


@device_profile_api_blueprint.route('/Marti/api/tls/profile/enrollment')
def enrollment():
    try:
        profile_zip = create_profile_zip()
        profile_zip.seek(0)
        return Response(FileWrapper(profile_zip), mimetype="application/zip", direct_passthrough=True)
    except BaseException as e:
        logger.error(f"Failed to send enrollment package: {e}")
        logger.debug(traceback.format_exc())
        return '', 500


@device_profile_api_blueprint.route('/api/profile')
@roles_required("administrator")
def get_device_profiles():
    return


@device_profile_api_blueprint.route('/api/profile', methods=['POST'])
@roles_required("administrator")
def add_device_profile():
    form = DeviceProfileForm()
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400
    elif "zip" not in form.data_package.data.mimetype:
        return jsonify({'success': False, 'error': 'Only data package zip files are allowed'}), 400

    device_profile = DeviceProfiles()
    device_profile.from_wtf(form)

    try:
        device_profile_id = db.session.add(device_profile)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        device_profile_id = db.session.execute(update(DeviceProfiles).where(DeviceProfiles.name == device_profile.name)
                                               .values(**device_profile.serialize()))

    sha256 = hashlib.sha256()
    sha256.update(form.data_package.data.stream.read())
    form.data_package.data.stream.seek(0)
    file_hash = sha256.hexdigest()

    data_package = DataPackage()
    data_package.filename = secure_filename(form.data_package.data.filename)
    data_package.hash = file_hash
    data_package.submission_time = datetime.datetime.now()
    data_package.submission_user = current_user.id
    data_package.mime_type = form.data_package.data.mimetype
    data_package.size = form.data_package.data.stream.tell()

    try:
        data_package_id = db.session.add(data_package)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        dp = db.session.execute(db.session.query(DataPackage).filter_by(hash=data_package.hash)).first()[0]
        data_package_id = dp.id

    form.data_package.data.save(app.config.get("UPLOAD_FOLDER"), f"{file_hash}.zip")

    return '', 200


@device_profile_api_blueprint.route('/api/profile', methods=['DELETE'])
@roles_required("administrator")
def delete_device_profile():
    return
