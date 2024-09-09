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
from werkzeug.wsgi import FileWrapper

import opentakserver
from opentakserver.extensions import db, logger
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.models.Packages import Packages

device_profile_api_blueprint = Blueprint('device_profile_api_blueprint', __name__)


def create_profile_zip(enrollment=True):
    # preference.pref
    prefs = Element("preferences")
    pref = SubElement(prefs, "preference", {"version": "1", "name": "com.atakmap.app_preferences"})

    enable_update_server = SubElement(pref, "entry", {"key": "appMgmtEnableUpdateServer", "class": "class java.lang.Boolean"})
    enable_update_server.text = "true"

    update_server_address = SubElement(pref, "entry", {"key": "atakUpdateServerUrl", "class": "class java.lang.String"})
    update_server_address.text = f"https://{urlparse(request.url_root).hostname}:{app.config.get('OTS_MARTI_HTTPS_PORT')}/api/packages"

    startup_sync = SubElement(pref, "entry", {"key": "repoStartupSync", "class": "class java.lang.Boolean"})
    startup_sync.text = "true"

    startup_sync = SubElement(pref, "entry", {"key": "deviceProfileEnableOnConnect", "class": "class java.lang.Boolean"})
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
    if app.config.get("OTS_PROFILE_MAP_SOURCES"):
        maps_path = os.path.join(os.path.dirname(opentakserver.__file__), "maps")
        for root, dirs, map_files in os.walk(maps_path):
            for map in map_files:
                zipf.writestr(f"maps/{map}", open(os.path.join(maps_path, map), 'r').read())
                SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"maps/{map}"})

    if enrollment:
        device_profiles = db.session.execute(db.session.query(DeviceProfiles).filter_by(enrollment=True)).all()
        plugins = db.session.execute(db.session.query(Packages).filter_by(install_on_enrollment=True)).all()
    else:
        device_profiles = db.session.execute(db.session.query(DeviceProfiles).filter_by(connection=True)).all()
        plugins = db.session.execute(db.session.query(Packages).filter_by(install_on_connection=True)).all()

    for profile in device_profiles:
        p = SubElement(pref, "entry", {"key": profile[0].preference_key, "class": profile[0].value_class})
        p.text = profile[0].preference_value

    for plugin in plugins:
        plugin = plugin[0]
        SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"5c2bfcae3d98c9f4d262172df99ebac5/{plugin.file_name}"})
        zipf.write(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", plugin.file_name), f"5c2bfcae3d98c9f4d262172df99ebac5/{plugin.file_name}")
    zipf.writestr("MANIFEST/manifest.xml", tostring(manifest))

    zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/preference.pref", tostring(prefs))

    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12'), 'rb') as truststore:
        zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/truststore-root.p12", truststore.read())

    return zip_buffer


# Authentication for /Marti endpoints handled by client cert validation
# EUDs hit this endpoint after a successful certificate enrollment
@device_profile_api_blueprint.route('/api/enrollment')
@device_profile_api_blueprint.route('/Marti/api/tls/profile/enrollment')
def enrollment_profile():
    try:
        profile_zip = create_profile_zip()
        profile_zip.seek(0)
        return Response(FileWrapper(profile_zip), mimetype="application/zip", direct_passthrough=True)
    except BaseException as e:
        logger.error(f"Failed to send enrollment package: {e}")
        logger.debug(traceback.format_exc())
        return '', 500


# EUDs his this endpoint when the app connects to the server if repoStartupSync is enabled
@device_profile_api_blueprint.route('/Marti/api/device/profile/connection')
@device_profile_api_blueprint.route('/api/connection')
def connection_profile():
    try:
        profile_zip = create_profile_zip(False)
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
@auth_required()
@roles_required("administrator")
def add_device_profile():
    form = DeviceProfileForm()
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    device_profile = DeviceProfiles()
    device_profile.from_wtf(form)

    try:
        db.session.add(device_profile)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        db.session.execute(update(DeviceProfiles).where(DeviceProfiles.preference_key == device_profile.preference_key)
                           .values(**device_profile.serialize()))
        db.session.commit()

    return jsonify({'success': True})


@device_profile_api_blueprint.route('/api/profile', methods=['DELETE'])
@roles_required("administrator")
def delete_device_profile():
    return
