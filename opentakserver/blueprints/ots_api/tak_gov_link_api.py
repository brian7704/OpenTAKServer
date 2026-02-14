import os
import re
import traceback
from datetime import datetime, timezone

import httpx
from flask import Blueprint
from flask import current_app as app
from flask import jsonify, request
from flask_security import roles_required

from opentakserver import __version__ as version
from opentakserver.blueprints.ots_api.api import change_config_setting
from opentakserver.blueprints.ots_api.package_api import create_product_infz
from opentakserver.extensions import db, logger
from opentakserver.models.Packages import Packages

tak_gov_link_blueprint = Blueprint("tak_gov_link_blueprint", __name__)

HEADERS = {"User-Agent": f"OpenTAKServer {version}"}


def get_new_access_token():
    try:
        client = httpx.Client(http2=True)
        refresh_payload = {
            "client_id": "tak-gov-eud",
            "grant_type": "refresh_token",
            "refresh_token": app.config.get("OTS_TAK_GOV_REFRESH_TOKEN"),
        }
        response = client.post(
            "https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/token",
            data=refresh_payload,
            headers=HEADERS,
        )

        if response.status_code != 200:
            logger.error(
                {"success": False, "error": f"Failed to get new access token: {response.text}"}
            )
            return {"success": False, "error": f"Failed to get new access token: {response.text}"}

        response_data = response.json()
        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        expires_in = response_data["expires_in"]
        change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", refresh_token)
        app.config["OTS_TAK_GOV_REFRESH_TOKEN"] = refresh_token

        return {"success": True, "access_token": access_token, "expires_in": expires_in}
    except BaseException as e:
        logger.error(f"Failed to get new access token: {e}")
        logger.debug(traceback.format_exc())
        return {"success": False, "error": f"Failed to get new access token: {e}"}


@tak_gov_link_blueprint.route("/api/takgov/link")
@roles_required("administrator")
def link_tak_gov_account():
    """Interacts with tak.gov's eud_api to get the user_code and device_code required to link OpenTAKServer to a tak.gov account

    :return: The device_code and user_code on success, error message otherwise
    """

    try:
        # Use httpx since it supports http/2.0
        client = httpx.Client(http2=True)

        # Step 1: Get the device_code and user_code
        payload = {
            "client_id": "tak-gov-eud",
            "scope": "openid offline_access email profile",
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
        }
        response = client.post(
            "https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/auth/device",
            headers=HEADERS,
            data=payload,
        )
        if response.status_code != 200:
            logger.info(f"Failed to get new access token: {response.text}")
            logger.info(response.content)
            logger.info(response.headers)
            return (
                jsonify(
                    {"success": False, "error": f"Failed to link tak.gov account: {response.text}"}
                ),
                response.status_code,
            )

        response_data = response.json()
        device_code = response_data["device_code"]
        user_code = response_data["user_code"]

        return jsonify({"success": True, "device_code": device_code, "user_code": user_code})

    except BaseException as e:
        logger.error(f"Failed to link tak.gov account: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to link tak.gov account: {e}"}), 500


@tak_gov_link_blueprint.route("/api/takgov/token")
@roles_required("administrator")
def get_initial_tak_gov_token():
    """Queries the tak.gov eud_api to get the initial refresh_token and access_token once the user has entered their user_code into tak.gov.

    :return: JSON object with access_token and expires_in, error message otherwise
    """

    device_code = request.args.get("device_code")
    if not device_code:
        return jsonify({"success": False, "error": "device_code is required"}), 400

    try:
        client = httpx.Client(http2=True)

        payload = {
            "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            "device_code": device_code,
            "client_id": "tak-gov-eud",
        }
        r = client.post(
            "https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/token",
            data=payload,
            headers=HEADERS,
        )

        logger.info(r.text)
        response_data = r.json()

        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        expires_in = response_data["expires_in"]

        change_config_setting("OTS_TAK_GOV_LINKED", True)
        change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", refresh_token)

        app.config.update({"OTS_TAK_GOV_LINKED": True})
        app.config.update({"OTS_TAK_GOV_REFRESH_TOKEN": refresh_token})

        return jsonify({"success": True, "access_token": access_token, "expires_in": expires_in})
    except BaseException as e:
        logger.error(f"Failed to get initial tak gov token: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to get initial tak gov token: {e}"})


@tak_gov_link_blueprint.route("/api/takgov/token", methods=["PATCH"])
@roles_required("administrator")
def get_new_tak_gov_token():
    """Uses the refresh_token to get a new access_token. This is required since the access_token expires three minutes after
    it is generated.

    :return: JSON object with the new access_token, error message otherwise.
    """

    if not app.config.get("OTS_TAK_GOV_LINKED") or not app.config.get("OTS_TAK_GOV_REFRESH_TOKEN"):
        return jsonify({"success": False, "error": "Not linked to a tak.gov account"}), 400

    try:
        token = get_new_access_token()
        if token["success"]:
            return jsonify(token)
        else:
            return jsonify(token), 500

    except BaseException as e:
        logger.error(f"Failed to get new tak.gov token: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to get new tak.gov token {e}"}), 500


@tak_gov_link_blueprint.route("/api/takgov/plugins")
@roles_required("administrator")
def get_plugins_list():
    """Query tak.gov's eud_api for a list of plugins for the specified product and product version (i.e. ATAK-CIV 5.5.0)

    :return: JSON array of available plugins.
    """
    product = request.args.get("product")
    product_version = request.args.get("product_version")

    if not product or not product_version:
        return jsonify({"success": False, "error": "product and product_version are required"}), 400

    token = get_new_access_token()
    if not token["success"]:
        return jsonify(token), 500

    client = httpx.Client(http2=True)
    HEADERS["Authorization"] = f"Bearer {token['access_token']}"
    params = {"product": product, "product_version": product_version}

    try:
        response = client.get(
            "https://tak.gov/eud_api/software/v1/plugins", params=params, headers=HEADERS
        )
        return jsonify(response.json())
    except BaseException as e:
        logger.error(f"Failed to get plugin list: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to get plugin list: {e}"}), 500


@tak_gov_link_blueprint.route("/api/takgov", methods=["DELETE"])
@roles_required("administrator")
def unlink_tak_gov_account():
    if not app.config.get("OTS_TAK_GOV_LINKED"):
        return jsonify({"success": False, "error": "Not linked to a TAK.gov account"}), 400

    change_config_setting("OTS_TAK_GOV_LINKED", False)
    change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", None)

    app.config.update({"OTS_TAK_GOV_LINKED": False})
    app.config.update({"OTS_TAK_GOV_REFRESH_TOKEN": None})

    return jsonify({"success": True})


@tak_gov_link_blueprint.route("/api/takgov")
@roles_required("administrator")
def check_if_linked():
    return jsonify(
        {"success": True, "tak_gov_account_linked": app.config.get("OTS_TAK_GOV_LINKED")}
    )


@tak_gov_link_blueprint.route("/api/takgov/icon")
@roles_required("administrator")
def get_plugin_icon():
    """Downloads the plugin's icon from tak.gov's eud_api using the access_token

    :return: The icon or an error message.
    """
    icon_url = request.args.get("icon_url")
    if not icon_url:
        return jsonify({"success": False, "error": "icon_link is required"}), 400
    elif not icon_url.startswith("https://tak.gov/eud_api"):
        return jsonify({"success": False, "error": "icon_link is invalid"}), 400

    token = get_new_access_token()
    if not token["success"]:
        return jsonify(token), 500

    client = httpx.Client(http2=True)
    HEADERS["Authorization"] = f"Bearer {token['access_token']}"
    response = client.get(icon_url, headers=HEADERS)
    logger.warning(response.content)
    logger.warning(response.text)
    logger.warning(response.headers)

    return response.content


@tak_gov_link_blueprint.route("/api/takgov/plugin", methods=["POST"])
@roles_required("administrator")
def download_plugin():
    apk_hash = request.json.get("apk_hash")
    apk_size = request.json.get("apk_size_bytes")
    apk_url = request.json.get("apk_url")
    apk_type = request.json.get("apk_type")
    description = request.json.get("description")
    name = request.json.get("display_name")
    platform = request.json.get("platform")
    package_name = request.json.get("package_name")
    plugin_version = request.json.get("version")
    revision_code = request.json.get("revision_code")
    os_requirement = request.json.get("os_requirement")
    atak_version = request.json.get("atak_version")

    # Don't set an ATAK version for the plugin for ATAK < 5.5.0.
    # ATAK 5.4.0 and below don't check for plugins for their specific version of ATAK
    major, minor, _ = atak_version.split(".")
    if int(major) < 5 or (int(major) == 5 and int(minor) < 5):
        atak_version = None

    if not apk_url:
        return jsonify({"success": False, "error": "plugin_url is required"}), 400

    exising_plugin = db.session.execute(
        db.session.query(Packages).filter_by(version=plugin_version, package_name=package_name)
    ).first()
    if exising_plugin:
        return jsonify({"success": False, "error": f"Plugin {package_name} already exists"}), 400

    client = httpx.Client(http2=True)
    token = get_new_access_token()
    if not token["success"]:
        return jsonify(token), 500

    HEADERS["Authorization"] = f"Bearer {token['access_token']}"
    response = client.get(apk_url, headers=HEADERS, follow_redirects=True)
    if response.status_code != 200:
        return jsonify(response.content), response.status_code

    content_disposition = response.headers.get("content-disposition")
    filename = re.search(r"filename=\"(.+)\"", content_disposition).group(1)
    with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", filename), "wb") as f:
        f.write(response.content)

    icon = None
    icon_filename = None
    icon_response = client.get(request.json.get("icon_url"), headers=HEADERS, follow_redirects=True)
    # Some plugins don't have icons and will return a 404
    if icon_response.status_code == 200:
        icon = icon_response.content
        content_disposition = icon_response.headers.get("content-disposition")
        icon_filename = re.search(r"filename=\"(.+)\"", content_disposition).group(1)

    plugin = Packages()
    plugin.platform = platform
    plugin.apk_hash = apk_hash
    plugin.file_size = apk_size
    plugin.package_name = package_name
    plugin.version = plugin_version
    plugin.description = description
    plugin.name = name
    plugin.revision_code = revision_code
    plugin.os_requirement = os_requirement
    plugin.plugin_type = apk_type
    plugin.atak_version = atak_version
    plugin.icon = icon
    plugin.icon_filename = icon_filename
    plugin.file_name = filename
    plugin.publish_time = datetime.now(tz=timezone.utc)

    try:
        db.session.add(plugin)
        db.session.commit()
    except BaseException as e:
        logger.error(f"Failed to add plugin to database: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to add plugin to database: {e}"}), 500

    create_product_infz(atak_version)

    return jsonify({"success": True})
