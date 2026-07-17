"""Federation server process entry point.

Runs the federation v1 engine as its own process, mirroring the eud_handler
and cot_parser process model: it builds a minimal Flask app for configuration
and database access, then serves federation connections until stopped.
"""

import logging
import os
import platform
import sys
from logging.handlers import TimedRotatingFileHandler

import colorlog
import flask_wtf
import yaml
from apscheduler.jobstores import sqlalchemy
from flask import Flask, jsonify
from flask_security import SQLAlchemyUserDatastore, Security
from flask_security.models import fsqla

from opentakserver.defaultconfig import DefaultConfig
from opentakserver.EmailValidator import EmailValidator
from opentakserver.extensions import db, logger
from opentakserver.federation.engine import FederationManager
from opentakserver.PasswordValidator import PasswordValidator


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] - federation_server[%(process)d] - %(module)s - "
            "%(funcName)s - %(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %Z",
        )
        color_log_handler.setFormatter(color_log_formatter)
        color_log_handler.set_name("federation_server")
        logger.addHandler(color_log_handler)

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs", "federation_server.log"),
        when=app.config.get("OTS_LOG_ROTATE_WHEN"),
        interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
        backupCount=app.config.get("OTS_BACKUP_COUNT"),
    )
    fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] - federation_server[%(process)d] - %(module)s - %(funcName)s - "
            "%(lineno)d - %(levelname)s - %(message)s"
        )
    )
    logger.addHandler(fh)
    return logger


def create_app():
    app = Flask(__name__)
    app.config.from_object(DefaultConfig)

    if os.path.exists(os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml")):
        app.config.from_file(
            os.path.join(app.config.get("OTS_DATA_FOLDER"), "config.yml"), load=yaml.safe_load
        )

    setup_logging(app)
    db.init_app(app)

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
    if not app.config.get("OTS_ENABLE_FEDERATION"):
        logger.info("Federation is disabled, set OTS_ENABLE_FEDERATION to true to enable it")
        return

    manager = FederationManager(app, logger)
    try:
        manager.run()
    except KeyboardInterrupt:
        logger.info("Shutting down federation server")
        manager.stop()


if __name__ == "__main__":
    main()
