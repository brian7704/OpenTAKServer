import ssl

from opentakserver.secret_key import *
from pathlib import Path
import os
from flask_security import uia_username_mapper, uia_email_mapper


class Config:
    SECRET_KEY = secret_key
    #SERVER_NAME = server_name

    OTS_DATA_FOLDER = os.path.join(Path.home(), 'ots')
    OTS_LISTENER_PORT = 8081  # OTS will listen for HTTP requests on this port. Nginx will listen on OTS_HTTP_PORT,
                              # OTS_HTTPS_PORT, and OTS_CERTIFICATE_ENROLLMENT_PORT and proxy requests to OTS_LISTENER_PORT
    OTS_HTTP_PORT = 8080
    OTS_HTTPS_PORT = 8443
    OTS_CERTIFICATE_ENROLLMENT_PORT = 8446
    OTS_COT_PORT = 8087
    OTS_TCP_STREAMING_PORT = 8088
    OTS_SSL_STREAMING_PORT = 8089
    OTS_MEDIAMTX_TOKEN = mediamtx_token
    OTS_MEDIAMTX_BINARY = os.path.join(OTS_DATA_FOLDER, "mediamtx", "mediamtx")
    OTS_MEDIAMTX_CONFIG = os.path.join(OTS_DATA_FOLDER, "mediamtx", "mediamtx.yml")
    OTS_MEDIAMTX_RECORDINGS = os.path.join(OTS_DATA_FOLDER, "mediamtx", "recordings")
    OTS_VERSION = '0.1-OTS-DEV'
    OTS_SSL_VERIFICATION_MODE = ssl.CERT_OPTIONAL  # https://docs.python.org/3/library/ssl.html#ssl.SSLContext.verify_mode
    OTS_SERVER_ADDRESS = server_address
    OTS_NODE_ID = node_id
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

    # Gmail settings
    OTS_ENABLE_EMAIL = True
    MAIL_SERVER = 'smtp.gmail.com'
    MAIL_PORT = '465'
    MAIL_USE_SSL = True
    MAIL_USERNAME = mail_username
    MAIL_PASSWORD = mail_password

    # flask-sqlalchemy
    SQLALCHEMY_DATABASE_URI = "sqlite:////{}".format(os.path.join(OTS_DATA_FOLDER, 'ots.db'))
    SQLALCHEMY_ECHO = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_RECORD_QUERIES = True

    ALLOWED_EXTENSIONS = {'zip', 'xml'}

    UPLOAD_FOLDER = os.path.join(OTS_DATA_FOLDER, 'uploads')
    if not os.path.exists(UPLOAD_FOLDER):
        os.makedirs(UPLOAD_FOLDER)

    # Flask-Security-Too
    SECURITY_PASSWORD_SALT = security_password_salt
    REMEMBER_COOKIE_SAMESITE = "strict"
    SESSION_COOKIE_SAMESITE = "strict"
    SECURITY_USER_IDENTITY_ATTRIBUTES = [{"username": {"mapper": uia_username_mapper, "case_insensitive": False}}]
    if OTS_ENABLE_EMAIL:
        SECURITY_USER_IDENTITY_ATTRIBUTES.append({"email": {"mapper": uia_email_mapper, "case_insensitive": True}})
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
    SECURITY_TOTP_SECRETS = totp_secrets
    SECURITY_TOTP_ISSUER = "OpenTAKServer"
    SECURITY_TWO_FACTOR_ENABLED_METHODS = ["authenticator"]
    if OTS_ENABLE_EMAIL:
        SECURITY_TWO_FACTOR_ENABLED_METHODS.append("email")
    SECURITY_TWO_FACTOR_RESCUE_MAIL = MAIL_USERNAME
    SECURITY_TWO_FACTOR_ALWAYS_VALIDATE = False
    SECURITY_LOGIN_WITHOUT_CONFIRMATION = True
