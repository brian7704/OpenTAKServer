import os
import shutil
import traceback
from datetime import datetime

from flask import Blueprint, request, jsonify, current_app as app, send_from_directory
from flask_security import auth_required
from sqlalchemy import update
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.blueprints.marti_api.data_package_marti_api import data_package_share
from opentakserver.extensions import logger, db
from opentakserver.forms.data_package_form import DataPackageUpdateForm
from opentakserver.models.Certificate import Certificate
from opentakserver.models.DataPackage import DataPackage

data_package_api = Blueprint('data_package_api', __name__)


@data_package_api.route('/api/data_packages', methods=['PATCH'])
@auth_required()
def edit_data_package():
    form = DataPackageUpdateForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    data_package = db.session.execute(db.session.query(DataPackage).filter_by(hash=form.hash.data)).first()
    if not data_package:
        return jsonify({'success': False, 'error': f"Package with hash {form.hash.data} not found"}), 404

    data_package = data_package[0]

    if data_package.filename.endswith("_CONFIG.zip"):
        return jsonify({'success': False, 'error': "Server connection data packages can't be installed on enrollment or connection"}), 400

    if form.install_on_enrollment.data is not None:
        data_package.install_on_enrollment = form.install_on_enrollment.data
    if form.install_on_connection.data is not None:
        data_package.install_on_connection = form.install_on_connection.data

    data_package.submission_time = datetime.now()

    db.session.execute(update(DataPackage).filter(DataPackage.hash == data_package.hash).values(**data_package.serialize()))
    db.session.commit()

    return jsonify({'success': True})


@data_package_api.route('/api/data_packages', methods=['DELETE'])
@auth_required()
def delete_data_package():
    file_hash = request.args.get('hash')
    if not file_hash:
        return jsonify({'success': False, 'error': 'Please provide a file hash'}), 400

    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'hash')
    data_package = db.session.execute(query).first()
    if not data_package:
        return jsonify({'success': False, 'error': 'Invalid/unknown hash'}), 400

    try:
        logger.warning("Deleting data package {} - {}".format(data_package[0].filename, data_package[0].hash))
        db.session.delete(data_package[0])
        db.session.commit()
        os.remove(os.path.join(app.config.get("UPLOAD_FOLDER"), "{}.zip".format(data_package[0].hash)))

        if data_package[0].certificate:
            Certificate.query.filter_by(id=data_package[0].certificate.id).delete()
            db.session.commit()
            shutil.rmtree(
                os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", data_package[0].certificate.common_name),
                ignore_errors=True)
    except BaseException as e:
        logger.error("Failed to delete data package")
        logger.error(traceback.format_exc())
        return jsonify({'success': False, 'error': str(e)}), 500

    return jsonify({'success': True})


@data_package_api.route('/api/data_packages')
@auth_required()
def data_packages():
    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'filename')
    query = search(query, DataPackage, 'hash')
    query = search(query, DataPackage, 'createor_uid')
    query = search(query, DataPackage, 'keywords')
    query = search(query, DataPackage, 'mime_type')
    query = search(query, DataPackage, 'size')
    query = search(query, DataPackage, 'tool')

    return paginate(query)


@data_package_api.route('/api/data_packages/download')
@auth_required()
def data_package_download():
    if 'hash' not in request.args.keys():
        return ({'success': False, 'error': 'Please provide a data package hash'}, 400,
                {'Content-Type': 'application/json'})

    file_hash = request.args.get('hash')

    query = db.session.query(DataPackage)
    query = search(query, DataPackage, 'hash')

    data_package = db.session.execute(query).first()

    if not data_package:
        return ({'success': False, 'error': "Data package with hash '{}' not found".format(file_hash)}, 404,
                {'Content-Type': 'application/json'})

    download_name = data_package[0].filename
    name, extension = os.path.splitext(download_name)

    return send_from_directory(app.config.get("UPLOAD_FOLDER"), f"{file_hash}{extension}", as_attachment=True,
                               download_name=download_name)


@data_package_api.route('/api/data_packages', methods=['POST'])
@auth_required()
def upload_data_package():
    return data_package_share()
