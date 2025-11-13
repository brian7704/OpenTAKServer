from typing import Any
from gevent import monkey

from opentakserver.telemetry.context import LogCtx
from opentakserver.telemetry.logs import ConsoleSinkOpts, FileSinkOpts, LoggingOptions, setup_logging
monkey.patch_all()

from opentakserver.models.Group import Group, GroupTypeEnum

from opentakserver.UsernameValidator import UsernameValidator

import sys
import traceback
import logging

from flask_migrate import Migrate, upgrade
from opentakserver.PasswordValidator import PasswordValidator

import platform
import requests
from sqlalchemy import insert
import sqlite3
from opentakserver.models.Icon import Icon
from opentakserver.plugins.Plugin import Plugin
from opentakserver.plugins.PluginManager import PluginManager
from opentakserver.sql_jobstore import SQLJobStore

import yaml

from opentakserver.EmailValidator import EmailValidator

from logging.handlers import TimedRotatingFileHandler
import os

import colorlog
from werkzeug.middleware.proxy_fix import ProxyFix
from datetime import datetime, timezone
import sqlalchemy

import flask_wtf

import pika
from flask import Flask, current_app
from flask_cors import CORS

from flask_security import Security, SQLAlchemyUserDatastore, hash_password, uia_username_mapper, uia_email_mapper
from flask_security.models import fsqla_v3 as fsqla
from flask_security.signals import user_registered

import opentakserver
from opentakserver.extensions import logger, db, socketio, mail, apscheduler, ldap_manager
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.models.WebAuthn import WebAuthn

from opentakserver.controllers.meshtastic_controller import MeshtasticController
from opentakserver.certificate_authority import CertificateAuthority

try:
    from opentakserver.mumble.mumble_ice_app import MumbleIceDaemon
except ModuleNotFoundError:
    print("Mumble auth not supported on this platform")


def init_extensions(app):
    db.init_app(app)
    Migrate(app, db)

    logger.info(f"OpenTAKServer {opentakserver.__version__}")
    logger.info("Loading the database...")
    with app.app_context():
        upgrade(directory=os.path.join(os.path.dirname(os.path.realpath(opentakserver.__file__)), 'migrations'))
        # Flask-Migrate does weird things to the logger
        logger.disabled = False
        logger.parent.handlers.pop()
        if app.config.get("DEBUG"):
            logger.setLevel(logging.DEBUG)
        else:
            logger.setLevel(logging.INFO)

    # Handle config options that can't be serialized to yaml
    app.config.update({"SCHEDULER_JOBSTORES": {'default': SQLJobStore(url=app.config.get("SQLALCHEMY_DATABASE_URI"))}})
    identity_attributes = [{"username": {"mapper": uia_username_mapper, "case_insensitive": True}}]

    # Don't allow registration unless email is enabled
    if app.config.get("OTS_ENABLE_EMAIL"):
        identity_attributes.append({"email": {"mapper": uia_email_mapper, "case_insensitive": True}})
        app.config.update({
            "SECURITY_REGISTERABLE": True,
            "SECURITY_CONFIRMABLE": True,
            "SECURITY_RECOVERABLE": True,
            "SECURITY_TWO_FACTOR_ENABLED_METHODS": ["authenticator", "email"]
        })
    else:
        app.config.update({
            "SECURITY_REGISTERABLE": False,
            "SECURITY_CONFIRMABLE": False,
            "SECURITY_RECOVERABLE": False,
            "SECURITY_TWO_FACTOR_ENABLED_METHODS": ["authenticator"]
        })

    if app.config.get("OTS_ENABLE_LDAP"):
        logger.info("Enabling LDAP")
        ldap_manager.init_app(app)
        identity_attributes.append({"ldap": {}})

    app.config.update({"SECURITY_USER_IDENTITY_ATTRIBUTES": identity_attributes})

    ca = CertificateAuthority(logger, app)
    ca.create_ca()

    cors = CORS(app, resources={r"/api/*": {"origins": "*"}, r"/Marti/*": {"origins": "*"}, r"/*": {"origins": "*"}},
                supports_credentials=True)
    flask_wtf.CSRFProtect(app)

    socketio_logger = False
    if app.config.get("DEBUG"):
        socketio_logger = logger
    socketio.init_app(app, logger=socketio_logger, ping_timeout=1, message_queue="amqp://" + app.config.get("OTS_RABBITMQ_SERVER_ADDRESS"))

    rabbit_credentials = pika.PlainCredentials(app.config.get("OTS_RABBITMQ_USERNAME"), app.config.get("OTS_RABBITMQ_PASSWORD"))
    rabbit_host = app.config.get("OTS_RABBITMQ_SERVER_ADDRESS")
    rabbit_connection = pika.BlockingConnection(pika.ConnectionParameters(host=rabbit_host, credentials=rabbit_credentials))

    channel = rabbit_connection.channel()
    channel.exchange_declare('dms', durable=True, exchange_type='direct')
    channel.exchange_declare('cot_parser', durable=True, exchange_type='direct')
    channel.exchange_declare('chatrooms', durable=True, exchange_type='direct')
    channel.exchange_declare("missions", durable=True, exchange_type='topic')  # For Data Sync mission feeds
    channel.exchange_declare("groups", durable=True, exchange_type='topic')  # For channels/groups
    channel.close()
    rabbit_connection.close()

    if not apscheduler.running:
        apscheduler.init_app(app)
        apscheduler.start(paused=False)

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.user import User
    from opentakserver.models.role import Role

    user_datastore = SQLAlchemyUserDatastore(db, User, Role, WebAuthn)
    app.security = Security(app, user_datastore, mail_util_cls=EmailValidator, password_util_cls=PasswordValidator, username_util_cls=UsernameValidator)

    mail.init_app(app)


def create_groups(app: Flask):
    try:
        with app.app_context():
            public_group = Group()
            public_group.name("__ANON__")
            public_group.type = GroupTypeEnum.SYSTEM
            public_group.bitpos = 2
            public_group.description = "Default public group"

            db.session.add(public_group)
            db.session.commit()

            adsb_group = Group()
            adsb_group.name("ADS-B")
            adsb_group.type = GroupTypeEnum.SYSTEM
            adsb_group.bitpos = 3
            adsb_group.description = "ADS-B data"

            db.session.add(adsb_group)
            db.session.commit()

            ais_group = Group()
            ais_group.name("AIS")
            ais_group.type = GroupTypeEnum.SYSTEM
            ais_group.bitpos = 4
            ais_group.description = "AIS data"

            db.session.add(ais_group)
            db.session.commit()
    except BaseException as e:
        logger.error(f"Failed to create groups: {e}")
        logger.debug(traceback.format_exc())

def is_first_run(cfg: dict[str, Any]):
    # existence of config file is used to determine whether OTS has been run before
    return not os.path.exists(os.path.join(cfg.get("OTS_DATA_FOLDER"), "config.yml"))


def get_config() -> dict[str, Any]:
    config = DefaultConfig.to_dict()
    if is_first_run(config):
        DefaultConfig.to_file()  # persist default settings
    else:
        filepath = os.path.join(config.get("OTS_DATA_FOLDER"), "config.yml")
        with open(filepath, "r") as f:
            config = yaml.safe_load(f)
            # TODO: validation with fast fail?
    return config


def configure_logging(cfg: dict[str, Any]) -> LoggingOptions:
    opts = LoggingOptions()
    if cfg.get("DEBUG"):
        opts.level = "DEBUG"
    else:
        opts.level = cfg.get("OTS_LOG_LEVEL")

    # file
    if cfg.get("OTS_LOG_FILE_ENABLED", True):
        opts.file = FileSinkOpts(
            backup_count=cfg.get("OTS_BACKUP_COUNT"),
            directory=cfg.get("OTS_DATA_FOLDER"),
            name="opentakserver.log",
            format=cfg.get("OTS_LOG_FILE_FORMAT"),
            rotate_interval=cfg.get("OTS_LOG_ROTATE_INTERVAL"),
            rotate_when=cfg.get("OTS_LOG_ROTATE_WHEN"),
            level=cfg.get("OTS_LOG_FILE_LEVEL"),
        )

    # console
    if cfg.get("OTS_LOG_CONSOLE_ENABLED", True):
        opts.console = ConsoleSinkOpts(
            format=cfg.get("OTS_LOG_CONSOLE_FORMAT"),
            level=cfg.get("OTS_LOG_CONSOLE_LEVEL"),
        )

    # otel
    opts.otel_enabled = cfg.get("OTS_LOG_OTEL_ENABLE")
    return opts


def create_app(cli=True):
    # get config and setup logger
    config = get_config()
    logger = setup_logging(configure_logging(config))

    # then setup app
    with LogCtx(somerandom="test") as log:
        log.info("creating app")
        app = Flask(__name__)
        app.config.from_mapping(config)
    log.info("created app")

    if not cli:
        if is_first_run(config):
            create_groups(app)

        # Try to set the MediaMTX token
        if app.config.get("OTS_MEDIAMTX_ENABLE"):
            try:
                new_conf = None
                with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "mediamtx.yml"), "r") as mediamtx_config:
                    conf = mediamtx_config.read()
                    if "MTX_TOKEN" in conf:
                        new_conf = conf.replace("MTX_TOKEN", app.config.get("OTS_MEDIAMTX_TOKEN"))
                if new_conf:
                    with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "mediamtx", "mediamtx.yml"), "w") as mediamtx_config:
                        mediamtx_config.write(new_conf)
            except BaseException as e:
                logger.error("Failed to set MediaMTX token: {}".format(e))
        else:
            logger.info("MediaMTX disabled")

        init_extensions(app)

        from opentakserver.blueprints.marti_api import marti_blueprint
        app.register_blueprint(marti_blueprint)

        from opentakserver.blueprints.ots_api import ots_api
        app.register_blueprint(ots_api)

        from opentakserver.blueprints.ots_socketio import ots_socketio_blueprint
        app.register_blueprint(ots_socketio_blueprint)

        from opentakserver.blueprints.scheduled_jobs import scheduler_blueprint
        app.register_blueprint(scheduler_blueprint)

        app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_host=1)

    else:
        from opentakserver.blueprints.cli import ots
        app.cli.add_command(ots, name="ots")

        if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
            app.config.from_file(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load)
            db.init_app(app)
            Migrate(app, db)

        flask_wtf.CSRFProtect(app)

        try:
            fsqla.FsModels.set_db_info(db)
        except sqlalchemy.exc.InvalidRequestError:
            pass

        from opentakserver.models.user import User
        from opentakserver.models.role import Role

        user_datastore = SQLAlchemyUserDatastore(db, User, Role, WebAuthn)
        app.security = Security(app, user_datastore, mail_util_cls=EmailValidator, password_util_cls=PasswordValidator, username_util_cls=UsernameValidator)

        # Register blueprints to properly import all the DB models without circular imports
        from opentakserver.blueprints.marti_api import marti_blueprint
        app.register_blueprint(marti_blueprint)

        from opentakserver.blueprints.ots_api import ots_api
        app.register_blueprint(ots_api)

        from opentakserver.blueprints.ots_socketio import ots_socketio_blueprint
        app.register_blueprint(ots_socketio_blueprint)

        from opentakserver.blueprints.scheduled_jobs import scheduler_blueprint
        app.register_blueprint(scheduler_blueprint)

    return app


@user_registered.connect_via(current_app)
def user_registered_sighandler(app, user, confirmation_token, **kwargs):
    default_role = app.security.datastore.find_or_create_role(
        name="user", permissions={"user-read", "user-write"}
    )
    app.security.datastore.add_role_to_user(user, default_role)


def main(app):
    with app.app_context():
        # Download the icon sets if they aren't already in the DB
        icons = db.session.query(Icon).count()
        if icons == 0:
            logger.info("Downloading icons...")
            try:
                r = requests.get("https://github.com/brian7704/OpenTAKServer-Installer/raw/master/iconsets.sqlite", stream=True)
                with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "icons.sqlite"), "wb") as f:
                    f.write(r.content)

                def dict_factory(cursor, row):
                    d = {}
                    for idx, col in enumerate(cursor.description):
                        d[col[0]] = row[idx]
                    return d

                con = sqlite3.connect(os.path.join(app.config.get("OTS_DATA_FOLDER"), "icons.sqlite"))
                con.row_factory = dict_factory
                cur = con.cursor()
                rows = cur.execute("SELECT * FROM icons")
                for row in rows:
                    db.session.execute(insert(Icon).values(**row))
                db.session.commit()
            except BaseException as e:
                logger.error("Failed to download icons: {}".format(e))
                logger.debug(traceback.format_exc())

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

    if app.config.get("OTS_ENABLE_MESHTASTIC"):
        mestastic_thread = MeshtasticController(app.app_context())
        app.mestastic_thread = mestastic_thread
    else:
        app.meshtastic_thread = None

    if app.config.get("OTS_ENABLE_MUMBLE_AUTHENTICATION"):
        try:
            logger.info("Starting Mumble authentication handler")
            mumble_daemon = MumbleIceDaemon(app, logger)
            mumble_daemon.daemon = True
            mumble_daemon.start()
        except BaseException as e:
            logger.error("Failed to enable Mumble authentication: {}".format(e))
            logger.error(traceback.format_exc())
    else:
        logger.info("Mumble authentication handler disabled")

    if app.config.get("OTS_ENABLE_PLUGINS"):
        try:
            app.plugin_manager = PluginManager(Plugin.group, app)
            app.plugin_manager.load_plugins()
            app.plugin_manager.activate(app)
        except BaseException as e:
            logger.error(f"Failed to load plugins: {e}")
            logger.debug(traceback.format_exc())

    with app.app_context():
        if not app.config.get("OTS_ENABLE_LDAP") and not db.session.execute(db.session.query(Group)).first():
            anon_in = Group()
            anon_in.name = "__ANON__"
            anon_in.type = GroupTypeEnum.SYSTEM
            anon_in.bitpos = 2
            db.session.add(anon_in)

            db.session.commit()

    app.start_time = datetime.now(timezone.utc)

    try:
        socketio.run(app, host=app.config.get("OTS_LISTENER_ADDRESS"), port=app.config.get("OTS_LISTENER_PORT"),
                     debug=app.config.get("DEBUG"), log_output=app.config.get("DEBUG"), use_reloader=False)
    except KeyboardInterrupt:
        logger.warning("Caught CTRL+C, exiting...")
        if app.config.get("OTS_ENABLE_PLUGINS"):
            app.plugin_manager.stop_plugins()


def start():
    app = create_app(cli=False)
    main(app)
