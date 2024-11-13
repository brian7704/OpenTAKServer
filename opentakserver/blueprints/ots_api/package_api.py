import csv
import datetime
import os
import zipfile

import sqlalchemy.exc
from flask import current_app as app, request, Blueprint, jsonify, send_from_directory
from flask_security import roles_accepted, auth_required
from werkzeug.datastructures import ImmutableMultiDict

from opentakserver.forms.package_form import PackageForm, PackageUpdateForm
from opentakserver.models.Packages import Packages
from opentakserver.extensions import db
from opentakserver.blueprints.ots_api.api import search, paginate
from opentakserver.blueprints.marti_api.certificate_enrollment_api import basic_auth

from werkzeug.utils import secure_filename

packages_blueprint = Blueprint('packages_api_blueprint', __name__)


@packages_blueprint.route('/api/packages/<package_name>')
def download_package(package_name):
    if not basic_auth(request.headers.get('Authorization')):
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

    return paginate(query)


@packages_blueprint.route('/api/packages/product.infz', methods=['HEAD'])
@auth_required("session", "token", "basic")
@roles_accepted("user", "administrator")
def head_product_infz():
    return jsonify({'success': True})


@packages_blueprint.route('/api/packages/product.infz', methods=['GET'])
@auth_required("session", "token", "basic")
@roles_accepted("user", "administrator")
def get_product_infz():
    return send_from_directory(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages"), "product.infz")


def create_product_infz():
    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.infz")):
        os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.infz"))
    packages = db.session.execute(db.session.query(Packages)).all()

    with zipfile.ZipFile(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.infz"), mode='a',
                         compression=zipfile.ZIP_DEFLATED) as zipf:

        with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.inf"), "w") as inf:
            csv_writer = csv.writer(inf)

            for package in packages:
                package = package[0]
                csv_writer.writerow([package.platform, package.plugin_type, package.package_name,
                                     package.name, package.version, package.revision_code, package.file_name,
                                     package.icon_filename, package.description, package.apk_hash, package.os_requirement,
                                     package.tak_prereq, package.file_size])

                if package.icon:
                    zipf.writestr(package.icon_filename, package.icon)

        zipf.write(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.inf"), arcname="product.inf")
        os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", "product.inf"))


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

    try:
        db.session.add(package)
        db.session.commit()
    except sqlalchemy.exc.IntegrityError:
        db.session.rollback()
        db.session.execute(sqlalchemy.update(Packages).where(Packages.package_name == package.package_name).values(**package.serialize()))
        db.session.commit()

    create_product_infz()

    return jsonify({'success': True})


@packages_blueprint.route('/api/packages', methods=['PATCH'])
@auth_required()
@roles_accepted("administrator")
def edit_package():
    form = PackageUpdateForm(formdata=ImmutableMultiDict(request.json))
    if not form.validate():
        return jsonify({'success': False, 'errors': form.errors}), 400

    package = db.session.execute(db.session.query(Packages).filter_by(package_name=form.package_name.data)).first()
    if not package:
        return jsonify({'success': False, 'error': f"{form.package_name.data} not found"}), 404

    package = package[0]
    package.install_on_enrollment = form.install_on_enrollment.data
    package.install_on_connection = form.install_on_connection.data
    package.publish_time = datetime.datetime.now()

    db.session.execute(sqlalchemy.update(Packages).where(Packages.package_name == form.package_name.data).values(**package.serialize()))
    db.session.commit()

    return jsonify({'success': True})


@packages_blueprint.route('/api/packages', methods=['DELETE'])
@auth_required()
@roles_accepted("administrator")
def delete_package():
    package_name = request.args.get("package_name")
    if not package_name:
        return jsonify({'success': False, 'error': 'Please provide the package name of the plugin to delete'}), 400

    query = db.session.query(Packages)
    query = search(query, Packages, 'package_name')
    package = db.session.execute(query).first()
    if not package:
        return jsonify({'success': False, 'error': f'Unknown package name: {package_name}'}), 404

    package = package[0]
    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", package.file_name)):
        os.remove(os.path.join(app.config.get("OTS_DATA_FOLDER"), "packages", package.file_name))

    db.session.delete(package)
    db.session.commit()

    create_product_infz()

    return jsonify({'success': True})
