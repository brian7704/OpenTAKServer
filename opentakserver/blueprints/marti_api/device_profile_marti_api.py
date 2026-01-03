import datetime
import io
import os
import re
import traceback
import uuid
import zipfile
from urllib.parse import urlparse

from xml.etree.ElementTree import Element, SubElement, tostring

from flask import Blueprint, request, current_app as app, Response
from werkzeug.wsgi import FileWrapper

import opentakserver
from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.extensions import db, logger, ldap_manager
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.models.Packages import Packages
from opentakserver.models.DataPackage import DataPackage

device_profile_marti_api_blueprint = Blueprint('device_profile_marti_api_blueprint', __name__)


def get_ldap_attributes(prefs: Element):
    if app.config.get("OTS_ENABLE_LDAP"):
        cert = verify_client_cert()
        if not cert:
            return

        username = cert.get_subject().commonName
        user_info = ldap_manager.get_user_info_for_username(username)

        for field in user_info:
            if field.lower() == app.config.get("OTS_LDAP_COLOR_ATTRIBUTE").lower():
                team = SubElement(prefs, "entry", {"key": "locationTeam", "class": "class java.lang.String"})
                team.text = user_info[field][0]

            elif field.lower() == app.config.get("OTS_LDAP_ROLE_ATTRIBUTE").lower():
                role = SubElement(prefs, "entry", {"key": "atakRoleType", "class": "class java.lang.String"})
                role.text = user_info[field][0]

            elif field.lower() == app.config.get("OTS_LDAP_CALLSIGN_ATTRIBUTE").lower():
                callsign = SubElement(prefs, "entry", {"key": "locationCallsign", "class": "class java.lang.String"})
                callsign.text = user_info[field][0]

            elif field.lower().startswith(app.config.get("OTS_LDAP_PREFERENCE_ATTRIBUTE_PREFIX").lower()):
                # Remove prefix, case insensitive
                remove_prefix = re.compile(re.escape(app.config.get("OTS_LDAP_PREFERENCE_ATTRIBUTE_PREFIX")), re.IGNORECASE)
                attribute = remove_prefix.sub("", field)
                subelement = SubElement(prefs, "entry", {"key": attribute, "class": "class java.lang.String"})
                subelement.text = user_info[field][0]


def create_profile_zip(enrollment=True, syncSecago=-1):
    # preference.pref
    prefs = Element("preferences")
    pref = SubElement(prefs, "preference", {"version": "1", "name": "com.atakmap.app_preferences"})

    get_ldap_attributes(pref)

    plugins = None
    data_packages = None
    device_profiles = None
    zip_buffer = io.BytesIO()
    zipf = zipfile.ZipFile(zip_buffer, "a", zipfile.ZIP_DEFLATED, False)

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


    enable_update_server = SubElement(pref, "entry", {"key": "appMgmtEnableUpdateServer", "class": "class java.lang.Boolean"})
    enable_update_server.text = "true"

    update_server_address = SubElement(pref, "entry", {"key": "atakUpdateServerUrl", "class": "class java.lang.String"})
    update_server_address.text = f"https://{urlparse(request.url_root).hostname}:{app.config.get('OTS_MARTI_HTTPS_PORT')}/api/packages"

    startup_sync = SubElement(pref, "entry", {"key": "repoStartupSync", "class": "class java.lang.Boolean"})
    startup_sync.text = "true"

    enable_profiles = SubElement(pref, "entry",
                                 {"key": "deviceProfileEnableOnConnect", "class": "class java.lang.Boolean"})
    enable_profiles.text = "true"

    ca_location = SubElement(pref, "entry", {"key": "updateServerCaLocation", "class": "class java.lang.String"})
    ca_location.text = "/storage/emulated/0/atak/cert/truststore-root.p12"

    ca_password = SubElement(pref, "entry", {"key": "updateServerCaPassword", "class": "class java.lang.String"})
    ca_password.text = app.config.get("OTS_CA_PASSWORD")

    enable_channels_host = SubElement(pref, "entry",
                                      {'key': f'prefs_enable_channels_host-{urlparse(request.url_root).hostname}',
                                       'class': 'class java.lang.String'})
    enable_channels_host.text = "true"

    enable_channels = SubElement(pref, "entry", {'key': 'prefs_enable_channels', 'class': 'class java.lang.String'})
    enable_channels.text = "true" if app.config.get("OTS_ENABLE_CHANNELS") else "false"

    if enrollment:
        # Add the maps to the zip
        if app.config.get("OTS_PROFILE_MAP_SOURCES") and enrollment:
            maps_path = os.path.join(os.path.dirname(opentakserver.__file__), "maps")
            for root, dirs, map_files in os.walk(maps_path):
                for map in map_files:
                    zipf.writestr(f"maps/{map}", open(os.path.join(maps_path, map), 'r').read())
                    SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"maps/{map}"})

            device_profiles = db.session.execute(
                db.session.query(DeviceProfiles).filter_by(enrollment=True, active=True)).all()
            plugins = db.session.execute(db.session.query(Packages).filter_by(install_on_enrollment=True)).all()
            data_packages = db.session.execute(db.session.query(DataPackage).filter_by(install_on_enrollment=True)).all()
    elif syncSecago > 0:
        publish_time = datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(seconds=syncSecago)

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
@device_profile_marti_api_blueprint.route('/Marti/api/tls/profile/enrollment')
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
@device_profile_marti_api_blueprint.route('/api/connection')
@device_profile_marti_api_blueprint.route('/Marti/api/device/profile/connection')
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
