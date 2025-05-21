import secrets
import string
import random

import pyotp
from pathlib import Path
import os

import opentakserver


class DefaultConfig:
    SECRET_KEY = os.getenv("SECRET_KEY", secrets.token_hex())
    DEBUG = os.getenv("DEBUG", "False").lower() in ["true", "1", "yes"]

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
    OTS_RABBITMQ_SERVER_ADDRESS = os.getenv("OTS_RABBITMQ_SERVER_ADDRESS", "172.17.0.2")
    OTS_RABBITMQ_USERNAME = os.getenv("OTS_RABBITMQ_USERNAME", "")
    OTS_RABBITMQ_PASSWORD = os.getenv("OTS_RABBITMQ_PASSWORD", "")
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
    OTS_CA_SUBJECT = os.getenv(
        "OTS_CA_SUBJECT",
        f"/C={OTS_CA_COUNTRY}/ST={OTS_CA_STATE}/L={OTS_CA_CITY}/O={OTS_CA_ORGANIZATION}/OU={OTS_CA_ORGANIZATIONAL_UNIT}"
    )

    # Flask-SQLAlchemy settings
    SQLALCHEMY_DATABASE_URI = os.getenv("SQLALCHEMY_DATABASE_URI", f"sqlite:///{os.path.join(OTS_DATA_FOLDER, 'ots.db')}")
    SQLALCHEMY_ECHO = os.getenv("SQLALCHEMY_ECHO", "False").lower() in ["true", "1", "yes"]
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = os.getenv("SQLALCHEMY_TRACK_MODIFICATIONS", "False").lower() in ["true", "1", "yes"]
    SQLALCHEMY_RECORD_QUERIES = os.getenv("SQLALCHEMY_RECORD_QUERIES", "False").lower() in ["true", "1", "yes"]

    # Email Settings
    OTS_ENABLE_EMAIL = os.getenv("OTS_ENABLE_EMAIL", "False").lower() in ["true", "1", "yes"]
    MAIL_SERVER = os.getenv("MAIL_SERVER", "smtp.gmail.com")
    MAIL_PORT = int(os.getenv("MAIL_PORT", 587))
    MAIL_USE_SSL = os.getenv("MAIL_USE_SSL", "False").lower() in ["true", "1", "yes"]
    MAIL_USE_TLS = os.getenv("MAIL_USE_TLS", "True").lower() in ["true", "1", "yes"]
    MAIL_USERNAME = os.getenv("MAIL_USERNAME", None)
    MAIL_PASSWORD = os.getenv("MAIL_PASSWORD", None)

    # Flask-Security-Too
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", str(secrets.SystemRandom().getrandbits(128)))
    SECURITY_REGISTERABLE = os.getenv("SECURITY_REGISTERABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]
    SECURITY_CONFIRMABLE = os.getenv("SECURITY_CONFIRMABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]
    SECURITY_RECOVERABLE = os.getenv("SECURITY_RECOVERABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]

    # TOTP Settings
    SECURITY_TOTP_SECRETS = {1: os.getenv("SECURITY_TOTP_SECRET", pyotp.random_base32())}
    SECURITY_TOTP_ISSUER = os.getenv("SECURITY_TOTP_ISSUER", "OpenTAKServer")

    # Log Rotation
    OTS_LOG_ROTATE_WHEN = os.getenv("OTS_LOG_ROTATE_WHEN", "midnight")
    OTS_LOG_ROTATE_INTERVAL = int(os.getenv("OTS_LOG_ROTATE_INTERVAL", 0))

    # Data Cleanup
    OTS_DELETE_OLD_DATA_DAYS = int(os.getenv("OTS_DELETE_OLD_DATA_DAYS", 0))

    # Allowed Upload Extensions
    ALLOWED_EXTENSIONS = os.getenv("ALLOWED_EXTENSIONS", "zip,xml,txt,pdf,png,jpg,jpeg,gif,kml,kmz").split(",")

    # Upload Folder
    UPLOAD_FOLDER = os.getenv("UPLOAD_FOLDER", os.path.join(OTS_DATA_FOLDER, "uploads"))
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Flask Security
    SECURITY_PASSWORD_SALT = os.getenv("SECURITY_PASSWORD_SALT", str(secrets.SystemRandom().getrandbits(128)))
    REMEMBER_COOKIE_SAMESITE = os.getenv("REMEMBER_COOKIE_SAMESITE", "strict")
    SESSION_COOKIE_SAMESITE = os.getenv("SESSION_COOKIE_SAMESITE", "strict")
    SECURITY_USERNAME_ENABLE = os.getenv("SECURITY_USERNAME_ENABLE", "True").lower() in ["true", "1", "yes"]
    SECURITY_USERNAME_REQUIRED = os.getenv("SECURITY_USERNAME_REQUIRED", "True").lower() in ["true", "1", "yes"]
    SECURITY_TRACKABLE = os.getenv("SECURITY_TRACKABLE", "True").lower() in ["true", "1", "yes"]
    SECURITY_CSRF_COOKIE_NAME = os.getenv("SECURITY_CSRF_COOKIE_NAME", "XSRF-TOKEN")
    WTF_CSRF_TIME_LIMIT = os.getenv("WTF_CSRF_TIME_LIMIT", None)
    SECURITY_CSRF_IGNORE_UNAUTH_ENDPOINTS = os.getenv("SECURITY_CSRF_IGNORE_UNAUTH_ENDPOINTS", "True").lower() in ["true", "1", "yes"]
    WTF_CSRF_CHECK_DEFAULT = os.getenv("WTF_CSRF_CHECK_DEFAULT", "False").lower() in ["true", "1", "yes"]
    SECURITY_RETURN_GENERIC_RESPONSES = os.getenv("SECURITY_RETURN_GENERIC_RESPONSES", "True").lower() in ["true", "1", "yes"]
    SECURITY_URL_PREFIX = os.getenv("SECURITY_URL_PREFIX", "/api")
    SECURITY_CHANGEABLE = os.getenv("SECURITY_CHANGEABLE", "True").lower() in ["true", "1", "yes"]
    SECURITY_CHANGE_URL = os.getenv("SECURITY_CHANGE_URL", "/password/change")
    SECURITY_RESET_URL = os.getenv("SECURITY_RESET_URL", "/password/reset")
    SECURITY_PASSWORD_LENGTH_MIN = int(os.getenv("SECURITY_PASSWORD_LENGTH_MIN", 8))
    SECURITY_REGISTERABLE = os.getenv("SECURITY_REGISTERABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]
    SECURITY_CONFIRMABLE = os.getenv("SECURITY_CONFIRMABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]
    SECURITY_RECOVERABLE = os.getenv("SECURITY_RECOVERABLE", str(OTS_ENABLE_EMAIL)).lower() in ["true", "1", "yes"]
    SECURITY_TWO_FACTOR = os.getenv("SECURITY_TWO_FACTOR", "True").lower() in ["true", "1", "yes"]
    SECURITY_TOTP_SECRETS = {1: os.getenv("SECURITY_TOTP_SECRET", pyotp.random_base32())}
    SECURITY_TOTP_ISSUER = os.getenv("SECURITY_TOTP_ISSUER", "OpenTAKServer")
    SECURITY_TWO_FACTOR_ENABLED_METHODS = os.getenv("SECURITY_TWO_FACTOR_ENABLED_METHODS", "authenticator,email").split(",")
    SECURITY_TWO_FACTOR_RESCUE_MAIL = os.getenv("SECURITY_TWO_FACTOR_RESCUE_MAIL", MAIL_USERNAME)
    SECURITY_TWO_FACTOR_ALWAYS_VALIDATE = os.getenv("SECURITY_TWO_FACTOR_ALWAYS_VALIDATE", "False").lower() in ["true", "1", "yes"]
    SECURITY_CSRF_PROTECT_MECHANISMS = os.getenv("SECURITY_CSRF_PROTECT_MECHANISMS", "session,basic").split(",")
    SECURITY_LOGIN_WITHOUT_CONFIRMATION = os.getenv("SECURITY_LOGIN_WITHOUT_CONFIRMATION", "True").lower() in ["true", "1", "yes"]
    SECURITY_POST_CONFIRM_VIEW = os.getenv("SECURITY_POST_CONFIRM_VIEW", "/login")
    SECURITY_REDIRECT_BEHAVIOR = os.getenv("SECURITY_REDIRECT_BEHAVIOR", "spa")
    SECURITY_RESET_VIEW = os.getenv("SECURITY_RESET_VIEW", "/reset")
    SECURITY_USERNAME_MIN_LENGTH = int(os.getenv("SECURITY_USERNAME_MIN_LENGTH", 1))

    # Job Scheduler
    SCHEDULER_API_ENABLED = os.getenv("SCHEDULER_API_ENABLED", "False").lower() in ["true", "1", "yes"]
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
