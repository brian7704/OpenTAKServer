import os
import traceback

from flask_security import roles_required
from sqlalchemy import or_, update
import pickle

import bleach
from flask import current_app as app, request, Blueprint, jsonify
from flask_security import uia_username_mapper, uia_email_mapper

from opentakserver.extensions import db, logger
from opentakserver.models.Config import ConfigSettings

config_blueprint = Blueprint('config_blueprint', __name__)


def search(query, model, field):
    arg = request.args.get(field)
    if arg:
        arg = bleach.clean(arg)
        return query.where(getattr(model, field) == arg)
    return query


@config_blueprint.route('/api/config')
@roles_required('administrator')
def get_config():
    query = db.session.query(ConfigSettings).filter(
        or_(*[ConfigSettings.key.like("OTS%"), ConfigSettings.key.like("MAIL%")]))
    query = search(query, ConfigSettings, 'key')

    results = {}
    types = []

    settings = db.session.execute(query).all()
    for setting in settings:
        setting = setting[0]

        if type(pickle.loads(setting.value)) not in types:
            types.append(type(pickle.loads(setting.value)))

        if type(pickle.loads(setting.value)) == 'function':
            logger.warning(setting)
        elif setting.type == 'timedelta':
            results[setting.key] = str(pickle.loads(setting.value))
        else:
            results[setting.key] = pickle.loads(setting.value)

    return jsonify({'success': True, 'results': results})


@config_blueprint.route('/api/config', methods=['PATCH'])
@roles_required('administrator')
def change_setting():
    if not request.json:
        return jsonify({'success': False, 'error': 'Empty request'}), 400

    try:
        for setting in request.json:
            setting = bleach.clean(setting)
            config = db.session.execute(db.session.query(ConfigSettings).where(ConfigSettings.key == setting)).first()[0]
            value = request.json.get(setting)

            if value and type(value) is 'str':
                value = bleach.clean(value)

            #  Enable/disable account registration, confirmation, and recovery  based on whether email is enabled
            if setting == 'OTS_ENABLE_EMAIL':
                app.config.update({"SECURITY_REGISTERABLE": value})
                db.session.execute(update(ConfigSettings).filter(ConfigSettings.key == "SECURITY_REGISTERABLE")
                                   .values(value=pickle.dumps(value)))
                app.config.update({"SECURITY_CONFIRMABLE": value})
                db.session.execute(update(ConfigSettings).filter(ConfigSettings.key == "SECURITY_CONFIRMABLE")
                                   .values(value=pickle.dumps(value)))
                app.config.update({"SECURITY_RECOVERABLE": value})
                db.session.execute(update(ConfigSettings).filter(ConfigSettings.key == "SECURITY_RECOVERABLE")
                                   .values(value=pickle.dumps(value)))

                #  Users can always enable authenticator based 2FA. If email is enabled they can also use email based 2FA
                two_factor_methods = ["authenticator"]
                if value:
                    two_factor_methods.append("email")
                app.config.update({"SECURITY_TWO_FACTOR_ENABLED_METHODS": two_factor_methods})
                db.session.execute(
                    update(ConfigSettings).filter(ConfigSettings.key == "SECURITY_TWO_FACTOR_ENABLED_METHODS")
                    .values(value=pickle.dumps(two_factor_methods)))

                #  Users can always log in with usernames. If email is enabled they can also log in with email addresses
                identity_attributes = [{"username": {"mapper": uia_username_mapper, "case_insensitive": False}}]
                if value:
                    identity_attributes.append({"email": {"mapper": uia_email_mapper, "case_insensitive": True}})
                app.config.update({"SECURITY_USER_IDENTITY_ATTRIBUTES": identity_attributes})
                db.session.execute(
                    update(ConfigSettings).filter(ConfigSettings.key == "SECURITY_USER_IDENTITY_ATTRIBUTES")
                    .values(value=pickle.dumps(identity_attributes)))

                config.value = pickle.dumps(value)
                app.config.update({setting: value})
                db.session.add(config)

            elif setting == "OTS_ENABLE_MUMBLE_AUTHENTICATION" or setting.startswith("OTS_AIRPLANES_LIVE") or \
                    setting.startswith("MAIL"):

                config.value = pickle.dumps(value)
                app.config.update({setting: value})
                db.session.add(config)

        db.session.commit()
    except BaseException as e:
        db.session.rollback()
        logger.error(request.json)
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True})
