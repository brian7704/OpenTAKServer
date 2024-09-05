import datetime
import hashlib

from flask import Blueprint, request, jsonify, current_app as app
from flask_security import auth_required, current_user, roles_required
from sqlalchemy import insert, update
from sqlalchemy.exc import IntegrityError
from werkzeug.utils import secure_filename

from opentakserver.extensions import db, logger
from opentakserver.forms.device_profile_form import DeviceProfileForm
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.DeviceProfiles import DeviceProfiles

device_profile_api_blueprint = Blueprint('device_profile_api_blueprint', __name__)


@device_profile_api_blueprint.route('/api/profile')
@roles_required("administrator")
def get_device_profiles():
    return


@device_profile_api_blueprint.route('/api/profile', methods=['POST'])
@roles_required("administrator")
def add_device_profile():
    form = DeviceProfileForm()
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400
    elif "zip" not in form.data_package.data.mimetype:
        return jsonify({'success': False, 'error': 'Only data package zip files are allowed'}), 400

    device_profile = DeviceProfiles()
    device_profile.from_wtf(form)

    try:
        device_profile_id = db.session.add(device_profile)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        device_profile_id = db.session.execute(update(DeviceProfiles).where(DeviceProfiles.name == device_profile.name)
                                               .values(**device_profile.serialize()))

    sha256 = hashlib.sha256()
    sha256.update(form.data_package.data.stream.read())
    form.data_package.data.stream.seek(0)
    file_hash = sha256.hexdigest()

    data_package = DataPackage()
    data_package.filename = secure_filename(form.data_package.data.filename)
    data_package.hash = file_hash
    data_package.submission_time = datetime.datetime.now()
    data_package.submission_user = current_user.id
    data_package.mime_type = form.data_package.data.mimetype
    data_package.size = form.data_package.data.stream.tell()

    try:
        data_package_id = db.session.add(data_package)
        db.session.commit()
    except IntegrityError:
        db.session.rollback()
        dp = db.session.execute(db.session.query(DataPackage).filter_by(hash=data_package.hash)).first()[0]
        data_package_id = dp.id

    form.data_package.data.save(app.config.get("UPLOAD_FOLDER"), f"{file_hash}.zip")

    return '', 200


@device_profile_api_blueprint.route('/api/profile', methods=['DELETE'])
@roles_required("administrator")
def delete_device_profile():
    return
