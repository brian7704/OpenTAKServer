import csv
import datetime
import os
import zipfile

import bleach
import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import roles_accepted, auth_required
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.blueprints.marti_api.marti_api import verify_client_cert
from opentakserver.forms.package_form import PackageForm, PackageUpdateForm
from opentakserver.models.Packages import Packages
from opentakserver.extensions import db, logger
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.blueprints.marti_api.certificate_enrollment_api import basic_auth

from werkzeug.utils import secure_filename

packages_blueprint = Blueprint('packages_api_blueprint', __name__)


@packages_blueprint.route('/api/packages/<package_name>')
@packages_blueprint.route('/api/packages/<atak_version>/<package_name>')
def download_package(package_name, atak_version=None):
    cert = verify_client_cert()
    if not cert:
        return '', 401
    return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages"), secure_filename(package_name))


@packages_blueprint.route('/api/packages')
@auth_required()
@roles_accepted("administrator")
def get_packages():
    query = db.session.query(Packages)
    query = search(query, Packages, 'platform')
    query = search(query, Packages, 'plugin_type')
    query = search(query, Packages, 'package_name')
    query = search(query, Packages, 'name')
    query = search(query, Packages, 'file_name')
    query = search(query, Packages, 'version')
    query = search(query, Packages, 'revision_code')
    query = search(query, Packages, 'apk_hash')
    query = search(query, Packages, 'tak_prereq')
    query = search(query, Packages, 'file_size')
    query = search(query, Packages, 'atak_version')

    return paginate(query)


@packages_blueprint.route('/api/packages/product.infz', methods=['HEAD'])
def head_product_infz():
    cert = verify_client_cert()
    if not cert:
        return '', 401

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.infz")):
        return jsonify({'success': True})

    return jsonify({'success': False}), 404


@packages_blueprint.route('/api/packages/<atak_version>/product.infz', methods=['HEAD'])
def head_product_infz_with_version(atak_version: str):
    cert = verify_client_cert()
    if not cert:
        return '', 401

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", atak_version, "product.infz")):
        return jsonify({'success': True})

    return jsonify({'success': False}), 404


@packages_blueprint.route('/api/packages/product.infz', methods=['GET'])
def get_product_infz():
    cert = verify_client_cert()
    if not cert:
        return '', 401
    return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages"), "product.infz")


@packages_blueprint.route('/api/packages/<atak_version>/product.infz', methods=['GET'])
def get_product_infz_with_version(atak_version: str):
    cert = verify_client_cert()
    if not cert:
        return '', 401
    return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", atak_version), "product.infz")


def create_product_infz(atak_version: str | None):
    product_infz_file = os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.infz")
    product_inf_file = os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.inf")

    if atak_version:
        atak_version = bleach.clean(atak_version)
        product_infz_file = os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", atak_version, "product.infz")
        product_inf_file = os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", atak_version, "product.inf")
        os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", atak_version), exist_ok=True)

    if os.path.exists(product_infz_file):
        os.remove(product_infz_file)

    query = db.session.query(Packages)
    if atak_version:
        query = query.where(Packages.atak_version == atak_version)
    packages = db.session.execute(query).all()

    with zipfile.ZipFile(product_infz_file, mode='a', compression=zipfile.ZIP_DEFLATED) as zipf:

        with open(product_inf_file, "w") as inf:
            csv_writer = csv.writer(inf)

            for package in packages:
                package = package[0]
                csv_writer.writerow([package.platform, package.plugin_type, package.package_name,
                                     package.name, package.version, package.revision_code, package.file_name,
                                     package.icon_filename, package.description, package.apk_hash, package.os_requirement,
                                     package.tak_prereq, package.file_size])

                if package.icon:
                    zipf.writestr(package.icon_filename, package.icon)

        zipf.write(product_inf_file, arcname="product.inf")
        os.remove(product_inf_file)


@packages_blueprint.route('/api/packages/repositories.inf')
def get_repository_inf():
    cert = verify_client_cert()
    if not cert:
        return '', 401

    versions = Packages.query.distinct(Packages.atak_version).where(Packages.atak_version is not None).all()
    if not versions:
        return "", 404

    response = ""
    for version in versions:
        if version.atak_version:
            response += version.atak_version + "\n"

    return response, 200


@packages_blueprint.route('/api/packages', methods=['POST'])
@auth_required()
@roles_accepted("administrator")
def add_package():
    form = PackageForm()
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages"), exist_ok=True)

    apk_filename = secure_filename(request.files['apk'].filename)

    request.files['apk'].save(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", apk_filename))

    package = Packages()
    package.from_wtform(form)

    existing_package = db.session.execute(db.session.query(Packages).filter_by(package_name=package.package_name, atak_version=package.atak_version)).scalar()
    if existing_package:
        logger.warning(f"{package.name} version {package.version} for ATAK {package.atak_version} is already on the server and will be removed")

        if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", existing_package.file_name)):
            os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", existing_package.file_name))

        db.session.delete(existing_package)

    try:
        db.session.add(package)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        db.session.execute(sqlalchemy.update(Packages).where(Packages.package_name == package.package_name).values(**package.serialize()))
        db.session.commit()

    create_product_infz(form.atak_version.data)

    return jsonify({'success': True})


@packages_blueprint.route('/api/packages', methods=['PATCH'])
@auth_required()
@roles_accepted("administrator")
def edit_package():
    form = PackageUpdateForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    package = db.session.execute(db.session.query(Packages).filter_by(package_name=form.package_name.data, atak_version=form.atak_version.data)).first()
    if not package:
        return jsonify({'success': False, 'error': f"{form.package_name.data} not found"}), 404

    package = package[0]
    package.install_on_enrollment = form.install_on_enrollment.data
    package.install_on_connection = form.install_on_connection.data
    package.publish_time = datetime.datetime.now(datetime.timezone.utc)

    db.session.execute(sqlalchemy.update(Packages).where(Packages.package_name == form.package_name.data).where(Packages.atak_version == form.atak_version.data).values(**package.serialize()))
    db.session.commit()

    return jsonify({'success': True})


@packages_blueprint.route('/api/packages', methods=['DELETE'])
@auth_required()
@roles_accepted("administrator")
def delete_package():
    package_name = request.args.get("package_name")
    if not package_name:
        return jsonify({'success': False, 'error': 'Please provide the package name of the plugin to delete'}), 400

    atak_version = None

    query = db.session.query(Packages)
    query = search(query, Packages, 'package_name')
    if request.args.get('atak_version'):
        atak_version = bleach.clean(request.args.get("atak_version"))
        query = query.where(Packages.atak_version == atak_version)

    package = db.session.execute(query).first()
    if not package:
        return jsonify({'success': False, 'error': f'Unknown package name: {package_name}'}), 404

    package = package[0]
    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", package.file_name)):
        os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", package.file_name))

    db.session.delete(package)
    db.session.commit()

    create_product_infz(atak_version)

    return jsonify({'success': True})
