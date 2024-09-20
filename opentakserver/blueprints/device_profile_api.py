import datetime
import io
import os
import traceback
import uuid
import zipfile
from urllib.parse import urlparse

from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, request, jsonify, current_app as app, Response
from flask_security import auth_required, roles_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from werkzeug.wsgi import FileWrapper

import opentakserver
from opentakserver.extensions import db, logger
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.models.Packages import Packages
from opentakserver.models.DataPackage import DataPackage
from opentakserver.blueprints.api import search, paginate

device_profile_api_blueprint = Blueprint('device_profile_api_blueprint', __name__)


def create_profile_zip(enrollment=True, syncSecago=-1):
    # preference.pref
    prefs = Element("preferences")
    pref = SubElement(prefs, "preference", {"version": "1", "name": "com.atakmap.app_preferences"})

    enable_update_server = SubElement(pref, "entry",
                                      {"key": "appMgmtEnableUpdateServer", "class": "class java.lang.Boolean"})
    enable_update_server.text = "true"

    update_server_address = SubElement(pref, "entry", {"key": "atakUpdateServerUrl", "class": "class java.lang.String"})
    update_server_address.text = f"https://{urlparse(request.url_root).hostname}:{app.config.get('OTS_MARTI_HTTPS_PORT')}/api/packages"

    startup_sync = SubElement(pref, "entry", {"key": "repoStartupSync", "class": "class java.lang.Boolean"})
    startup_sync.text = "true"

    enable_profiles = SubElement(pref, "entry",{"key": "deviceProfileEnableOnConnect", "class": "class java.lang.Boolean"})
    enable_profiles.text = "true"

    ca_location = SubElement(pref, "entry", {"key": "updateServerCaLocation", "class": "class java.lang.String"})
    ca_location.text = "/storage/emulated/0/atak/cert/truststore-root.p12"

    ca_password = SubElement(pref, "entry", {"key": "updateServerCaPassword", "class": "class java.lang.String"})
    ca_password.text = app.config.get("OTS_CA_PASSWORD")

    # MANIFEST file
    manifest = Element("MissionPackageManifest", {"version": "2"})
    config = SubElement(manifest, "Configuration")
    SubElement(config, "Parameter", {"name": "uid", "value": str(uuid.uuid4())})
    SubElement(config, "Parameter", {"name": "name", "value": "Device Profile"})
    SubElement(config, "Parameter", {"name": "onReceiveDelete", "value": "true"})

    contents = SubElement(manifest, "Contents")
    SubElement(contents, "Content", {"ignore": "false", "zipEntry": "5c2bfcae3d98c9f4d262172df99ebac5/preference.pref"})
    SubElement(contents, "Content",
               {"ignore": "false", "zipEntry": "5c2bfcae3d98c9f4d262172df99ebac5/truststore-root.p12"})

    zip_buffer = io.BytesIO()
    zipf = zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False)

    # Add the maps to the zip
    if app.config.get("OTS_PROFILE_MAP_SOURCES") and enrollment:
        maps_path = os.path.join(os.path.dirname(opentakserver.__file__), "maps")
        for root, dirs, map_files in os.walk(maps_path):
            for map in map_files:
                zipf.writestr(f"maps/{map}", open(os.path.join(maps_path, map), 'r').read())
                SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"maps/{map}"})

    plugins = None
    if enrollment:
        device_profiles = db.session.execute(
            db.session.query(DeviceProfiles).filter_by(enrollment=True, active=True)).all()
        plugins = db.session.execute(db.session.query(Packages).filter_by(install_on_enrollment=True)).all()
        data_packages = db.session.execute(db.session.query(DataPackage).filter_by(install_on_enrollment=True)).all()
    elif syncSecago > 0:
        publish_time = datetime.datetime.now() - datetime.timedelta(seconds=syncSecago)

        device_profiles = db.session.execute(db.session.query(DeviceProfiles).filter_by(connection=True, active=True)
                                             .filter(DeviceProfiles.publish_time >= publish_time)).all()
        data_packages = db.session.execute(db.session.query(DataPackage).filter_by(install_on_connection=True)
                                           .filter(DataPackage.submission_time >= publish_time)).all()
        plugins = db.session.execute(db.session.query(Packages).filter_by(install_on_connection=True)
                                     .filter(Packages.publish_time >= publish_time)).all()
    else:
        device_profiles = db.session.execute(
            db.session.query(DeviceProfiles).filter_by(connection=True, active=True)).all()
        data_packages = db.session.execute(db.session.query(DataPackage).filter_by(install_on_connection=True)).all()

    for profile in device_profiles:
        p = SubElement(pref, "entry", {"key": profile[0].preference_key, "class": profile[0].value_class})
        p.text = profile[0].preference_value

    if plugins:
        for plugin in plugins:
            plugin = plugin[0]

            SubElement(contents, "Content",
                       {"ignore": "false", "zipEntry": f"5c2bfcae3d98c9f4d262172df99ebac5/{plugin.file_name}"})
            zipf.write(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", plugin.file_name),
                       f"5c2bfcae3d98c9f4d262172df99ebac5/{plugin.file_name}")

    if data_packages:
        for data_package in data_packages:
            data_package = data_package[0]
            SubElement(contents, "Content",
                       {"ignore": "false", "zipEntry": f"5c2bfcae3d98c9f4d262172df99ebac5/{data_package.filename}"})
            zipf.write(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{data_package.hash}.zip"),
                       f"5c2bfcae3d98c9f4d262172df99ebac5/{data_package.filename}")

    zipf.writestr("MANIFEST/manifest.xml", tostring(manifest))

    zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/preference.pref", tostring(prefs))

    with open(os.path.join(app.config.get("OTS_CA_FOLDER"), 'truststore-root.p12'), 'rb') as truststore:
        zipf.writestr("5c2bfcae3d98c9f4d262172df99ebac5/truststore-root.p12", truststore.read())

    return zip_buffer


# Authentication for /Marti endpoints handled by client cert validation
# EUDs hit this endpoint after a successful certificate enrollment
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


# EUDs hit this endpoint when the app connects to the server if repoStartupSync is enabled
@device_profile_api_blueprint.route('/Marti/api/device/profile/connection')
def connection_profile():
    try:
        syncSecago = -1
        if 'syncSecago' in request.args:
            try:
                syncSecago = int(request.args['syncSecago'])
            except ValueError:
                pass
        profile_zip = create_profile_zip(False, syncSecago)
        profile_zip.seek(0)
        return Response(FileWrapper(profile_zip), mimetype="application/zip", direct_passthrough=True)
    except BaseException as e:
        logger.error(f"Failed to send enrollment package: {e}")
        logger.debug(traceback.format_exc())
        return '', 500


@device_profile_api_blueprint.route('/api/profiles')
@roles_required("administrator")
def get_device_profiles():
    query = db.session.query(DeviceProfiles)
    query = search(query, DeviceProfiles, 'preference_key')
    query = search(query, DeviceProfiles, 'preference_value')
    query = search(query, DeviceProfiles, 'tool')
    return paginate(query)


@device_profile_api_blueprint.route('/api/profiles', methods=['POST'])
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


@device_profile_api_blueprint.route('/api/profiles', methods=['DELETE'])
@roles_required("administrator")
def delete_device_profile():
    preference_key = request.args.get('preference_key')
    if not preference_key:
        return jsonify({'success': False, 'error': 'Please specify the preference_key'}), 400
    try:
        query = db.session.query(DeviceProfiles)
        query = search(query, DeviceProfiles, 'preference_key')
        preference = db.session.execute(query).first()
        if not preference:
            return jsonify({'success': False, 'error': f'Unknown preference_key: {preference_key}'}), 404

        db.session.delete(preference[0])
        db.session.commit()
        return jsonify({'success': True})
    except BaseException as e:
        logger.error(f"Failed to delete device profile: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 400
