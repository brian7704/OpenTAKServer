from gevent import monkey
monkey.patch_all()

import pytz
from opentakserver.models.role import Role
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
from flask import Flask, current_app, g, request, session
from flask_cors import CORS

from flask_security import Security, SQLAlchemyUserDatastore, hash_password, uia_username_mapper, uia_email_mapper
from flask_security.models import fsqla_v3 as fsqla, fsqla_v3
from flask_security.signals import user_registered

import opentakserver
from opentakserver.extensions import logger, db, socketio, mail, apscheduler, ldap_manager, babel
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.models.WebAuthn import WebAuthn

from opentakserver.controllers.meshtastic_controller import MeshtasticController
from opentakserver.certificate_authority import CertificateAuthority

try:
    from opentakserver.mumble.mumble_ice_app import MumbleIceDaemon
except ModuleNotFoundError:
    print("Mumble auth not supported on this platform")


def get_locale():
    if 'language' in session:
        return session['language']
    return request.accept_languages.best_match(current_app.config.get("OTS_LANGUAGES").keys())


def get_timezone():
    # Always return UTC and let the frontend handle converting timezones
    return pytz.timezone("UTC")


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
    channel.exchange_declare("firehose", durable=True, exchange_type='fanout')  # A firehose of all CoT data
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

    babel.init_app(app, locale_selector=get_locale, timezone_selector=get_timezone)


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            '%(log_color)s[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s', datefmt="%Y-%m-%d %H:%M:%S")
        color_log_handler.setFormatter(color_log_formatter)
        logger.addHandler(color_log_handler)
        logger.info("Added color logger")

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'logs', 'opentakserver.log'),
                                  when=app.config.get("OTS_LOG_ROTATE_WHEN"), interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
                                  backupCount=app.config.get("OTS_BACKUP_COUNT"))
    fh.setFormatter(logging.Formatter("[%(asctime)s] - OpenTAKServer[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"))
    logger.addHandler(fh)


def create_app(cli=True):
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)
    setup_logging(app)

    if not cli:
        # Load config.yml if it exists
        if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
            app.config.from_file(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load)
        else:
            # First run, created config.yml based on default settings
            logger.info("Creating config.yml")
            with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config:
                conf = {}
                for option in DefaultConfig.__dict__:
                    # Fix the sqlite DB path on Windows
                    if option == "SQLALCHEMY_DATABASE_URI" and platform.system() == "Windows" and DefaultConfig.__dict__[option].startswith("sqlite"):
                        conf[option] = DefaultConfig.__dict__[option].replace("////", "///").replace("\\", "/")
                    elif option.isupper():
                        conf[option] = DefaultConfig.__dict__[option]
                config.write(yaml.safe_dump(conf))

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
        from opentakserver.blueprints.cli import ots, translate
        app.cli.add_command(ots, name="ots")
        app.cli.add_command(translate, name="translate")

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


def create_default_groups(app):
    with app.app_context():
        if not app.config.get("OTS_ENABLE_LDAP"):
            anon_group = db.session.execute(db.session.query(Group).filter_by(name="__ANON__")).first()
            adsb_group = db.session.execute(db.session.query(Group).filter_by(name=app.config.get("OTS_ADSB_GROUP"))).first()
            ais_group = db.session.execute(db.session.query(Group).filter_by(name=app.config.get("OTS_AIS_GROUP"))).first()
            meshtastic_group = db.session.execute(db.session.query(Group).filter_by(name=app.config.get("OTS_MESHTASTIC_GROUP"))).first()

            # Commit to DB after every one to ensure that get_next_bitpos works

            if not anon_group:
                logger.info("Creating the __ANON__ group")
                anon_group = Group()
                anon_group.name = "__ANON__"
                anon_group.type = GroupTypeEnum.SYSTEM
                anon_group.bitpos = 2
                db.session.add(anon_group)
                db.session.commit()

            if not adsb_group:
                logger.info(f"Creating the {app.config.get('OTS_ADSB_GROUP')} group")
                adsb_group = Group()
                adsb_group.name = app.config.get("OTS_ADSB_GROUP")
                adsb_group.type = GroupTypeEnum.SYSTEM
                adsb_group.bitpos = adsb_group.get_next_bitpos()
                db.session.add(adsb_group)
                db.session.commit()

            if not ais_group:
                logger.info(f"Creating the {app.config.get('OTS_AIS_GROUP')} group")
                ais_group = Group()
                ais_group.name = app.config.get("OTS_AIS_GROUP")
                ais_group.type = GroupTypeEnum.SYSTEM
                ais_group.bitpos = ais_group.get_next_bitpos()
                db.session.add(ais_group)
                db.session.commit()

            if not meshtastic_group:
                logger.info(f"Creating the {app.config.get('OTS_MESHTASTIC_GROUP')} group")
                meshtastic_group = Group()
                meshtastic_group.name = app.config.get("OTS_MESHTASTIC_GROUP")
                meshtastic_group.type = GroupTypeEnum.SYSTEM
                meshtastic_group.bitpos = meshtastic_group.get_next_bitpos()
                db.session.add(meshtastic_group)
                db.session.commit()


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

        # Make sure at least one admin user exists
        admin_user = db.session.execute(db.session.query(Role).join(fsqla_v3.FsModels.roles_users).where(Role.name == "administrator")).scalar()
        if not admin_user:
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

    app.start_time = datetime.now(timezone.utc)

    create_default_groups(app)

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
