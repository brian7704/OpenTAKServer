import logging
import os
from typing import Any

from flask_ldap3_login import LDAP3LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
import yaml
from opentakserver.defaultconfig import DefaultConfig
from opentakserver.models.Base import Base
from flask_mailman import Mail
from flask_apscheduler import APScheduler

from opentakserver.telemetry import TelemetryOpts, setup_telemetry
from opentakserver.telemetry.ots import configure_logging, configure_metrics, configure_tracing

def _get_config() -> dict[str, Any]:
    config = DefaultConfig.to_dict()
    if not os.path.exists(os.path.join(config.get("OTS_DATA_FOLDER"), "config.yml")):
        DefaultConfig.to_file()  # persist default settings
    else:
        filepath = os.path.join(config.get("OTS_DATA_FOLDER"), "config.yml")
        with open(filepath, "r") as f:
            config = yaml.safe_load(f)
    return config

__cfg = _get_config()

logger, meter = setup_telemetry(TelemetryOpts(
        logging=configure_logging(__cfg),
        metrics=configure_metrics(__cfg),
        tracing=configure_tracing(__cfg)
        ))

mail = Mail()

apscheduler = APScheduler()

db = SQLAlchemy(model_class=Base)

socketio = SocketIO(async_mode="gevent")

migrate = Migrate()

ldap_manager = LDAP3LoginManager()
