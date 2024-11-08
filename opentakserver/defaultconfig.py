import secrets
import string
import random

import pyotp
from pathlib import Path
import os

import opentakserver


class DefaultConfig:
    SECRET_KEY = secrets.token_hex()
    DEBUG = False

    OTS_DATA_FOLDER = os.path.join(Path.home(), 'ots')
    OTS_LISTENER_ADDRESS = "127.0.0.1"
    OTS_LISTENER_PORT = 8081  # OTS will listen for HTTP requests on this port. Nginx will listen on ports 80, 443,
    # 8080, 8443, and 8446 and proxy requests to OTS_LISTENER_PORT
    OTS_MARTI_HTTP_PORT = 8080
    OTS_MARTI_HTTPS_PORT = 8443
    OTS_ENABLE_TCP_STREAMING_PORT = True
    OTS_TCP_STREAMING_PORT = 8088
    OTS_SSL_STREAMING_PORT = 8089
    OTS_BACKUP_COUNT = 7
    OTS_ENABLE_CHANNELS = True
    OTS_RABBITMQ_SERVER_ADDRESS = "127.0.0.1"
    OTS_MEDIAMTX_ENABLE = True
    OTS_MEDIAMTX_API_ADDRESS = "http://localhost:9997"
    OTS_MEDIAMTX_TOKEN = secrets.token_urlsafe(30 * 3 // 4)
    OTS_SSL_VERIFICATION_MODE = 2  # Equivalent to ssl.CERT_REQUIRED. https://docs.python.org/3/library/ssl.html#ssl.SSLContext.verify_mode
    OTS_SSL_CERT_HEADER = 'X-Ssl-Cert'
    OTS_NODE_ID = ''.join(random.choices(string.ascii_lowercase + string.digits, k=32))
    OTS_CA_NAME = 'OpenTAKServer-CA'
    OTS_CA_FOLDER = os.path.join(OTS_DATA_FOLDER, 'ca')
    OTS_CA_PASSWORD = 'atakatak'
    OTS_CA_EXPIRATION_TIME = 3650  # In days, defaults to 10 years
    OTS_CA_COUNTRY = 'WW'
    OTS_CA_STATE = 'XX'
    OTS_CA_CITY = 'YY'
    OTS_CA_ORGANIZATION = 'ZZ'
    OTS_CA_ORGANIZATIONAL_UNIT = 'OpenTAKServer'
    OTS_CA_SUBJECT = '/C={}/ST={}/L={}/O={}/OU={}'.format(OTS_CA_COUNTRY, OTS_CA_STATE, OTS_CA_CITY,
                                                          OTS_CA_ORGANIZATION, OTS_CA_ORGANIZATIONAL_UNIT)
    OTS_FIGLET_WIDTH = 100
    OTS_FIGLET_FONTS = ["slant", "thin", "stampatello", "rectangles", "bell", "doom", "banner", "banner3-D", "banner3",
                        "mini", "marquee", "big", "chunky", "poison", "pepper", "computer", "puffy", "cosmic", "script",
                        "sblood", "epic", "speed", "trek", "rev", "larry3d", "3-d", "5lineoblique", "lean", "cursive",
                        "gothic"]
    # Messages queued in RabbitMQ will auto-delete after 1 day if not consumed https://www.rabbitmq.com/docs/ttl
    # Set to '0' to disable auto-deletion
    OTS_RABBITMQ_TTL = '86400000'

    # See https://docs.python.org/3/library/logging.handlers.html#logging.handlers.TimedRotatingFileHandler
    OTS_LOG_ROTATE_WHEN = 'midnight'
    OTS_LOG_ROTATE_INTERVAL = 0

    # ADS-B Settings
    OTS_AIRPLANES_LIVE_LAT = 40.744213
    OTS_AIRPLANES_LIVE_LON = -73.986939
    OTS_AIRPLANES_LIVE_RADIUS = 10

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

    # Meshtastic settings
    OTS_ENABLE_MESHTASTIC = False
    OTS_MESHTASTIC_TOPIC = "opentakserver"
    OTS_MESHTASTIC_PUBLISH_INTERVAL = 30
    OTS_MESHTASTIC_DOWNLINK_CHANNELS = []

    # Gmail settings
    OTS_ENABLE_EMAIL = False
    OTS_EMAIL_DOMAIN_WHITELIST = []
    OTS_EMAIL_DOMAIN_BLACKLIST = []
    OTS_EMAIL_TLD_WHITELIST = []
    OTS_EMAIL_TLD_BLACKLIST = []
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = 587
    MAIL_USE_SSL = False
    MAIL_USE_TLS = True
    MAIL_DEBUG = False
    MAIL_DEFAULT_SENDER = None
    MAIL_MAX_EMAILS = None
    MAIL_SUPPRESS_SEND = False
    MAIL_ASCII_ATTACHMENTS = False
    MAIL_USERNAME = None
    MAIL_PASSWORD = None

    OTS_DELETE_OLD_DATA_SECONDS = 0
    OTS_DELETE_OLD_DATA_MINUTES = 0
    OTS_DELETE_OLD_DATA_HOURS = 0
    OTS_DELETE_OLD_DATA_DAYS = 0
    OTS_DELETE_OLD_DATA_WEEKS = 1

    # flask-sqlalchemy
    SQLALCHEMY_DATABASE_URI = "sqlite:////{}".format(os.path.join(OTS_DATA_FOLDER, 'ots.db'))
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = False

    ALLOWED_EXTENSIONS = ['zip', 'xml', 'txt', 'pdf', 'png', 'jpg', 'jpeg', 'gif', 'kml', 'kmz']

    UPLOAD_FOLDER = os.path.join(OTS_DATA_FOLDER, 'uploads')
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Flask-Security-Too
    SECURITY_PASSWORD_SALT = str(secrets.SystemRandom().getrandbits(128))
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
    SECURITY_REGISTERABLE = OTS_ENABLE_EMAIL
    SECURITY_CONFIRMABLE = OTS_ENABLE_EMAIL
    SECURITY_RECOVERABLE = OTS_ENABLE_EMAIL
    SECURITY_TWO_FACTOR = True
    SECURITY_TOTP_SECRETS = {1: pyotp.random_base32()}
    SECURITY_TOTP_ISSUER = "OpenTAKServer"
    SECURITY_TWO_FACTOR_ENABLED_METHODS = ["authenticator", "email"]
    SECURITY_TWO_FACTOR_RESCUE_MAIL = MAIL_USERNAME
    SECURITY_TWO_FACTOR_ALWAYS_VALIDATE = False
    SECURITY_CSRF_PROTECT_MECHANISMS = ["session", "basic"]
    SECURITY_LOGIN_WITHOUT_CONFIRMATION = True
    SECURITY_POST_CONFIRM_VIEW = "/login"
    SECURITY_REDIRECT_BEHAVIOR = 'spa'
    SECURITY_RESET_VIEW = '/reset'
    SECURITY_USERNAME_MIN_LENGTH = 1

    SCHEDULER_API_ENABLED = False
