from secret_key import *


class Config:
    HTTP_PORT = 8080
    COT_PORT = 8087
    COT_STREAMING_PORT = 8088
    SSL_PORT = 8089
    SECRET_KEY = secret_key
    VERSION = '0.1-OTS-DEV'
    SQLALCHEMY_DATABASE_URI = "sqlite:////home/administrator/ots.db"
    SQLALCHEMY_ECHO = False
