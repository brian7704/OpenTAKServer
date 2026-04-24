import os
import signal
import traceback

import yaml
from flask import Blueprint, jsonify, request, current_app as app, send_from_directory
from flask_security import roles_required
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.extensions import logger
from opentakserver.forms.Settings_Form import SettingsForm

settings_api_blueprint = Blueprint("settings_api_blueprint", __name__)


@settings_api_blueprint.route("/api/settings")
@roles_required("administrator")
def get_settings():
    settings = {}
    for field in SettingsForm().fields():
        if field["label"] != "CSRF Token":
            settings[field["label"]] = app.config.get(field["label"])

    return jsonify(settings)


@settings_api_blueprint.route("/api/settings/form")
@roles_required("administrator")
def get_settings_form():
    """
    Gets a list of fields from the SettingsForm

    :return: dict
    """
    return SettingsForm().fields()


@settings_api_blueprint.route("/api/settings/download")
@roles_required("administrator")
def download_config_yml():
    """
    Downloads the server's config.yml

    :return: yaml file
    """
    return send_from_directory(app.config.get("OTS_DATA_FOLDER"), "config.yml")


@settings_api_blueprint.route("/api/settings", methods=["POST"])
@roles_required("administrator")
def update_settings():
    sanitized_json = request.json.copy()
    for key in request.json.keys():
        if sanitized_json[key] is None:
            sanitized_json.pop(key)
    form = SettingsForm(formdata=ImmutableMultiDict(sanitized_json))

    if not form.validate():
        return jsonify({"success": False, "errors": form.errors}), 400

    try:
        with open(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "r"
        ) as config_file:
            config = yaml.safe_load(config_file.read())

        for field in form:
            if field.name == "csrf_token":
                continue
            config[field.label.text.upper()] = field.data
            app.config.update({field.label.text.upper(): field.data})

        logger.error(f"{config['DEBUG']} - {app.config.get('DEBUG')}")
        with open(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w"
        ) as config_file:
            yaml.safe_dump(config, config_file)

        os.kill(os.getpid(), signal.SIGHUP)

    except BaseException as e:
        logger.error(f"Failed to update config: {e}")
        logger.debug(traceback.format_exc())

    return "", 200
