import traceback
from pprint import pprint

from flask_security import roles_required
from sqlalchemy import update, or_
import pickle

import bleach
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify

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

            logger.debug("Setting {} to {}".format(setting, value))
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
