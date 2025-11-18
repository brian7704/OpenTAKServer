import os
import platform
import sys
from opentakserver.telemetry import TelemetryOpts, setup_telemetry
from opentelemetry.instrumentation.flask import FlaskInstrumentor

from typing import Any

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
from opentakserver.models.GroupMission import GroupMission
from opentakserver.extensions import db, logger, ldap_manager
from opentakserver.defaultconfig import DefaultConfig
import colorlog
from flask import Flask, jsonify
import logging
import argparse

from opentakserver.telemetry.ots import configure_logging, configure_metrics, configure_tracing


def args():
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssl", help="Enable SSL", default=False, action=argparse.BooleanOptionalAction)
    return parser.parse_args()


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



def create_app(cli=True):
    # get config and setup logger
    config = get_config()
    logger, meter = setup_telemetry(TelemetryOpts(
        logging=configure_logging(config),
        metrics=configure_metrics(config),
        tracing=configure_tracing(config)
        ),__name__)

    # then setup app
    app = Flask(__name__)
    app.config.from_mapping(config)
    FlaskInstrumentor.instrument_app(app)
    db.init_app(app)

    if app.config.get("OTS_ENABLE_LDAP"):
        logger.info("Enabling LDAP")
        ldap_manager.init_app(app)

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

@app.route("/status")
def status():
    return jsonify({"status": "ok"})


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
