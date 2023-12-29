import os
import ssl
import sys
import traceback

import flask_wtf
from gevent.pywsgi import WSGIServer

import pika
from flask import Flask, jsonify
from flask_cors import CORS
import socket
import threading

# from flask_socketio import SocketIO

from flask_security import Security, SQLAlchemyUserDatastore, hash_password
from flask_security.models import fsqla_v3 as fsqla

from extensions import logger, db
from config import Config

from controllers.client_controller import ClientController
from controllers.cot_controller import CoTController
from opentakserver.certificate_authority import CertificateAuthority

app = Flask(__name__)
app.config.from_object(Config)
cors = CORS(app, resources={r"/api/*": {"origins": "*"}, r"/Marti/*": {"origins": "*"}, r"/*": {"origins": "*"}},
            supports_credentials=True)
flask_wtf.CSRFProtect(app)

# socketio = SocketIO(app)
db.init_app(app)
fsqla.FsModels.set_db_info(db)

from models.user import User
from models.role import Role

user_datastore = SQLAlchemyUserDatastore(db, User, Role)
app.security = Security(app, user_datastore)

from blueprints.marti import marti_blueprint

app.register_blueprint(marti_blueprint)

from blueprints.api import api_blueprint

app.register_blueprint(api_blueprint)

rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
channel = rabbit_connection.channel()
channel.exchange_declare('cot', durable=True, exchange_type='fanout')
channel.exchange_declare('dms', durable=True, exchange_type='direct')
channel.exchange_declare('chatrooms', durable=True, exchange_type='direct')

ca = CertificateAuthority(logger, app)
ca.create_ca()


@app.route("/")
def home():
    return jsonify([])


@app.after_request
def after_request_func(response):
    response.direct_passthrough = False
    return response


def get_ssl_context():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)

    context.load_cert_chain(
        os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", app.config.get("OTS_SERVER_ADDRESS"),
                     app.config.get("OTS_SERVER_ADDRESS") + ".pem"),
        os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", app.config.get("OTS_SERVER_ADDRESS"),
                     app.config.get("OTS_SERVER_ADDRESS") + ".nopass.key"))

    context.verify_mode = app.config.get("OTS_SSL_VERIFICATION_MODE")
    context.load_verify_locations(cafile=os.path.join(app.config.get("OTS_CA_FOLDER"), 'ca.pem'))

    return context


def launch_ssl_server():
    lock = threading.Lock()

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        context = get_ssl_context()

        sconn = context.wrap_socket(sock, server_side=True)
        sconn.bind(('0.0.0.0', app.config.get("OTS_SSL_STREAMING_PORT")))
        sconn.listen(0)

        while True:
            try:
                conn, addr = sconn.accept()
            except (ConnectionResetError, ssl.SSLError):
                # Prevents crashing this thread if a client tries to connect without using SSL
                continue
            logger.info("New SSL connection from {}".format(addr[0]))
            new_thread = ClientController(addr[0], addr[1], conn, lock, logger, app.app_context())
            new_thread.daemon = True
            new_thread.start()


def launch_tcp_server():
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    s.bind(('0.0.0.0', app.config.get("OTS_TCP_STREAMING_PORT")))
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

    http_server = WSGIServer(('0.0.0.0', app.config.get("OTS_HTTP_PORT")), app)
    http_server.start()

    certificate_enrollment_server = WSGIServer(('0.0.0.0', app.config.get("OTS_CERTIFICATE_ENROLLMENT_PORT")),
                                               app, ssl_context=get_ssl_context())
    certificate_enrollment_server.start()

    https_server = WSGIServer(('0.0.0.0', app.config.get("OTS_HTTPS_PORT")), app,
                              ssl_context=get_ssl_context())

    try:
        https_server.serve_forever()
    except KeyboardInterrupt:
        sys.exit()
