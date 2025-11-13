from flask import Blueprint

federation_blueprint = Blueprint('federation', __name__)

from . import federation_api
