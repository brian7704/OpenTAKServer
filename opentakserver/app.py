import ipaddress
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path

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

from extensions import logger, db, socketio, nginx_config_template
from config import Config

from controllers.cot_controller import CoTController
from certificate_authority import CertificateAuthority
from SocketServer import SocketServer

def first_run(app):
    with app.app_context():
        if app.config.get("OTS_FIRST_RUN"):
            logger.info("Getting IPs...")

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
                server_address = input("What is your domain name or IP? ")
            else:
                server_address = interfaces[choice - 1]['address']

            ots_path = os.path.dirname(os.path.realpath(__file__))
            with open(os.path.join(ots_path, "secret_key.py"), "r+") as f:
                file_contents = f.read()
                text_pattern = re.compile(re.escape("server_address = 'example.com'"), 0)
                file_contents = text_pattern.sub("server_address = '{}'".format(server_address), file_contents)
                f.seek(0)
                f.truncate()
                f.write(file_contents)

            app.config.update(OTS_SERVER_ADDRESS=server_address)

            config_file = os.path.join(os.path.dirname(os.path.realpath(__file__)), "config.py")

            with open(config_file, "r+") as f:
                file_contents = f.read()
                text_pattern = re.compile(re.escape("OTS_FIRST_RUN = True"), 0)
                file_contents = text_pattern.sub("OTS_FIRST_RUN = False", file_contents)
                f.seek(0)
                f.truncate()
                f.write(file_contents)

            logger.info("Configuring nginx...")

            http_port = app.config.get("OTS_HTTP_PORT")
            https_port = app.config.get("OTS_HTTPS_PORT")
            server_cert_file = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", server_address, server_address + ".pem")
            server_key_file = os.path.join(app.config.get("OTS_CA_FOLDER"), "certs", server_address, server_address + ".nopass.key")
            ca_cert = os.path.join(app.config.get("OTS_CA_FOLDER"), "ca.pem")
            certificate_enrollment_port = app.config.get("OTS_CERTIFICATE_ENROLLMENT_PORT")

            nginx_config = nginx_config_template.render(
                http_port=http_port, https_port=https_port, server_cert_file=server_cert_file, server_key_file=server_key_file,
                ca_cert=ca_cert, certificate_enrollment_port=certificate_enrollment_port
            )

            logger.warning("Attempting to save the nginx config to /etc/nginx/sites-available. If your nginx configs "
                           "are somewhere else, this will fail and you will need to copy the config manually.")

            try:
                with open("/etc/nginx/sites-available/ots_proxy", "w") as f:
                    f.write(nginx_config)

                try:
                    os.remove("/etc/nginx/sites-enabled/*")
                except FileNotFoundError:
                    pass

                try:
                    os.symlink("/etc/nginx/sites-available/ots_proxy", "/etc/nginx/sites-enabled/ots_proxy")
                except FileExistsError:
                    pass

                ca = CertificateAuthority(logger, app)
                ca.create_ca()

                logger.info("Config file saved. Attempting to restart nginx. You may need to input your sudo password.")
                exit_code = subprocess.call("sudo systemctl restart nginx", shell=True)
                if exit_code:
                    logger.error("Failed to restart nginx. Please restart it manually.")
                else:
                    logger.info("Successfully restarted nginx!")

            except FileNotFoundError:
                ots_nginx_proxy = os.path.join(Path.home(), "ots_nginx_proxy")
                with open(ots_nginx_proxy) as f:
                    f.write(nginx_config)

                logger.error("Failed to save the nginx config to the appropriate directory. A copy is saved at {}. "
                             "Please move it to your nginx config folder manually and restart nginx.".format(ots_nginx_proxy))

            logger.info("Setup is complete. If you would like to change other settings they are in {}".format(config_file))
            input("Press enter to continue")


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    first_run(app)

    ca = CertificateAuthority(logger, app)
    ca.create_ca()

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

    return app

app = create_app()

@app.route("/")
def home():
    return jsonify([])


@app.after_request
def after_request_func(response):
    response.direct_passthrough = False
    return response

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

    tcp_thread = SocketServer(logger, app, app.config.get("OTS_TCP_STREAMING_PORT"))
    tcp_thread.start()
    app.tcp_thread = tcp_thread

    ssl_thread = SocketServer(logger, app, app.config.get("OTS_SSL_STREAMING_PORT"), True)
    ssl_thread.start()
    app.ssl_thread = ssl_thread

    cot_thread = CoTController(app.app_context(), logger, db, socketio)
    app.cot_thread = cot_thread

    app.start_time = datetime.now()

    socketio.run(app, host="127.0.0.1", port=app.config.get("OTS_LISTENER_PORT"), debug=False, log_output=True)
