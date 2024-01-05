import ipaddress
import os
import random
import re
import secrets
import string
from datetime import datetime

import eventlet
import psutil
import requests

eventlet.monkey_patch()

import traceback

import flask_wtf

import pika
from flask import Flask, jsonify
from flask_cors import CORS

from flask_security import Security, SQLAlchemyUserDatastore, hash_password
from flask_security.models import fsqla_v3 as fsqla

from extensions import logger, db, socketio
from config import Config

from controllers.cot_controller import CoTController
from certificate_authority import CertificateAuthority
from SocketServer import SocketServer

app = Flask(__name__)
app.config.from_object(Config)
cors = CORS(app, resources={r"/api/*": {"origins": "*"}, r"/Marti/*": {"origins": "*"}, r"/*": {"origins": "*"}},
            supports_credentials=True)
flask_wtf.CSRFProtect(app)

socketio.init_app(app)
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

from blueprints.ots_socketio import ots_socketio_blueprint

app.register_blueprint(ots_socketio_blueprint)

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


def first_run():
    with app.app_context():
        if app.config.get("OTS_FIRST_RUN"):
            logger.info("Generating secret keys...")
            secret_key = secrets.token_hex()
            node_id = ''.join(random.choices(string.ascii_lowercase + string.digits, k=64))
            security_password_salt = secrets.SystemRandom().getrandbits(128)

            interfaces = []
            ifs = psutil.net_if_addrs()
            for interface in ifs:
                for address in ifs[interface]:
                    try:
                        ipaddress.IPv4Address(address.address)
                        interfaces.append({'interface': interface, 'address': address.address})
                    except:
                        continue

            try:
                public_ip = requests.get("http://ipinfo.io/ip").text
                interfaces.append({'interface': "Public IP", "address": public_ip})
            except:
                pass

            choice = 0
            while choice < 1 or choice > len(interfaces) + 1:
                if choice:
                    print("{} is an invalid selection".format(choice))

                x = 1
                for interface in interfaces:
                    print("{}) {}: {}".format(x, interface['interface'], interface['address']))
                    x += 1

                print("{}) Other IP or domain name".format(x))

                choice = input("Which address will users connect to? ")
                try:
                    choice = int(choice)
                except ValueError:
                    print("{} is an invalid selection".format(choice))
                    choice = 0
                    continue

            if choice == len(interfaces) + 1:
                server_address = input("What is your domain name? ")
            else:
                server_address = interfaces[choice - 1]['address']

            ots_path = os.path.dirname(os.path.realpath(__file__))
            f = open(os.path.join(ots_path, "secret_key.py"), "w")
            f.write("secret_key = '{}'\n".format(secret_key))
            f.write("node_id = '{}'\n".format(node_id))
            f.write("security_password_salt = '{}'\n".format(security_password_salt))
            f.write("server_address = '{}'\n".format(server_address))
            f.close()

        config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py")

        with open(config_file, "r+") as f:
            file_contents = f.read()
            text_pattern = re.compile(re.escape("OTS_FIRST_RUN = True"), 0)
            file_contents = text_pattern.sub("OTS_FIRST_RUN = False", file_contents)
            f.seek(0)
            f.truncate()
            f.write(file_contents)

        app.config.from_object(Config)

        logger.info("Setup is complete. If you would like to change other settings they are in {}".format(config_file))
        input("Press enter to continue")


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

    first_run()

    tcp_thread = SocketServer(logger, app.config.get("OTS_TCP_STREAMING_PORT"))
    tcp_thread.start()
    app.tcp_thread = tcp_thread

    ssl_thread = SocketServer(logger, app.config.get("OTS_SSL_STREAMING_PORT"), True)
    ssl_thread.start()
    app.ssl_thread = ssl_thread

    cot_thread = CoTController(app.app_context(), logger, db, socketio)
    app.cot_thread = cot_thread

    app.start_time = datetime.now()

    socketio.run(app, host="127.0.0.1", port=app.config.get("OTS_LISTENER_PORT"), debug=False, log_output=True)
