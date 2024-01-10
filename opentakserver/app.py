import ipaddress
import os
import re
import subprocess
from datetime import datetime
from pathlib import Path
from shutil import copyfile

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


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

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
