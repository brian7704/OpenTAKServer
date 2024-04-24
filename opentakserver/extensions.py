import colorlog
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from opentakserver.models.Base import Base
from flask_mailman import Mail
from flask_apscheduler import APScheduler

logger = colorlog.getLogger('OpenTAKServer')

mail = Mail()

apscheduler = APScheduler()

db = SQLAlchemy(model_class=Base)

socketio = SocketIO(async_mode='eventlet')

migrate = Migrate()
