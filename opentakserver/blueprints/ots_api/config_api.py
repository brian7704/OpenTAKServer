from flask import Blueprint, jsonify, request
from flask import current_app as app
from flask_babel import gettext
from flask_security import auth_required, roles_required

from opentakserver.blueprints.ots_api.api import change_config_setting
from opentakserver.extensions import logger

config_api_blueprint = Blueprint("config_api_blueprint", __name__)

CONFIG_WHITELIST = {
    "OTS_MAP_DEFAULT_LAT",
    "OTS_MAP_DEFAULT_LON",
    "OTS_MAP_DEFAULT_ZOOM",
    "OTS_MAP_DEFAULT_LAYER",
}


@config_api_blueprint.route("/api/config")
@auth_required()
def get_config():
    return jsonify({key: app.config.get(key) for key in CONFIG_WHITELIST})


@config_api_blueprint.route("/api/config", methods=["PUT"])
@auth_required()
@roles_required("administrator")
def update_config():
    data = request.json
    if not data:
        return jsonify({"success": False, "error": gettext("No data provided")}), 400

    invalid_keys = set(data.keys()) - CONFIG_WHITELIST
    if invalid_keys:
        return jsonify({
            "success": False,
            "error": gettext("Invalid config keys: %(keys)s", keys=", ".join(invalid_keys))
        }), 400

    for key, value in data.items():
        change_config_setting(key, value)
        app.config[key] = value

    return jsonify({"success": True})
