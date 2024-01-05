import ssl

from secret_key import *
from pathlib import Path
import os
from flask_security import uia_username_mapper


class Config:
    SECRET_KEY = secret_key

    OTS_FIRST_RUN = True
    OTS_DATA_FOLDER = os.path.join(Path.home(), 'ots')
    OTS_LISTENER_PORT = 8081  # OTS will listen for HTTP requests on this port. Nginx will listen on OTS_HTTP_PORT,
                              # OTS_HTTPS_PORT, and OTS_CERTIFICATE_ENROLLMENT_PORT and proxy requests to OTS_LISTENER_PORT
    OTS_HTTP_PORT = 8080
    OTS_HTTPS_PORT = 8443
    OTS_CERTIFICATE_ENROLLMENT_PORT = 8446
    OTS_COT_PORT = 8087
    OTS_TCP_STREAMING_PORT = 8088
    OTS_SSL_STREAMING_PORT = 8089
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
    SECURITY_USER_IDENTITY_ATTRIBUTES = [{"username": {"mapper": uia_username_mapper, "case_insensitive": True}}]
    SECURITY_USERNAME_ENABLE = True
    SECURITY_USERNAME_REQUIRED = True
    SECURITY_TRACKABLE = True
    SECURITY_CSRF_COOKIE_NAME = "XSRF-TOKEN"
    WTF_CSRF_TIME_LIMIT = None
    SECURITY_CSRF_IGNORE_UNAUTH_ENDPOINTS = True
    WTF_CSRF_CHECK_DEFAULT = False
    SECURITY_RETURN_GENERIC_RESPONSES = True
