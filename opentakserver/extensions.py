import colorlog
from flask_ldap3_login import LDAP3LoginManager
from flask_migrate import Migrate
from flask_sqlalchemy import SQLAlchemy
from flask_socketio import SocketIO
from opentakserver.models.Base import Base
from flask_mailman import Mail
from flask_apscheduler import APScheduler

logger = colorlog.getLogger('OpenTAKServer')

mail: Mail = Mail()

apscheduler: APScheduler = APScheduler()

db = SQLAlchemy(model_class=Base)

socketio: SocketIO = SocketIO(async_mode='gevent')

migrate: Migrate = Migrate()

ldap_manager: LDAP3LoginManager = LDAP3LoginManager()
