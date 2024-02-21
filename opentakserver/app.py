import logging
import os

import colorlog
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime
import eventlet
import sqlalchemy

try:
    eventlet.monkey_patch()
except:
    print('failed to monkey_patch()')

import traceback
import flask_wtf
import pickle

import pika
from flask import Flask, jsonify
from flask_cors import CORS

from flask_security import Security, SQLAlchemyUserDatastore, hash_password
from flask_security.models import fsqla_v3 as fsqla
from flask_security.signals import user_registered

from opentakserver.extensions import logger, db, socketio, mail, apscheduler
from opentakserver.config import Config
from opentakserver.models.Config import ConfigSettings

from opentakserver.controllers.cot_controller import CoTController
from opentakserver.certificate_authority import CertificateAuthority
from opentakserver.SocketServer import SocketServer
from opentakserver.mumble.mumble_ice_app import MumbleIceDaemon


def load_config_from_db(app):
    with app.app_context():
        rows = db.session.query(ConfigSettings).count()
        if not rows:
            # First run, save defaults from config.py to the DB
            logger.debug("Saving to config table")
            for key in app.config.keys():
                try:
                    config_setting = ConfigSettings()
                    config_setting.key = key
                    config_setting.type = type(app.config.get(key)).__name__
                    config_setting.value = pickle.dumps(app.config.get(key))
                    db.session.add(config_setting)
                except:
                    pass
            db.session.commit()
        else:
            # Already have settings in the DB, load them into the config
            logger.debug("Getting config from DB")
            rows = db.session.execute(db.session.query(ConfigSettings)).scalars()
            settings_in_db = []
            for row in rows:
                settings_in_db.append(row.key)
                app.config.update({row.key: pickle.loads(row.value)})

            # If there's a new setting in config.py that's not in the DB, add it
            for setting in app.config.keys():
                try:
                    if setting not in settings_in_db:
                        config_setting = ConfigSettings()
                        config_setting.key = setting
                        config_setting.type = type(app.config.get(setting)).__name__
                        config_setting.value = pickle.dumps(app.config.get(setting))
                        db.session.add(config_setting)
                except:
                    pass
            db.session.commit()


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG

    color_log_handler = colorlog.StreamHandler()
    color_log_formatter = colorlog.ColoredFormatter(
        '%(log_color)s[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(levelname)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
    color_log_handler.setFormatter(color_log_formatter)
    logger.setLevel(level)
    logger.addHandler(color_log_handler)

    fh = logging.FileHandler(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'opentakserver.log'))
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter("[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(levelname)s - %(message)s"))
    logger.addHandler(fh)


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)

    setup_logging(app)

    db.init_app(app)

    ca = CertificateAuthority(logger, app)
    ca.create_ca()

    cors = CORS(app, resources={r"/api/*": {"origins": "*"}, r"/Marti/*": {"origins": "*"}, r"/*": {"origins": "*"}},
                supports_credentials=True)
    flask_wtf.CSRFProtect(app)

    socketio.init_app(app)

    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters('localhost'))
    channel = rabbit_connection.channel()
    channel.exchange_declare('cot', durable=True, exchange_type='fanout')
    channel.exchange_declare('dms', durable=True, exchange_type='direct')
    channel.exchange_declare('chatrooms', durable=True, exchange_type='direct')
    channel.queue_declare(queue='cot_controller')
    channel.exchange_declare(exchange='cot_controller', exchange_type='fanout')

    cot_thread = CoTController(app.app_context(), logger, db, socketio)
    app.cot_thread = cot_thread

    apscheduler.init_app(app)
    apscheduler.start(paused=True)

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.user import User
    from opentakserver.models.role import Role

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    app.security = Security(app, user_datastore)

    from opentakserver.blueprints.marti import marti_blueprint
    app.register_blueprint(marti_blueprint)

    from opentakserver.blueprints.api import api_blueprint
    app.register_blueprint(api_blueprint)

    from opentakserver.blueprints.ots_socketio import ots_socketio_blueprint
    app.register_blueprint(ots_socketio_blueprint)

    from opentakserver.blueprints.scheduled_jobs import scheduler_blueprint
    app.register_blueprint(scheduler_blueprint)

    from opentakserver.blueprints.scheduler_api import scheduler_api_blueprint
    app.register_blueprint(scheduler_api_blueprint)

    from opentakserver.blueprints.config import config_blueprint
    app.register_blueprint(config_blueprint)

    app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    mail.init_app(app)

    return app


app = create_app()


@app.route("/")
def home():
    return jsonify([])


@app.after_request
def after_request_func(response):
    response.direct_passthrough = False
    return response


@user_registered.connect_via(app)
def user_registered_sighandler(app, user, confirmation_token, **kwargs):
    default_role = app.security.datastore.find_or_create_role(
        name="user", permissions={"user-read", "user-write"}
    )
    app.security.datastore.add_role_to_user(user, default_role)


if __name__ == '__main__':
    with app.app_context():
        logger.debug("Loading DB..")
        db.create_all()
        load_config_from_db(app)

        if app.config.get("DEBUG"):
            logger.debug("Starting in debug mode")
        else:
            logger.info("Starting in production mode")

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

    if app.config.get("OTS_ENABLE_MUMBLE_AUTHENTICATION"):
        logger.info("Starting mumble authentication handler")
        mumble_daemon = MumbleIceDaemon(app, logger)
        mumble_daemon.daemon = True
        mumble_daemon.start()
    else:
        logger.info("Mumble authentication handler disabled")

    app.start_time = datetime.now()

    socketio.run(app, host="127.0.0.1", port=app.config.get("OTS_LISTENER_PORT"), debug=False, log_output=True)
