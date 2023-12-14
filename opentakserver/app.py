import datetime
import hashlib
import os
import ssl
import sys
import traceback
import uuid
from shutil import copyfile
from gevent.pywsgi import WSGIServer

import bleach
import pika
from flask import Flask, request, render_template_string
import socket
import threading

# from flask_socketio import SocketIO

from flask_security import Security, SQLAlchemyUserDatastore, auth_required, hash_password, current_user, roles_accepted
from flask_security.models import fsqla_v3 as fsqla

from extensions import logger, db

from AtakOfTheCerts import AtakOfTheCerts
from config import Config

from controllers.client_controller import ClientController
from controllers.cot_controller import CoTController
from opentakserver.models.DataPackage import DataPackage

app = Flask(__name__)
app.config.from_object(Config)

from blueprints.marti import marti_blueprint
app.register_blueprint(marti_blueprint)

from blueprints.api import api_blueprint
app.register_blueprint(api_blueprint)

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
@roles_accepted("administrator")
def home():
    return render_template_string('Hello {{current_user.username}}!')


@app.route("/api/certificate", methods=['GET', 'POST'])
def certificate():
    if request.method == 'POST' and 'common_name' in request.form.keys():
        try:
            common_name = bleach.clean(request.form.get('common_name'))
            aotc.issue_certificate(hostname=common_name, common_name=common_name, cert_password=Config.CERT_PASSWORD)
            filename = aotc.generate_zip(server_address=Config.SERVER_DOMAIN_OR_IP,
                                         server_filename=os.path.join(Config.CA_FOLDER, 'certs',
                                                                      Config.SERVER_DOMAIN_OR_IP,
                                                                      "{}.p12".format(Config.SERVER_DOMAIN_OR_IP)),
                                         user_filename=os.path.join(Config.CA_FOLDER, 'certs', common_name,
                                                                    "{}.p12".format(common_name)))
            file_hash = hashlib.file_digest(open(os.path.join(Config.CA_FOLDER, 'certs', common_name, filename),
                                                 'rb'), 'sha256').hexdigest()
            data_package = DataPackage()
            data_package.filename = filename
            data_package.keywords = "public"
            data_package.creator_uid = str(uuid.uuid4())
            data_package.submission_time = datetime.datetime.now().isoformat() + "Z"
            data_package.mime_type = "application/x-zip-compressed"
            data_package.size = os.path.getsize(os.path.join(Config.CA_FOLDER, 'certs', common_name, filename))
            data_package.hash = file_hash
            db.session.add(data_package)
            db.session.commit()

            copyfile(os.path.join(Config.CA_FOLDER, 'certs', common_name, "{}_DP.zip".format(common_name)),
                     os.path.join(Config.UPLOAD_FOLDER, "{}.zip".format(file_hash)))

            return '', 200
        except BaseException as e:
            logger.error(traceback.format_exc())
            return {'error': str(e)}, 500, {'Content-Type': 'application/json'}


def launch_ssl_server():
    lock = threading.Lock()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

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
            try:
                conn, addr = sconn.accept()
            except ssl.SSLError:
                # Prevents crashing this thread if a client tries to connect without using SSL
                continue
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

    http_server = WSGIServer(('0.0.0.0', Config.HTTP_PORT), app)
    http_server.start()

    https_server = WSGIServer(('0.0.0.0', Config.HTTPS_PORT), app,
                              keyfile=os.path.join(Config.CA_FOLDER, 'certs', Config.SERVER_DOMAIN_OR_IP,
                                                   Config.SERVER_DOMAIN_OR_IP + ".pem"),
                              certfile=os.path.join(Config.CA_FOLDER, 'certs', Config.SERVER_DOMAIN_OR_IP,
                                                    Config.SERVER_DOMAIN_OR_IP + ".crt"))

    try:
        https_server.serve_forever()
    except KeyboardInterrupt:
        sys.exit()
