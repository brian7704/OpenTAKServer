import argparse
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

from opentakserver.EmailValidator import EmailValidator
from opentakserver.PasswordValidator import PasswordValidator
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.eud_handler import EudHandler
from opentakserver.eud_handler.EudHandlerSSL import EudHandlerSSL
from opentakserver.eud_handler.EudServer import EudServer
from opentakserver.eud_handler.EudServerSSL import EudServerSSL
from opentakserver.extensions import logger, db, ldap_manager


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
        color_log_handler.set_name("eud_handler")
        logger.addHandler(color_log_handler)

    opts = args()
    log_file_name = "eud_handler_tcp.log"
    if opts.ssl:
        log_file_name = "eud_handler_ssl.log"

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs", log_file_name),
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
    return logger


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
        socket_server = EudServerSSL(("0.0.0.0", 9999), EudHandlerSSL, logger)
        logger.info(f"Started SSL server on port {app.config.get('OTS_SSL_STREAMING_PORT')}")
    else:
        socket_server = EudServer(
            ("0.0.0.0", app.config.get("OTS_SSL_STREAMING_PORT")), EudHandler, logger
        )
        logger.info(f"Started TCP server on port {app.config.get('OTS_TCP_STREAMING_PORT')}")

    try:
        socket_server.serve_forever()
    except KeyboardInterrupt:
        logger.info("Shutting down server")


if __name__ == "__main__":
    main()
