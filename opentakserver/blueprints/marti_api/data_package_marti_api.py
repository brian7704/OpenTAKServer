import hashlib
import os
import traceback
import uuid
from datetime import datetime
from urllib.parse import urlparse
import zipfile

import bleach
import sqlalchemy
from flask import Blueprint, request, jsonify, current_app as app, send_from_directory
from flask_login import current_user
from werkzeug.utils import secure_filename
from werkzeug.datastructures.file_storage import FileStorage

from xml.etree.ElementTree import Element, tostring, SubElement

from opentakserver.extensions import logger, db
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.MissionContent import MissionContent

data_package_marti_api = Blueprint('data_package_marti_api', __name__)


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


@data_package_marti_api.route('/Marti/sync/missionupload', methods=['POST'])
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


@data_package_marti_api.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
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


@data_package_marti_api.route('/Marti/sync/search', methods=['GET'])
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


@data_package_marti_api.route('/Marti/sync/content', methods=['GET', 'HEAD'])
def download_data_package():
    file_hash = request.args.get('hash')
    file = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).first()
    if not file:
        file = db.session.execute(db.select(MissionContent).filter_by(hash=file_hash)).first()
    if not file and request.method == 'HEAD':
        return '', 404
    elif not file:
        return jsonify({'success': False, 'error': f'No data package found with hash {file_hash}'}), 404
    elif file and request.method == 'HEAD':
        return '', 200

    filename, extension = os.path.splitext(secure_filename(file[0].filename))
    if os.path.exists(os.path.join(app.config.get("UPLOAD_FOLDER"), f"{file_hash}{extension}")):
        return send_from_directory(app.config.get("UPLOAD_FOLDER"), f"{file_hash}{extension}", download_name=file[0].filename)
    elif os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions", file[0].filename)):
        return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "missions"), file[0].filename)
    else:
        return jsonify({'success': False, 'error': f'File not found: {file[0].filename}'}), 404


@data_package_marti_api.route('/Marti/sync/missionquery')
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