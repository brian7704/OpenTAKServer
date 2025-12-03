import traceback

from flask import Blueprint, request, jsonify, current_app as app
from flask_security import roles_required

import httpx

from opentakserver import __version__ as version
from opentakserver.blueprints.ots_api.api import change_config_setting
from opentakserver.extensions import logger

tak_gov_link_blueprint = Blueprint('tak_gov_link_blueprint', __name__)

HEADERS = {"User-Agent": f"OpenTAKServer {version}"}


def get_new_access_token():
    try:
        client = httpx.Client(http2=True)
        refresh_payload = {"client_id": "tak-gov-eud", "grant_type": "refresh_token", "refresh_token": app.config.get("OTS_TAK_GOV_REFRESH_TOKEN")}
        response = client.post("https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/token", data=refresh_payload, headers=HEADERS)

        if response.status_code != 200:
            logger.error({"success": False, "error": f"Failed to get new access token: {response.text}"})
            return {"success": False, "error": f"Failed to get new access token: {response.text}"}

        response_data = response.json()
        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        expires_in = response_data["expires_in"]
        change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", refresh_token)

        return {"success": True, "access_token": access_token, "expires_in": expires_in}
    except BaseException as e:
        logger.error(f"Failed to get new access token: {e}")
        logger.debug(traceback.format_exc())
        return {"success": False, "error": f"Failed to get new access token: {e}"}


@tak_gov_link_blueprint.route('/api/takgov/link')
@roles_required('administrator')
def link_tak_gov_account():
    """Interacts with tak.gov's eud_api to get the user_code and device_code required to link OpenTAKServer to a tak.gov account

    :return: The device_code and user_code on success, error message otherwise
    """

    try:
        # Use httpx since it supports http/2.0
        client = httpx.Client(http2=True)

        # Step 1: Get the device_code and user_code
        payload = {"client_id": "tak-gov-eud", "scope": "openid offline_access email profile", "grant_type": "urn:ietf:params:oauth:grant-type:device_code"}
        response = client.post("https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/auth/device", headers=HEADERS, data=payload)
        if response.status_code != 200:
            return jsonify({"success": False, "error": f"Failed to link tak.gov account: {response.text}"})

        response_data = response.json()
        device_code = response_data["device_code"]
        verification_uri = response_data["verification_uri"]
        verification_uri_complete = response_data["verification_uri_complete"]
        user_code = response_data["user_code"]
        expires_in = response_data["expires_in"]
        interval = response_data["interval"]

        return jsonify({"success": True, "device_code": device_code, "user_code": user_code})

    except BaseException as e:
        logger.error(f"Failed to link tak.gov account: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to link tak.gov account: {e}"}), 500


@tak_gov_link_blueprint.route('/api/takgov/token')
@roles_required('administrator')
def get_initial_tak_gov_token():
    """Queries the tak.gov eud_api to get the initial refresh_token and access_token once the user has entered their user_code into tak.gov.

    :return: JSON object with access_token and expires_in, error message otherwise
    """

    device_code = request.args.get('device_code')
    if not device_code:
        return jsonify({"success": False, "error": "device_code is required"}), 400

    try:
        client = httpx.Client(http2=True)

        payload = {"grant_type": "urn:ietf:params:oauth:grant-type:device_code", "device_code": device_code, "client_id": "tak-gov-eud"}
        r = client.post("https://auth.tak.gov/auth/realms/TPC/protocol/openid-connect/token", data=payload, headers=HEADERS)
        response_data = r.json()

        access_token = response_data["access_token"]
        refresh_token = response_data["refresh_token"]
        expires_in = response_data["expires_in"]

        change_config_setting("OTS_TAK_GOV_LINKED", True)
        change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", refresh_token)

        return jsonify({"success": True, "access_token": access_token, "expires_in": expires_in})
    except BaseException as e:
        logger.error(f"Failed to get initial tak gov token: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to get initial tak gov token: {e}"})


@tak_gov_link_blueprint.route('/api/takgov/token', methods=["PATCH"])
@roles_required('administrator')
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

@tak_gov_link_blueprint.route('/api/takgov/plugins')
@roles_required('administrator')
def get_plugins_list():
    """Query tak.gov's eud_api for a list of plugins for the specified product and product version (i.e. ATAK-CIV 5.5.0)

    :return: JSON array of available plugins.
    """
    product = request.args.get('product')
    product_version = request.args.get('product_version')

    if not product or not product_version:
        return jsonify({"success": False, "error": "product and product_version are required"}), 400

    token = get_new_access_token()
    if not token["success"]:
        return jsonify(token), 500

    client = httpx.Client(http2=True)
    HEADERS["Authentication"] = f"Bearer {app.config.get('OTS_TAK_GOV_LINKED')}"
    params = {"product": "ATAK-MIL", "product_version": "5.5.0"}

    try:
        response = client.get("https://tak.gov/eud_api/software/v1/plugins", params=params, headers=HEADERS)
        return jsonify(response.json())
    except BaseException as e:
        logger.error(f"Failed to get plugin list: {e}")
        logger.debug(traceback.format_exc())
        return jsonify({"success": False, "error": f"Failed to get plugin list: {e}"}), 500


@tak_gov_link_blueprint.route('/api/takgov', methods=['DELETE'])
@roles_required("administrator")
def unlink_tak_gov_account():
    if not app.config.get('OTS_TAK_GOV_LINKED'):
        return jsonify({"success": False, "error": "Not linked to a TAK.gov account"}), 400

    change_config_setting("OTS_TAK_GOV_LINKED", False)
    change_config_setting("OTS_TAK_GOV_REFRESH_TOKEN", None)

    return jsonify({"success": True})


@tak_gov_link_blueprint.route('/api/takgov')
@roles_required("administrator")
def check_if_linked():
    return jsonify({"success": True, "tak_gov_account_linked": app.config.get('OTS_TAK_GOV_LINKED')})