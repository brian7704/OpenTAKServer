import secrets
import string
import random

import pyotp
from pathlib import Path
import os


class DefaultConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex())
    DEBUG = os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"]

    OTS_LANGUAGES = {'US': {'name': 'English', 'language_code': 'en'},
                     'DE': {'name': 'Deutsch', 'language_code': 'de'},
                     'FR': {'name': 'Français', 'language_code': 'fr'},
                     'PT': {'name': 'Português', 'language_code': 'pt'},
                     'ES': {'name': 'Español', 'language_code': 'es'},
                     'DK': {'name': 'dansk', 'language_code': 'da'},
                     'UA': {'name': 'українська', 'language_code': 'uk'},
                     'KR': {'name': '한국어', 'language_code': 'ko'},
                     'PL': {'name': 'Polski', 'language_code': 'pl'},
                     'BR': {'name': 'Português', 'language_code': 'pt_BR'},
                     }

    OTS_DATA_FOLDER = os.getenv("OTS_DATA_FOLDER", os.path.join(Path.home(), "ots"))
    OTS_LISTENER_ADDRESS = os.getenv("OTS_LISTENER_ADDRESS", "127.0.0.1")
    OTS_LISTENER_PORT = int(os.getenv("OTS_LISTENER_PORT", 8081))
    OTS_MARTI_HTTP_PORT = int(os.getenv("OTS_MARTI_HTTP_PORT", 8080))
    OTS_MARTI_HTTPS_PORT = int(os.getenv("OTS_MARTI_HTTPS_PORT", 8443))
    OTS_ENABLE_TCP_STREAMING_PORT = os.getenv("OTS_ENABLE_TCP_STREAMING_PORT", "True").lower() in ["true", "1", "yes"]
    OTS_TCP_STREAMING_PORT = int(os.getenv("OTS_TCP_STREAMING_PORT", 8088))
    OTS_SSL_STREAMING_PORT = int(os.getenv("OTS_SSL_STREAMING_PORT", 8089))
    OTS_BACKUP_COUNT = int(os.getenv("OTS_BACKUP_COUNT", 7))
    OTS_ENABLE_CHANNELS = os.getenv("OTS_ENABLE_CHANNELS", "True").lower() in ["true", "1", "yes"]

    # RabbitMQ Settings
    OTS_RABBITMQ_SERVER_ADDRESS = os.getenv("OTS_RABBITMQ_SERVER_ADDRESS", "127.0.0.1")
    OTS_RABBITMQ_USERNAME = os.getenv("OTS_RABBITMQ_USERNAME", "guest")
    OTS_RABBITMQ_PASSWORD = os.getenv("OTS_RABBITMQ_PASSWORD", "guest")
    # Messages queued in RabbitMQ will auto-delete after 1 day if not consumed https://www.rabbitmq.com/docs/ttl
    # Set to '0' to disable auto-deletion
    OTS_RABBITMQ_TTL = '86400000'
    # How many CoT messages that cot_parser processes should prefetch. https://www.rabbitmq.com/docs/consumer-prefetch
    OTS_RABBITMQ_PREFETCH = 2

    # TAK.gov account link settings
    OTS_TAK_GOV_LINKED = False
    OTS_TAK_GOV_ACCESS_TOKEN = ""
    OTS_TAK_GOV_REFRESH_TOKEN = ""

    OTS_MEDIAMTX_ENABLE = os.getenv("OTS_MEDIAMTX_ENABLE", "True").lower() in ["true", "1", "yes"]
    OTS_MEDIAMTX_API_ADDRESS = os.getenv("OTS_MEDIAMTX_API_ADDRESS", "http://localhost:9997")
    OTS_MEDIAMTX_TOKEN = os.getenv("OTS_MEDIAMTX_TOKEN", secrets.token_urlsafe(30 * 3 // 4))
    OTS_SSL_VERIFICATION_MODE = int(os.getenv("OTS_SSL_VERIFICATION_MODE", 2))
    OTS_SSL_CERT_HEADER = os.getenv("OTS_SSL_CERT_HEADER", "X-Ssl-Cert")
    OTS_NODE_ID = os.getenv("OTS_NODE_ID", ''.join(random.choices(string.ascii_lowercase + string.digits, k=32)))

    # Certificate Authority Settings
    OTS_CA_NAME = os.getenv("OTS_CA_NAME", "OpenTAKServer-CA")
    OTS_CA_FOLDER = os.getenv("OTS_CA_FOLDER", os.path.join(OTS_DATA_FOLDER, "ca"))
    OTS_CA_PASSWORD = os.getenv("OTS_CA_PASSWORD", "atakatak")
    OTS_CA_EXPIRATION_TIME = int(os.getenv("OTS_CA_EXPIRATION_TIME", 3650))
    OTS_CA_COUNTRY = os.getenv("OTS_CA_COUNTRY", "WW")
    OTS_CA_STATE = os.getenv("OTS_CA_STATE", "XX")
    OTS_CA_CITY = os.getenv("OTS_CA_CITY", "YY")
    OTS_CA_ORGANIZATION = os.getenv("OTS_CA_ORGANIZATION", "ZZ")
    OTS_CA_ORGANIZATIONAL_UNIT = os.getenv("OTS_CA_ORGANIZATIONAL_UNIT", "OpenTAKServer")
    OTS_CA_SUBJECT = os.getenv("OTS_CA_SUBJECT",
                               f"/C={OTS_CA_COUNTRY}/ST={OTS_CA_STATE}/L={OTS_CA_CITY}/O={OTS_CA_ORGANIZATION}/OU={OTS_CA_ORGANIZATIONAL_UNIT}")

    OTS_COT_PARSER_PROCESSES = int(os.getenv("OTS_COT_PARSER_PROCESSES", 1))

    OTS_ENABLE_LDAP = False
    # LDAP users in this group will be considered OTS administrators
    OTS_LDAP_ADMIN_GROUP = "ots_admin"

    # Attributes to control a user's team color, role, and callsign. The default values match takserver's attributes
    OTS_LDAP_COLOR_ATTRIBUTE = "colorAttribute"
    OTS_LDAP_ROLE_ATTRIBUTE = "roleAttribute"
    OTS_LDAP_CALLSIGN_ATTRIBUTE = "callsignAttribute"

    # LDAP user attributes with this prefix can be used to control ATAK settings for a specific user
    OTS_LDAP_PREFERENCE_ATTRIBUTE_PREFIX = "ots_"
    OTS_LDAP_GROUP_PREFIX = "ots_"

    # Flask-LDAP3-Login settings
    LDAP_HOST = "127.0.0.1"
    LDAP_BASE_DN = ""
    LDAP_USER_DN = ""
    LDAP_GROUP_DN = ""
    LDAP_BIND_USER_DN = "cn=admin,ou=users=dc=example,dc=com"
    LDAP_BIND_USER_PASSWORD = "password"

    # See https://docs.python.org/3/library/logging.handlers.html#logging.handlers.TimedRotatingFileHandler
    OTS_LOG_ROTATE_WHEN = os.getenv("OTS_LOG_ROTATE_WHEN", "midnight")
    OTS_LOG_ROTATE_INTERVAL = int(os.getenv("OTS_LOG_ROTATE_INTERVAL", 0))

    # ADS-B Settings
    OTS_AIRPLANES_LIVE_LAT = 40.744213
    OTS_AIRPLANES_LIVE_LON = -73.986939
    OTS_AIRPLANES_LIVE_RADIUS = 10

    OTS_ADSB_GROUP = "ADS-B"
    OTS_AIS_GROUP = "AIS"

    OTS_ENABLE_PLUGINS = True
    OTS_PLUGIN_REPO = "https://repo.opentakserver.io/brian/prod/"
    OTS_PLUGIN_PREFIXES = ["ots-", "ots_"]

    # AIS Settings
    OTS_AISHUB_USERNAME = None
    OTS_AISHUB_SOUTH_LAT = None
    OTS_AISHUB_WEST_LON = None
    OTS_AISHUB_NORTH_LAT = None
    OTS_AISHUB_EAST_LON = None
    OTS_AISHUB_MMSI_LIST = ""
    OTS_AISHUB_IMO_LIST = ""

    OTS_PROFILE_MAP_SOURCES = True

    OTS_ENABLE_MUMBLE_AUTHENTICATION = False

    OTS_IP_WHITELIST = ["127.0.0.1"]

    # Meshtastic settings
    OTS_ENABLE_MESHTASTIC = False
    OTS_MESHTASTIC_TOPIC = "opentakserver"
    OTS_MESHTASTIC_PUBLISH_INTERVAL = 30
    OTS_MESHTASTIC_DOWNLINK_CHANNELS = []
    OTS_MESHTASTIC_NODEINFO_INTERVAL = 3
    OTS_MESHTASTIC_GROUP = "Meshtastic"

    # Email settings
    OTS_ENABLE_EMAIL = os.getenv("OTS_ENABLE_EMAIL", "False").lower() in ["true", "1", "yes"]
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() in ["true", "1", "yes"]
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ["true", "1", "yes"]
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", None)
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", None)
    MAIL_DEBUG = False
    MAIL_DEFAULT_SENDER = None
    MAIL_MAX_EMAILS = None
    MAIL_SUPPRESS_SEND = False
    MAIL_ASCII_ATTACHMENTS = False
    OTS_EMAIL_DOMAIN_WHITELIST = []
    OTS_EMAIL_DOMAIN_BLACKLIST = []
    OTS_EMAIL_TLD_WHITELIST = []
    OTS_EMAIL_TLD_BLACKLIST = []

    OTS_DELETE_OLD_DATA_SECONDS = int(os.getenv("OTS_DELETE_OLD_DATA_SECONDS", 0))
    OTS_DELETE_OLD_DATA_MINUTES = int(os.getenv("OTS_DELETE_OLD_DATA_MINUTES", 0))
    OTS_DELETE_OLD_DATA_HOURS = int(os.getenv("OTS_DELETE_OLD_DATA_HOURS", 0))
    OTS_DELETE_OLD_DATA_DAYS = int(os.getenv("OTS_DELETE_OLD_DATA_DAYS", 0))
    OTS_DELETE_OLD_DATA_WEEKS = int(os.getenv("OTS_DELETE_OLD_DATA_WEEKS", 1))

    # flask-sqlalchemy
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI",
                                        f"postgresql+psycopg://ots:POSTGRESQL_PASSWORD@127.0.0.1/ots")
    SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "False").lower() in ["true", "1", "yes"]
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = False

    ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS",
                                   "zip,xml,txt,pdf,png,jpg,jpeg,gif,kml,kmz,p12,tif,sqlite").split(",")

    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(OTS_DATA_FOLDER, "uploads"))
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Flask-Security-Too
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", str(secrets.SystemRandom().getrandbits(128)))
    REMEMBER_COOKIE_SAMESITE = "strict"
    SESSION_COOKIE_SAMESITE = "strict"
    SECURITY_USERNAME_ENABLE = True
    SECURITY_USERNAME_REQUIRED = True
    SECURITY_TRACKABLE = True
    SECURITY_CSRF_COOKIE_NAME = "XSRF-TOKEN"
    WTF_CSRF_TIME_LIMIT = None
    SECURITY_CSRF_IGNORE_UNAUTH_ENDPOINTS = True
    WTF_CSRF_CHECK_DEFAULT = False
    SECURITY_RETURN_GENERIC_RESPONSES = True
    SECURITY_URL_PREFIX = "/api"
    SECURITY_CHANGEABLE = True
    SECURITY_CHANGE_URL = "/password/change"
    SECURITY_RESET_URL = "/password/reset"
    SECURITY_PASSWORD_LENGTH_MIN = 8
    SECURITY_PASSWORD_CONFIRM_REQUIRED = False
    SECURITY_REGISTERABLE = OTS_ENABLE_EMAIL
    SECURITY_CONFIRMABLE = OTS_ENABLE_EMAIL
    SECURITY_RECOVERABLE = OTS_ENABLE_EMAIL
    SECURITY_TWO_FACTOR = True
    SECURITY_TOTP_SECRETS = {1: os.getenv("SECURITY_TOTP_SECRET", pyotp.random_base32())}
    SECURITY_TOTP_ISSUER = os.getenv("SECURITY_TOTP_ISSUER", "OpenTAKServer")
    SECURITY_TWO_FACTOR_ENABLED_METHODS = ["authenticator", "email"]
    SECURITY_TWO_FACTOR_RESCUE_MAIL = MAIL_USERNAME
    SECURITY_TWO_FACTOR_ALWAYS_VALIDATE = False
    SECURITY_CSRF_PROTECT_MECHANISMS = ["session", "basic"]
    SECURITY_LOGIN_WITHOUT_CONFIRMATION = True
    SECURITY_POST_CONFIRM_VIEW = "/login"
    SECURITY_REDIRECT_BEHAVIOR = 'spa'
    SECURITY_RESET_VIEW = '/reset'
    SECURITY_USERNAME_MIN_LENGTH = 1
    SECURITY_MSG_USERNAME_DISALLOWED_CHARACTERS = (
    "Username can contain only letters, numbers, underscores, and periods", "error")

    SCHEDULER_API_ENABLED = False
    JOBS = [
        {
            "id": "get_airplanes_live_data",
            "func": "opentakserver.blueprints.scheduled_jobs:get_airplanes_live_data",
            "trigger": "interval",
            "seconds": 0,
            "minutes": 1,
            "next_run_time": None
        },
        {
            "id": "delete_video_recordings",
            "func": "opentakserver.blueprints.scheduled_jobs:delete_video_recordings",
            "trigger": "interval",
            "seconds": 0,
            "minutes": 1,
            "next_run_time": None
        },
        {
            "id": "purge_data",
            "func": "opentakserver.blueprints.scheduled_jobs:purge_data",
            "trigger": "cron",
            "day": "*",
            "hour": 0,
            "minute": 0,
            "next_run_time": None
        },
        {
            "id": "ais",
            "func": "opentakserver.blueprints.scheduled_jobs:get_aishub_data",
            "trigger": "interval",
            "seconds": 0,
            "minutes": 1,
            "next_run_time": None
        },
        {
            "id": "delete_old_data",
            "func": "opentakserver.blueprints.scheduled_jobs:delete_old_data",
            "trigger": "interval",
            "seconds": 0,
            "minutes": 1,
            "next_run_time": None
        }
    ]
