from secret_key import *
from pathlib import Path
import os

upload_folder = os.path.join(Path.home(), 'ots', 'uploads')
if not os.path.exists(upload_folder):
    os.makedirs(upload_folder)


class Config:
    HTTP_PORT = 8080
    HTTPS_PORT = 8443
    COT_PORT = 8087
    COT_STREAMING_PORT = 8088
    SSL_PORT = 8089
    SECRET_KEY = secret_key
    VERSION = '0.1-OTS-DEV'
    SQLALCHEMY_DATABASE_URI = "sqlite:////{}".format(os.path.join(Path.home(), 'ots', 'ots.db'))
    SQLALCHEMY_ECHO = False
    UPLOAD_FOLDER = upload_folder
    ALLOWED_EXTENSIONS = {'zip'}
    SERVER_DOMAIN = 'example.com'
    NODE_ID = node_id
