import argparse
import logging
import os
import platform
import sys
from logging.handlers import TimedRotatingFileHandler

import colorlog
import flask_wtf
import sqlalchemy
import yaml
from flask import Flask, jsonify
from flask_security import Security, SQLAlchemyUserDatastore
from flask_security.models import fsqla

from opentakserver.defaultconfig import DefaultConfig
from opentakserver.EmailValidator import EmailValidator

# These unused imports are required by SQLAlchemy, don't remove them
from opentakserver.eud_handler.SocketServer import SocketServer
from opentakserver.extensions import db, ldap_manager, logger
from opentakserver.models.Alert import Alert  # noqa: F401
from opentakserver.models.CasEvac import CasEvac  # noqa: F401
from opentakserver.models.Certificate import Certificate  # noqa: F401
from opentakserver.models.Chatrooms import Chatroom  # noqa: F401
from opentakserver.models.ChatroomsUids import ChatroomsUids  # noqa: F401
from opentakserver.models.CoT import CoT  # noqa: F401
from opentakserver.models.DataPackage import DataPackage  # noqa: F401
from opentakserver.models.DeviceProfiles import DeviceProfiles  # noqa: F401
from opentakserver.models.EUD import EUD  # noqa: F401
from opentakserver.models.EUDStats import EUDStats  # noqa: F401
from opentakserver.models.Group import Group  # noqa: F401
from opentakserver.models.GroupMission import GroupMission  # noqa: F401
from opentakserver.models.Marker import Marker  # noqa: F401
from opentakserver.models.Mission import Mission  # noqa: F401
from opentakserver.models.MissionChange import MissionChange  # noqa: F401
from opentakserver.models.MissionContentMission import MissionContentMission  # noqa: F401
from opentakserver.models.MissionInvitation import MissionInvitation  # noqa: F401
from opentakserver.models.MissionLogEntry import MissionLogEntry  # noqa: F401
from opentakserver.models.MissionUID import MissionUID  # noqa: F401
from opentakserver.models.Point import Point  # noqa: F401
from opentakserver.models.RBLine import RBLine  # noqa: F401
from opentakserver.models.Team import Team  # noqa: F401
from opentakserver.models.VideoRecording import VideoRecording  # noqa: F401
from opentakserver.models.VideoStream import VideoStream  # noqa: F401
from opentakserver.models.WebAuthn import WebAuthn  # noqa: F401
from opentakserver.models.ZMIST import ZMIST  # noqa: F401
from opentakserver.PasswordValidator import PasswordValidator


def args():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--ssl", help="Enable SSL", default=False, action=argparse.BooleanOptionalAction
    )
    return parser.parse_args()


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] - eud_handler[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %Z",
        )
        color_log_handler.setFormatter(color_log_formatter)
        logger.addHandler(color_log_handler)

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs", "opentakserver.log"),
        when=app.config.get("OTS_LOG_ROTATE_WHEN"),
        interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
        backupCount=app.config.get("OTS_BACKUP_COUNT"),
    )
    fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] - eud_handler[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"
        )
    )
    logger.addHandler(fh)


def create_app():
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)

    # Load config.yml if it exists
    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
        app.config.from_file(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load
        )
    else:
        # First run, created config.yml based on default settings
        logger.info("Creating config.yml")
        with open(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), "w") as config:
            conf = {}
            for option in DefaultConfig.__dict__:
                # Fix the sqlite DB path on Windows
                if (
                    option == "SQLALCHEMY_DATABASE_URI"
                    and platform.system() == "Windows"
                    and DefaultConfig.__dict__[option].startswith("sqlite")
                ):
                    conf[option] = (
                        DefaultConfig.__dict__[option].replace("////", "///").replace("\\", "/")
                    )
                elif option.isupper():
                    conf[option] = DefaultConfig.__dict__[option]
            config.write(yaml.safe_dump(conf))

    setup_logging(app)
    db.init_app(app)

    if app.config.get("OTS_ENABLE_LDAP"):
        logger.info("Enabling LDAP")
        ldap_manager.init_app(app)

    # The rest is required by flask, leave it in
    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.role import Role
    from opentakserver.models.user import User

    flask_wtf.CSRFProtect(app)
    user_datastore = SQLAlchemyUserDatastore(db, User, Role)
    app.security = Security(
        app, user_datastore, mail_util_cls=EmailValidator, password_util_cls=PasswordValidator
    )

    return app


app = create_app()


@app.route("/status")
def status():
    return jsonify({"status": "ok"})


def main():
    opts = args()
    if opts.ssl:
        socket_server = SocketServer(
            logger, app.app_context(), app.config.get("OTS_SSL_STREAMING_PORT"), True
        )
        logger.info(f"Started SSL server on port {app.config.get('OTS_SSL_STREAMING_PORT')}")
    else:
        socket_server = SocketServer(
            logger, app.app_context(), app.config.get("OTS_TCP_STREAMING_PORT")
        )
        logger.info(f"Started TCP server on port {app.config.get('OTS_TCP_STREAMING_PORT')}")
    socket_server.run()


if __name__ == "__main__":
    main()
