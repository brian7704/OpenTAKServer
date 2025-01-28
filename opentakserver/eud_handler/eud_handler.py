import os
import platform
import sys
import traceback
from logging.handlers import TimedRotatingFileHandler

import sqlalchemy
import yaml
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla

from opentakserver.eud_handler.SocketServer import SocketServer
from opentakserver.controllers.client_controller import ClientController
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


def setup_logging(app):
    level = logging.DEBUG
    #if app.config.get("DEBUG"):
    #    level = logging.DEBUG
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


def create_app():
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)
    setup_logging(app)

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

    db.init_app(app)

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.user import User
    from opentakserver.models.role import Role

    user_datastore = SQLAlchemyUserDatastore(db, User, Role)

    return app


app = create_app()
logger = colorlog.getLogger('OpenTAKServer')
socket_server = SocketServer(logger, app.app_context(), 9999)
socket_server.run()
