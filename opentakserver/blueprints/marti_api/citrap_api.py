import bleach
from flask import Blueprint, current_app as app, request, jsonify

citrap_api_blueprint = Blueprint("citrap_api_blueprint", __name__)


@citrap_api_blueprint.route('/Marti/api/missions/citrap/subscription', methods=['PUT'])
def citrap_subscription():
    uid = bleach.clean(request.args.get('uid'))
    response = {
        'version': 3, 'type': 'com.bbn.marti.sync.model.MissionSubscription',
        'data': {

        }
    }
    return '', 201


@citrap_api_blueprint.route('/Marti/api/citrap')
def citrap():
    return jsonify([])
