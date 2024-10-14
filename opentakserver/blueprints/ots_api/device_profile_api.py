import traceback

from flask import Blueprint, request, jsonify
from flask_security import auth_required, roles_required
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError

from opentakserver.extensions import db, logger
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.models.DeviceProfiles import DeviceProfiles
from opentakserver.blueprints.ots_api.api import search, paginate

device_profile_api_blueprint = Blueprint('device_profile_api_blueprint', __name__)


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
