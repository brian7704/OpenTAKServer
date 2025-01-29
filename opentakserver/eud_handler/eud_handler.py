import os
import platform
import sys
from logging.handlers import TimedRotatingFileHandler

import flask_wtf
import sqlalchemy
import yaml
from flask_security import SQLAlchemyUserDatastore, Security
from flask_security.models import fsqla

from opentakserver.EmailValidator import EmailValidator
from opentakserver.PasswordValidator import PasswordValidator
# These unused imports are required by SQLAlchemy, don't remove them
from opentakserver.eud_handler.SocketServer import SocketServer
from opentakserver.models.EUD import EUD
from opentakserver.models.CoT import CoT
from opentakserver.models.Point import Point
from opentakserver.models.Alert import Alert
from opentakserver.models.DataPackage import DataPackage
from opentakserver.models.Certificate import Certificate
from opentakserver.models.Marker import Marker
from opentakserver.models.RBLine import RBLine
from opentakserver.models.Team import Team
from opentakserver.models.GroupEud import GroupEud
from opentakserver.models.Group import Group
from opentakserver.models.EUDStats import EUDStats
from opentakserver.models.Mission import Mission
from opentakserver.models.MissionInvitation import MissionInvitation
from opentakserver.models.MissionContentMission import MissionContentMission
from opentakserver.models.MissionLogEntry import MissionLogEntry
from opentakserver.models.MissionChange import MissionChange
from opentakserver.models.MissionUID import MissionUID
from opentakserver.models.CasEvac import CasEvac
from opentakserver.models.ZMIST import ZMIST
from opentakserver.models.Chatrooms import Chatroom
from opentakserver.models.ChatroomsUids import ChatroomsUids
from opentakserver.models.VideoStream import VideoStream
from opentakserver.models.VideoRecording import VideoRecording
from opentakserver.models.WebAuthn import WebAuthn
from opentakserver.extensions import db, logger
from opentakserver.defaultconfig import DefaultConfig
import colorlog
from flask import Flask
import logging
import argparse


def args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssl", help="Enable SSL", default=False, action=argparse.BooleanOptionalAction)
    return parser.parse_args()


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            '%(log_color)s[%(asctime)s] - eud_handler[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s',
            datefmt="%Y-%m-%d %H:%M:%S")
        color_log_handler.setFormatter(color_log_formatter)
        logger.addHandler(color_log_handler)

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(os.path.join(app.config.get("OTS_DATA_FOLDER"), 'logs', 'opentakserver.log'),
                                  when=app.config.get("OTS_LOG_ROTATE_WHEN"),
                                  interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
                                  backupCount=app.config.get("OTS_BACKUP_COUNT"))
    fh.setFormatter(logging.Formatter(
        "[%(asctime)s] - eud_handler[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"))
    logger.addHandler(fh)


def create_app():
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)

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

    setup_logging(app)
    db.init_app(app)

    # The rest is required by flask, leave it in
    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.user import User
    from opentakserver.models.role import Role

    flask_wtf.CSRFProtect(app)
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    app.security = Security(app, user_datastore, mail_util_cls=EmailValidator, password_util_cls=PasswordValidator)

    return app


app = create_app()


def main():
    opts = args()
    if opts.ssl:
        socket_server = SocketServer(logger, app.app_context(), app.config.get("OTS_SSL_STREAMING_PORT"), True)
        logger.info(f"Started SSL server on port {app.config.get('OTS_SSL_STREAMING_PORT')}")
    else:
        socket_server = SocketServer(logger, app.app_context(), app.config.get("OTS_TCP_STREAMING_PORT"))
        logger.info(f"Started TCP server on port {app.config.get('OTS_TCP_STREAMING_PORT')}")
    socket_server.run()


if __name__ == "__main__":
    main()
