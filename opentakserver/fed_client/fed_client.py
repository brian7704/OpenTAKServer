import logging
import os
import sys
import uuid
from logging.handlers import TimedRotatingFileHandler

import colorlog
import grpc
import sqlalchemy
import yaml
from flask import Flask, jsonify
from flask_security import SQLAlchemyUserDatastore
from flask_security.models import fsqla

from opentakserver.defaultconfig import DefaultConfig
from opentakserver.extensions import logger, db
from opentakserver.models.FederationConnections import FederationConnections
from opentakserver.models.WebAuthn import WebAuthn
from opentakserver.proto import fig_pb2_grpc, fig_pb2


def setup_logging(app):
    level = logging.INFO
    if app.config.get("DEBUG"):
        level = logging.DEBUG
    logger.setLevel(level)

    if sys.stdout.isatty():
        color_log_handler = colorlog.StreamHandler()
        color_log_formatter = colorlog.ColoredFormatter(
            "%(log_color)s[%(asctime)s] - fed_client[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S %Z",
        )
        color_log_handler.setFormatter(color_log_formatter)
        logger.addHandler(color_log_handler)
        logger.info("Added color logger")

    os.makedirs(os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs"), exist_ok=True)
    fh = TimedRotatingFileHandler(
        os.path.join(app.config.get("OTS_DATA_FOLDER"), "logs", "fed_client.log"),
        when=app.config.get("OTS_LOG_ROTATE_WHEN"),
        interval=app.config.get("OTS_LOG_ROTATE_INTERVAL"),
        backupCount=app.config.get("OTS_BACKUP_COUNT"),
    )
    fh.setFormatter(
        logging.Formatter(
            "[%(asctime)s] - fed_client[%(process)d] - %(module)s - %(funcName)s - %(lineno)d - %(levelname)s - %(message)s"
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
                if option.isupper():
                    conf[option] = DefaultConfig.__dict__[option]
            config.write(yaml.safe_dump(conf))

    setup_logging(app)
    db.init_app(app)

    try:
        fsqla.FsModels.set_db_info(db)
    except sqlalchemy.exc.InvalidRequestError:
        pass

    from opentakserver.models.role import Role
    from opentakserver.models.user import User

    user_datastore = SQLAlchemyUserDatastore(db, User, Role, WebAuthn)

    return app


app = create_app()
child_processes = []


@app.route("/status")
def status():
    return jsonify({"status": "ok"})


def main():
    connections = db.session.execute(db.session.query(FederationConnections)).all()

    for connection in connections:
        connection: FederationConnections = connection[0]

        channel_creds = grpc.ssl_channel_credentials(
            open(
                os.path.join(
                    app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "opentakserver",
                    "opentakserver.pem",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    "opentakserver",
                    "opentakserver.nopass.key",
                ),
                "rb",
            ).read(),
            open(
                os.path.join(
                    app.config.get("OTS_CA_FOLDER"),
                    "certs",
                    f"{connection.certificate.server_address}.pem",
                ),
                "rb",
            ).read(),
        )

        # https://github.com/grpc/grpc/blob/master/examples/python/hellostreamingworld/async_greeter_client.py

        with grpc.aio.secure_channel(
            f"{connection.address}:{connection.port}", channel_creds, compression=True
        ) as chanel:
            stub = fig_pb2_grpc.FederatedChannelStub(chanel)
            identity = fig_pb2.Identity()
            identity.name = connection.display_name
            identity.uid = str(uuid.uuid4())
            identity.description = connection.description
            identity.type = 3
            identity.serverId = connection.uid
            subscription = fig_pb2.Subscription()
            subscription.identity.CopyFrom(identity)

            async for response in stub.ClientEventStream(subscription):
                logger.warning(f"ClientEventStream response {response}")


if __name__ == "__main__":
    main()
