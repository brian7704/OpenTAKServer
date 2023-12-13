import datetime
import json
import os
import ssl
import sys
import traceback

import bleach
import pika
import sqlalchemy
from flask import Flask, request, send_from_directory, render_template_string
import socket
import threading

from werkzeug.utils import secure_filename

# from flask_socketio import SocketIO

from flask_security import Security, SQLAlchemyUserDatastore, auth_required, hash_password, current_user, roles_accepted
from flask_security.models import fsqla_v3 as fsqla

from extensions import logger, db

from AtakOfTheCerts import AtakOfTheCerts
from config import Config

from controllers.client_controller import ClientController
from controllers.cot_controller import CoTController
from models.DataPackage import DataPackage
from opentakserver.models.EUD import EUD

app = Flask(__name__)
app.config.from_object(Config)
# socketio = SocketIO(app)
db.init_app(app)
fsqla.FsModels.set_db_info(db)

from models.user import User
from models.role import Role

user_datastore = SQLAlchemyUserDatastore(db, User, Role)
app.security = Security(app, user_datastore)

rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = rabbit_connection.channel()
channel.exchange_declare('cot', durable=True, exchange_type='fanout')
channel.exchange_declare('dms', durable=True, exchange_type='direct')
channel.exchange_declare('chatrooms', durable=True, exchange_type='direct')


def atak_of_the_certs():
    logger.info("Loading CA...")

    aotc = AtakOfTheCerts(logger=logger, pwd=Config.CERT_PASSWORD, ca_storage=Config.CA_FOLDER,
                          common_name=Config.SERVER_DOMAIN_OR_IP + "-CA", maximum_days=Config.CA_EXPIRATION_TIME)

    if Config.SERVER_DOMAIN_OR_IP not in aotc.certificates:
        aotc.issue_certificate(hostname=Config.SERVER_DOMAIN_OR_IP, maximum_days=Config.CA_EXPIRATION_TIME,
                               common_name=Config.SERVER_DOMAIN_OR_IP, ca=False)

        logger.info("Created Server Cert")

    logger.info("CA loaded!")
    return aotc


aotc = atak_of_the_certs()


@app.route("/")
@auth_required()
def home():
    return render_template_string('Hello {{current_user.username}}!')


@app.route('/Marti/api/clientEndPoints', methods=['GET'])
def client_end_points():
    euds = db.session.execute(db.select(EUD)).scalars()
    return_value = {'version': 3, "type": "com.bbn.marti.remote.ClientEndpoint", 'data': [], 'nodeId': Config.NODE_ID}
    for eud in euds:
        return_value['data'].append({
            'callsign': eud.callsign,
            'uid': eud.uid,
            'username': 'anonymous',  # TODO: change this once auth is working
            'lastEventTime': eud.last_event_time,
            'lastStatus': eud.last_status
        })

    return return_value, 200, {'Content-Type': 'application/json'}


@app.route('/Marti/api/version/config', methods=['GET'])
def marti_config():
    return {"version": "3", "type": "ServerConfig",
            "data": {"version": Config.VERSION, "api": "3", "hostname": Config.SERVER_DOMAIN_OR_IP},
            "nodeId": Config.NODE_ID}, 200, {'Content-Type': 'application/json'}


@app.route('/Marti/sync/missionupload', methods=['POST'])
def data_package_share():
    if not len(request.files):
        return {'error': 'no file'}, 400, {'Content-Type': 'application/json'}
    for file in request.files:
        file = request.files[file]
        logger.debug("Got file: {} - {}".format(file.filename, request.args.get('hash')))
        if file:
            file_hash = request.args.get('hash')
            if file.content_type != 'application/x-zip-compressed':
                return {'error': 'Please only upload zip files'}, 415, {'Content-Type': 'application/json'}
            filename = secure_filename(file_hash + '.zip')
            file.save(os.path.join(Config.UPLOAD_FOLDER, filename))

            try:
                data_package = DataPackage()
                data_package.filename = file.filename
                data_package.hash = file_hash
                data_package.creator_uid = request.args.get('creatorUid')
                data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
                data_package.mime_type = file.mimetype
                data_package.size = os.path.getsize(os.path.join(Config.UPLOAD_FOLDER, filename))
                db.session.add(data_package)
                db.session.commit()
            except sqlalchemy.exc.IntegrityError as e:
                db.session.rollback()
                logger.error("Failed to save data package: {}".format(e))

            return 'http://{}:{}/Marti/api/sync/metadata/{}/tool'.format(
                Config.SERVER_DOMAIN_OR_IP, Config.HTTP_PORT, file_hash), 200


@app.route('/Marti/api/sync/metadata/<file_hash>/tool', methods=['GET', 'PUT'])
def data_package_metadata(file_hash):
    if request.method == 'PUT':
        try:
            data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()
            if data_package:
                data_package.keywords = request.data
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
        return send_from_directory(Config.UPLOAD_FOLDER, data_package.hash + ".zip",
                                   download_name=data_package.filename)


@app.route('/Marti/sync/missionquery')
def data_package_query():
    try:
        data_package = db.session.execute(db.select(DataPackage).filter_by(hash=request.args.get('hash'))).scalar_one()
        if data_package:
            return 'http://{}/Marti/api/sync/metadata/{}/tool'.format(
                request.headers.get('Host'), request.args.get('hash')), 200
        else:
            return {'error': '404'}, 404, {'Content-Type': 'application/json'}
    except sqlalchemy.exc.NoResultFound as e:
        logger.error("Failed to get dps: {}".format(e))
        return {'error': '404'}, 404, {'Content-Type': 'application/json'}


@app.route('/Marti/sync/search', methods=['GET'])
def data_package_search():
    data_packages = db.session.execute(db.select(DataPackage)).scalars()
    res = {'resultCount': 0, 'results': []}
    for dp in data_packages:
        res['results'].append(
            {'UID': dp.hash, 'Name': dp.filename, 'Hash': dp.hash, 'CreatorUid': dp.creator_uid,
             "SubmissionDateTime": dp.submission_time, "Expiration": -1, "Keywords": "[missionpackage]",
             "MIMEType": dp.mime_type, "Size": dp.size, "SubmissionUser": "anonymous", "PrimaryKey": dp.id,
             "Tool": "public"
             })
        res['resultCount'] += 1

    return json.dumps(res), 200, {'Content-Type': 'application/json'}


@app.route('/Marti/sync/content', methods=['GET'])
def download_data_package():
    file_hash = request.args.get('hash')
    data_package = db.session.execute(db.select(DataPackage).filter_by(hash=file_hash)).scalar_one()

    return send_from_directory(Config.UPLOAD_FOLDER, file_hash + ".zip", download_name=data_package.filename)


@roles_accepted("administrator")
@app.route("/api/certificate", methods=['GET', 'POST'])
def certificate():
    if request.method == 'POST' and 'common_name' in request.form.keys():
        try:
            common_name = bleach.clean(request.form.get('common_name'))
            aotc.issue_certificate(hostname=common_name, common_name=common_name, cert_password=Config.CERT_PASSWORD)
            aotc.generate_zip(server_address=Config.SERVER_DOMAIN_OR_IP,
                              server_filename=os.path.join(Config.CA_FOLDER, 'certs', Config.SERVER_DOMAIN_OR_IP,
                                                           "{}.p12".format(Config.SERVER_DOMAIN_OR_IP)),
                              user_filename=os.path.join(Config.CA_FOLDER, 'certs', common_name,
                                                         "{}.p12".format(common_name)))
            return '', 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500, {'Content-Type': 'application/json'}


def launch_ssl_server():
    lock = threading.Lock()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        logger.error(os.path.join(Config.CA_FOLDER, "ca.crt"))
        # logger.error("{} {}".format(os.path.join(Config.CA_FOLDER, "ca.crt")), os.path.join(Config.CA_FOLDER, "private", "ca_key.pem"))

        context.load_cert_chain(os.path.join(Config.CA_FOLDER, "certs", Config.SERVER_DOMAIN_OR_IP,
                                             Config.SERVER_DOMAIN_OR_IP + ".crt"),
                                os.path.join(Config.CA_FOLDER, "certs", Config.SERVER_DOMAIN_OR_IP,
                                             Config.SERVER_DOMAIN_OR_IP + ".pem"))
        context.verify_mode = ssl.CERT_REQUIRED
        context.load_verify_locations(os.path.join(Config.CA_FOLDER, 'ca.crt'))
        sconn = context.wrap_socket(sock, server_side=True)
        sconn.bind(('0.0.0.0', Config.COT_SSL_PORT))
        sconn.listen(0)

        while True:
            conn, addr = sconn.accept()
            logger.info("New SSL connection from {}".format(addr[0]))
            new_thread = ClientController(addr[0], addr[1], conn, lock, logger, app.app_context())
            new_thread.daemon = True
            new_thread.start()


def launch_tcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', Config.COT_STREAMING_PORT))
    s.listen(1)
    lock = threading.Lock()

    while True:
        try:
            sock, addr = s.accept()
            logger.info("New TCP connection from {}".format(addr[0]))
            new_thread = ClientController(addr[0], addr[1], sock, lock, logger, app.app_context())
            new_thread.daemon = True
            new_thread.start()
        except KeyboardInterrupt:
            break


if __name__ == '__main__':
    with app.app_context():
        logger.debug("Creating DB")
        try:
            db.create_all()
        except BaseException as e:
            logger.error("Error creating DB: {}".format(e))
            logger.error(traceback.format_exc())

        app.security.datastore.find_or_create_role(
            name="user", permissions={"user-read", "user-write"}
        )
        app.security.datastore.find_or_create_role(
            name="administrator", permissions={"administrator"}
        )
        db.session.commit()
        if not app.security.datastore.find_user(username="administrator"):
            logger.info("Creating administrator account. The password is 'password'")
            app.security.datastore.create_user(username="administrator",
                                               password=hash_password("password"), roles=["administrator"])
        db.session.commit()

    tcp_thread = threading.Thread(target=launch_tcp_server)
    tcp_thread.daemon = True
    tcp_thread.start()

    ssl_thread = threading.Thread(target=launch_ssl_server)
    ssl_thread.daemon = True
    ssl_thread.start()

    cot_thread = CoTController(app.app_context(), logger, db)
    cot_thread.daemon = True
    cot_thread.start()

    app.run(host='0.0.0.0', debug=True, use_reloader=False, port=Config.HTTPS_PORT,
            ssl_context=(os.path.join(Config.CA_FOLDER, 'certs', Config.SERVER_DOMAIN_OR_IP,
                                      Config.SERVER_DOMAIN_OR_IP + ".crt"),
                         os.path.join(Config.CA_FOLDER, 'certs', Config.SERVER_DOMAIN_OR_IP,
                                      Config.SERVER_DOMAIN_OR_IP + ".pem")))
