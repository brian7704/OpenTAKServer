import hashlib
import os
import shutil
import traceback
import uuid
from datetime import datetime
from urllib.parse import urlparse
import zipfile

import bleach
import sqlalchemy
from flask import Blueprint, request, jsonify, current_app as app, send_from_directory
from flask_login import current_user
from flask_security import auth_required
from sqlalchemy import update
from werkzeug.datastructures import ImmutableMultiDict
from werkzeug.utils import secure_filename
from werkzeug.datastructures.file_storage import FileStorage

from xml.etree.ElementTree import Element, tostring, SubElement

from opentakserver.blueprints.api import search, paginate
from opentakserver.extensions import logger, db
from opentakserver.forms.data_package_form import DataPackageUpdateForm
from opentakserver.models.Certificate import Certificate
from opentakserver.models.DataPackage import DataPackage

data_package_api = Blueprint('data_package_api', __name__)


def save_data_package_to_db(filename: str = None, sha256_hash: str = None, mimetype: str = "application/zip", file_size: int = 0):
    try:
        data_package = DataPackage()
        data_package.filename = filename
        data_package.hash = sha256_hash
        data_package.creator_uid = request.args.get('creatorUid') if request.args.get('creatorUid') else str(
            uuid.uuid4())
        data_package.submission_user = current_user.id if current_user.is_authenticated else None
        data_package.submission_time = datetime.now()
        data_package.mime_type = mimetype
        data_package.size = file_size
        db.session.add(data_package)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        db.session.rollback()
        logger.error("Failed to save data package: {}".format(e))
        return jsonify({'success': False, 'error': 'This data package has already been uploaded'}), 400


def create_data_package_zip(file: FileStorage) -> str:
    filename, extension = os.path.splitext(secure_filename(file.filename))
    zipf = zipfile.ZipFile(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{filename}.zip"), "a", zipfile.ZIP_DEFLATED, False)

    # Use the md5 of the uploaded file as its folder name in the data package zip
    md5 = hashlib.md5()
    md5.update(file.stream.read())
    file.stream.seek(0)
    md5_hash = md5.hexdigest()

    zipf.writestr(f"{md5_hash}/{secure_filename(file.filename)}", file.stream.read())

    # MANIFEST file
    manifest = Element("MissionPackageManifest", {"version": "2"})
    config = SubElement(manifest, "Configuration")
    SubElement(config, "Parameter", {"name": "uid", "value": str(uuid.uuid4())})
    SubElement(config, "Parameter", {"name": "name", "value": secure_filename(file.filename)})

    contents = SubElement(manifest, "Contents")
    content = SubElement(contents, "Content", {"ignore": "false", "zipEntry": f"{md5_hash}/{secure_filename(file.filename)}"})

    filename, extension = os.path.splitext(secure_filename(file.filename))
    extension = extension.lower().replace(".", "")
    if extension == 'kml' or extension == 'kmz':
        SubElement(content, 'Parameter', {'name': 'name', 'value': secure_filename(file.filename)})
        SubElement(content, 'Parameter', {'name': 'contentType', 'value': 'KML'})
        SubElement(content, 'Parameter', {'name': 'visible', 'value': 'true'})

    zipf.writestr("MANIFEST/manifest.xml", tostring(manifest))
    zipf.close()

    # Get the sha256 hash of the data package zip for its file name on disk and for the data_packages table
    zip_file = open(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{filename}.zip"), 'rb')
    zip_file_bytes = zip_file.read()
    zip_file.close()

    sha256 = hashlib.sha256()
    sha256.update(zip_file_bytes)
    data_package_hash = sha256.hexdigest()

    os.rename(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{filename}.zip"), os.path.join(app.config.get("UPLOAD_FOLDER"), f"{data_package_hash}.zip"))
    save_data_package_to_db(f"{filename}.zip", data_package_hash, file.content_type, len(zip_file_bytes))

    return data_package_hash


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
    if not download_name.endswith('.zip'):
        download_name += ".zip"

    return send_from_directory(app.config.get("UPLOAD_FOLDER"), "{}.zip".format(file_hash), as_attachment=True,
                               download_name=download_name)


@data_package_api.route('/Marti/sync/missionupload', methods=['POST'])
def data_package_share():
    if not len(request.files):
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    for file in request.files:
        file = request.files[file]

        name, extension = os.path.splitext(file.filename)
        extension = extension.replace(".", "")

        # ATAK sends data packages as zips with a file name but no extension
        if not extension and 'zip' in file.mimetype:
            extension = 'zip'

        if extension.lower() not in app.config.get("ALLOWED_EXTENSIONS"):
            logger.info(f"file is {file.filename}, extension is {extension}, content-type {file.mimetype}")
            return jsonify({'success': False, 'error': f'Invalid file extension: {extension}'}), 400

        if extension != 'zip':
            file_hash = create_data_package_zip(file)

        else:
            file_hash = request.args.get('hash')
            if not file_hash:
                sha256 = hashlib.sha256()
                sha256.update(file.stream.read())
                file.stream.seek(0)
                file_hash = sha256.hexdigest()
                logger.debug("got sha256 {}".format(file_hash))

            logger.debug("Got file: {} - {}".format(file.filename, file_hash))

            file.save(os.path.join(app.config.get("UPLOAD_FOLDER"), f'{file_hash}.zip'))

            filename, extension = os.path.splitext(secure_filename(file.filename))
            file_size = os.path.getsize(os.path.join(app.config.get("UPLOAD_FOLDER"), f'{file_hash}.zip'))
            save_data_package_to_db(f'{filename}.zip', file_hash, file.content_type, file_size)

        url = urlparse(request.url_root)
        return 'https://{}:{}/Marti/api/sync/metadata/{}/tool'.format(url.hostname,
                                                                      app.config.get("OTS_MARTI_HTTPS_PORT"),
                                                                      file_hash), 200


@data_package_api.route('/api/data_packages', methods=['POST'])
@auth_required()
def upload_data_package():
    return data_package_share()


@data_package_api.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
def data_package_metadata(file_hash):
    if request.method == 'PUT':
        try:
            data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
            if data_package:
                data_package.keywords = bleach.clean(request.data.decode("utf-8"))
                db.session.add(data_package)
                db.session.commit()
                return '', 200
            else:
                return '', 404
        except BaseException as e:
            logger.error("Data package PUT failed: {}".format(e))
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500
    elif request.method == 'GET':
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
        return send_from_directory(app.config.get("UPLOAD_FOLDER"), data_package.hash + ".zip",
                                   download_name=data_package.filename)


@data_package_api.route('/Marti/sync/search', methods=['GET'])
def data_package_search():
    data_packages = db.session.execute(db.select(DataPackage)).scalars()
    res = {'resultCount': 0, 'results': []}
    for dp in data_packages:
        submission_user = "anonymous"
        if dp.user:
            submission_user = dp.user.username
        res['results'].append(
            {'UID': dp.hash, 'Name': dp.filename, 'Hash': dp.hash, 'CreatorUid': dp.creator_uid,
             "SubmissionDateTime": dp.submission_time.strftime('%Y-%m-%dT%H:%M:%S.000Z'), "EXPIRATION": "-1",
             "Keywords": ["missionpackage"],
             "MIMEType": dp.mime_type, "Size": "{}".format(dp.size), "SubmissionUser": submission_user,
             "PrimaryKey": "{}".format(dp.id),
             "Tool": dp.tool if dp.tool else "public"
             })
        res['resultCount'] += 1

    return jsonify(res)


@data_package_api.route('/Marti/sync/content', methods=['GET'])
def download_data_package():
    file_hash = request.args.get('hash')
    data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()

    return send_from_directory(app.config.get("UPLOAD_FOLDER"), f"{file_hash}.zip", download_name=data_package.filename)


@data_package_api.route('/Marti/sync/upload', methods=['POST'])
def itak_data_package_upload():
    if not request.content_length:
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    elif request.content_type != 'application/x-zip-compressed':
        logger.error("Not a zip")
        return {'error': 'Please only upload zip files'}, 415, {'Content-Type': 'application/json'}

    file = request.data
    sha256 = hashlib.sha256()
    sha256.update(file)
    file_hash = sha256.hexdigest()
    logger.debug("got sha256 {}".format(file_hash))
    hash_filename = secure_filename(file_hash + '.zip')

    with open(os.path.join(app.config.get("UPLOAD_FOLDER"), hash_filename), "wb") as f:
        f.write(file)

    try:
        data_package = DataPackage()
        data_package.filename = request.args.get('name')
        data_package.hash = file_hash
        data_package.creator_uid = request.args.get('CreatorUid') if request.args.get('CreatorUid') else str(
            uuid.uuid4())
        data_package.submission_user = current_user.id if current_user.is_authenticated else None
        data_package.submission_time = datetime.now()
        data_package.mime_type = request.content_type
        data_package.size = os.path.getsize(os.path.join(app.config.get("UPLOAD_FOLDER"), hash_filename))
        db.session.add(data_package)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError as e:
        db.session.rollback()
        logger.error("Failed to save data package: {}".format(e))
        return jsonify({'success': False, 'error': 'This data package has already been uploaded'}), 400

    return_value = {"UID": data_package.hash, "SubmissionDateTime": data_package.submission_time,
                    "Keywords": ["missionpackage"],
                    "MIMEType": data_package.mime_type, "SubmissionUser": "anonymous", "PrimaryKey": "1",
                    "Hash": data_package.hash, "CreatorUid": data_package.creator_uid, "Name": data_package.filename}

    return jsonify(return_value)


@data_package_api.route('/Marti/sync/missionquery')
def data_package_query():
    try:
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=request.args.get('hash'))).scalar_one()
        if data_package:

            url = urlparse(request.url_root)
            return 'https://{}:{}/Marti/api/sync/metadata/{}/tool'.format(url.hostname,
                                                                          app.config.get("OTS_MARTI_HTTPS_PORT"),
                                                                          request.args.get('hash')), 200
        else:
            return {'error': '404'}, 404, {'Content-Type': 'application/json'}
    except sqlalchemy.exc.NoResultFound as e:
        return {'error': '404'}, 404, {'Content-Type': 'application/json'}
