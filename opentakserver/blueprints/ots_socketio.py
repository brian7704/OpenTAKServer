import functools

from flask import request, Blueprint
from flask_security import current_user
from flask_socketio import disconnect

from opentakserver.extensions import logger, socketio

ots_socketio_blueprint = Blueprint('ots_socketio_blueprint', __name__)


def authenticated_only(f):
    @functools.wraps(f)
    def wrapped(*args, **kwargs):
        if not current_user.is_authenticated:
            logger.debug("Disconnecting {} from {}".format(request.sid, request.namespace))
            disconnect(request.sid, namespace=request.namespace)
        else:
            return f(*args, **kwargs)

    return wrapped


@socketio.on('connect', namespace="/socket.io")
@authenticated_only
def connect(data):
    logger.info('got a socketio connection from {}'.format(current_user.username))


@socketio.on('message', namespace="/socket.io")
@authenticated_only
def message(message):
    logger.info("Got a message".format(message))
